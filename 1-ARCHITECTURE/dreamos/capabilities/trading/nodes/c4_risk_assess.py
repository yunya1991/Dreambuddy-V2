"""
C4 风险评估节点

Classic Pipeline C0-C8 八阶段流水线第五阶段。
基于 C3 通过验证的信号做风险预算、仓位、止损止盈评估。

迁移自 ml_trade_service.py 的 risk 相关路由（无标准函数名匹配）。
原实现依赖 CONFIG 全局配置 + 复杂组合管理逻辑，
本节点采用与 C0-C3 一致的轻量级简化策略：
- 仓位 = (资金 * 单笔风险比例) / (入场价 * 止损比例)
- 止损价 = 入场价 * (1 - 止损比例 * direction_sign)  （LONG: 1-; SHORT: 1+）
- 止盈价 = 入场价 * (1 + 止盈比例 * direction_sign)
- 风险预算 = sum(仓位 * 入场价 * 止损比例) / 资金

设计原则（遵循优雅改动原则）：
- 不依赖全局 CONFIG / 复杂组合管理
- 所有输入通过 state.market + state.config + 上游 C3 outputs 提供
- 无 market 或无 C3 上游结果时降级返回 SUCCESS + 空结果（FAIL-OPEN）

inputs:
    - 上游 C3: state.get_result("C3").outputs["verified_signals"] (list[dict])
      每项含: symbol, direction, confidence, win_rate, ...
    - state.market: dict, 必须包含:
        - market_data: dict[str, dict], 币种→价格数据（含 price 字段）
        - portfolio_state: dict, 含:
            - capital: float, 可用资金
            - existing_positions: dict, 品种→已占用仓位（可选）
    - state.config: dict, 可选覆盖:
        - risk_per_trade: float (默认 0.02) — 单笔风险比例（占总资金）
        - risk_stop_loss_pct: float (默认 0.03) — 止损比例（相对入场价）
        - risk_take_profit_pct: float (默认 0.06) — 止盈比例（相对入场价）
        - risk_max_budget: float (默认 0.20) — 最大风险预算上限（占总资金）
outputs:
    - position_size: dict[str, float] — 品种→建议仓位（以币为单位，不是 USD）
    - stop_loss: dict[str, float] — 品种→止损价
    - take_profit: dict[str, float] — 品种→止盈价
    - risk_budget: float — 总风险预算占用比例 [0,1]
"""

from __future__ import annotations

import math
from typing import Any, Dict

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 默认阈值 ──────────────────────────────────────────────
_DEFAULT_RISK_PER_TRADE = 0.02
_DEFAULT_STOP_LOSS_PCT = 0.03
_DEFAULT_TAKE_PROFIT_PCT = 0.06
_DEFAULT_MAX_BUDGET = 0.20
_DEFAULT_CAPITAL = 10000.0


def _clip(value: float, low: float, high: float) -> float:
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)


