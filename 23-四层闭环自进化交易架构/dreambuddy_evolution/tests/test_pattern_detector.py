"""
Phase 4.1: 价格形态检测器 TDD 测试
SPEC-AGI升级蓝图.md §4.4.1

验收点：
  - 头肩顶检测准确率 ≥60%
  - 提取为独立模块，接入BCRM2.0技术评估
"""
from __future__ import annotations

import numpy as np
import pytest


def _make_head_shoulders_top() -> list[dict]:
    """构造头肩顶K线序列（含左肩峰+回撤→头→右肩→颈线跌破）"""
    klines = []
    # 左肩: 100→110→105 (峰+回撤)
    for i in range(10):
        c = 100.0 + i * 1.0  # 100→109
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 1000.0})
    for i in range(5):
        c = 109.0 - i * 0.8  # 109→105 回撤
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 800.0})
    # 头部: 105→120→110 (更高峰+回撤)
    for i in range(8):
        c = 105.0 + i * 1.875  # 105→118.125
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 700.0})
    for i in range(7):
        c = 118.125 - i * 1.16  # 118→110 回撤
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 600.0})
    # 右肩: 110→114→108 (与左肩对称的峰+回撤)
    for i in range(4):
        c = 110.0 + i * 1.0  # 110→113
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 500.0})
    for i in range(6):
        c = 113.0 - i * 0.83  # 113→108 回撤
        klines.append({"close": c, "high": c + 1.0, "low": c - 1.0, "volume": 450.0})
    # 颈线跌破: 108→95
    for i in range(25):
        c = 108.0 - i * 0.5
        klines.append({"close": c, "high": c + 0.8, "low": c - 1.2, "volume": 1200.0})
    return klines


def _make_uptrend() -> list[dict]:
    """构造纯上涨趋势（无头肩顶）"""
    klines = []
    for i in range(70):
        c = 100.0 + i * 0.5
        klines.append({"close": c, "high": c + 0.5, "low": c - 0.5, "volume": 1000.0})
    return klines


class TestPatternDetector:
    def test_detects_head_shoulders_top(self):
        """头肩顶形态应被检测到"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_head_shoulders_top()
        result = detector.detect_head_shoulders(klines)
        assert result["detected"] is True
        assert result["pattern_type"] == "head_shoulders_top"

    def test_no_head_shoulders_in_uptrend(self):
        """纯上涨趋势不应检测到头肩顶"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_uptrend()
        result = detector.detect_head_shoulders(klines)
        assert result["detected"] is False

    def test_returns_confidence_score(self):
        """检测结果包含置信度[0,1]"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_head_shoulders_top()
        result = detector.detect_head_shoulders(klines)
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["confidence"] > 0.0

    def test_short_sequence_returns_not_detected(self):
        """过短序列（<30根K线）返回未检测"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = [{"close": 100.0 + i} for i in range(10)]
        result = detector.detect_head_shoulders(klines)
        assert result["detected"] is False

    def test_neckline_level_provided(self):
        """检测到头肩顶时返回颈线价位"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_head_shoulders_top()
        result = detector.detect_head_shoulders(klines)
        if result["detected"]:
            assert "neckline" in result
            assert isinstance(result["neckline"], float)


class TestPatternDetectorBCRMIntegration:
    """形态检测器接入BCRM2.0技术评估"""

    def test_bcrm_assessment_includes_pattern(self):
        """BCRM技术评估返回结果包含形态因子"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_head_shoulders_top()
        # BCRM技术评估接口
        assessment = detector.bcrm_technical_assessment(klines)
        assert "pattern_factor" in assessment
        assert "is_reversal_signal" in assessment

    def test_head_shoulders_is_reversal_signal(self):
        """头肩顶作为反向信号（看跌反转）"""
        from dreambuddy_evolution.engines.pattern_detector import PatternDetector
        detector = PatternDetector()
        klines = _make_head_shoulders_top()
        assessment = detector.bcrm_technical_assessment(klines)
        assert assessment["is_reversal_signal"] is True
        # 头肩顶 = 看跌，方向应为 short 或 bearish
        assert assessment.get("direction") in ("short", "bearish", -1)
