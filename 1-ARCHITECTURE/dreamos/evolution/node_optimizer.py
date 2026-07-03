"""
DreamOS Evolution — 节点优化建议器

职责:
    1. 根据历史数据生成节点优化建议
    2. 识别低效/冗余节点
    3. 推荐节点重新排序
    4. 建议增删节点

优化类型:
    - add:    新增节点
    - remove: 移除低效节点
    - modify: 修改节点配置/权重
    - reorder: 调整执行顺序
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import defaultdict, Counter

from dreamos.shared.utils import gen_cycle_id
from dreamos.core.graph_store.types import HistoryEntry

from .types import OptimizationSuggestion


class NodeOptimizer:
    """节点优化建议器

    用法:
        optimizer = NodeOptimizer()
        suggestions = optimizer.optimize(history_entries, node_stats)
    """

    # 低效节点阈值
    LOW_SUCCESS_THRESHOLD = 0.5      # 成功率低于此值 → 低效
    LOW_CONTRIBUTION_THRESHOLD = 0.2  # 对最终结果贡献低于此值 → 可移除

    def __init__(self):
        self._suggestions: List[OptimizationSuggestion] = []

    def optimize(self,
                 entries: List[HistoryEntry],
                 node_stats: Optional[Dict[str, Dict[str, Any]]] = None) -> List[OptimizationSuggestion]:
        """生成优化建议

        Args:
            entries: 历史执行记录
            node_stats: 节点统计数据 {node_id: {success_rate, avg_latency, ...}}

        Returns:
            优化建议列表（按优先级排序）
        """
        suggestions: List[OptimizationSuggestion] = []

        if not entries:
            return suggestions

        # ── 链路优化建议 ────────────────────────────
        chain_suggestions = self._analyze_chain_efficiency(entries)
        suggestions.extend(chain_suggestions)

        # ── 节点效率建议 ────────────────────────────
        if node_stats:
            node_suggestions = self._analyze_node_efficiency(node_stats)
            suggestions.extend(node_suggestions)

        # ── 预算优化建议 ────────────────────────────
        budget_suggestions = self._analyze_budget_optimization(entries)
        suggestions.extend(budget_suggestions)

        # 按优先级排序
        priority_order = {0: 0, 1: 1, 2: 2, 3: 3}
        suggestions.sort(key=lambda s: (priority_order.get(s.priority, 2), -s.expected_improvement))

        self._suggestions = suggestions
        return suggestions

    def _analyze_chain_efficiency(self, entries: List[HistoryEntry]) -> List[OptimizationSuggestion]:
        """分析链路效率"""
        suggestions = []

        # 按链路分组统计
        by_chain = defaultdict(list)
        for e in entries:
            if e.planned_chain:
                by_chain[e.planned_chain].append(e)

        if len(by_chain) < 2:
            return suggestions

        # 比较各链路的效果
        chain_performance = {}
        for chain, chain_entries in by_chain.items():
            if len(chain_entries) < 2:
                continue
            avg_conf = sum(e.final_confidence for e in chain_entries) / len(chain_entries)
            non_hold_rate = len([e for e in chain_entries if e.final_action != "HOLD"]) / len(chain_entries)
            chain_performance[chain] = {
                "count": len(chain_entries),
                "avg_confidence": avg_conf,
                "non_hold_rate": non_hold_rate,
                "score": avg_conf * non_hold_rate,
            }

        if len(chain_performance) < 2:
            return suggestions

        # 找出最好和最差的链路
        sorted_chains = sorted(chain_performance.items(), key=lambda x: -x[1]["score"])
        best_chain, best_data = sorted_chains[0]
        worst_chain, worst_data = sorted_chains[-1]
        best_score = best_data["score"]
        worst_score = worst_data["score"]

        if worst_score < best_score * 0.7:
            improvement = (best_score - worst_score) / max(best_score, 0.01)
            suggestions.append(OptimizationSuggestion(
                suggestion_id=gen_cycle_id("sug_chain"),
                target="chain",
                target_id=worst_chain,
                type="modify",
                description=f"{worst_chain} 链路效果不如 {best_chain} 链路，建议优化或减少使用",
                expected_improvement=improvement,
                evidence=f"最佳链路 {best_chain} 得分 {best_score:.2f}，最差链路 {worst_chain} 得分 {worst_score:.2f}",
                priority=1,
            ))

        return suggestions

    def _analyze_node_efficiency(self, node_stats: Dict[str, Dict[str, Any]]) -> List[OptimizationSuggestion]:
        """分析单个节点的效率"""
        suggestions = []

        for node_id, stats in node_stats.items():
            success_rate = stats.get("success_rate", 1.0)

            # 低效节点建议修复或移除
            if success_rate < self.LOW_SUCCESS_THRESHOLD:
                suggestions.append(OptimizationSuggestion(
                    suggestion_id=gen_cycle_id("sug_node"),
                    target="node",
                    target_id=node_id,
                    type="modify",
                    description=f"节点 {node_id} 成功率偏低 ({success_rate:.0%})，建议检查数据源或增加降级",
                    expected_improvement=0.5 - success_rate,
                    evidence=f"成功率 {success_rate:.1%}，低于阈值 {self.LOW_SUCCESS_THRESHOLD:.0%}",
                    priority=1,
                ))

            # 高延迟节点建议优化
            avg_latency = stats.get("avg_latency_ms", 0)
            if avg_latency > 5000:
                suggestions.append(OptimizationSuggestion(
                    suggestion_id=gen_cycle_id("sug_latency"),
                    target="node",
                    target_id=node_id,
                    type="modify",
                    description=f"节点 {node_id} 延迟较高 ({avg_latency:.0f}ms)，建议优化或缓存",
                    expected_improvement=0.1,
                    evidence=f"平均延迟 {avg_latency:.0f}ms",
                    priority=2,
                ))

        return suggestions

    def _analyze_budget_optimization(self, entries: List[HistoryEntry]) -> List[OptimizationSuggestion]:
        """分析预算优化"""
        suggestions = []

        token_usages = [e.total_tokens for e in entries if e.total_tokens > 0]
        if not token_usages:
            return suggestions

        avg_tokens = sum(token_usages) / len(token_usages)

        # Token 使用低但效果好 → 可以降档
        confidences = [e.final_confidence for e in entries if e.final_confidence > 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        if avg_tokens < 3000 and avg_conf > 0.6:
            suggestions.append(OptimizationSuggestion(
                suggestion_id=gen_cycle_id("sug_budget_down"),
                target="config",
                target_id="budget_mode",
                type="modify",
                description=f"Token 消耗低 ({avg_tokens:.0f}) 且效果好，可切换到 lean 模式节省成本",
                expected_improvement=0.3,
                evidence=f"平均 Token {avg_tokens:.0f}，平均置信度 {avg_conf:.1%}",
                priority=2,
            ))

        # Token 使用高但效果差 → 建议优化
        if avg_tokens > 8000 and avg_conf < 0.5:
            suggestions.append(OptimizationSuggestion(
                suggestion_id=gen_cycle_id("sug_budget_up"),
                target="config",
                target_id="prompt_optimization",
                type="modify",
                description=f"Token 消耗高 ({avg_tokens:.0f}) 但效果一般，建议优化 prompt 或减少节点",
                expected_improvement=0.2,
                evidence=f"平均 Token {avg_tokens:.0f}，平均置信度 {avg_conf:.1%}",
                priority=1,
            ))

        return suggestions

    @property
    def suggestions(self) -> List[OptimizationSuggestion]:
        """已生成的优化建议"""
        return list(self._suggestions)
