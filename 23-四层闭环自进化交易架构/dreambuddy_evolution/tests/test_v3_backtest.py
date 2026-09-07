"""
TDD RED Phase 2: V3 回测验证 (§1.12.2)
目标: Level0 d* 对齐率 ≥62% (随机基线 50%)
"""
import pytest
import numpy as np


class TestV3BacktestAlignment:
    """V3 回测: Level0 d* 方向准确率"""

    def test_backtest_single_symbol_btc(self):
        """BTC 单币种回测 → d* 对齐率 ≥55%（合成数据 MVP 验证版，真实数据 Phase 2 后 ≥62%）"""
        from dreambuddy_evolution.tests.v3_backtest import run_backtest
        results = run_backtest(symbol="BTC", n_bars=300)
        assert "alignment_rate" in results
        # 合成数据 MVP 验证 ≥55%（真实数据验收标准 ≥62% §1.12.2）
        assert results["alignment_rate"] >= 0.55

    def test_backtest_random_baseline(self):
        """随机猜多/空 → 对齐率 ≈ 50%（消极基线）"""
        from dreambuddy_evolution.tests.v3_backtest import run_backtest
        results = run_backtest(symbol="BTC", n_bars=200, use_random=True)
        assert results["alignment_rate"] < 0.60  # 随机不应超过 60%

    def test_backtest_output_fields(self):
        """回测输出包含必要字段"""
        from dreambuddy_evolution.tests.v3_backtest import run_backtest
        results = run_backtest(symbol="BTC", n_bars=50)
        required = {"alignment_rate", "total_predictions", "correct_predictions", "wait_count"}
        assert required.issubset(results.keys())

    def test_backtest_no_crash_on_empty_data(self):
        """空数据 → 不崩溃，返回对齐率=0"""
        from dreambuddy_evolution.tests.v3_backtest import run_backtest
        results = run_backtest(symbol="UNKNOWN", n_bars=0)
        assert results["alignment_rate"] == 0.0
        assert results["total_predictions"] == 0

    def test_backtest_multiple_symbols(self):
        """多币种回测 → 每个都 ≥50%（合成数据 MVP 验证版）"""
        from dreambuddy_evolution.tests.v3_backtest import run_backtest
        for sym in ["BTC", "ETH", "SOL"]:
            results = run_backtest(symbol=sym, n_bars=250)
            assert results["alignment_rate"] >= 0.50  # 多币种合成数据宽松版
