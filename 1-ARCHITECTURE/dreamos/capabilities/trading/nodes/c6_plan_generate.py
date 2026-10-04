"""
C6 计划生成节点

Classic Pipeline C0-C8 八阶段流水线第七阶段。
整合 C4 风险评估（仓位/止损/止盈）+ C5 参数优化 + C3 信号方向，
产出可执行的交易计划 Draft，供前端 governance 流程审批。

迁移自 ml_trade_service.py 的 plan/draft 相关路由（无标准函数名匹配）。
原实现依赖 CONFIG 全局 + 复杂 draft 引擎 + 数据库持久化，
本节点采用与 C0-C5 一致的轻量级简化策略：
- trade_plan：每品种聚合 {symbol, direction, size, entry_price, sl, tp, params}
- changeset：{symbols: [...], <symbol>: {direction, size, sl, tp}} 供前端审批
- strategy_name：基于主流方向（LONG/SHORT/NEUTRAL）
- trace_id：uuid4

设计原则（遵循优雅改动原则）：
- 不依赖全局 CONFIG / draft 引擎 / 数据库
- 所有输入通过 state.market + state.config + 上游 C3/C4/C5 outputs 提供
- 无 market 或无 C4/C5 上游时降级返回 SUCCESS + 空结果（FAIL-OPEN）
- 仓位为 0 的品种被过滤（C4 是仓位真相源）

inputs:
    - 上游 C4: state.get_result("C4").outputs["position_size"] / ["stop_loss"] / ["take_profit"]
    - 上游 C5: state.get_result("C5").outputs["optimized_params"]
    - 上游 C3: state.get_result("C3").outputs["verified_signals"]（含 direction）
    - state.market: dict, 含 market_data: dict[str, dict]（含 price 字段）
    - state.config: dict, 可选:
        - plan_strategy_prefix: str (默认 "Classic") — strategy_name 前缀
outputs:
    - trade_plan: dict[str, dict] — 品种→完整交易计划
    - changeset: dict — 供前端 governance 审批的变更集
    - strategy_name: str — 基于主流方向的策略名
    - trace_id: str — uuid4 追溯 ID
"""

from __future__ import annotations

import math
from typing import Any, Dict, List
from uuid import uuid4

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


_DEFAULT_STRATEGY_PREFIX = "Classic"


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


