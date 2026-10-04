"""
C8 绩效归因节点

Classic Pipeline C0-C8 八阶段流水线终点（第九阶段）。
对已平仓交易做归因分析，反馈到记忆系统形成认知闭环。

迁移自 ml_trade_service.py 的 attribution/performance 相关路由（无标准函数名匹配）。
原实现依赖数据库 / 全局 CONFIG / 复杂归因引擎，
本节点采用与 C0-C7 一致的轻量级简化策略：
- pnl_attribution: 按品种/方向分解盈亏 + 总盈亏 + 胜率
- lessons: 基于盈亏/胜率生成经验教训字符串
- memory_feedback: 结构化数据供认知记忆系统 record

设计原则（遵循优雅改动原则）：
- 不依赖数据库 / 全局 CONFIG / 复杂归因引擎
- closed_trades 从 state.config 或 state.market 读取（双源）
- 无 C7 上游或无 closed_trades → FAIL-OPEN 返回 SUCCESS + 空 outputs

inputs:
    - 上游 C7: state.get_result("C7").outputs["exec_log"]（含 trace_id）
    - state.config["closed_trades"] 或 state.market["closed_trades"]: list[dict]
      每项含: symbol, direction, entry_price, exit_price, size, pnl(可选)
outputs:
    - pnl_attribution: dict — {total_pnl, by_symbol, by_direction, trade_count, win_rate}
    - lessons: list[str] — 经验教训
    - memory_feedback: dict — {total_pnl, trace_id, tags, summary}
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _compute_pnl(trade: Dict[str, Any]) -> float:
    """从 trade 计算 pnl：优先用 pnl 字段，否则从 entry/exit/size 计算"""
    pnl = trade.get("pnl")
    if _is_finite(pnl):
        return float(pnl)
    entry = float(trade.get("entry_price") or 0.0) if _is_finite(trade.get("entry_price")) else 0.0
    exit_p = float(trade.get("exit_price") or 0.0) if _is_finite(trade.get("exit_price")) else 0.0
    size = float(trade.get("size") or 0.0) if _is_finite(trade.get("size")) else 0.0
    direction = str(trade.get("direction") or "LONG").strip().upper()
    if direction == "SHORT":
        return (entry - exit_p) * size
    return (exit_p - entry) * size


class C8PerfAttributionNode(BaseNode):
    """C8 绩效归因节点

    轻量级归因：
    - 按品种/方向聚合 pnl
    - 胜率 = 盈利笔数 / 总笔数
    - lessons 基于盈亏表现生成
    - memory_feedback 供认知记忆系统 record

    本节点是 C0-C8 流水线终点。
    """

    node_id = "C8"
    name = "绩效归因"
    description = "交易后归因分析、复盘、反馈到记忆系统"
    chain = "C"
    tags = ["classic", "classic_v2", "attribution", "review", "feedback", "memory"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    @staticmethod
    def _get_closed_trades(state: State) -> List[Dict[str, Any]]:
        """双源读取：config 优先，market 次之"""
        cfg = state.config or {}
        trades = cfg.get("closed_trades")
        if trades is None and isinstance(state.market, dict):
            trades = state.market.get("closed_trades")
        if not isinstance(trades, list):
            return []
        return trades

    @staticmethod
    def _build_lessons(total_pnl: float, win_rate: float, trade_count: int,
                       by_direction: Dict[str, float]) -> List[str]:
        lessons: List[str] = []
        if trade_count == 0:
            return lessons
        if win_rate >= 0.8:
            lessons.append(f"高胜率策略（{win_rate:.1%}），可考虑维持当前信号阈值")
        elif win_rate >= 0.5:
            lessons.append(f"中等胜率（{win_rate:.1%}），建议优化信号过滤条件")
        else:
            lessons.append(f"低胜率（{win_rate:.1%}），建议收紧入场条件或暂停策略")
        if total_pnl > 0:
            lessons.append(f"整体盈利 {total_pnl:.2f}，方向判断正确，可适当放大仓位")
        else:
            lessons.append(f"整体亏损 {abs(total_pnl):.2f}，需复盘止损执行和方向判断")
        # 方向偏好
        long_pnl = by_direction.get("LONG", 0.0)
        short_pnl = by_direction.get("SHORT", 0.0)
        if long_pnl > short_pnl and long_pnl > 0:
            lessons.append("LONG 方向表现更优，市场可能处于上升趋势")
        elif short_pnl > long_pnl and short_pnl > 0:
            lessons.append("SHORT 方向表现更优，市场可能处于下降趋势")
        return lessons

    def execute_core(self, state: State) -> NodeResult:
        """执行绩效归因

        流程：
            1. FAIL-OPEN：无 C7 / 无 closed_trades → 空 outputs
            2. 遍历 closed_trades 计算 pnl
            3. 按品种/方向聚合
            4. 生成 lessons + memory_feedback
        """
        empty_outputs = {"pnl_attribution": {}, "lessons": [], "memory_feedback": {}}

        # 1. FAIL-OPEN
        c7_result = state.get_result("C7")
        if c7_result is None or not c7_result.outputs:
            return NodeResult(
                node_id="C8",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs=empty_outputs,
                error="C8 无 C7 上游结果，降级返回空结果",
            )

        trades = self._get_closed_trades(state)
        if not trades:
            return NodeResult(
                node_id="C8",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs=empty_outputs,
                error="C8 无 closed_trades，降级返回空结果",
            )

        c7_outputs = c7_result.outputs
        exec_log = c7_outputs.get("exec_log") or {}
        trace_id = str(exec_log.get("trace_id") or "") if isinstance(exec_log, dict) else ""

        # 2. 聚合
        by_symbol: Dict[str, float] = {}
        by_direction: Dict[str, float] = {}
        total_pnl = 0.0
        win_count = 0

        for trade in trades:
            if not isinstance(trade, dict):
                continue
            symbol = str(trade.get("symbol") or "").strip().upper()
            direction = str(trade.get("direction") or "LONG").strip().upper()
            if direction not in ("LONG", "SHORT"):
                direction = "LONG"
            pnl = _compute_pnl(trade)
            total_pnl += pnl
            if pnl > 0:
                win_count += 1
            if symbol:
                by_symbol[symbol] = by_symbol.get(symbol, 0.0) + pnl
            by_direction[direction] = by_direction.get(direction, 0.0) + pnl

        trade_count = len(trades)
        win_rate = (win_count / trade_count) if trade_count > 0 else 0.0

        pnl_attribution: Dict[str, Any] = {
            "total_pnl": float(total_pnl),
            "by_symbol": {k: float(v) for k, v in by_symbol.items()},
            "by_direction": {k: float(v) for k, v in by_direction.items()},
            "trade_count": trade_count,
            "win_rate": float(win_rate),
        }

        lessons = self._build_lessons(total_pnl, win_rate, trade_count, by_direction)

        memory_feedback: Dict[str, Any] = {
            "total_pnl": float(total_pnl),
            "trace_id": trace_id,
            "tags": ["classic", "attribution", "perf"],
            "summary": f"trades={trade_count} pnl={total_pnl:.2f} win_rate={win_rate:.1%}",
        }

        confidence = _clip_value(win_rate, 0.0, 1.0)

        return NodeResult(
            node_id="C8",
            status=NodeStatus.SUCCESS,
            confidence=float(confidence),
            outputs={
                "pnl_attribution": pnl_attribution,
                "lessons": lessons,
                "memory_feedback": memory_feedback,
            },
        )


def _clip_value(value: float, low: float, high: float) -> float:
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)
