"""
Phase 3.5: 验证回流闭环 TDD 测试
SPEC-主要矛盾识别与最小阻力路径设计.md §4.6

矛盾论 §矛盾转化: 验证失败 → 降低矛盾权重, 验证成功 → 升级
HC-AGI-22: weight_factor ∈ [0.3, 1.5], 下限 0.3 防止矛盾权重归零
"""
from __future__ import annotations

import pytest


class TestContradictionFeedback:
    """验证回流闭环单元测试"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        assert ContradictionFeedback is not None

    def test_feedback_success_increases_weight(self):
        """验证成功 → 权重升级"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {"direction": "long", "strength": 0.5, "dimension": "C3"}
        outcome = {"success": True, "pnl": 0.1, "n_trials": 5}
        result = fb.adjust_weight(primary, outcome)
        assert result["weight_adjustment"]["weight_factor"] > 1.0

    def test_feedback_failure_decreases_weight(self):
        """验证失败 → 权重降级"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {"direction": "long", "strength": 0.5, "dimension": "C3"}
        outcome = {"success": False, "pnl": -0.05, "fail_streak": 2}
        result = fb.adjust_weight(primary, outcome)
        assert result["weight_adjustment"]["weight_factor"] < 1.0

    def test_feedback_weight_floor_0_3(self):
        """HC-AGI-22: weight_factor 下限 0.3"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {"direction": "long", "strength": 0.5}
        # 连续失败 10 次 → weight_factor 应被截断到 0.3
        outcome = {"success": False, "fail_streak": 10}
        result = fb.adjust_weight(primary, outcome)
        assert result["weight_adjustment"]["weight_factor"] >= 0.3

    def test_feedback_weight_ceiling_1_5(self):
        """HC-AGI-22: weight_factor 上限 1.5"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {"direction": "long", "strength": 0.5}
        outcome = {"success": True, "n_trials": 100}  # 大量验证
        result = fb.adjust_weight(primary, outcome)
        assert result["weight_adjustment"]["weight_factor"] <= 1.5

    def test_feedback_preserves_primary_fields(self):
        """返回结果保留 primary_contradiction 原有字段"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {
            "direction": "long", "strength": 0.5, "dimension": "C3",
            "cause_score": 0.6, "continuation_score": 0.7,
        }
        outcome = {"success": True, "n_trials": 3}
        result = fb.adjust_weight(primary, outcome)
        assert result["direction"] == "long"
        assert result["dimension"] == "C3"
        assert "weight_adjustment" in result

    def test_feedback_fail_open_on_exception(self):
        """异常 FAIL-OPEN → 返回原 primary + 默认权重"""
        from dreambuddy_evolution.core.contradiction_feedback import (
            ContradictionFeedback,
        )
        fb = ContradictionFeedback()
        primary = {"direction": "long", "strength": 0.5}
        # 传入畸形 outcome
        result = fb.adjust_weight(primary, "not_a_dict")  # type: ignore
        assert "weight_adjustment" in result
        assert result["weight_adjustment"]["weight_factor"] == 1.0  # 默认
