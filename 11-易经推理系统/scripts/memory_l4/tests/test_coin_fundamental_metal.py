"""B4: 贵金属四信号模块测试 — TDD 先红后绿。

验证四个基本面信号计算（基于已有 SQLite 数据源）：
- rate_reversion：联邦基金利率 → 低利率→正（黄金不生息，低利率=低持有成本）
- liquidity_expansion：M2 同比扩张 → 高扩张→正（货币贬值→黄金升值）
- inflation_pressure：CPI 同比 → 高通胀→正（抗通胀属性）
- risk_hedging_premium：VIX → 高波动→正（避险溢价）
- compute_all：组合四个信号 + FAIL-OPEN
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_metal import (
    compute_rate_reversion,
    compute_liquidity_expansion,
    compute_inflation_pressure,
    compute_risk_hedging_premium,
    compute_all,
)


class TestRateReversion:
    def test_low_rate_positive(self):
        # 0.25% 利率（低利率环境）→ 正信号
        score = compute_rate_reversion(fed_funds_rate=0.25)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_high_rate_negative(self):
        # 5.5% 利率（高利率环境）→ 负信号
        score = compute_rate_reversion(fed_funds_rate=5.5)
        assert -1.0 <= score <= 1.0
        assert score < 0.0

    def test_neutral_rate_near_zero(self):
        # 2.0% 中性利率 → 接近 0
        score = compute_rate_reversion(fed_funds_rate=2.0)
        assert -1.0 <= score <= 1.0
        assert abs(score) < 0.5

    def test_zero_rate_returns_zero(self):
        assert compute_rate_reversion(fed_funds_rate=0.0) == 0.0


class TestLiquidityExpansion:
    def test_high_expansion_positive(self):
        # M2 同比 +15%（大幅扩张）→ 正信号
        score = compute_liquidity_expansion(m2_yoy=15.0)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_contraction_negative(self):
        # M2 同比 -5%（收缩）→ 负信号
        score = compute_liquidity_expansion(m2_yoy=-5.0)
        assert -1.0 <= score <= 1.0
        assert score < 0.0

    def test_zero_growth_returns_zero(self):
        assert compute_liquidity_expansion(m2_yoy=0.0) == 0.0


class TestInflationPressure:
    def test_high_inflation_positive(self):
        # CPI 同比 +5%（高通胀）→ 正信号
        score = compute_inflation_pressure(cpi_yoy=5.0)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_low_inflation_negative(self):
        # CPI 同比 0%（低通胀）→ 负信号
        score = compute_inflation_pressure(cpi_yoy=0.0)
        assert -1.0 <= score <= 1.0
        assert score < 0.0

    def test_moderate_inflation_neutral(self):
        # CPI 同比 2%（美联储目标）→ 接近中性
        score = compute_inflation_pressure(cpi_yoy=2.0)
        assert -1.0 <= score <= 1.0
        assert abs(score) < 0.6


class TestRiskHedgingPremium:
    def test_high_vix_positive(self):
        # VIX=35（高恐慌）→ 正信号（避险溢价）
        score = compute_risk_hedging_premium(vix=35.0)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_low_vix_negative(self):
        # VIX=12（低波动）→ 负信号（无避险需求）
        score = compute_risk_hedging_premium(vix=12.0)
        assert -1.0 <= score <= 1.0
        assert score < 0.0

    def test_moderate_vix_neutral(self):
        # VIX=20（中性）→ 接近 0
        score = compute_risk_hedging_premium(vix=20.0)
        assert -1.0 <= score <= 1.0
        assert abs(score) < 0.5

    def test_zero_vix_returns_zero(self):
        assert compute_risk_hedging_premium(vix=0.0) == 0.0


class TestComputeAll:
    def test_compute_all_returns_four_signals(self):
        with patch("force_vector.coin_fundamental_metal._fetch_fred_series") as mock_fred, \
             patch("force_vector.coin_fundamental_metal._fetch_vix") as mock_vix:
            # 模拟 FRED 数据：series_id → {"value": ..., "timeseries": [...]}
            mock_fred.side_effect = lambda db, sid: {
                "FEDFUNDS": {"value": 0.25, "timeseries": []},
                "M2NS": {"value": 21000.0, "timeseries": [
                    {"date": "2025-01", "value": 18000.0},
                    {"date": "2026-01", "value": 21000.0},
                ]},
                "CPIAUCSL": {"value": 315.0, "timeseries": [
                    {"date": "2025-01", "value": 300.0},
                    {"date": "2026-01", "value": 315.0},
                ]},
            }.get(sid, {})
            mock_vix.return_value = 35.0
            signals = compute_all("XAUUSD", db_path="/fake/db.db")
            assert len(signals) == 4
            assert "rate_reversion" in signals
            assert "liquidity_expansion" in signals
            assert "inflation_pressure" in signals
            assert "risk_hedging_premium" in signals

    def test_compute_all_missing_data_returns_zeros(self):
        with patch("force_vector.coin_fundamental_metal._fetch_fred_series", return_value={}), \
             patch("force_vector.coin_fundamental_metal._fetch_vix", return_value=0.0):
            signals = compute_all("XAUUSD", db_path="/fake/db.db")
            assert all(v == 0.0 for v in signals.values())

    def test_compute_all_unknown_coin_returns_zeros(self):
        signals = compute_all("UNKNOWN", db_path="/fake/db.db")
        assert all(v == 0.0 for v in signals.values())

    def test_compute_all_exception_returns_zeros(self):
        with patch("force_vector.coin_fundamental_metal._fetch_fred_series",
                   side_effect=RuntimeError("boom")):
            signals = compute_all("XAUUSD", db_path="/fake/db.db")
            assert all(v == 0.0 for v in signals.values())