class C6PlanGenerateNode(BaseNode):
    """C6 计划生成节点

    轻量级计划生成：
    - 聚合 C4 仓位 + C5 参数 + C3 方向 → trade_plan
    - changeset 供前端 governance 审批
    - strategy_name 基于主流方向
    - trace_id 唯一 uuid

    下游 C7 通过 state.get_result("C6").outputs["trade_plan"] 访问。
    """

    node_id = "C6"
    name = "计划生成"
    description = "整合 C4 风险评估 + C5 参数优化，产出可执行交易计划 Draft"
    chain = "C"
    tags = ["classic", "classic_v2", "plan", "draft", "execution_plan"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _read_config(state: State) -> str:
        cfg = state.config or {}
        prefix = cfg.get("plan_strategy_prefix", _DEFAULT_STRATEGY_PREFIX)
        if not isinstance(prefix, str) or not prefix.strip():
            return _DEFAULT_STRATEGY_PREFIX
        return prefix.strip()

    @staticmethod
    def _build_direction_map(c3_result: NodeResult | None) -> Dict[str, str]:
        """从 C3 verified_signals 构建 symbol→direction 映射"""
        mapping: Dict[str, str] = {}
        if c3_result is None or not c3_result.outputs:
            return mapping
        signals = c3_result.outputs.get("verified_signals") or []
        if not isinstance(signals, list):
            return mapping
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            symbol = str(sig.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            direction = str(sig.get("direction") or "").strip().upper()
            if direction not in ("LONG", "SHORT"):
                direction = "LONG"  # 默认 LONG
            mapping[symbol] = direction
        return mapping

    @staticmethod
    def _get_entry_price(state: State, symbol: str, fallback: float) -> float:
        """从 state.market.market_data 获取入场价，缺失用 fallback"""
        market = state.market if isinstance(state.market, dict) else {}
        market_data = market.get("market_data") or {}
        if not isinstance(market_data, dict):
            return fallback
        coin_data = market_data.get(symbol) or {}
        if not isinstance(coin_data, dict):
            return fallback
        price = coin_data.get("price")
        if _is_finite(price) and float(price) > 0:
            return float(price)
        return fallback

    @staticmethod
    def _compute_strategy_name(
        directions: List[str],
        prefix: str,
    ) -> str:
        """基于主流方向生成 strategy_name"""
        if not directions:
            return prefix
        long_count = sum(1 for d in directions if d == "LONG")
        short_count = sum(1 for d in directions if d == "SHORT")
        if long_count > short_count:
            suffix = "LONG"
        elif short_count > long_count:
            suffix = "SHORT"
        else:
            suffix = "NEUTRAL"
        return f"{prefix}_{suffix}"

    def execute_core(self, state: State) -> NodeResult:
        """执行计划生成

        流程：
            1. FAIL-OPEN：无 market / 无 C4 / 无 C5 → 空 outputs
            2. 读 C4 position_size/stop_loss/take_profit
            3. 读 C5 optimized_params
            4. 读 C3 verified_signals → direction 映射
            5. 遍历 C4 品种（size>0）→ trade_plan entry
            6. 构建 changeset（symbols + 每品种变更条目）
            7. strategy_name + trace_id
        """
        # 1. FAIL-OPEN
        if not isinstance(state.market, dict):
            return NodeResult(
                node_id="C6",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"trade_plan": {}, "changeset": {},
                         "strategy_name": "", "trace_id": ""},
                error="C6 无 market 数据，降级返回空结果",
            )

        c4_result = state.get_result("C4")
        if c4_result is None or not c4_result.outputs:
            return NodeResult(
                node_id="C6",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"trade_plan": {}, "changeset": {},
                         "strategy_name": "", "trace_id": ""},
                error="C6 无 C4 上游结果，降级返回空结果",
            )

        c5_result = state.get_result("C5")
        if c5_result is None or not c5_result.outputs:
            return NodeResult(
                node_id="C6",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"trade_plan": {}, "changeset": {},
                         "strategy_name": "", "trace_id": ""},
                error="C6 无 C5 上游结果，降级返回空结果",
            )

        c4_outputs = c4_result.outputs
        c5_outputs = c5_result.outputs

        position_size = c4_outputs.get("position_size") or {}
        stop_loss_map = c4_outputs.get("stop_loss") or {}
        take_profit_map = c4_outputs.get("take_profit") or {}

        if not isinstance(position_size, dict) or not position_size:
            return NodeResult(
                node_id="C6",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={"trade_plan": {}, "changeset": {},
                         "strategy_name": "", "trace_id": ""},
                error="C6 C4 position_size 为空",
            )

        optimized_params = c5_outputs.get("optimized_params") or {}
        if not isinstance(optimized_params, dict):
            optimized_params = {}

        c3_result = state.get_result("C3")
        direction_map = self._build_direction_map(c3_result)

        prefix = self._read_config(state)

        trade_plan: Dict[str, Dict[str, Any]] = {}
        changeset: Dict[str, Any] = {"symbols": []}
        directions: List[str] = []

        for symbol, size in position_size.items():
            try:
                size_f = float(size) if _is_finite(size) else 0.0
            except Exception:
                size_f = 0.0
            if size_f <= 0:
                continue  # 过滤零仓位

            sym = str(symbol).strip().upper()
            if not sym:
                continue

            direction = direction_map.get(sym, "LONG")
            directions.append(direction)

            sl = float(stop_loss_map.get(sym, 0.0) or 0.0) if isinstance(stop_loss_map, dict) else 0.0
            tp = float(take_profit_map.get(sym, 0.0) or 0.0) if isinstance(take_profit_map, dict) else 0.0

            entry_price = self._get_entry_price(state, sym, fallback=sl)
            if entry_price <= 0:
                entry_price = tp  # 极端 fallback

            params = optimized_params.get(sym)
            if not isinstance(params, dict):
                params = {}

            trade_plan[sym] = {
                "symbol": sym,
                "direction": direction,
                "size": size_f,
                "entry_price": entry_price,
                "stop_loss": sl,
                "take_profit": tp,
                "params": params,
            }

            changeset["symbols"].append(sym)
            changeset[sym] = {
                "direction": direction,
                "size": size_f,
                "stop_loss": sl,
                "take_profit": tp,
            }

        strategy_name = self._compute_strategy_name(directions, prefix)
        trace_id = str(uuid4())

        # confidence 基于品种数和方向一致性
        if directions:
            consistency = max(directions.count("LONG"), directions.count("SHORT")) / len(directions)
            confidence = 0.4 + 0.4 * consistency
        else:
            confidence = 0.0

        return NodeResult(
            node_id="C6",
            status=NodeStatus.SUCCESS,
            confidence=float(confidence),
            outputs={
                "trade_plan": trade_plan,
                "changeset": changeset,
                "strategy_name": strategy_name,
                "trace_id": trace_id,
            },
        )
