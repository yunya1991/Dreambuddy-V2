"""
DreamOS A层 — 预算分配器

职责:
    将 Token 预算分配到各节点

分配策略:
    1. 预留 reserve_ratio 的预算给反射/重试（默认 15%）
    2. 必须节点 (priority=0): 按 estimated_tokens 分配，保底 min_tokens
    3. 高优节点 (priority=1): 剩余预算按权重分配
    4. 可选节点 (priority=2): 剩余预算平均分配，不够则跳过

降级机制:
    - 预算不足时，可选节点先被裁剪
    - 仍然不足时，高优节点降为最小预算
"""

from __future__ import annotations

from typing import List, Optional

from .types import NodeMeta, BudgetAllocation


class BudgetAllocator:
    """预算分配器

    用法:
        allocator = BudgetAllocator(total=6000, mode="standard")
        allocation = allocator.allocate(node_metas)
        # → BudgetAllocation(allocated={"A0": 500, "A1": 800, ...}, reserved=900)
    """

    # 预留比例（给反射/重试/LLM 补充调用）
    RESERVE_RATIO = 0.15

    # 节点最小预算保底
    MIN_TOKENS_PER_NODE = 200

    def __init__(self, total: int = 6000, mode: str = "standard",
                 reserve_ratio: float = None):
        self._total = total
        self._mode = mode
        self._reserve_ratio = reserve_ratio if reserve_ratio is not None else self.RESERVE_RATIO

    def allocate(self, nodes: List[NodeMeta]) -> BudgetAllocation:
        """分配预算到节点

        Args:
            nodes: 选中的节点元信息列表

        Returns:
            BudgetAllocation: 预算分配方案
        """
        if not nodes:
            return BudgetAllocation(total_budget=self._total, mode=self._mode)

        reserved = int(self._total * self._reserve_ratio)
        available = self._total - reserved

        # 按优先级分组
        required = [n for n in nodes if n.priority == 0]
        high_pri = [n for n in nodes if n.priority == 1]
        optional = [n for n in nodes if n.priority == 2]

        allocated = {}

        # ── 第1步: 分配必须节点 ─────────────────────
        for n in required:
            need = max(n.estimated_tokens, self.MIN_TOKENS_PER_NODE)
            # 如果需求超过可用预算的 1/3，限制为 1/3
            cap = available // max(len(required), 1) * 2
            actual = min(need, cap) if cap > 0 else need
            allocated[n.node_id] = actual
            available -= actual

        # ── 第2步: 分配高优节点 ─────────────────────
        if high_pri and available > 0:
            total_est = sum(n.estimated_tokens for n in high_pri) or len(high_pri)
            for n in high_pri:
                weight = n.estimated_tokens / total_est if total_est > 0 else 1 / len(high_pri)
                actual = max(int(available * weight), self.MIN_TOKENS_PER_NODE // 2)
                allocated[n.node_id] = actual

        # ── 第3步: 分配可选节点（剩余预算不够则跳过） ──
        if optional and available > 0:
            per_node = available // len(optional)
            if per_node >= self.MIN_TOKENS_PER_NODE // 2:
                for n in optional:
                    allocated[n.node_id] = per_node
            # else: 可选节点全部不分配

        return BudgetAllocation(
            total_budget=self._total,
            allocated=allocated,
            reserved=reserved,
            mode=self._mode,
        )

    def reallocate(self, allocation: BudgetAllocation,
                   completed_node_id: str,
                   actual_tokens_used: int) -> BudgetAllocation:
        """节点执行后回收/重分配预算

        如果节点用得比分配的少，多出的预算回流到 reserved 池。

        Args:
            allocation: 原分配方案
            completed_node_id: 已完成的节点
            actual_tokens_used: 实际消耗

        Returns:
            更新后的 BudgetAllocation
        """
        original = allocation.allocated.get(completed_node_id, 0)
        if original == 0:
            return allocation

        saved = max(0, original - actual_tokens_used)
        if saved > 0:
            allocation.reserved += saved
            allocation.allocated[completed_node_id] = actual_tokens_used

        return allocation

    def can_add_node(self, allocation: BudgetAllocation,
                     estimated_tokens: int) -> bool:
        """检查是否还能添加一个新节点"""
        return allocation.remaining >= estimated_tokens
