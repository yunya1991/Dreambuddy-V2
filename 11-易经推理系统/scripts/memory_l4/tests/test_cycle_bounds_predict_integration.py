"""T7 验收测试：predict() 集成轨道三（T_CB5）

位置: scripts/memory_l4/tests/test_cycle_bounds_predict_integration.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_predict_integration.py -v

对应 Spec §3bis.5 predict() 内三轨编排 + §3bis.9 T_CB5。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp
from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame
from bcrm2.morph_cycle_predictor import MorphCyclePredictor


# ================================================================
# 工具：构造合成 trajectory（复用既有测试模式）
# ================================================================
def _make_synthetic_frames(days: int, seed: int = 42) -> list:
    """构造 days 根日线的合成形态数据。"""
    rng = np.random.default_rng(seed)
    t = np.arange(days, dtype=float)
    level_raw = (2.0 * np.sin(2 * np.pi * t / 120.0 + 0.5)
                 + 1.2 * np.sin(2 * np.pi * t / 60.0 - 0.8)
                 + 0.5 * np.sin(2 * np.pi * t / 30.0 + 0.3)
                 + rng.normal(0, 0.15, days))
    smooth = np.zeros(days)
    smooth[0] = level_raw[0]
    for i in range(1, days):
        smooth[i] = 0.3 * level_raw[i] + 0.7 * smooth[i - 1]
    trend_smooth = np.concatenate([[0.0], np.diff(smooth)])
    price_base = 40000.0 * np.exp(smooth / 10.0)

    frames = []
    for i in range(days):
        from datetime import date, timedelta
        d = date(2026, 1, 1) + timedelta(days=i)
        frames.append(RegimeStateFrame(
            t=d.strftime("%Y-%m-%d"),
            price=float(price_base[i]),
            level_raw=float(level_raw[i]),
            trend_raw=float(trend_smooth[i]),
            level_smooth=float(smooth[i]),
            trend_smooth=float(trend_smooth[i] * 5.0),
            regime_probs={
                "TREND_UP_STRONG": float(max(0, smooth[i]) / 8.0),
                "TREND_BULL": float(max(0, smooth[i]) / 8.0),
                "RANGE_BOUND": float(1.0 - abs(smooth[i]) / 4.0) * 0.5,
                "RANGING": 0.1,
                "MEAN_REVERTING": 0.05,
                "TREND_BEAR": float(max(0, -smooth[i]) / 8.0),
                "STRONG_TREND_BEAR": 0.0,
                "VOLATILE_DROP": 0.0,
            },
            top3=[["TREND_BULL", 0.4], ["RANGE_BOUND", 0.3], ["MEAN_REVERTING", 0.2]],
            consensus=0.7,
            hmm_state=2 if smooth[i] > 0 else 0,
            bocpd_cp_prob=0.01,
            indicators={},
        ))
    return frames


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时 SQLite + 180 根合成数据。"""
    db_path = tmp_path / "evo_test.db"
    storage = EvolutionStorageSQLite(db_path)
    frames = _make_synthetic_frames(days=180, seed=42)
    storage.upsert_daily_batch("BTCUSDT", frames)
    yield storage
    storage.close()


# ================================================================
# T_CB5: predict() 集成轨道三
# ================================================================

class TestPredictBoundsDisabled:
    """CYCLE_BOUNDS_ENABLED=False（默认）时，predict() 行为不变。"""

    def test_disabled_no_cycle_bounds_key(self, tmp_storage):
        """默认关闭时，返回结果中 cycle_bounds 为 None 或不存在。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = False
        try:
            predictor = MorphCyclePredictor(tmp_storage)
            result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            assert result["ok"]
            # 关闭时 cycle_bounds 应为 None
            assert result.get("cycle_bounds") is None
            assert result.get("overshoot_events") is None or result.get("overshoot_events") == []
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original

    def test_disabled_classic_cycle_unchanged(self, tmp_storage):
        """关闭时，classic_curve 不受边界约束影响（与原有逻辑一致）。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = False
        try:
            predictor = MorphCyclePredictor(tmp_storage)
            result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            assert result["ok"]
            # classic_cycle 应存在且非空
            assert len(result["series"]["classic_cycle"]) > 0
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original


class TestPredictBoundsEnabled:
    """CYCLE_BOUNDS_ENABLED=True 时，predict() 应用边界约束。"""

    def test_enabled_returns_cycle_bounds(self, tmp_storage):
        """开启时，返回结果包含 cycle_bounds 且结构正确。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = True
        try:
            predictor = MorphCyclePredictor(tmp_storage)
            result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            assert result["ok"]

            cb = result.get("cycle_bounds")
            assert cb is not None, "cycle_bounds 不应为 None"
            required = {"t_rel_current", "phase_hint", "level_lo", "level_hi",
                        "level_mean", "amplitude_cap", "decay_strength"}
            assert set(cb.keys()) == required
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original

    def test_enabled_returns_overshoot_events(self, tmp_storage):
        """开启时，返回结果包含 overshoot_events 列表（可能为空）。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = True
        try:
            predictor = MorphCyclePredictor(tmp_storage)
            result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            assert result["ok"]

            events = result.get("overshoot_events")
            assert events is not None, "overshoot_events 不应为 None"
            assert isinstance(events, list)
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original

    def test_enabled_current_stage_unchanged(self, tmp_storage):
        """开启时，current_stage（现实曲线）不受边界约束影响。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = True
        try:
            predictor = MorphCyclePredictor(tmp_storage)

            # 先关闭获取基线
            mcp.CYCLE_BOUNDS_ENABLED = False
            result_off = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            current_off = result_off["series"]["current_stage"]

            # 开启获取对比
            mcp.CYCLE_BOUNDS_ENABLED = True
            result_on = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            current_on = result_on["series"]["current_stage"]

            # 现实曲线应完全一致
            assert current_on == current_off, "现实曲线不应受边界约束影响"
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original

    def test_enabled_correction_bounds_info(self, tmp_storage):
        """开启时，correction 字段包含 bounds 子字段。"""
        original = mcp.CYCLE_BOUNDS_ENABLED
        mcp.CYCLE_BOUNDS_ENABLED = True
        try:
            predictor = MorphCyclePredictor(tmp_storage)
            result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)
            assert result["ok"]

            bounds_info = result["correction"].get("bounds")
            assert bounds_info is not None, "correction.bounds 不应为 None"
            assert "applied" in bounds_info
        finally:
            mcp.CYCLE_BOUNDS_ENABLED = original
