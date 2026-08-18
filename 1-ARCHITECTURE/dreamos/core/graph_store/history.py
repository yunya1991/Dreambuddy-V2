"""
DreamOS G层 — 历史回放

职责:
    1. 存储每次执行的完整记录
    2. 按条件查询历史记录
    3. 识别历史模式（相似场景的决策结果）
    4. 从历史中学习（哪些意图/链路更有效）

存储:
    - 内存存储（默认）
    - 可选文件存储（持久化）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import deque
from datetime import datetime

from dreamos.shared.state import State

from .types import HistoryEntry, ReplayResult


class HistoryReplay:
    """历史回放管理器

    用法:
        history = HistoryReplay(max_entries=200)

        # 记录一次执行
        history.record(state, report_dict)

        # 查询历史
        entries = history.query(intent_type="TREND_FOLLOWING", limit=10)

        # 识别模式
        patterns = history.find_patterns()
    """

    def __init__(self, max_entries: int = 200):
        self._entries: deque = deque(maxlen=max_entries)
        self._max = max_entries

    def record(self, state: State, report: Optional[Dict[str, Any]] = None) -> HistoryEntry:
        """记录一次执行

        Args:
            state: 执行完成后的状态
            report: C 层的执行报告字典

        Returns:
            HistoryEntry: 记录条目
        """
        intent = state.intent or {}
        plan = state.plan or {}

        entry = HistoryEntry(
            cycle_id=state.cycle_id,
            intent_type=intent.get("intent_type", ""),
            planned_chain=plan.get("planned_chain", ""),
            final_action=state.final_action or "",
            final_confidence=state.final_confidence,
            total_tokens=report.get("total_tokens", 0) if report else 0,
            total_latency_ms=report.get("total_latency_ms", 0) if report else 0,
            success_rate=report.get("success_rate", 0) if report else 0,
            node_count=report.get("executed_nodes", 0) if report else 0,
            early_terminated=report.get("early_terminated", False) if report else False,
            snapshot=self._create_snapshot(state),
        )

        self._entries.append(entry)
        return entry

    def query(self,
              intent_type: Optional[str] = None,
              final_action: Optional[str] = None,
              chain: Optional[str] = None,
              min_confidence: float = 0.0,
              limit: int = 20) -> List[HistoryEntry]:
        """查询历史记录

        Args:
            intent_type: 按意图类型过滤
            final_action: 按最终方向过滤
            chain: 按链路过滤
            min_confidence: 最低置信度
            limit: 返回数量上限

        Returns:
            匹配的历史记录列表
        """
        results = []
        for entry in reversed(self._entries):
            if intent_type and entry.intent_type != intent_type:
                continue
            if final_action and entry.final_action != final_action:
                continue
            if chain and entry.planned_chain != chain:
                continue
            if entry.final_confidence < min_confidence:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def find_patterns(self, limit: int = 10) -> Dict[str, Any]:
        """识别历史模式

        Returns:
            模式分析结果
        """
        if not self._entries:
            return {"total": 0}

        # 统计
        intent_counts: Dict[str, int] = {}
        action_counts: Dict[str, int] = {}
        chain_counts: Dict[str, int] = {}
        action_by_intent: Dict[str, Dict[str, int]] = {}

        avg_confidence = 0.0
        avg_tokens = 0
        avg_latency = 0.0

        for entry in self._entries:
            intent_counts[entry.intent_type] = intent_counts.get(entry.intent_type, 0) + 1
            action_counts[entry.final_action] = action_counts.get(entry.final_action, 0) + 1
            chain_counts[entry.planned_chain] = chain_counts.get(entry.planned_chain, 0) + 1

            if entry.intent_type not in action_by_intent:
                action_by_intent[entry.intent_type] = {}
            action_by_intent[entry.intent_type][entry.final_action] = \
                action_by_intent[entry.intent_type].get(entry.final_action, 0) + 1

            avg_confidence += entry.final_confidence
            avg_tokens += entry.total_tokens
            avg_latency += entry.total_latency_ms

        total = len(self._entries)
        return {
            "total": total,
            "intent_counts": dict(sorted(intent_counts.items(), key=lambda x: -x[1])),
            "action_counts": dict(sorted(action_counts.items(), key=lambda x: -x[1])),
            "chain_counts": dict(sorted(chain_counts.items(), key=lambda x: -x[1])),
            "action_by_intent": action_by_intent,
            "avg_confidence": round(avg_confidence / total, 3),
            "avg_tokens": avg_tokens // total,
            "avg_latency_ms": round(avg_latency / total, 1),
        }

    def get_similar(self, state: State, limit: int = 5) -> List[HistoryEntry]:
        """找到与当前状态相似的历史记录

        简单匹配: 意图类型 + 链路一致
        """
        intent = state.intent or {}
        plan = state.plan or {}
        intent_type = intent.get("intent_type", "")
        chain = plan.get("planned_chain", "")

        return self.query(
            intent_type=intent_type if intent_type else None,
            chain=chain if chain else None,
            limit=limit,
        )

    def replay(self, cycle_id: str) -> Optional[HistoryEntry]:
        """回放指定 cycle 的历史记录"""
        for entry in self._entries:
            if entry.cycle_id == cycle_id:
                return entry
        return None

    @property
    def total(self) -> int:
        return len(self._entries)

    def all_entries(self) -> List[HistoryEntry]:
        """获取所有历史记录"""
        return list(self._entries)

    def clear(self) -> int:
        """清空历史"""
        count = len(self._entries)
        self._entries.clear()
        return count

    # ── 内部方法 ───────────────────────────────────────

    def _create_snapshot(self, state: State) -> Dict[str, Any]:
        """创建状态快照（精简版）"""
        return {
            "cycle_id": state.cycle_id,
            "final_action": state.final_action,
            "final_confidence": state.final_confidence,
            "result_count": len(state.results),
            "trace_count": len(state.trace),
        }
