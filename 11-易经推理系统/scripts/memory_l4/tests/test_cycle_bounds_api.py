"""T10 验收测试：/api/morph/cycle_bounds API

位置: scripts/memory_l4/tests/test_cycle_bounds_api.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_api.py -v

对应 Spec §3bis.7 API 集成。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

# 将 data_server_fixed.py 所在目录加入 path
DATA_SERVER_DIR = Path(__file__).resolve().parents[2]  # 11-易经推理系统/
sys.path.insert(0, str(DATA_SERVER_DIR))


# ================================================================
# T10: /api/morph/cycle_bounds API
# ================================================================

class TestCycleBoundsAPIExists:
    """验证 get_cycle_bounds 函数和 API 路由存在。"""

    def test_get_cycle_bounds_function_exists(self):
        """data_server_fixed.py 有 get_cycle_bounds 函数。"""
        import data_server_fixed as ds
        assert hasattr(ds, "get_cycle_bounds"), "get_cycle_bounds 函数未定义"

    def test_api_route_registered(self):
        """API 路由 /api/morph/cycle_bounds 已注册。"""
        import data_server_fixed as ds
        # 检查 do_GET 或路由处理中是否包含 /api/morph/cycle_bounds
        import inspect
        source = inspect.getsource(ds)
        assert "/api/morph/cycle_bounds" in source, "API 路由 /api/morph/cycle_bounds 未注册"


class TestCycleBoundsAPIReturn:
    """验证 get_cycle_bounds 返回结构。"""

    def test_returns_ok_and_bounds(self, tmp_path):
        """get_cycle_bounds 返回 ok=True 和 bounds 结构。"""
        # 构造临时 DB 并填充数据
        from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame
        import numpy as np

        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)

        # 构造合成数据
        rng = np.random.default_rng(42)
        frames = []
        for i in range(180):
            from datetime import date, timedelta
            d = date(2026, 1, 1) + timedelta(days=i)
            level = 2.0 * np.sin(2 * np.pi * i / 120.0 + 0.5)
            frames.append(RegimeStateFrame(
                t=d.strftime("%Y-%m-%d"),
                price=40000.0,
                level_raw=float(level),
                trend_raw=0.0,
                level_smooth=float(level),
                trend_smooth=0.0,
                regime_probs={},
                top3=[["TREND_BULL", 0.4]],
                consensus=0.7,
                hmm_state=0,
                bocpd_cp_prob=0.01,
                indicators={},
            ))
        storage.upsert_daily_batch("BTCUSDT", frames)

        # mock _get_predictor 返回使用此 storage 的 predictor
        import data_server_fixed as ds
        from bcrm2.morph_cycle_predictor import MorphCyclePredictor
        original_get_predictor = ds._get_predictor
        predictor = MorphCyclePredictor(storage)
        ds._get_predictor = lambda: predictor

        try:
            result = ds.get_cycle_bounds("BTCUSDT")
            assert result["ok"] is True
            assert "bounds" in result
            assert "cycle_4y" in result
            bounds = result["bounds"]
            required = {"t_rel_current", "phase_hint", "level_lo", "level_hi",
                        "level_mean", "amplitude_cap", "decay_strength"}
            assert set(bounds.keys()) == required
        finally:
            ds._get_predictor = original_get_predictor
            storage.close()

    def test_returns_ok_even_without_trajectory(self, tmp_path):
        """无 trajectory 数据时仍返回 ok=True（cycle4y_theory 不依赖 storage 数据）。"""
        import data_server_fixed as ds
        from bcrm2.storage import EvolutionStorageSQLite
        from bcrm2.morph_cycle_predictor import MorphCyclePredictor

        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)
        predictor = MorphCyclePredictor(storage)
        original_get_predictor = ds._get_predictor
        ds._get_predictor = lambda: predictor

        try:
            result = ds.get_cycle_bounds("BTCUSDT")
            # cycle4y_theory 不依赖 storage，所以即使无 trajectory 也应返回 ok=True
            assert result["ok"] is True
            assert "bounds" in result
        finally:
            ds._get_predictor = original_get_predictor
            storage.close()
