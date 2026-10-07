"""
TDD-PRE-003: ContradictionShiftAccumulator 数据采集修复

修复项:
  - detect_shift() 返回值增加 consecutive_count 字段
  - 质变事件落盘到 quality_change_log.jsonl（解决内存列表重启丢失问题）
  - structural_break_threshold 临时默认 0.4（修复 fallback 状态下不可触发问题）
"""
import json
import os

import numpy as np
import pytest


def _make_contradictions(dim: str, strength: float, direction: str = "bull",
                        weak_dim: str = "technical", weak_strength: float = 0.2):
    """构造矛盾列表，始终包含一个弱 technical 作为旧主矛盾追踪对象."""
    return [
        {"dimension": dim, "timeframe": "short", "direction": direction,
         "normalized_strength": strength},
        {"dimension": weak_dim, "timeframe": "short", "direction": "bull",
         "normalized_strength": weak_strength},
        {"dimension": "macro", "timeframe": "long", "direction": "bear",
         "normalized_strength": 0.3},
    ]


class TestConsecutiveCountField:
    """detect_shift 返回值应包含 consecutive_count 字段."""

    def test_shift_returns_consecutive_count(self):
        """质变事件返回值应包含 consecutive_count 字段."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator

        acc = ContradictionShiftAccumulator(persistence=5)
        # 1 条 technical + 4 条 fundamental = 5 条，recent[0] 为 technical
        acc.record(_make_contradictions("technical", 0.8))
        for _ in range(4):
            acc.record(_make_contradictions("fundamental", 0.9, "bear"))

        structural_break = {
            "volatility_regime_shift": {"detected": True, "method": "simple_threshold"},
            "correlation_break": None,
            "market_form_shift": None,
            "any_structural_break": True,
        }
        result = acc.detect_shift(structural_break)

        assert result is not None
        assert "consecutive_count" in result, "质变返回值必须包含 consecutive_count 字段"
        assert result["consecutive_count"] >= 1
        assert isinstance(result["consecutive_count"], int)

    def test_no_shift_no_consecutive_count(self):
        """未检测到质变时返回 None（无 consecutive_count）."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator

        acc = ContradictionShiftAccumulator(persistence=5)
        for _ in range(7):
            acc.record(_make_contradictions("technical", 0.8))
        # 无结构性断裂
        assert acc.detect_shift({"volatility_regime_shift": None,
                                 "correlation_break": None,
                                 "market_form_shift": None,
                                 "any_structural_break": False}) is None


class TestQualityChangeLogPersistence:
    """质变事件落盘到 quality_change_log.jsonl."""

    def test_quality_change_log_written(self, tmp_path):
        """检测到质变时应写入 quality_change_log.jsonl."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator

        log_path = tmp_path / "quality_change_log.jsonl"
        acc = ContradictionShiftAccumulator(
            persistence=5,
            quality_change_log_path=str(log_path),
        )
        acc.record(_make_contradictions("technical", 0.8))
        for _ in range(4):
            acc.record(_make_contradictions("fundamental", 0.9, "bear"))

        structural_break = {
            "volatility_regime_shift": {"detected": True, "method": "simple_threshold"},
            "correlation_break": None,
            "market_form_shift": None,
            "any_structural_break": True,
        }
        result = acc.detect_shift(structural_break)

        assert result is not None
        assert log_path.exists(), "质变事件应写入 quality_change_log.jsonl"

        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert "timestamp" in record
        assert "consecutive_count" in record
        assert record["consecutive_count"] == result["consecutive_count"]
        assert "shifted_from" in record
        assert "shifted_to" in record
        assert "structural_break_type" in record

    def test_quality_change_log_not_written_when_no_shift(self, tmp_path):
        """未检测到质变时不应写入日志."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator

        log_path = tmp_path / "quality_change_log.jsonl"
        acc = ContradictionShiftAccumulator(
            persistence=5,
            quality_change_log_path=str(log_path),
        )
        for _ in range(7):
            acc.record(_make_contradictions("technical", 0.8))

        acc.detect_shift({"volatility_regime_shift": None,
                          "correlation_break": None,
                          "market_form_shift": None,
                          "any_structural_break": False})

        assert not log_path.exists(), "未质变时不应创建日志文件"


class TestStructuralBreakThresholdDefault:
    """structural_break_threshold 临时默认 0.4."""

    def test_threshold_default_is_0_4(self):
        """质变共识阈值默认应为 0.4（修复 fallback 状态下 1.0 不可触发问题）."""
        from dreambuddy_evolution.core import contradiction_shift_accumulator as csa

        # 模块级常量应暴露 0.4
        threshold = getattr(csa, "STRUCTURAL_BREAK_THRESHOLD", None)
        assert threshold == 0.4, (
            f"STRUCTURAL_BREAK_THRESHOLD 应为 0.4（fallback 状态下 1.0 不可触发），实际: {threshold}"
        )
