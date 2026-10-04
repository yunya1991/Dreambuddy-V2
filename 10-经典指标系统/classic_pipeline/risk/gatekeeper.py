"""风控层（Risk Gatekeeper）。

参考传统金融 Risk Sidecar 独立 veto 设计：
- 独立于策略逻辑
- 单笔最大风险 2%
- 仓位管理（波动率反比）
- 最大仓位限制

所有函数为纯函数。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from classic_pipeline.core.utils import _clip, _sf0


def check(
    signal: Dict[str, Any],
    portfolio_state: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """风控检查（Risk Gatekeeper veto）。

    Args:
        signal: 信号 {direction, confidence, entry_price}
        portfolio_state: 组合状态 {equity, atr, positions}
        config: 配置

    Returns:
        {approved, position_size, stop_loss, take_profit, reason}
    """
    cfg = config or {}
    ps = portfolio_state or {}

    direction = str(signal.get("direction") or "neutral").strip().lower()
    if direction not in ("long", "short"):
        return {"approved": False, "position_size": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "reason": "no_direction"}

    equity = _sf0(ps.get("equity"), 0.0)
    if equity <= 0:
        return {"approved": False, "position_size": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "reason": "no_equity"}

    # 单笔最大风险占总资产比例（默认 2%）
    max_risk_pct = float(cfg.get("max_risk_pct", 0.02))
    risk_amount = equity * max_risk_pct

    # 止损距离：优先用 ATR，否则用固定比例
    atr = _sf0(ps.get("atr"), 0.0)
    entry_price = _sf0(signal.get("entry_price"), 0.0)
    atr_mult = float(cfg.get("atr_stop_mult", 2.0))

    if atr > 0 and entry_price > 0:
        stop_distance = (atr * atr_mult) / entry_price
    else:
        stop_distance = float(cfg.get("default_stop_pct", 0.02))

    stop_distance = _clip(stop_distance, 0.001, 0.5)

    # 仓位大小：风险金额 / 止损距离
    if stop_distance > 0:
        position_pct = risk_amount / (equity * stop_distance)
    else:
        position_pct = float(cfg.get("default_position_pct", 0.1))

    # 最大仓位限制
    max_position_pct = float(cfg.get("max_position_pct", 0.1))
    position_pct = _clip(position_pct, 0.0, max_position_pct)

    # 止盈：基于盈亏比
    reward_risk_ratio = float(cfg.get("reward_risk_ratio", 2.0))
    take_profit_pct = stop_distance * reward_risk_ratio

    return {
        "approved": True,
        "position_size": position_pct,
        "stop_loss": stop_distance,
        "take_profit": take_profit_pct,
        "reason": "",
    }


def position_sizing(
    volatility: float,
    equity: float,
    config: Optional[Dict[str, Any]] = None,
) -> float:
    """波动率反比仓位管理。

    波动率越高，仓位越小。

    Args:
        volatility: 波动率（如 ATR%）
        equity: 账户权益
        config: 配置

    Returns:
        建议仓位比例 [0, max_position_pct]
    """
    cfg = config or {}
    if volatility <= 0 or equity <= 0:
        return 0.0

    base_position = float(cfg.get("base_position_pct", 0.1))
    max_position = float(cfg.get("max_position_pct", 0.1))
    target_vol = float(cfg.get("target_volatility", 0.02))

    # 波动率反比缩放
    position = base_position * (target_vol / volatility)
    return _clip(position, 0.0, max_position)


def max_drawdown_check(
    current_drawdown: float,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """最大回撤检查。超过阈值时停止开仓。

    Args:
        current_drawdown: 当前回撤比例
        config: 配置

    Returns:
        True 表示可以开仓，False 表示应停止
    """
    cfg = config or {}
    max_dd = float(cfg.get("max_drawdown_limit", 0.20))
    return current_drawdown < max_dd
