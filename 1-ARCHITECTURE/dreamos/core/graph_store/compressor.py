"""
DreamOS G层 — 上下文压缩器

职责:
    当 State 过大时压缩历史数据:
        1. 保留最近的 N 条 trace
        2. 合并旧节点结果为摘要
        3. 压缩 market/memory 快照（只保留关键字段）
        4. 估算压缩前后大小

压缩策略（对齐 24 BAC 锚点语义）:
    - 锚点原文保留并重注入: 目标 / 最新用户指令 / 未完成计划节点
    - trace 保留首部 anchor_nodes 条（跨片连续性）+ 最近 N 条，中间合并为摘要
    - results 保留高置信度的，低置信度的只留方向和置信度（锚点节点除外）
    - market 只保留最新值
    - memory 只保留最近 N 条教训
    - 工具结果只进 trace，不写入摘要（证据外置）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dreamos.shared.state import NodeResult, State
from dreamos.shared.utils import safe_json

from .types import CompressedState

# 计划步骤视为已完成的状态
_DONE_STEP_STATUSES = {"done", "completed", "success", "succeeded", "skipped", "settled"}


class ContextCompressor:
    """上下文压缩器

    用法:
        compressor = ContextCompressor()
        result = compressor.compress(state, keep_recent_trace=5)
        print(result.compression_ratio)  # 0.45
    """

    # 默认配置
    DEFAULT_KEEP_RECENT_TRACE = 10
    DEFAULT_KEEP_RECENT_RESULTS = 15
    DEFAULT_MIN_CONFIDENCE = 0.3

    DEFAULT_RESULT_COUNT_THRESHOLD = 20
    DEFAULT_TOKEN_ESTIMATE_RATIO = 4.0
    DEFAULT_ANCHOR_NODES = 2  # 24 BAC：每片首部强制保留的锚点条数

    def __init__(
        self,
        keep_recent_trace: int = DEFAULT_KEEP_RECENT_TRACE,
        keep_recent_results: int = DEFAULT_KEEP_RECENT_RESULTS,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        result_count_threshold: int = DEFAULT_RESULT_COUNT_THRESHOLD,
        token_estimate_ratio: float = DEFAULT_TOKEN_ESTIMATE_RATIO,
        anchor_nodes: int = DEFAULT_ANCHOR_NODES,
    ):
        self._keep_trace = keep_recent_trace
        self._keep_results = keep_recent_results
        self._min_confidence = min_confidence
        self._result_count_threshold = result_count_threshold
        self._token_estimate_ratio = token_estimate_ratio
        self._anchor_nodes = anchor_nodes

    def compress(
        self,
        state: State,
        keep_recent_trace: Optional[int] = None,
        keep_recent_results: Optional[int] = None,
        anchor_nodes: Optional[int] = None,
    ) -> CompressedState:
        """压缩 State

        Args:
            state: 要压缩的状态
            keep_recent_trace: 保留最近 N 条 trace
            keep_recent_results: 保留最近 N 条完整结果
            anchor_nodes: 首部锚点保留条数（默认 2，对齐 24 BAC）

        Returns:
            CompressedState: 压缩信息（注意：会原地修改 state）
        """
        keep_trace = keep_recent_trace or self._keep_trace
        keep_results = keep_recent_results or self._keep_results
        keep_anchors = self._anchor_nodes if anchor_nodes is None else max(0, anchor_nodes)

        original_size = self._estimate_size(state)

        # ── 锚点：目标 / 最新指令 / 未完成节点（原文保留）──
        anchors = self._collect_anchors(state)
        anchored_ids = set(anchors.get("unfinished_node_ids") or []) | set(
            anchors.get("required_node_ids") or []
        )

        # ── 压缩 trace（首部锚点 + 最近 N 条，中间合并摘要）──
        old_trace_count = len(state.trace)
        if old_trace_count > keep_trace:
            head_anchors = state.trace[:keep_anchors]
            middle = state.trace[keep_anchors:-keep_trace]
            summary = self._summarize_trace(middle)
            state.trace = head_anchors + state.trace[-keep_trace:]
        else:
            summary = {}
        new_trace_count = len(state.trace)
        removed_trace = old_trace_count - new_trace_count

        # ── 压缩 results（锚点节点不降级，保留证据）──
        all_result_ids = list(state.results.keys())
        if len(all_result_ids) > keep_results:
            old_ids = all_result_ids[:-keep_results]
            for nid in old_ids:
                if nid in anchored_ids:
                    continue
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

        # ── 锚点重注入：下一轮组装上下文时必须原文可见 ──
        if anchors:
            if state.extra is None:
                state.extra = {}
            state.extra["compression_anchors"] = anchors

        return CompressedState(
            original_size=original_size,
            compressed_size=compressed_size,
            compression_ratio=compression_ratio,
            summary=summary,
            retained_trace_count=new_trace_count,
            removed_trace_count=removed_trace,
            anchors=anchors,
            anchored_node_ids=sorted(anchored_ids),
        )

    def should_compress(self, state: State, threshold: int = 10000) -> bool:
        """判断是否需要压缩

        触发条件（满足任一即压缩）:
            1. State 估算 token 数超过阈值（文档: 10000 tokens）
            2. 节点结果数超过阈值（文档: 20 个节点）

        阈值单位为 tokens，内部按字节/ratio 换算。
        """
        estimated_tokens = self._estimate_tokens(state)
        if estimated_tokens > threshold:
            return True

        result_count = len(state.results) if state.results else 0
        if result_count >= self._result_count_threshold:
            return True

        return False

    # ── 内部方法 ──────────────────────────

    def _collect_anchors(self, state: State) -> Dict[str, Any]:
        """收集压缩后必须原文保留的锚点（Blueprint 目标 / 最新指令 / 未完成节点）"""
        anchors: Dict[str, Any] = {}

        intent = state.intent if isinstance(state.intent, dict) else {}
        instruction = intent.get("user_message") or intent.get("raw_message") or intent.get("text")
        if instruction:
            anchors["latest_instruction"] = instruction

        blueprint = state.blueprint if isinstance(state.blueprint, dict) else {}
        objective = blueprint.get("objective")
        if objective:
            anchors["objective"] = objective

        unfinished = self._unfinished_node_ids(state)
        if unfinished:
            anchors["unfinished_node_ids"] = unfinished

        required = self._required_node_ids(state)
        if required:
            anchors["required_node_ids"] = required

        return anchors

    def _required_node_ids(self, state: State) -> List[str]:
        """Plan 中 is_required 的节点：其证据不降级（防止关键结论被摘要覆盖）"""
        plan = state.plan if isinstance(state.plan, dict) else {}
        found: List[str] = []
        for item in plan.get("selected_nodes") or []:
            if not isinstance(item, dict) or not item.get("is_required"):
                continue
            node_id = item.get("node_id") or item.get("node") or item.get("id")
            if isinstance(node_id, str) and node_id not in found:
                found.append(node_id)
        return found[:10]

    def _unfinished_node_ids(self, state: State) -> List[str]:
        """从 plan / blueprint 提取未完成节点（已执行或状态为完成的不算）"""
        executed = set(state.results.keys()) if state.results else set()
        found: List[str] = []

        def _scan(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                node_id = item.get("node_id") or item.get("node") or item.get("id")
                if not node_id or not isinstance(node_id, str):
                    continue
                status = str(item.get("status") or "").lower()
                if status in _DONE_STEP_STATUSES:
                    continue
                if node_id in executed:
                    continue
                if node_id not in found:
                    found.append(node_id)

        plan = state.plan if isinstance(state.plan, dict) else {}
        _scan(plan.get("selected_nodes"))
        _scan(plan.get("steps"))
        deferred = plan.get("deferred_nodes")
        if isinstance(deferred, list):
            for node_id in deferred:
                if isinstance(node_id, str) and node_id not in executed and node_id not in found:
                    found.append(node_id)

        blueprint = state.blueprint if isinstance(state.blueprint, dict) else {}
        _scan(blueprint.get("execution_plan"))

        return found[:10]

    def _estimate_tokens(self, state: State) -> int:
        """估算 State 的 token 数（粗略估算：字节数 / ratio）"""
        byte_size = self._estimate_size(state)
        return int(byte_size / self._token_estimate_ratio)

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
