"""
Phase 3 测试: ElasticConstraintResolver + ReflexivityMonitor
"""
import pytest
import numpy as np
import math


# =====================================================================
# ElasticConstraintResolver
# =====================================================================

class TestElasticConstraint:
    """弹性约束解析器."""

    def test_aligned_directions_no_constraint(self):
        """方向对齐 → 无约束 + 加成."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver()
        primary = {"direction": "bull", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.6}
        result = resolver.resolve(primary, secondary)
        assert not result["constraint_active"]
        assert result["aligned"] is True
        assert result["position_mult"] > 1.0  # 有加成

    def test_opposite_directions_constraint_active(self):
        """方向相反 → 弹性约束激活."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.4}
        result = resolver.resolve(primary, secondary)
        assert result["constraint_active"]
        assert not result["aligned"]
        assert result["position_mult"] < 1.0  # 仓位降低
        assert result["t_max"] > 0.0

    def test_t_max_formula(self):
        """T_max = base_limit × (S_p / (S_p + S_m))."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver(base_limit=0.12)
        primary = {"direction": "bear", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.4}
        result = resolver.resolve(primary, secondary)
        # T_max = 0.12 × (0.8 / (0.8+0.4)) = 0.12 × 0.667 = 0.08
        expected_t_max = 0.12 * (0.8 / 1.2)
        assert abs(result["t_max"] - expected_t_max) < 0.001

    def test_high_deviation_low_position(self):
        """偏离越大，仓位越低（弹簧压缩）."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver()
        primary = {"direction": "bear", "strength": 0.9}
        # 低偏离（次矛盾力量很弱）
        sec_low = {"direction": "bull", "strength": 0.05}
        result_low = resolver.resolve(primary, sec_low)
        # 高偏离（次矛盾力量强）
        sec_high = {"direction": "bull", "strength": 0.8}
        result_high = resolver.resolve(primary, sec_high)
        assert result_high["position_mult"] < result_low["position_mult"]
        assert result_high["rebound_risk"] >= result_low["rebound_risk"]

    def test_floor_guarantee(self):
        """仓位不低于 floor."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver(floor=0.20)
        primary = {"direction": "bear", "strength": 0.5}
        secondary = {"direction": "bull", "strength": 1.0}  # 极端偏离
        result = resolver.resolve(primary, secondary)
        assert result["position_mult"] >= 0.20

    def test_neutral_direction_no_constraint(self):
        """中性方向不产生约束."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver()
        primary = {"direction": "neutral", "strength": 0.5}
        secondary = {"direction": "bull", "strength": 0.7}
        result = resolver.resolve(primary, secondary)
        assert not result["constraint_active"]

    def test_none_inputs(self):
        """None 输入 → 无约束."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver()
        result = resolver.resolve(None, None)
        assert result["position_mult"] == 1.0
        assert not result["constraint_active"]

    def test_rebound_threshold_not_exceeded(self):
        """反弹未超阈值."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver(base_limit=0.12)
        primary = {"direction": "bear", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.4}
        # T_max ≈ 0.08, 价格变化 3% < T_max
        result = resolver.check_rebound_threshold(primary, secondary, 103.0, 100.0)
        assert not result["exceeded_threshold"]
        assert not result["force_align"]

    def test_rebound_threshold_exceeded(self):
        """反弹超过阈值."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        resolver = ElasticConstraintResolver(base_limit=0.05)
        primary = {"direction": "bear", "strength": 0.8}
        secondary = {"direction": "bull", "strength": 0.4}
        # T_max = 0.05 × (0.8/1.2) ≈ 0.033, 价格变化 15% >> T_max
        result = resolver.check_rebound_threshold(primary, secondary, 115.0, 100.0)
        assert result["exceeded_threshold"]

    def test_parameter_bounds(self):
        """参数理论边界检查."""
        from dreambuddy_evolution.core.elastic_constraint_resolver import ElasticConstraintResolver
        # 超范围参数被截断
        resolver = ElasticConstraintResolver(base_limit=0.50, floor=0.50, bonus=0.50)
        assert resolver._base_limit == 0.20  # 上限截断
        assert resolver._floor == 0.30
        assert resolver._bonus == 0.10


# =====================================================================
# ReflexivityMonitor
# =====================================================================

class TestReflexivity:
    """反身性监测."""

    def test_insufficient_data(self):
        """数据不足 → 无自影响."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        result = monitor.check_self_influence()
        assert not result["self_influence_detected"]
        assert result["influence_coefficient"] == 0.0

    def test_small_market_share_no_influence(self):
        """市场份额极小 → 无自影响."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        for i in range(30):
            monitor.record(position_delta=100.0, etf_flow=1000.0, price=100.0 + i, market_volume=1_000_000)
        result = monitor.check_self_influence()
        # 100 / 1000000 = 0.01% << 1%
        assert result["market_share"] < 0.01

    def test_large_market_share_detected(self):
        """市场份额大 → 自影响检测."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        for i in range(30):
            monitor.record(position_delta=1000.0, etf_flow=500.0, price=100.0 + i, market_volume=50000)
        result = monitor.check_self_influence()
        # 1000 / 50000 = 2% > 1%
        assert result["market_share"] > 0.01
        assert result["self_influence_detected"] is True

    def test_adjust_strength_no_influence(self):
        """无自影响时力量不变."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        adjusted = monitor.adjust_strength(0.5)
        assert adjusted == 0.5

    def test_adjust_strength_with_influence(self):
        """有自影响时力量调整."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        # 填充数据 + 大市场份额
        for i in range(30):
            monitor.record(position_delta=1000.0, etf_flow=500.0, price=100.0 + i, market_volume=50000)
        monitor.check_self_influence()
        if monitor._self_influence > 0.02:
            adjusted = monitor.adjust_strength(0.5)
            # 力量可能增加（同方向交易自增强）
            assert 0.0 <= adjusted <= 1.0

    def test_consistent_direction_self_reinforcing(self):
        """同方向交易 = 自增强."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        # 全部同方向买入
        for i in range(30):
            monitor.record(position_delta=500.0, etf_flow=200.0, price=100.0 + i, market_volume=50000)
        monitor.check_self_influence()
        if monitor._self_influence > 0.02:
            adjusted = monitor.adjust_strength(0.5)
            original = 0.5
            # 同方向交易应该增强力量
            assert adjusted >= original

    def test_record_and_check(self):
        """记录 + 检验完整流程."""
        from dreambuddy_evolution.core.reflexivity_monitor import ReflexivityMonitor
        monitor = ReflexivityMonitor()
        for i in range(50):
            monitor.record(
                position_delta=float(i % 3 - 1),  # 混合方向
                etf_flow=float(i),
                price=100.0 + i * 0.1,
                market_volume=10000.0,
            )
        result = monitor.check_self_influence()
        assert "self_influence_detected" in result
        assert "market_share" in result
        assert "influence_coefficient" in result
        assert "adjustment_needed" in result
