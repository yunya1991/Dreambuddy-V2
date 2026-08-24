"""T4 验收测试：FFT 振幅缩放（动作A，T_CB2）

位置: scripts/memory_l4/tests/test_cycle_bounds_fft_scale.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_fft_scale.py -v

对应 Spec §3bis.4.2 动作A + §3bis.9 T_CB2。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.morph_cycle_predictor import MorphCyclePredictor


def _make_predictor() -> MorphCyclePredictor:
    """构造 MorphCyclePredictor 实例（绕过 __init__ 的 storage 依赖）。"""
    return MorphCyclePredictor.__new__(MorphCyclePredictor)


# ================================================================
# T_CB2: FFT 振幅缩放
# ================================================================

class TestFFTScaleTriggered:
    """验证 FFT 振幅超过 amplitude_cap 时被软缩放。"""

    def test_scale_triggered_when_amplitude_exceeds_cap(self):
        """振幅=2.0 > cap=0.75 → 触发缩放，缩放后振幅 ≤ cap × 1.1。"""
        p = _make_predictor()
        # 构造振幅约 2.0 的曲线（正弦 ±2.0）
        theoretical = np.array([2.0 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {
            "amplitude_cap": 0.75,
            "level_mean": 0.0,
        }

        scaled, info = p._scale_fft_amplitude(theoretical, bounds)

        # 缩放后振幅 ≤ cap × 1.1（允许 10% 容差）
        actual_amp = float(np.std(scaled - bounds["level_mean"]))
        assert actual_amp <= 0.75 * 1.1 + 0.01, f"缩放后振幅 {actual_amp} > cap×1.1"
        assert info["applied"] is True

    def test_scale_factor_recorded(self):
        """返回的 scale_factor 反映实际缩放比例。"""
        p = _make_predictor()
        theoretical = np.array([3.0 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {"amplitude_cap": 0.5, "level_mean": 0.0}

        _, info = p._scale_fft_amplitude(theoretical, bounds)

        assert info["applied"] is True
        assert 0 < info["scale_factor"] < 1.0, "缩放因子应在 (0, 1) 之间"
        assert info["original_amp"] > 0.5


class TestFFTScaleNotTriggered:
    """验证振幅在 cap 之内时不缩放。"""

    def test_no_scale_when_within_bounds(self):
        """振幅=0.3 < cap=0.75 → 不缩放，applied=False。"""
        p = _make_predictor()
        theoretical = np.array([0.3 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {"amplitude_cap": 0.75, "level_mean": 0.0}

        scaled, info = p._scale_fft_amplitude(theoretical, bounds)

        assert info["applied"] is False
        # 曲线应未改变
        np.testing.assert_array_almost_equal(scaled, theoretical)

    def test_no_scale_when_amplitude_equals_cap(self):
        """振幅正好等于 cap → 不缩放（边界情况）。"""
        p = _make_predictor()
        theoretical = np.array([0.75 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {"amplitude_cap": 0.75, "level_mean": 0.0}

        _, info = p._scale_fft_amplitude(theoretical, bounds)

        assert info["applied"] is False


class TestFFTScaleSmoothness:
    """验证缩放后曲线平滑，无突变。"""

    def test_scaled_curve_smooth_no_jumps(self):
        """缩放后曲线平滑：相邻点差分无突变。"""
        p = _make_predictor()
        theoretical = np.array([2.0 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {"amplitude_cap": 0.5, "level_mean": 0.0}

        scaled, _ = p._scale_fft_amplitude(theoretical, bounds)

        # 相邻点差分应平滑（无超过原始曲线最大差分 2 倍的突变）
        orig_diffs = np.abs(np.diff(theoretical))
        scaled_diffs = np.abs(np.diff(scaled))
        max_orig = float(np.max(orig_diffs))
        max_scaled = float(np.max(scaled_diffs))
        assert max_scaled <= max_orig * 2.0 + 0.01, \
            f"缩放后最大差分 {max_scaled} 超过原始 {max_orig} 的 2 倍"

    def test_scaled_curve_preserves_shape(self):
        """缩放后保持正弦波形（峰谷位置不变）。"""
        p = _make_predictor()
        theoretical = np.array([2.0 * np.sin(2 * np.pi * t / 10) for t in range(60)])
        bounds = {"amplitude_cap": 0.5, "level_mean": 0.0}

        scaled, _ = p._scale_fft_amplitude(theoretical, bounds)

        # 原始峰位置
        orig_peak_idx = int(np.argmax(theoretical))
        scaled_peak_idx = int(np.argmax(scaled))
        assert orig_peak_idx == scaled_peak_idx, "缩放后峰位置不应改变"
