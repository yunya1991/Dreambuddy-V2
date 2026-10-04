"""测试 classic_pipeline.signals.quant_signal 模块。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# signal_confidence — 基于规则的置信度计算
# ---------------------------------------------------------------------------

class TestSignalConfidence:
    def test_basic_bias(self):
        """基础 bias 直接返回。"""
        from classic_pipeline.signals.quant_signal import signal_confidence
        rules = {"trend": {"bias": 0.7}}
        conf = signal_confidence("s1", "trend", None, {}, rules)
        assert conf == 0.7

    def test_feature_weight(self):
        """特征权重加权。"""
        from classic_pipeline.signals.quant_signal import signal_confidence
        rules = {"trend": {"bias": 0.5, "w": {"macd_slope": 0.1}}}
        conf = signal_confidence("s1", "trend", None, {"macd_slope": 2.0}, rules)
        assert conf == 0.7  # 0.5 + 0.1 * 2.0

    def test_tag_bias(self):
        """tag 偏差加权。"""
        from classic_pipeline.signals.quant_signal import signal_confidence
        rules = {"trend": {"bias": 0.5, "tag_bias": {"breakout": 0.3}}}
        conf = signal_confidence("s1", "trend", "breakout", {}, rules)
        assert conf == 0.8

    def test_clipped_to_0_1(self):
        """置信度被裁剪到 [0, 1]。"""
        from classic_pipeline.signals.quant_signal import signal_confidence
        rules = {"trend": {"bias": 2.0}}
        conf = signal_confidence("s1", "trend", None, {}, rules)
        assert conf == 1.0

    def test_missing_rule_returns_1(self):
        """无规则时返回 1.0。"""
        from classic_pipeline.signals.quant_signal import signal_confidence
        conf = signal_confidence("s1", "unknown", None, {}, {})
        assert conf == 1.0


# ---------------------------------------------------------------------------
# strategy_weight — 策略权重调整
# ---------------------------------------------------------------------------

class TestStrategyWeight:
    def test_weight_within_floor_cap(self):
        """权重在 [floor, cap] 范围内。"""
        from classic_pipeline.signals.quant_signal import strategy_weight
        w = strategy_weight(current=1.0, perf={"pf": 1.5, "maxdd": 0.05}, config={})
        assert 0.25 <= w <= 2.0

    def test_high_pf_increases_weight(self):
        """高 PF 提升权重。"""
        from classic_pipeline.signals.quant_signal import strategy_weight
        w_high = strategy_weight(current=1.0, perf={"pf": 2.0, "maxdd": 0.05}, config={})
        w_low = strategy_weight(current=1.0, perf={"pf": 0.5, "maxdd": 0.05}, config={})
        assert w_high > w_low


# ---------------------------------------------------------------------------
# compute — quant 信号计算
# ---------------------------------------------------------------------------

class TestCompute:
    def test_compute_returns_signal_structure(self):
        """compute 返回 signals/dominant_direction/confidence。"""
        from classic_pipeline.signals.quant_signal import compute

        np.random.seed(42)
        n = 100
        close = 100 * np.cumprod(1 + np.random.randn(n) * 0.01)
        df = pd.DataFrame({
            "open": close * 0.999, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": np.random.randint(1000, 5000, n),
        })

        result = compute(df, config={})
        assert "signals" in result
        assert "dominant_direction" in result
        assert "confidence" in result

    def test_compute_fail_open(self):
        """异常时返回 FAIL-OPEN。"""
        from classic_pipeline.signals.quant_signal import compute
        result = compute(None, config={})
        assert result["dominant_direction"] == "neutral"
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# 纯函数验证
# ---------------------------------------------------------------------------

class TestPureFunction:
    def test_no_global_state(self):
        import inspect
        from classic_pipeline.signals import quant_signal
        for name, func in inspect.getmembers(quant_signal, inspect.isfunction):
            if name.startswith("_"):
                continue
            src = inspect.getsource(func)
            assert "TRACKER_STATE" not in src, f"{name} 引用了 TRACKER_STATE"
