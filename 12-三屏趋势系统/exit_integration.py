"""三屏趋势系统 — 离场决策集成

通过经典指标系统（10-经典指标系统）的 ClassicExitSystem 进行离场决策。

三屏趋势系统的定位：
- 负责趋势方向、置信度、仓位计算
- 离场策略委托给经典系统的 ClassicExitSystem

经典离场系统的四大优先级（P0-P3）：
    P0 - L0 安全硬退出（一票否决）
    P1 - L1/L2 价值-风险评估（主体）
    P2 - Triple Barrier 三重屏障
    P3 - 执行层行为约束（跟踪止损、TSTP等）
"""

import sys
import os
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum


class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 提高止盈价（强反弹时让利润奔跑）


@dataclass
class PositionInfo:
    """持仓信息"""
    symbol: str
    side: str = "long"
    entry_price: float = 0.0
    current_price: float = 0.0
    quantity: float = 0.0
    entry_time: float = 0.0
    notional_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0


@dataclass
class ExitDecisionResult:
    """离场决策结果"""
    action: ExitAction
    confidence: float = 0.0
    reason: str = ""
    priority: str = ""
    reduce_fraction: float = 0.0
    suggested_price: float = 0.0
    new_tp_price: float = 0.0    # RAISE_TP 新止盈价
    new_tp_pct: float = 0.0      # RAISE_TP 新止盈比例
    raw_data: Dict[str, Any] = field(default_factory=dict)


def get_exit_system_classic() -> Optional[Any]:
    """
    尝试直接导入经典离场系统（同机部署时直接导入

    返回 ClassicExitSystem 实例
    """
    try:
        classic_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "10-经典指标系统"
        )
        if classic_path not in sys.path:
            sys.path.insert(0, classic_path)
        from classic_exit_system import ClassicExitSystem, get_default_system
        return get_default_system()
    except Exception:
        return None


def evaluate_exit_via_api(
    position: PositionInfo,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
) -> ExitDecisionResult:
    """
    通过 HTTP API 调用经典系统的离场决策

    参数:
        position: 持仓信息
        candles_1h: 1小时K线数据
        regime: 市场状态 trend / choppy / neutral

    返回:
        ExitDecisionResult
    """
    try:
        from .classic_bridge import _make_request
    except ImportError:
        from classic_bridge import _make_request

    payload = {
        "symbol": position.symbol,
        "side": position.side,
        "entry_price": position.entry_price,
        "current_price": position.current_price,
        "quantity": position.quantity,
        "entry_time": position.entry_time,
        "notional_usd": position.notional_usd,
        "regime": regime,
    }

    resp = _make_request(
        "/exit/evaluate",
        method="POST",
        json_data=payload,
        timeout=5.0,
    )

    if not resp["ok"]:
        return ExitDecisionResult(
            action=ExitAction.HOLD,
            reason=f"经典系统不可用: {resp.get('error', 'unknown')}",
            priority="unavailable",
            raw_data={"error": resp.get("error")},
        )

    data = resp["data"]
    if isinstance(data, dict):
        action_str = (data.get("action") or "hold").lower()
        action = ExitAction(action_str) if action_str in [e.value for e in ExitAction] else ExitAction.HOLD

        return ExitDecisionResult(
            action=action,
            confidence=float(data.get("confidence", 0) or 0),
            reason=data.get("reason", ""),
            priority=data.get("priority", ""),
            reduce_fraction=float(data.get("reduce_fraction", 0) or 0),
            suggested_price=float(data.get("suggested_price", position.current_price) or position.current_price),
            new_tp_price=float(data.get("new_tp_price", 0) or 0),
            new_tp_pct=float(data.get("new_tp_pct", 0) or 0),
            raw_data=data,
        )

    return ExitDecisionResult(action=ExitAction.HOLD, reason="未知响应格式", priority="unknown", raw_data=data)


def evaluate_exit(
    position: PositionInfo,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
    use_api: bool = True,
) -> ExitDecisionResult:
    """
    离场决策主入口

    优先通过 API 调用经典系统，API 不可用时降级为直接导入（同机部署）。

    参数:
        position: 持仓信息
        candles_1h: 1小时K线数据（用于离场特征计算
        regime: 市场 regime（trend/choppy/neutral）
        use_api: 是否优先使用 API 调用

    返回:
        ExitDecisionResult
    """
    if use_api:
        result = evaluate_exit_via_api(position, candles_1h, regime)
        if result.priority != "unavailable":
            return result

    classic_sys = get_exit_system_classic()
    if classic_sys is not None:
        try:
            from classic_exit_system import PositionState as ClassicPosState
            classic_pos = ClassicPosState(
                coin=position.symbol,
                side=position.side,
                entry_price=position.entry_price,
                current_price=position.current_price,
                position_age_sec=time.time() - position.entry_time if position.entry_time else 0,
                unrealized_pnl_pct=position.unrealized_pnl_pct,
                leverage=position.leverage,
                atr_pct=position.atr_pct,
                mfe_pnl_pct=position.mfe_pnl_pct,
                max_dd_pct=position.max_dd_pct,
                trailing_armed=position.trailing_armed,
                trailing_stop_price=position.trailing_stop_price,
                liq_price=position.liq_price,
                entry_ts=position.entry_time,
                metadata={
                    "quantity": position.quantity,
                    "notional_usd": position.notional_usd,
                },
            )
            decision = classic_sys.evaluate_full(classic_pos, candles_1h, regime)
            action_val = decision.action.value if hasattr(decision.action, 'value') else str(decision.action)
            result_action = ExitAction(action_val) if action_val in [e.value for e in ExitAction] else ExitAction.HOLD
            return ExitDecisionResult(
                action=result_action,
                confidence=decision.confidence,
                reason=decision.reason or "",
                priority=decision.priority.value if decision.priority else "",
                reduce_fraction=decision.reduce_frac,
                suggested_price=decision.suggested_price,
                new_tp_price=getattr(decision, 'new_tp_price', 0.0),
                new_tp_pct=getattr(decision, 'new_tp_pct', 0.0),
                raw_data={"source": "direct_import", "features": decision.features},
            )
        except Exception as e:
            return ExitDecisionResult(
                action=ExitAction.HOLD,
                reason=f"经典系统导入失败: {str(e)[:100]}",
                priority="error",
                raw_data={},
            )

    return ExitDecisionResult(
        action=ExitAction.HOLD,
        reason="经典离场系统不可用（API和本地均不可达",
        priority="unavailable",
        raw_data={},
    )