class C4RiskAssessNode(BaseNode):
    """C4 风险评估节点

    简化版风险评估：
    - 基于信号 confidence 调整单笔风险比例（confidence 越高，风险比例越大）
    - 仓位 = (资金 * 风险比例) / (入场价 * 止损比例)
    - LONG: 止损 = price*(1-sl), 止盈 = price*(1+tp)
    - SHORT: 止损 = price*(1+sl), 止盈 = price*(1-tp)
    - 风险预算 = sum(仓位*入场价*止损比例) / 资金，受 max_budget 上限约束

    下游 C5 可通过 state.get_result("C4").outputs 访问。

    设计原则（遵循优雅改动原则）：
    - 不依赖全局 CONFIG / 复杂组合管理
    - 所有输入通过 state.market + state.config + 上游 C3 outputs 提供
    - 无 market 或无 C3 上游结果时降级返回 SUCCESS + 空结果（FAIL-OPEN）
    """

    node_id = "C4"
    name = "风险评估"
    description = "风险预算、仓位、止损止盈评估"
    chain = "C"
    tags = ["classic", "classic_v2", "risk", "position_sizing", "sl_tp"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _read_config(state: State) -> Dict[str, float]:
        cfg = state.config or {}

        def _get_float(key: str, default: float) -> float:
            try:
                v = float(cfg.get(key, default))
                if not math.isfinite(v):
                    return float(default)
                return v
            except Exception:
                return float(default)

        return {
            "risk_per_trade": _clip(_get_float("risk_per_trade", _DEFAULT_RISK_PER_TRADE), 0.001, 0.50),
            "stop_loss_pct": _clip(_get_float("risk_stop_loss_pct", _DEFAULT_STOP_LOSS_PCT), 0.001, 0.50),
            "take_profit_pct": _clip(_get_float("risk_take_profit_pct", _DEFAULT_TAKE_PROFIT_PCT), 0.001, 1.00),
            "max_budget": _clip(_get_float("risk_max_budget", _DEFAULT_MAX_BUDGET), 0.01, 1.00),
        }

    @staticmethod
    def _get_float(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            v = float(d.get(key, default) or default)
            if not math.isfinite(v):
                return float(default)
            return v
        except Exception:
            return float(default)

    @staticmethod
    def _confidence_adjusted_risk(base_risk: float, confidence: float) -> float:
        """根据 signal confidence 调整风险比例

        confidence 0.5-1.0 线性映射到 [0.5*base, 1.5*base]
        """
        if confidence <= 0.5:
            return base_risk * 0.5
        # confidence 0.5 → 0.5x, confidence 1.0 → 1.5x
        multiplier = 0.5 + (confidence - 0.5) * 2.0  # 0.5 + [0,1] = [0.5, 1.5]
        return base_risk * multiplier

    def execute_core(self, state: State) -> NodeResult:
        """执行风险评估

        流程：
            1. 读取 state.market + state.config + 上游 C3 verified_signals
            2. 对每个 signal 查价格 → 计算仓位/止损/止盈
            3. 累积风险预算，超过 max_budget 时按比例缩放
        """
        # 1. FAIL-OPEN：无 market 或无 C3 上游结果
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C4",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"position_size": {}, "stop_loss": {}, "take_profit": {}, "risk_budget": 0.0},
                error="C4 无 market 数据，降级返回空结果",
            )

        c3_result = state.get_result("C3")
        if c3_result is None or not c3_result.outputs:
            return NodeResult(
                node_id="C4",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"position_size": {}, "stop_loss": {}, "take_profit": {}, "risk_budget": 0.0},
                error="C4 无 C3 上游结果，降级返回空结果",
            )

        verified = c3_result.outputs.get("verified_signals") or []
        if not isinstance(verified, list) or not verified:
            return NodeResult(
                node_id="C4",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"position_size": {}, "stop_loss": {}, "take_profit": {}, "risk_budget": 0.0},
                error="C4 上游 verified_signals 为空",
            )

        market_data = market.get("market_data") or {}
        if not isinstance(market_data, dict):
            market_data = {}
        portfolio_state = market.get("portfolio_state") or {}
        if not isinstance(portfolio_state, dict):
            portfolio_state = {}
        capital = max(1.0, self._get_float(portfolio_state, "capital", _DEFAULT_CAPITAL))

        cfg = self._read_config(state)
        base_risk = cfg["risk_per_trade"]
        sl_pct = cfg["stop_loss_pct"]
        tp_pct = cfg["take_profit_pct"]
        max_budget = cfg["max_budget"]

        # 2. 逐个信号计算仓位/止损/止盈
        position_size: Dict[str, float] = {}
        stop_loss: Dict[str, float] = {}
        take_profit: Dict[str, float] = {}
        risk_used = 0.0  # 累积风险占用（USD）

        for sig in verified:
            if not isinstance(sig, dict):
                continue
            symbol = str(sig.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            coin_data = market_data.get(symbol)
            if not isinstance(coin_data, dict):
                continue
            price = self._get_float(coin_data, "price", 0.0)
            if price <= 0:
                continue

            direction = str(sig.get("direction") or "").upper()
            confidence = _clip(self._get_float(sig, "confidence", 0.5), 0.0, 1.0)

            # 根据置信度调整风险比例
            risk_pct = self._confidence_adjusted_risk(base_risk, confidence)
            risk_usd = capital * risk_pct  # 单笔风险金额（USD）

            # 仓位 = 风险金额 / (入场价 * 止损比例)
            size = risk_usd / (price * sl_pct) if sl_pct > 0 else 0.0
            if size <= 0:
                continue

            # 止损/止盈价
            sign = 1.0 if direction == "LONG" else -1.0
            sl_price = price * (1.0 - sign * sl_pct)
            tp_price = price * (1.0 + sign * tp_pct)

            position_size[symbol] = float(size)
            stop_loss[symbol] = float(sl_price)
            take_profit[symbol] = float(tp_price)
            risk_used += size * price * sl_pct  # 该笔交易的实际风险金额

        # 3. 风险预算：占总资金比例，受 max_budget 约束
        risk_budget = risk_used / capital
        if risk_budget > max_budget:
            # 超过上限，按比例缩放所有仓位
            scale = max_budget / risk_budget if risk_budget > 0 else 1.0
            for sym in list(position_size.keys()):
                position_size[sym] *= scale
            # 重新计算风险预算
            risk_budget = sum(position_size[sym] * (market_data.get(sym, {}).get("price", 0.0) or 0.0) * sl_pct for sym in position_size) / capital

        risk_budget = _clip(risk_budget, 0.0, max_budget)

        # 4. 节点置信度：基于风险预算占用率（适中最佳）
        # 过低=信号不足，过高=风险过大，0.5*max_budget 附近最佳
        if max_budget > 0:
            budget_ratio = risk_budget / max_budget
            # 0.5 附近最佳，过低/过高都降低置信度
            node_confidence = _clip(1.0 - abs(budget_ratio - 0.5) * 2.0, 0.0, 0.95)
        else:
            node_confidence = 0.0

        return NodeResult(
            node_id="C4",
            status=NodeStatus.SUCCESS,
            confidence=float(node_confidence),
            outputs={
                "position_size": position_size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_budget": float(risk_budget),
            },
        )
