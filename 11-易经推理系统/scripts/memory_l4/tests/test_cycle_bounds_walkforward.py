"""T11 验收测试：WalkForward 回测验证

位置: scripts/memory_l4/tests/test_cycle_bounds_walkforward.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_walkforward.py -v

对应 Spec §3bis.9 T_CB8 + §3bis.10 T11。
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


def _make_synthetic_frames(days: int, seed: int = 42) -> list:
    """构造合成数据。"""
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
            regime_probs={},
            top3=[["TREND_BULL", 0.4]],
            consensus=0.7,
            hmm_state=2 if smooth[i] > 0 else 0,
            bocpd_cp_prob=0.01,
            indicators={},
        ))
    return frames


# ================================================================
# T_CB8: WalkForward 回测验证
# ================================================================

class TestWalkForwardMethodExists:
    """验证 walkforward_compare 方法存在。"""

    def test_method_exists(self):
        """MorphCyclePredictor 有 walkforward_compare 方法。"""
        assert hasattr(MorphCyclePredictor, "walkforward_compare")


class TestWalkForwardCompare:
    """验证回测对比逻辑。"""

    def test_returns_mae_for_both_modes(self, tmp_path):
        """walkforward_compare 返回 enabled 和 disabled 两种模式的 MAE。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)
        frames = _make_synthetic_frames(days=200, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        predictor = MorphCyclePredictor(storage)
        result = predictor.walkforward_compare(
            symbol="BTCUSDT",
            train_days=120,
            test_days=20,
            step_days=10,
        )

        assert "enabled_mae" in result
        assert "disabled_mae" in result
        assert isinstance(result["enabled_mae"], float)
        assert isinstance(result["disabled_mae"], float)
        assert result["enabled_mae"] >= 0.0
        assert result["disabled_mae"] >= 0.0
        storage.close()

    def test_returns_comparison_summary(self, tmp_path):
        """返回 comparison 字段：improvement_pct 和 recommended。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)
        frames = _make_synthetic_frames(days=200, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        predictor = MorphCyclePredictor(storage)
        result = predictor.walkforward_compare(
            symbol="BTCUSDT",
            train_days=120,
            test_days=20,
            step_days=10,
        )

        assert "comparison" in result
        comp = result["comparison"]
        assert "improvement_pct" in comp
        assert "recommended" in comp
        # improvement_pct = (disabled_mae - enabled_mae) / disabled_mae × 100
        exp_improvement = (result["disabled_mae"] - result["enabled_mae"]) / max(result["disabled_mae"], 1e-6) * 100
        assert abs(comp["improvement_pct"] - exp_improvement) < 0.1
        storage.close()

    def test_recommended_true_when_improvement_ge_5pct(self, tmp_path):
        """improvement ≥ 5% 时 recommended=True。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)
        frames = _make_synthetic_frames(days=200, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        predictor = MorphCyclePredictor(storage)
        result = predictor.walkforward_compare(
            symbol="BTCUSDT",
            train_days=120,
            test_days=20,
            step_days=10,
        )

        # 如果改善 >= 5%，recommended 应为 True
        if result["comparison"]["improvement_pct"] >= 5.0:
            assert result["comparison"]["recommended"] is True
        else:
            assert result["comparison"]["recommended"] is False
        storage.close()

    def test_returns_per_window_details(self, tmp_path):
        """返回 windows 列表，每个窗口含 forecast_mae_enabled/disabled。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)
        frames = _make_synthetic_frames(days=200, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        predictor = MorphCyclePredictor(storage)
        result = predictor.walkforward_compare(
            symbol="BTCUSDT",
            train_days=120,
            test_days=20,
            step_days=30,
        )

        assert "windows" in result
        assert isinstance(result["windows"], list)
        assert len(result["windows"]) >= 1
        w0 = result["windows"][0]
        assert "forecast_mae_enabled" in w0
        assert "forecast_mae_disabled" in w0
        assert "start_date" in w0
        storage.close()
