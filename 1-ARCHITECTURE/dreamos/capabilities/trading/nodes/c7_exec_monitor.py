"""
C7 执行监控节点

Classic Pipeline C0-C8 八阶段流水线第八阶段。
执行 C6 生成的 trade_plan，模拟成交，并生成异常告警。

迁移自 ml_trade_service.py 的 execute/monitor 相关路由（无标准函数名匹配）。
原实现依赖交易所 API / WebSocket / 实时持仓管理，
本节点采用与 C0-C6 一致的轻量级简化策略：
- 从 state.market.market_data 读取当前价格作为成交价
- 模拟全部成交（无部分成交场景），缺价格时该订单未成交
- exec_status: filled（全成交）/partial_filled（部分）/pending（空计划）
- alerts: 滑点超限 + 市场数据缺失

设计原则（遵循优雅改动原则）：
- 不依赖交易所 API / WebSocket / 全局 CONFIG
- 所有输入通过 state.market + state.config + 上游 C6 outputs 提供
- 无 market 或无 C6 上游时降级返回 SUCCESS + pending（FAIL-OPEN）

inputs:
    - 上游 C6: state.get_result("C6").outputs["trade_plan"] + ["trace_id"]
    - state.market: dict, 含:
        - market_data: dict[str, dict], 品种→{price: float}
    - state.config: dict, 可选:
        - exec_slippage_threshold: float (默认 0.02) — 滑点告警阈值（相对偏离）
outputs:
    - exec_status: str — filled/partial_filled/pending
    - filled_orders: list[dict] — 已成交订单（含 symbol/direction/size/filled_price/status）
    - alerts: list[dict] — 告警（type/symbol/message/value）
    - exec_log: dict — 执行日志（total/filled_count/failed_count/trace_id）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


_DEFAULT_SLIPPAGE_THRESHOLD = 0.02


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


class C7ExecMonitorNode(BaseNode):
    """C7 执行监控节点

    轻量级执行模拟：
    - 从 C6 trade_plan 读取订单
    - 从 market_data 获取当前价格作为成交价
    - 缺价格 → 订单未成交 + missing_data alert
    - 滑点超阈值 → slippage alert
    - exec_status 基于成交数统计

    下游 C8 通过 state.get_result("C7").outputs 访问。
    """

    node_id = "C7"
    name = "执行监控"
    description = "执行交易计划 + 实时监控 + 异常干预"
    chain = "C"
    tags = ["classic", "classic_v2", "execution", "monitor", "anomaly"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _read_threshold(state: State) -> float:
        cfg = state.config or {}
        try:
            v = float(cfg.get("exec_slippage_threshold", _DEFAULT_SLIPPAGE_THRESHOLD))
            if not math.isfinite(v) or v <= 0:
                return _DEFAULT_SLIPPAGE_THRESHOLD
            return v
        except Exception:
            return _DEFAULT_SLIPPAGE_THRESHOLD

    @staticmethod
    def _get_market_price(state: State, symbol: str) -> float | None:
        market = state.market if isinstance(state.market, dict) else {}
        market_data = market.get("market_data") or {}
        if not isinstance(market_data, dict):
            return None
        coin_data = market_data.get(symbol) or {}
        if not isinstance(coin_data, dict):
            return None
        price = coin_data.get("price")
        if _is_finite(price) and float(price) > 0:
            return float(price)
        return None

    def execute_core(self, state: State) -> NodeResult:
        """执行监控

        流程：
            1. FAIL-OPEN：无 market / 无 C6 → pending
            2. 遍历 trade_plan，模拟成交
            3. 生成 alerts（滑点/缺失数据）
            4. 计算 exec_status + exec_log
        """
        empty_outputs = {
            "exec_status": "pending",
            "filled_orders": [],
            "alerts": [],
            "exec_log": {},
        }

        # 1. FAIL-OPEN
        if not isinstance(state.market, dict):
            return NodeResult(
                node_id="C7",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs=empty_outputs,
                error="C7 无 market 数据，降级返回 pending",
            )

        c6_result = state.get_result("C6")
        if c6_result is None or not c6_result.outputs:
            return NodeResult(
                node_id="C7",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs=empty_outputs,
                error="C7 无 C6 上游结果，降级返回 pending",
            )

        trade_plan = c6_result.outputs.get("trade_plan") or {}
        if not isinstance(trade_plan, dict) or not trade_plan:
            return NodeResult(
                node_id="C7",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs=empty_outputs,
                error="C7 C6 trade_plan 为空",
            )

        trace_id = str(c6_result.outputs.get("trace_id") or "")
        threshold = self._read_threshold(state)

        filled_orders: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []
        total = 0
        filled_count = 0
        failed_count = 0

        for symbol, plan_entry in trade_plan.items():
            if not isinstance(plan_entry, dict):
                continue
            total += 1
            sym = str(plan_entry.get("symbol") or symbol).strip().upper()
            if not sym:
                sym = str(symbol).strip().upper()

            direction = str(plan_entry.get("direction") or "LONG").strip().upper()
            size = float(plan_entry.get("size") or 0.0) if _is_finite(plan_entry.get("size")) else 0.0
            entry_price = float(plan_entry.get("entry_price") or 0.0) if _is_finite(plan_entry.get("entry_price")) else 0.0

            market_price = self._get_market_price(state, sym)

            if market_price is None:
                failed_count += 1
                alerts.append({
                    "type": "missing_market_data",
                    "symbol": sym,
                    "message": f"{sym} 市场数据缺失，订单未成交",
                    "value": 0.0,
                })
                continue

            # 模拟成交
            filled_orders.append({
                "symbol": sym,
                "direction": direction,
                "size": size,
                "filled_price": market_price,
                "status": "filled",
            })
            filled_count += 1

            # 滑点检查
            if entry_price > 0:
                slippage = abs(market_price - entry_price) / entry_price
                if slippage > threshold:
                    alerts.append({
                        "type": "slippage",
                        "symbol": sym,
                        "message": f"{sym} 滑点 {slippage:.4f} 超过阈值 {threshold:.4f}",
                        "value": float(slippage),
                    })

        # exec_status
        if filled_count == 0:
            exec_status = "pending" if total == 0 else "canceled"
        elif filled_count < total:
            exec_status = "partial_filled"
        else:
            exec_status = "filled"

        exec_log: Dict[str, Any] = {
            "total": total,
            "filled_count": filled_count,
            "failed_count": failed_count,
            "trace_id": trace_id,
        }

        confidence = (filled_count / total) if total > 0 else 0.0

        return NodeResult(
            node_id="C7",
            status=NodeStatus.SUCCESS,
            confidence=float(confidence),
            outputs={
                "exec_status": exec_status,
                "filled_orders": filled_orders,
                "alerts": alerts,
                "exec_log": exec_log,
            },
        )
