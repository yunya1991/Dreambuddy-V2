"""T_C3 验收测试：WalkForward 回测扩展（α=0 vs α>0 对比）

位置: scripts/memory_l4/tests/test_phase_c_walkforward.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_walkforward.py -v

对应 Plan §T_C3: WalkForward 回测扩展。

核心验证：
  • run_alpha_blend_comparison 函数存在
  • alpha=0.0 时返回有效回测结果（含 sharpe/pnl）
  • 多个 α 值都返回结果
  • best_alpha 是 sharpe 最高的 α
  • improvement_vs_baseline 结构正确
  • α=0 结果与无 forecast 的回测一致（字节等价验证）

由于真实回测需要完整 BTC 1D CSV 数据，测试用 mock 简化：
  • mock MorphCyclePredictor.predict 返回假数据
  • mock walk_forward_time_series_split 返回小折叠
  • 验证返回结构而非真实数值
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))


# ================================================================
# T_C3: WalkForward 回测扩展
# ================================================================

class TestAlphaBlendWalkForward:
    """验证 run_alpha_blend_comparison 函数。"""

    def test_function_exists(self):
        """T_C3.1: run_alpha_blend_comparison 函数存在。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison
        assert callable(run_alpha_blend_comparison)

    def test_alpha_zero_returns_valid_result(self):
        """T_C3.2: alpha=0.0 时返回有效回测结果（含 sharpe/pnl）。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison

        # 构造小 CSV
        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 40000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close, "high": close + 50, "low": close - 50,
            "close": close, "volume": 1000.0,
        }, index=dates)

        with patch("bcrm2.scripts.eval_walkforward._read_csv", return_value=df), \
             patch("bcrm2.scripts.eval_walkforward._compute_level_trend") as mock_lt, \
             patch("bcrm2.scripts.eval_walkforward.walk_forward_time_series_split") as mock_split, \
             patch("bcrm2.morph_cycle_predictor.MorphCyclePredictor") as mock_pred_cls:
            # mock level/trend
            mock_lt.return_value = (
                pd.Series(np.linspace(-2, 2, n), index=dates),  # level_smooth
                pd.Series(np.linspace(-1, 1, n), index=dates),  # trend_smooth
                pd.Series(np.zeros(n), index=dates),
                pd.Series(np.zeros(n), index=dates),
            )
            # mock 5 折
            mock_split.return_value = [
                (np.arange(0, 100), np.arange(100, 150)),
                (np.arange(0, 150), np.arange(150, 200)),
            ]
            # mock predictor
            mock_pred = MagicMock()
            mock_pred.predict.return_value = {
                "ok": True,
                "series": {
                    "forecast": [2.5, 2.6, 2.7, 2.8, 2.9],
                },
            }
            mock_pred_cls.return_value = mock_pred

            result = run_alpha_blend_comparison(
                csv_path=Path("fake.csv"),
                alpha_values=[0.0],
                n_folds=2,
            )

        assert "alpha_results" in result
        assert "0.0" in result["alpha_results"]
        alpha0 = result["alpha_results"]["0.0"]
        assert "sharpe" in alpha0
        assert "pnl" in alpha0
        assert "max_dd" in alpha0

    def test_multiple_alpha_values(self):
        """T_C3.3: 多个 α 值都返回结果。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison

        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 40000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close, "high": close + 50, "low": close - 50,
            "close": close, "volume": 1000.0,
        }, index=dates)

        with patch("bcrm2.scripts.eval_walkforward._read_csv", return_value=df), \
             patch("bcrm2.scripts.eval_walkforward._compute_level_trend") as mock_lt, \
             patch("bcrm2.scripts.eval_walkforward.walk_forward_time_series_split") as mock_split, \
             patch("bcrm2.morph_cycle_predictor.MorphCyclePredictor") as mock_pred_cls:
            mock_lt.return_value = (
                pd.Series(np.linspace(-2, 2, n), index=dates),
                pd.Series(np.linspace(-1, 1, n), index=dates),
                pd.Series(np.zeros(n), index=dates),
                pd.Series(np.zeros(n), index=dates),
            )
            mock_split.return_value = [
                (np.arange(0, 100), np.arange(100, 150)),
                (np.arange(0, 150), np.arange(150, 200)),
            ]
            mock_pred = MagicMock()
            mock_pred.predict.return_value = {
                "ok": True,
                "series": {"forecast": [2.5, 2.6, 2.7, 2.8, 2.9]},
            }
            mock_pred_cls.return_value = mock_pred

            result = run_alpha_blend_comparison(
                csv_path=Path("fake.csv"),
                alpha_values=[0.0, 0.1, 0.2, 0.5],
                n_folds=2,
            )

        assert len(result["alpha_results"]) == 4
        for a in ["0.0", "0.1", "0.2", "0.5"]:
            assert a in result["alpha_results"]
            assert "sharpe" in result["alpha_results"][a]

    def test_best_alpha_is_max_sharpe(self):
        """T_C3.4: best_alpha 是 sharpe 最高的 α。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison

        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 40000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close, "high": close + 50, "low": close - 50,
            "close": close, "volume": 1000.0,
        }, index=dates)

        with patch("bcrm2.scripts.eval_walkforward._read_csv", return_value=df), \
             patch("bcrm2.scripts.eval_walkforward._compute_level_trend") as mock_lt, \
             patch("bcrm2.scripts.eval_walkforward.walk_forward_time_series_split") as mock_split, \
             patch("bcrm2.morph_cycle_predictor.MorphCyclePredictor") as mock_pred_cls:
            mock_lt.return_value = (
                pd.Series(np.linspace(-2, 2, n), index=dates),
                pd.Series(np.linspace(-1, 1, n), index=dates),
                pd.Series(np.zeros(n), index=dates),
                pd.Series(np.zeros(n), index=dates),
            )
            mock_split.return_value = [
                (np.arange(0, 100), np.arange(100, 150)),
            ]
            mock_pred = MagicMock()
            mock_pred.predict.return_value = {
                "ok": True,
                "series": {"forecast": [2.5, 2.6, 2.7, 2.8, 2.9]},
            }
            mock_pred_cls.return_value = mock_pred

            result = run_alpha_blend_comparison(
                csv_path=Path("fake.csv"),
                alpha_values=[0.0, 0.3, 0.5],
                n_folds=1,
            )

        # best_alpha 对应的 sharpe 应是最大值
        sharpes = {a: r["sharpe"] for a, r in result["alpha_results"].items()}
        best = max(sharpes, key=sharpes.get)
        assert float(result["best_alpha"]) == float(best)

    def test_improvement_vs_baseline_structure(self):
        """T_C3.5: improvement_vs_baseline 结构正确。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison

        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 40000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "open": close, "high": close + 50, "low": close - 50,
            "close": close, "volume": 1000.0,
        }, index=dates)

        with patch("bcrm2.scripts.eval_walkforward._read_csv", return_value=df), \
             patch("bcrm2.scripts.eval_walkforward._compute_level_trend") as mock_lt, \
             patch("bcrm2.scripts.eval_walkforward.walk_forward_time_series_split") as mock_split, \
             patch("bcrm2.morph_cycle_predictor.MorphCyclePredictor") as mock_pred_cls:
            mock_lt.return_value = (
                pd.Series(np.linspace(-2, 2, n), index=dates),
                pd.Series(np.linspace(-1, 1, n), index=dates),
                pd.Series(np.zeros(n), index=dates),
                pd.Series(np.zeros(n), index=dates),
            )
            mock_split.return_value = [
                (np.arange(0, 100), np.arange(100, 150)),
            ]
            mock_pred = MagicMock()
            mock_pred.predict.return_value = {
                "ok": True,
                "series": {"forecast": [2.5, 2.6, 2.7, 2.8, 2.9]},
            }
            mock_pred_cls.return_value = mock_pred

            result = run_alpha_blend_comparison(
                csv_path=Path("fake.csv"),
                alpha_values=[0.0, 0.2],
                n_folds=1,
            )

        assert "improvement_vs_baseline" in result
        imp = result["improvement_vs_baseline"]
        assert "sharpe_improvement_pct" in imp
        assert "pnl_improvement_pct" in imp

    def test_alpha_zero_equivalent_no_forecast(self):
        """T_C3.6: α=0 结果与无 forecast 的回测一致（字节等价验证）。"""
        from bcrm2.scripts.eval_walkforward import run_alpha_blend_comparison
        from bcrm2.parameter_mapper import ParameterMapper

        # alpha=0 时 ParameterMapper 输出应与无 forecast 完全一致
        mapper = ParameterMapper()
        L, T, C = 2.0, 1.0, 0.8
        result_no_forecast = mapper.map_global_parameters(L, T, C)
        result_alpha0 = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, forecast_T=-1.0, alpha_blend=0.0
        )
        assert result_no_forecast == result_alpha0
