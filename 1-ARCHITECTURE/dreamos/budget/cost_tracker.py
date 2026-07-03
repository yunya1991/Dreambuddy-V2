"""
DreamOS Budget — 成本追踪器

职责:
    1. 精细化的成本统计（按层/按节点/按周期）
    2. 成本趋势分析
    3. 预算预警
    4. 成本优化建议
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import defaultdict

from .global_budget import BudgetUsageRecord, BudgetLevel


class CostTracker:
    """成本追踪器

    用法:
        tracker = CostTracker()
        tracker.record("cycle_1", "A0", 300, layer="compute")
        tracker.record("cycle_1", "A1", 500, layer="compute")
        summary = tracker.summary()
    """

    def __init__(self):
        self._records: List[Dict[str, Any]] = []  # flat records
        self._by_cycle: Dict[str, int] = defaultdict(int)
        self._by_layer: Dict[str, int] = defaultdict(int)
        self._by_node: Dict[str, int] = defaultdict(int)
        self._total = 0

    def record(self, cycle_id: str, node_id: str, tokens: int,
               layer: str = "unknown", success: bool = True) -> None:
        """记录一次 token 消耗

        Args:
            cycle_id: 周期 ID
            node_id: 节点 ID
            tokens: 消耗的 token 数
            layer: 所属层
            success: 是否成功
        """
        self._records.append({
            "cycle_id": cycle_id,
            "node_id": node_id,
            "tokens": tokens,
            "layer": layer,
            "success": success,
        })
        self._by_cycle[cycle_id] += tokens
        self._by_layer[layer] += tokens
        self._by_node[node_id] += tokens
        self._total += tokens

    def summary(self) -> Dict[str, Any]:
        """成本汇总"""
        total_cycles = len(self._by_cycle)
        avg_per_cycle = self._total / total_cycles if total_cycles > 0 else 0

        # 最消耗的 Top 5 节点
        top_nodes = sorted(self._by_node.items(), key=lambda x: -x[1])[:5]

        # 按层分布
        layer_distribution = {k: v for k, v in sorted(
            self._by_layer.items(), key=lambda x: -x[1]
        )}

        return {
            "total_tokens": self._total,
            "total_cycles": total_cycles,
            "avg_per_cycle": round(avg_per_cycle, 1),
            "top_nodes": [
                {"node_id": nid, "tokens": tok, "ratio": round(tok / max(1, self._total), 3)}
                for nid, tok in top_nodes
            ],
            "layer_distribution": layer_distribution,
            "total_records": len(self._records),
        }

    def cost_by_node(self, node_id: str) -> int:
        """某节点的总成本"""
        return self._by_node.get(node_id, 0)

    def cost_by_layer(self, layer: str) -> int:
        """某层的总成本"""
        return self._by_layer.get(layer, 0)

    def cost_by_cycle(self, cycle_id: str) -> int:
        """某周期的总成本"""
        return self._by_cycle.get(cycle_id, 0)

    def node_stats(self, node_id: str) -> Dict[str, Any]:
        """某节点的统计"""
        node_records = [r for r in self._records if r["node_id"] == node_id]
        if not node_records:
            return {"count": 0}

        tokens = [r["tokens"] for r in node_records]
        success_rate = len([r for r in node_records if r["success"]]) / len(node_records)

        return {
            "node_id": node_id,
            "count": len(node_records),
            "total_tokens": sum(tokens),
            "avg_tokens": round(sum(tokens) / len(tokens), 1),
            "max_tokens": max(tokens),
            "min_tokens": min(tokens),
            "success_rate": round(success_rate, 3),
        }

    def clear(self) -> int:
        """清空记录，返回清理数量"""
        count = len(self._records)
        self._records.clear()
        self._by_cycle.clear()
        self._by_layer.clear()
        self._by_node.clear()
        self._total = 0
        return count

    @property
    def total_tokens(self) -> int:
        return self._total

    @property
    def record_count(self) -> int:
        return len(self._records)
