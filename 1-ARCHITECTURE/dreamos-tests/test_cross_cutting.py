"""
DreamOS 横切关注点测试

验证:
    Registry 扩展: YAML加载 / 版本管理 / 依赖检查
    Evolution: 教训提炼 / 差距分析 / 优化建议 / 进化引擎
    Budget: 全局预算 / 成本追踪
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_registry_loader_config():
    """测试注册表从字典配置加载（API节点）"""
    from dreamos.registry import RegistryLoader, NodeRegistry

    registry = NodeRegistry()
    loader = RegistryLoader(registry)

    # 模拟配置 - 用 API 节点（不需要真实函数）
    config = {
        "nodes": [
            {
                "id": "TEST_01",
                "name": "测试API节点",
                "chain": "A",
                "adapter": "api",
                "url": "https://api.example.com/v1/test",
                "method": "POST",
                "tags": ["test"],
                "estimated_tokens": 100,
            },
        ]
    }

    count = loader.load_from_config(config)
    assert count == 1
    assert registry.exists("TEST_01")

    node = registry.get("TEST_01")
    assert node is not None
    assert node.chain == "A"
    assert "test" in (node.tags or [])

    print("✅ RegistryLoader 配置加载测试通过")


def test_version_management():
    """测试版本管理"""
    from dreamos.registry import (
        parse_version, compare_versions, satisfies_requirement,
        VersionedNodeMixin, RegistryExtension,
    )
    from dreamos.registry.base import BaseNode
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.shared.state import NodeResult

    # 版本解析
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("2.0") == (2, 0, 0)
    assert parse_version("invalid") == (0, 0, 0)

    # 版本比较
    assert compare_versions("1.2.3", "1.2.0") == 1
    assert compare_versions("1.0.0", "2.0.0") == -1
    assert compare_versions("1.0.0", "1.0.0") == 0

    # 版本要求检查
    assert satisfies_requirement("1.2.3", ">=1.0.0")
    assert satisfies_requirement("1.2.3", "<=2.0.0")
    assert satisfies_requirement("1.2.3", "~1.2.0")
    assert satisfies_requirement("1.2.3", "^1.0.0")
    assert not satisfies_requirement("2.0.0", "^1.0.0")
    assert not satisfies_requirement("1.0.0", ">=2.0.0")

    # VersionedNodeMixin
    class VNode(VersionedNodeMixin, BaseNode):
        node_id = "V0"
        name = "版本节点"
        chain = "A"
        version = "1.0.0"
        requires = {"A0": ">=1.0.0"}
        provides = ["test_capability"]

        def execute_core(self, state):
            return NodeResult(node_id="V0", confidence=0.5)

    assert VNode.version == "1.0.0"
    assert "test_capability" in VNode.provides

    # RegistryExtension
    registry = NodeRegistry()
    vnode = VNode()
    registry.register(vnode)

    ext = RegistryExtension(registry)

    # 依赖检查（缺少 A0）
    result = ext.check_dependencies("V0")
    assert not result.ok
    assert "A0" in result.missing

    # 能力查找
    nodes = ext.find_by_capability("test_capability")
    assert len(nodes) == 1
    assert nodes[0].node_id == "V0"

    # 版本获取
    assert ext.get_version("V0", ">=1.0.0") is not None
    assert ext.get_version("V0", ">=2.0.0") is None

    # 验证
    is_valid, errors = ext.validate()
    assert not is_valid
    assert len(errors) > 0

    print("✅ 版本管理测试通过")


def test_evolution_lessons():
    """测试经验教训提炼"""
    from dreamos.evolution import LessonDistiller
    from dreamos.core.graph_store.types import HistoryEntry

    distiller = LessonDistiller(min_occurrences=2)

    # 准备混合数据：部分 HOLD、部分非 HOLD，覆盖多种情况
    entries = []
    # 3 次 HOLD（低置信度场景）
    for i in range(3):
        entries.append(HistoryEntry(
            cycle_id=f"c{i}",
            intent_type="TREND_FOLLOWING",
            planned_chain="A",
            final_action="HOLD",
            final_confidence=0.3,
            total_tokens=1000,
            success_rate=0.8,
        ))
    # 2 次 LONG（正常场景）
    for i in range(2):
        entries.append(HistoryEntry(
            cycle_id=f"c_long_{i}",
            intent_type="TREND_FOLLOWING",
            planned_chain="A",
            final_action="LONG",
            final_confidence=0.7,
            total_tokens=800,
            success_rate=0.9,
        ))
    # 高预算消耗
    for i in range(3):
        entries.append(HistoryEntry(
            cycle_id=f"c_budget_{i}",
            intent_type="BREAKOUT",
            planned_chain="C",
            final_action="LONG",
            final_confidence=0.6,
            total_tokens=9000,
            success_rate=0.5,
        ))

    lessons = distiller.distill(entries)
    assert len(lessons) > 0, f"期望至少 1 条教训，实际 0 条"

    # 应该有策略类或预算类教训
    categories = {l.category for l in lessons}
    assert len(categories) > 0

    print(f"✅ 经验教训提炼测试通过 ({len(lessons)} 条教训, categories={categories})")


def test_evolution_gap_analysis():
    """测试知行差距分析"""
    from dreamos.evolution import GapAnalyzer
    from dreamos.core.graph_store.types import HistoryEntry

    analyzer = GapAnalyzer()

    # 准备混合数据
    entries = []
    for i in range(4):
        entries.append(HistoryEntry(
            cycle_id=f"c{i}",
            intent_type="TREND_FOLLOWING",
            planned_chain="A",
            final_action="LONG" if i < 2 else "SHORT",  # 方向不一致
            final_confidence=0.6 + i * 0.05,
            success_rate=0.75,
        ))

    result = analyzer.analyze(entries)
    assert result.overall_gap_score >= 0
    assert result.overall_gap_score <= 1
    assert result.direction_accuracy <= 1.0
    assert len(result.gaps) >= 0

    print(f"✅ 知行差距分析测试通过 (gap={result.overall_gap_score:.2f})")


def test_evolution_node_optimizer():
    """测试节点优化建议"""
    from dreamos.evolution import NodeOptimizer
    from dreamos.core.graph_store.types import HistoryEntry

    optimizer = NodeOptimizer()

    entries = []
    for i in range(3):
        entries.append(HistoryEntry(
            cycle_id=f"c{i}",
            intent_type="TREND_FOLLOWING",
            planned_chain="A",
            final_action="LONG",
            final_confidence=0.7,
            total_tokens=1500,
            success_rate=0.8,
        ))
    for i in range(3):
        entries.append(HistoryEntry(
            cycle_id=f"c2{i}",
            intent_type="BREAKOUT",
            planned_chain="C",
            final_action="LONG",
            final_confidence=0.4,
            total_tokens=800,
            success_rate=0.5,
        ))

    node_stats = {
        "A0": {"success_rate": 0.9, "avg_latency_ms": 100},
        "B1": {"success_rate": 0.4, "avg_latency_ms": 6000},
    }

    suggestions = optimizer.optimize(entries, node_stats)
    assert len(suggestions) > 0

    # 应该有低效节点建议
    low_success = [s for s in suggestions if s.target_id == "B1" and s.type == "modify"]
    assert len(low_success) > 0

    print(f"✅ 节点优化建议测试通过 ({len(suggestions)} 条建议)")


def test_evolution_engine():
    """测试进化引擎"""
    from dreamos.evolution import EvolutionEngine
    from dreamos.core.graph_store.types import HistoryEntry
    from dreamos.shared.state import State, NodeResult, new_state

    engine = EvolutionEngine(min_occurrences=2)

    # 累积历史
    for i in range(5):
        state = new_state(cycle_id=f"cycle_{i}")
        state.intent = {"intent_type": "TREND_FOLLOWING"}
        state.plan = {"planned_chain": "A"}
        state.update("A0", NodeResult(node_id="A0", confidence=0.6, direction="LONG"))
        state.final_action = "LONG"
        state.final_confidence = 0.6

        engine.record_from_state(state, {
            "total_tokens": 500,
            "total_latency_ms": 1000,
            "success_rate": 1.0,
        })

    assert engine.history_count == 5

    # 单次差距分析
    gap = engine.analyze_gap(state)
    assert 0 <= gap <= 1

    # 完整进化
    report = engine.evolve()
    assert report.cycles_analyzed == 5
    assert len(report.lessons) >= 0
    assert report.gap_analysis is not None
    assert len(report.suggestions) >= 0
    assert "total_cycles" in report.performance_metrics

    print(f"✅ 进化引擎测试通过 (cycles={report.cycles_analyzed}, lessons={len(report.lessons)}, suggestions={len(report.suggestions)})")


def test_global_budget():
    """测试全局预算管理器"""
    from dreamos.budget import GlobalBudgetManager, BudgetLevel, BUDGET_MODES

    # 三档预算
    assert BUDGET_MODES["lean"]["per_cycle"] == 3000
    assert BUDGET_MODES["standard"]["per_cycle"] == 6000
    assert BUDGET_MODES["full"]["per_cycle"] == 10000

    budget = GlobalBudgetManager(mode="lean")

    # 开始周期
    cycle_id = budget.begin_cycle("test_cycle")
    assert cycle_id == "test_cycle"
    assert budget.used_per_cycle == 0
    assert budget.level() == BudgetLevel.HEALTHY

    # 消耗
    used = budget.consume(1000, layer="sense")
    assert used == 1000
    assert budget.used_per_cycle == 1000
    # 33% 使用率 → healthy (< 40%)
    assert budget.level() == BudgetLevel.HEALTHY

    # 层预算
    sense_budget = budget.layer_budget_per_cycle("sense")
    assert sense_budget > 0

    # can_afford
    assert budget.can_afford(500)
    assert not budget.can_afford(99999)

    # 降级
    assert not budget.should_degrade_llm()  # 还没到紧张

    # 消耗更多（超出周期预算，会被截断）
    budget.consume(4000, layer="compute")
    level = budget.level()
    assert level in (BudgetLevel.CRITICAL, BudgetLevel.EXHAUSTED, BudgetLevel.TIGHT)
    # 实际消耗不会超过预算
    assert budget.used_per_cycle <= budget.per_cycle_budget

    # 结束周期
    total = budget.end_cycle(status="success")
    assert total == budget.per_cycle_budget  # 被截断到上限

    # 状态报告
    status = budget.status()
    assert status["mode"] == "lean"
    assert "per_cycle" in status
    assert "per_day" in status
    assert "per_month" in status

    print(f"✅ 全局预算管理测试通过 (level={budget.level()})")


def test_cost_tracker():
    """测试成本追踪器"""
    from dreamos.budget import CostTracker

    tracker = CostTracker()

    # 记录一些消耗
    tracker.record("cycle1", "A0", 300, layer="compute", success=True)
    tracker.record("cycle1", "A1", 500, layer="compute", success=True)
    tracker.record("cycle2", "A0", 350, layer="compute", success=False)
    tracker.record("cycle2", "B1", 800, layer="compute", success=True)

    assert tracker.total_tokens == 1950
    assert tracker.record_count == 4

    # 按节点查询
    assert tracker.cost_by_node("A0") == 650
    assert tracker.cost_by_cycle("cycle1") == 800
    assert tracker.cost_by_layer("compute") == 1950

    # 节点统计
    stats = tracker.node_stats("A0")
    assert stats["count"] == 2
    assert stats["total_tokens"] == 650
    assert stats["avg_tokens"] == 325.0
    assert stats["success_rate"] == 0.5

    # 汇总
    summary = tracker.summary()
    assert summary["total_tokens"] == 1950
    assert summary["total_cycles"] == 2
    assert len(summary["top_nodes"]) > 0
    assert "compute" in summary["layer_distribution"]

    print(f"✅ 成本追踪测试通过 (total={tracker.total_tokens} tokens)")


def test_budget_cycle():
    """测试预算周期流转"""
    from dreamos.budget import GlobalBudgetManager

    budget = GlobalBudgetManager(mode="lean")

    # 周期1
    budget.begin_cycle("c1")
    budget.consume(2000, layer="compute")
    used1 = budget.end_cycle()
    assert used1 == 2000

    # 周期2 应该重置 cycle_used
    budget.begin_cycle("c2")
    assert budget.used_per_cycle == 0
    # 但 day_used 应该累加
    assert budget.used_per_day == 2000

    budget.consume(1000, layer="sense")
    used2 = budget.end_cycle()

    # 日总消耗
    assert budget.used_per_day == 3000

    # 历史
    history = budget.history()
    assert len(history) == 2

    print(f"✅ 预算周期流转测试通过 (total_cycles={budget.total_cycles})")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DreamOS 横切关注点测试")
    print("=" * 60)

    print("\n── Registry 扩展 ──")
    test_registry_loader_config()
    test_version_management()

    print("\n── Evolution 进化 ──")
    test_evolution_lessons()
    test_evolution_gap_analysis()
    test_evolution_node_optimizer()
    test_evolution_engine()

    print("\n── Budget 预算 ──")
    test_global_budget()
    test_cost_tracker()
    test_budget_cycle()

    print("\n" + "=" * 60)
    print("🎉 所有横切关注点测试通过！")
    print("=" * 60)
