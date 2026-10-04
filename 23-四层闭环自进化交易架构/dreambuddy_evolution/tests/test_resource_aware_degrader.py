"""test_resource_aware_degrader.py — 主动降级阶梯单元测试（D3: ds4 SSD streaming 借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 3
硬约束: HC-DS4-04（降级决策可观测）、HC-DS4-05（降级到规则基线时质量≥当前基线）

降级阶梯:
  Level 0 (FULL):        完整深度学习推理
  Level 1 (SIMPLIFIED):  简化推理（跳过路径积分）
  Level 2 (RULE_BASELINE): 规则基线
  Level 3 (FAIL_OPEN):   中性兜底

评估维度:
  - 有效样本数 (< 2000 → 降级)
  - 模型训练状态 (未训练 → 降级)
  - 最近推理耗时 (超时 → 降级)
  - 系统负载 (高负载 → 降级)

覆盖:
  - assess_level 各级别判定
  - degrade_path 路径过滤
  - 降级决策可观测性（日志）
  - FAIL-OPEN 降级到中性兜底
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.core.resource_aware_degrader import (
    ResourceAwareDegrader,
    DegradationLevel,
)


# ==============================================================================
# 1. assess_level 级别判定
# ==============================================================================
class TestAssessLevel:
    """D3: 资源感知降级级别判定"""

    def test_full_level_when_resources_sufficient(self):
        """资源充足 → Level 0 完整推理"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 5000,
            "model_trained": True,
            "inference_time_ms": 50,
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.FULL

    def test_simplified_when_samples_low(self):
        """样本数 < 2000 → Level 1 简化推理"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 1000,
            "model_trained": True,
            "inference_time_ms": 50,
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.SIMPLIFIED

    def test_simplified_when_model_untrained(self):
        """模型未训练 → Level 1 简化推理"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 5000,
            "model_trained": False,
            "inference_time_ms": 50,
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.SIMPLIFIED

    def test_rule_baseline_when_samples_very_low(self):
        """样本数 < 100 → Level 2 规则基线"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 50,
            "model_trained": True,
            "inference_time_ms": 50,
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.RULE_BASELINE

    def test_fail_open_when_inference_timeout(self):
        """推理超时 → Level 3 FAIL-OPEN"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 5000,
            "model_trained": True,
            "inference_time_ms": 10000,  # 超时
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.FAIL_OPEN

    def test_fail_open_when_system_overloaded(self):
        """系统负载过高 → Level 3 FAIL-OPEN"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 5000,
            "model_trained": True,
            "inference_time_ms": 50,
            "system_load": 0.95,  # 高负载
        }
        level = degrader.assess_level(context)
        assert level == DegradationLevel.FAIL_OPEN

    def test_missing_context_defaults_to_full(self):
        """缺少评估维度 → 默认 Level 0（保守不降级）"""
        degrader = ResourceAwareDegrader()
        level = degrader.assess_level({})
        assert level == DegradationLevel.FULL

    def test_combined_factors_pick_most_degraded(self):
        """多个降级因子同时存在 → 取最严重的降级级别"""
        degrader = ResourceAwareDegrader()
        context = {
            "sample_count": 50,          # → RULE_BASELINE
            "model_trained": False,       # → SIMPLIFIED
            "inference_time_ms": 50,
            "system_load": 0.3,
        }
        level = degrader.assess_level(context)
        # 样本极低 → RULE_BASELINE（比 SIMPLIFIED 更严重）
        assert level == DegradationLevel.RULE_BASELINE


# ==============================================================================
# 2. degrade_path 路径过滤
# ==============================================================================
class TestDegradePath:
    """D3: 降级路径过滤"""

    def _make_paths(self):
        return [
            {"path_id": "P1", "source": "deep_reasoning", "score": 0.9},
            {"path_id": "P2", "source": "path_integral", "score": 0.8},
            {"path_id": "P3", "source": "signature", "score": 0.7},
            {"path_id": "P4", "source": "rule_baseline", "score": 0.6},
        ]

    def test_full_level_keeps_all_paths(self):
        """Level 0: 保留所有路径"""
        degrader = ResourceAwareDegrader()
        paths = self._make_paths()
        result = degrader.degrade_path(paths, DegradationLevel.FULL)
        assert len(result) == len(paths)

    def test_simplified_skips_path_integral(self):
        """Level 1: 跳过路径积分路径"""
        degrader = ResourceAwareDegrader()
        paths = self._make_paths()
        result = degrader.degrade_path(paths, DegradationLevel.SIMPLIFIED)
        sources = {p["source"] for p in result}
        assert "path_integral" not in sources
        assert "deep_reasoning" in sources

    def test_rule_baseline_only_rules(self):
        """Level 2: 仅保留规则基线路径"""
        degrader = ResourceAwareDegrader()
        paths = self._make_paths()
        result = degrader.degrade_path(paths, DegradationLevel.RULE_BASELINE)
        sources = {p["source"] for p in result}
        assert sources == {"rule_baseline"}

    def test_fail_open_returns_empty(self):
        """Level 3: 返回空列表（中性兜底）"""
        degrader = ResourceAwareDegrader()
        paths = self._make_paths()
        result = degrader.degrade_path(paths, DegradationLevel.FAIL_OPEN)
        assert result == []

    def test_unknown_source_preserved(self):
        """未知 source 的路径在所有级别都保留（不误删）"""
        degrader = ResourceAwareDegrader()
        paths = [{"path_id": "P9", "source": "unknown_engine", "score": 0.5}]
        result = degrader.degrade_path(paths, DegradationLevel.SIMPLIFIED)
        assert len(result) == 1


# ==============================================================================
# 3. 降级决策可观测性
# ==============================================================================
class TestDegradationObservability:
    """HC-DS4-04: 降级决策必须可观测"""

    def test_decision_logged(self, caplog):
        """降级决策产生日志"""
        import logging
        degrader = ResourceAwareDegrader()
        with caplog.at_level(logging.INFO):
            context = {"sample_count": 50, "model_trained": True}
            level = degrader.assess_level(context)
        # 应有降级相关日志
        assert any("degrad" in r.message.lower() or "level" in r.message.lower()
                   for r in caplog.records)

    def test_decision_returns_reason(self):
        """assess_level 返回降级原因"""
        degrader = ResourceAwareDegrader()
        context = {"sample_count": 50, "model_trained": True}
        result = degrader.assess_level_with_reason(context)
        assert "level" in result
        assert "reason" in result
        assert result["reason"] != ""


# ==============================================================================
# 4. 降级阶梯完整性
# ==============================================================================
class TestDegradationLevels:
    """D3: 降级级别常量完整性"""

    def test_level_ordering(self):
        """降级级别数值递增（越高级别降级越严重）"""
        assert DegradationLevel.FULL < DegradationLevel.SIMPLIFIED
        assert DegradationLevel.SIMPLIFIED < DegradationLevel.RULE_BASELINE
        assert DegradationLevel.RULE_BASELINE < DegradationLevel.FAIL_OPEN

    def test_level_names(self):
        """级别名称可识别"""
        assert DegradationLevel.FULL.name == "FULL"
        assert DegradationLevel.SIMPLIFIED.name == "SIMPLIFIED"
        assert DegradationLevel.RULE_BASELINE.name == "RULE_BASELINE"
        assert DegradationLevel.FAIL_OPEN.name == "FAIL_OPEN"
