"""B3: 美股四信号模块测试 — TDD 先红后绿。

验证四个基本面信号计算：
- earnings_stability：盈利 Sharpe → 稳定→正
- pe_mean_reversion：PE 比率 → 高估值→负
- revenue_growth：营收 YoY → 增长→正
- profitability_quality：利润率×ROE → 高质量→正
- compute_all：组合四个信号 + FAIL-OPEN
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_stock import (
    compute_earnings_stability,
    compute_pe_mean_reversion,
    compute_revenue_growth,
    compute_profitability_quality,
    compute_all,
)


class TestEarningsStability:
    def test_earnings_stability_normal(self):
        ts = [{"date": f"Q{i}", "net_income": v} for i, v in enumerate([10e9, 11e9, 10.5e9, 11.5e9], 1)]
        score = compute_earnings_stability(ts)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_earnings_stability_insufficient_returns_zero(self):
        assert compute_earnings_stability([]) == 0.0
        assert compute_earnings_stability([{"net_income": 100}]) == 0.0

    def test_earnings_stability_volatile_negative(self):
        ts = [{"date": f"Q{i}", "net_income": v}
              for i, v in enumerate([1e6, 50e9, 500e6, 80e9, 2e6], 1)]
        score = compute_earnings_stability(ts)
        assert score < 0.0


class TestPEMeanReversion:
    def test_pe_overvalued_negative(self):
        score = compute_pe_mean_reversion(trailing_pe=80.0)
        assert -1.0 <= score <= 1.0
        assert score < 0.0

    def test_pe_undervalued_positive(self):
        score = compute_pe_mean_reversion(trailing_pe=12.0)
        assert score > 0.0

    def test_pe_zero_returns_zero(self):
        assert compute_pe_mean_reversion(trailing_pe=0.0) == 0.0


class TestRevenueGrowth:
    def test_revenue_growth_positive(self):
        score = compute_revenue_growth(revenue_growth=0.5)  # 50% YoY
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_revenue_decline_negative(self):
        score = compute_revenue_growth(revenue_growth=-0.2)  # -20% YoY
        assert score < 0.0

    def test_revenue_zero_growth_returns_zero(self):
        assert compute_revenue_growth(revenue_growth=0.0) == 0.0


class TestProfitabilityQuality:
    def test_high_quality_positive(self):
        score = compute_profitability_quality(operating_margins=0.35, return_on_equity=0.9)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_low_quality_negative(self):
        score = compute_profitability_quality(operating_margins=0.02, return_on_equity=0.01)
        assert score < 0.0

    def test_zero_margins_returns_zero(self):
        assert compute_profitability_quality(operating_margins=0.0, return_on_equity=0.5) == 0.0


class TestComputeAll:
    def test_compute_all_returns_four_signals(self):
        with patch("force_vector.coin_fundamental_stock._fetch_stock_info") as mock_info, \
             patch("force_vector.coin_fundamental_stock._fetch_stock_financials") as mock_fin:
            mock_info.return_value = {
                "trailingPE": 25.0,
                "operatingMargins": 0.35,
                "returnOnEquity": 0.9,
                "revenueGrowth": 0.5,
            }
            mock_fin.return_value = {
                "timeseries": [{"date": f"Q{i}", "net_income": 10e9 + i * 1e9} for i in range(4)],
            }
            signals = compute_all("NVDA", db_path="/fake/db.db")
            assert len(signals) == 4
            assert "earnings_stability" in signals
            assert "pe_mean_reversion" in signals
            assert "revenue_growth" in signals
            assert "profitability_quality" in signals

    def test_compute_all_missing_data_returns_zeros(self):
        with patch("force_vector.coin_fundamental_stock._fetch_stock_info", return_value={}), \
             patch("force_vector.coin_fundamental_stock._fetch_stock_financials", return_value={}):
            signals = compute_all("NVDA", db_path="/fake/db.db")
            assert all(v == 0.0 for v in signals.values())

    def test_compute_all_unknown_coin_returns_zeros(self):
        signals = compute_all("UNKNOWN", db_path="/fake/db.db")
        assert all(v == 0.0 for v in signals.values())

    def test_compute_all_exception_returns_zeros(self):
        with patch("force_vector.coin_fundamental_stock._fetch_stock_info",
                   side_effect=RuntimeError("boom")):
            signals = compute_all("NVDA", db_path="/fake/db.db")
            assert all(v == 0.0 for v in signals.values())
