"""
DreamOS G层 — 上下文压缩器

职责:
    当 State 过大时压缩历史数据:
        1. 保留最近的 N 条 trace
        2. 合并旧节点结果为摘要
        3. 压缩 market/memory 快照（只保留关键字段）
        4. 估算压缩前后大小

压缩策略:
    - trace 保留最近 N 条，旧的合并为摘要
    - results 保留高置信度的，低置信度的只留方向和置信度
    - market 只保留最新值
    - memory 只保留最近 N 条教训
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.utils import safe_json

from .types import CompressedState


class ContextCompressor:
    """上下文压缩器

    用法:
        compressor = ContextCompressor()
        result = compressor.compress(state, keep_recent_trace=5)
        print(result.compression_ratio)  # 0.45
    """

    # 默认配置
    DEFAULT_KEEP_RECENT_TRACE = 10         # 保留最近 N 条 trace
    DEFAULT_KEEP_RECENT_RESULTS = 15       # 保留最近 N 条完整结果
    DEFAULT_MIN_CONFIDENCE = 0.3           # 低于此置信度的结果只留摘要

    def __init__(self,
                 keep_recent_trace: int = DEFAULT_KEEP_RECENT_TRACE,
                 keep_recent_results: int = DEFAULT_KEEP_RECENT_RESULTS,
                 min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        self._keep_trace = keep_recent_trace
        self._keep_results = keep_recent_results
        self._min_confidence = min_confidence

    def compress(self, state: State,
                 keep_recent_trace: Optional[int] = None,
                 keep_recent_results: Optional[int] = None) -> CompressedState:
        """压缩 State

        Args:
            state: 要压缩的状态
            keep_recent_trace: 保留最近 N 条 trace
            keep_recent_results: 保留最近 N 条完整结果

        Returns:
            CompressedState: 压缩信息（注意：会原地修改 state）
        """
        keep_trace = keep_recent_trace or self._keep_trace
        keep_results = keep_recent_results or self._keep_results

        original_size = self._estimate_size(state)

        # ── 压缩 trace ───────────────────────────────
        old_trace_count = len(state.trace)
        if len(state.trace) > keep_trace:
            old_trace = state.trace[:-keep_trace]
            # 将旧 trace 合并为摘要
            summary = self._summarize_trace(old_trace)
            state.trace = state.trace[-keep_trace:]
        else:
            summary = {}
        new_trace_count = len(state.trace)
        removed_trace = old_trace_count - new_trace_count

        # ── 压缩 results ─────────────────────────────
        all_result_ids = list(state.results.keys())
        if len(all_result_ids) > keep_results:
            old_ids = all_result_ids[:-keep_results]
            for nid in old_ids:
                r = state.results[nid]
                # 低置信度的结果只保留摘要
                if r.confidence < self._min_confidence:
                    state.results[nid] = NodeResult(
                        node_id=nid,
                        status=r.status,
                        confidence=r.confidence,
                        direction=r.direction,
                        error=r.error,
                    )

        # ── 压缩 market ──────────────────────────────
        # 只保留最新值（market 本来就是快照，不需要太多历史）
        if state.market and isinstance(state.market, dict):
            # 移除大型数组数据（candles 等）
            for key in list(state.market.keys()):
                val = state.market[key]
                if isinstance(val, list) and len(val) > 20:
                    state.market[key] = val[-5:]  # 只保留最近 5 条

        # ── 压缩 memory ──────────────────────────────
        if state.memory and isinstance(state.memory, dict):
            for key in list(state.memory.keys()):
                val = state.memory[key]
                if isinstance(val, list) and len(val) > 20:
                    state.memory[key] = val[-10:]  # 保留最近 10 条

        compressed_size = self._estimate_size(state)
        compression_ratio = compressed_size / original_size if original_size > 0 else 0.0

        return CompressedState(
            original_size=original_size,
            compressed_size=compressed_size,
            compression_ratio=compression_ratio,
            summary=summary,
            retained_trace_count=new_trace_count,
            removed_trace_count=removed_trace,
        )

    def should_compress(self, state: State, threshold: int = 10000) -> bool:
        """判断是否需要压缩"""
        return self._estimate_size(state) > threshold

    # ── 内部方法 ───────────────────────────────────────

    def _estimate_size(self, state: State) -> int:
        """估算 State 的序列化大小（字节）"""
        try:
            return len(safe_json(state.to_dict()))
        except Exception:
            return 0

    def _summarize_trace(self, old_trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将旧 trace 合并为摘要"""
        if not old_trace:
            return {}

        # 统计
        status_counts: Dict[str, int] = {}
        direction_counts: Dict[str, int] = {}
        avg_confidence = 0.0

        for entry in old_trace:
            status = entry.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

            direction = entry.get("direction")
            if direction:
                direction_counts[direction] = direction_counts.get(direction, 0) + 1

            avg_confidence += entry.get("confidence", 0.0)

        avg_confidence = avg_confidence / len(old_trace) if old_trace else 0.0

        return {
            "compressed_from": len(old_trace),
            "status_counts": status_counts,
            "direction_counts": direction_counts,
            "avg_confidence": round(avg_confidence, 3),
        }
