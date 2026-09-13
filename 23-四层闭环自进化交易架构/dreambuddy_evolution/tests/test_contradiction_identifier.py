"""
Phase 3.1: PrimaryContradictionIdentifier TDD 测试
SPEC-主要矛盾识别与最小阻力路径设计.md §4.2

核心哲学: 主要矛盾识别 — 矛盾论 §主要矛盾 + §矛盾主要方面
HC-AGI-18: 异常必须 FAIL-OPEN，返回 neutral 兜底
HC-AGI-23: 至少 2 路径才做矛盾分析，单路径返回 neutral
"""
from __future__ import annotations

import pytest


class TestPrimaryContradictionIdentifier:
    """主要矛盾识别器单元测试"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        assert PrimaryContradictionIdentifier is not None

    def test_identify_resonance_all_long(self):
        """共振全多: 多路径方向一致 → 主要矛盾方向 long"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
            {"path_id": "p3", "source": "strategic", "direction": "long",
             "expected_return": 0.2, "confidence": 0.6, "resistance": 0.4},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "long"
        # Fix 4: 全做多 = 完全共识 → 矛盾强度为 0（矛盾 = 对立，非一致）
        # 但方向仍为 long（优势方）
        assert result["strength"] == 0.0
        assert 0.0 <= result["strength"] <= 1.0

    def test_identify_resonance_all_short(self):
        """共振全空: 多路径方向一致 → 主要矛盾方向 short"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "short",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "short",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "short"
        # Fix 4: 全做空 = 完全共识 → 矛盾强度为 0
        assert result["strength"] == 0.0

    def test_arbitrate_conflict_long_vs_short(self):
        """冲突裁决: long vs short 方向冲突 → 4维评分法识别主导者"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.9, "resistance": 0.1},
            {"path_id": "p2", "source": "strategic", "direction": "short",
             "expected_return": 0.05, "confidence": 0.3, "resistance": 0.7},
        ]
        result = identifier.identify(paths, {}, {})
        # long 方力量更大 (0.9 > 0.3)
        assert result["direction"] == "long"
        assert result["confidence"] >= 0.0

    def test_neutral_default_when_single_path(self):
        """HC-AGI-23: 单路径返回 neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_neutral_default_when_empty_paths(self):
        """空路径列表 → neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        result = identifier.identify([], {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_fail_open_on_exception(self):
        """HC-AGI-18: 异常 FAIL-OPEN，返回 neutral 兜底"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        # 传入畸形数据触发异常
        bad_paths = "not_a_list"  # type: ignore
        result = identifier.identify(bad_paths, {}, {})
        assert result["direction"] == "neutral"
        assert result["strength"] == 0.0

    def test_dominance_threshold(self):
        """主导阈值: 力量对比差距大 → 高置信度"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.2, "confidence": 0.95, "resistance": 0.05},
            {"path_id": "p2", "source": "strategic", "direction": "short",
             "expected_return": 0.01, "confidence": 0.1, "resistance": 0.9},
        ]
        result = identifier.identify(paths, {}, {})
        # long 力量远大于 short
        assert result["direction"] == "long"
        assert result["confidence"] > 0.5

    def test_dimension_mapping(self):
        """C1-C8 维度映射: BDSM → C1, BCRM → C3 等"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.9, "resistance": 0.1},
            {"path_id": "p2", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        assert result["dimension"] in ("C1", "C2", "C3", "C4", "C6", "C7", "C8")

    def test_output_has_required_fields(self):
        """输出包含所有必需字段"""
        from dreambuddy_evolution.core.contradiction_identifier import (
            PrimaryContradictionIdentifier,
        )
        identifier = PrimaryContradictionIdentifier()
        paths = [
            {"path_id": "p1", "source": "bcrm", "direction": "long",
             "expected_return": 0.1, "confidence": 0.8, "resistance": 0.2},
            {"path_id": "p2", "source": "bdsm", "direction": "long",
             "expected_return": 0.15, "confidence": 0.7, "resistance": 0.3},
        ]
        result = identifier.identify(paths, {}, {})
        required = {"dimension", "direction", "strength", "confidence",
                    "cause_score", "effort_result", "continuation_score"}
        assert required.issubset(result.keys())
