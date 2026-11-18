"""RippleEngine 放量门槛动态校准测试（20 日已实现波动率）。"""

import numpy as np
import pytest

from dreambuddy_evolution.engines.ripple_engine import RippleEngine


def _series(sigma_1h: float, n: int = 700, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, sigma_1h, n)
    return 100.0 * np.exp(np.cumsum(rets))


def test_calibrate_low_vol_hits_floor():
    """低波动 → 门槛落到下限 1.30"""
    eng = RippleEngine()
    thr = eng.calibrate_vol_threshold(_series(0.0005))
    assert thr == pytest.approx(1.30, abs=0.02)


def test_calibrate_high_vol_raises_threshold():
    """高波动 → 门槛显著提高，且不超过上限 2.50"""
    eng = RippleEngine()
    low = eng.calibrate_vol_threshold(_series(0.0010))
    high = eng.calibrate_vol_threshold(_series(0.0060))
    assert high > low + 0.2
    assert high <= 2.50


def test_calibrate_insufficient_data_uses_default(monkeypatch):
    """数据不足 48 根 → 回退默认阈值"""
    monkeypatch.delenv("EVOLUTION_RIPPLE_VOL_RATIO", raising=False)
    eng = RippleEngine()
    assert eng.calibrate_vol_threshold([100.0, 101.0]) == pytest.approx(2.0)


def test_detect_uses_passed_threshold():
    """调用方传入的动态门槛优先于实例默认值"""
    eng = RippleEngine()
    src = {
        "r_vector": {"R_up": 0.3, "R_down": 0.7},
        "ess_top_direction": "long",
        "vol_5": 150.0,
        "vol_20": 100.0,  # ratio = 1.5
        "liq_index_change": 0.5,
        "scale_class": "Classical",
    }
    assert eng.detect_ripple_source(src, vol_ratio_threshold=1.4) is True
    assert eng.detect_ripple_source(src) is False  # 默认 2.0
