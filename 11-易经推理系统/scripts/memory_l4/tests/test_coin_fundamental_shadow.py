"""B5: 主模块合成 + Shadow JSONL 输出测试 — TDD 先红后绿。

验证 compute_signal 主入口：
- 三类资产分派（crypto/stock/metal）
- 等权合成 fundamental_score
- 等级映射 S/A/B/C
- data_quality + confidence
- Shadow JSONL 追加写入
- FAIL-OPEN 中性默认
- 开关默认 False
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_ranker import (
    CoinFundamentalSignal,
    compute_signal,
    compute_for_coins,
    write_shadow,
    ENABLE_COIN_FUNDAMENTAL_RANKER,
)


class TestComputeSignalDispatch:
    def test_compute_signal_crypto_uni(self):
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value={"revenue_stability": 0.5, "mc_fees_mean_reversion": 0.3,
                                 "tvl_growth_momentum": 0.2, "revenue_quality": 0.4}):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.coin == "UNI"
            assert sig.asset_class == "crypto_usdt"
            assert len(sig.sub_signals) == 4
            assert -1.0 <= sig.fundamental_score <= 1.0

    def test_compute_signal_stock_nvda(self):
        with patch("force_vector.coin_fundamental_ranker.stock_compute_all",
                   return_value={"earnings_stability": 0.6, "pe_mean_reversion": 0.1,
                                 "revenue_growth": 0.5, "profitability_quality": 0.4}):
            sig = compute_signal("NVDA", db_path="/fake/db.db")
            assert sig.coin == "NVDA"
            assert sig.asset_class == "us_stock"
            assert len(sig.sub_signals) == 4

    def test_compute_signal_metal_xauusd(self):
        with patch("force_vector.coin_fundamental_ranker.metal_compute_all",
                   return_value={"rate_reversion": 0.3, "liquidity_expansion": 0.2,
                                 "inflation_pressure": 0.5, "risk_hedging_premium": 0.1}):
            sig = compute_signal("XAUUSD", db_path="/fake/db.db")
            assert sig.coin == "XAUUSD"
            assert sig.asset_class == "precious_metal"
            assert len(sig.sub_signals) == 4

    def test_compute_signal_unknown_coin_returns_neutral(self):
        sig = compute_signal("UNKNOWN", db_path="/fake/db.db")
        assert sig.coin == "UNKNOWN"
        assert sig.fundamental_score == 0.0
        assert sig.rank == "B"
        assert sig.data_quality == "insufficient"
        assert sig.error is not None


class TestRankMapping:
    def test_rank_s_requires_score_above_06_and_two_subsignals_above_05(self):
        sub = {"revenue_stability": 0.7, "mc_fees_mean_reversion": 0.6, "tvl_growth_momentum": 0.3, "revenue_quality": 0.5}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = 0.525 < 0.6 → 不是 S，是 A
            assert sig.rank == "A"

    def test_rank_s_when_score_above_06_and_two_subsignals_above_05(self):
        sub = {"revenue_stability": 0.8, "mc_fees_mean_reversion": 0.7, "tvl_growth_momentum": 0.5, "revenue_quality": 0.3}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = 0.575 < 0.6 → 不是 S
            assert sig.rank == "A"

    def test_rank_s_when_score_above_06_and_two_subsignals_strong(self):
        sub = {"revenue_stability": 0.9, "mc_fees_mean_reversion": 0.8, "tvl_growth_momentum": 0.5, "revenue_quality": 0.3}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = 0.625 > 0.6 且 3 子信号 > 0.5 → S
            assert sig.rank == "S"

    def test_rank_a_when_score_above_03(self):
        sub = {"revenue_stability": 0.4, "mc_fees_mean_reversion": 0.3, "tvl_growth_momentum": 0.2, "revenue_quality": 0.4}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = 0.325 > 0.3 → A
            assert sig.rank == "A"

    def test_rank_b_when_score_neutral(self):
        sub = {"revenue_stability": 0.1, "mc_fees_mean_reversion": -0.1, "tvl_growth_momentum": 0.05, "revenue_quality": -0.05}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = 0.0 → B
            assert sig.rank == "B"

    def test_rank_c_when_score_below_neg_03(self):
        sub = {"revenue_stability": -0.5, "mc_fees_mean_reversion": -0.4, "tvl_growth_momentum": -0.3, "revenue_quality": -0.2}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # mean = -0.35 < -0.3 → C
            assert sig.rank == "C"


class TestDataQuality:
    def test_data_quality_sufficient_all_nonzero(self):
        sub = {"revenue_stability": 0.5, "mc_fees_mean_reversion": 0.3, "tvl_growth_momentum": 0.2, "revenue_quality": 0.4}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.data_quality == "sufficient"

    def test_data_quality_partial_some_zero(self):
        sub = {"revenue_stability": 0.5, "mc_fees_mean_reversion": 0.0, "tvl_growth_momentum": 0.2, "revenue_quality": 0.4}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.data_quality == "partial"

    def test_data_quality_insufficient_all_zero(self):
        sub = {"revenue_stability": 0.0, "mc_fees_mean_reversion": 0.0, "tvl_growth_momentum": 0.0, "revenue_quality": 0.0}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.data_quality == "insufficient"


class TestConfidence:
    def test_confidence_full_coverage(self):
        sub = {"revenue_stability": 0.5, "mc_fees_mean_reversion": 0.3, "tvl_growth_momentum": 0.2, "revenue_quality": 0.4}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.confidence == 1.0

    def test_confidence_half_coverage(self):
        sub = {"revenue_stability": 0.5, "mc_fees_mean_reversion": 0.0, "tvl_growth_momentum": 0.2, "revenue_quality": 0.0}
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value=sub):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert 0.4 <= sig.confidence <= 0.6


class TestShadowJsonl:
    def test_write_shadow_appends_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "shadow.jsonl")
            sig = CoinFundamentalSignal(
                coin="UNI", asset_class="crypto_usdt",
                fundamental_score=0.5, rank="A",
                sub_signals={"revenue_stability": 0.5}, data_quality="sufficient",
                confidence=1.0, timestamp="2026-09-01T12:00:00+08:00",
            )
            write_shadow(sig, jsonl_path)
            assert os.path.exists(jsonl_path)
            with open(jsonl_path) as f:
                line = f.readline()
                rec = json.loads(line)
                assert rec["coin"] == "UNI"
                assert rec["fundamental_score"] == 0.5
                assert rec["rank"] == "A"

    def test_write_shadow_appends_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "shadow.jsonl")
            for coin in ("UNI", "NVDA", "XAUUSD"):
                sig = CoinFundamentalSignal(
                    coin=coin, asset_class="crypto_usdt",
                    fundamental_score=0.3, rank="A",
                    sub_signals={"revenue_stability": 0.3}, data_quality="sufficient",
                    confidence=1.0, timestamp="2026-09-01T12:00:00+08:00",
                )
                write_shadow(sig, jsonl_path)
            with open(jsonl_path) as f:
                lines = f.readlines()
            assert len(lines) == 3

    def test_write_shadow_includes_price_fields_null(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "shadow.jsonl")
            sig = CoinFundamentalSignal(
                coin="UNI", asset_class="crypto_usdt",
                fundamental_score=0.5, rank="A",
                sub_signals={"revenue_stability": 0.5}, data_quality="sufficient",
                confidence=1.0, timestamp="2026-09-01T12:00:00+08:00",
            )
            write_shadow(sig, jsonl_path)
            with open(jsonl_path) as f:
                rec = json.loads(f.readline())
            assert "price_at_signal" in rec
            assert rec["price_at_signal"] is None
            assert "price_7d_after" in rec
            assert rec["price_7d_after"] is None


class TestFailOpen:
    def test_failopen_on_exception_returns_neutral(self):
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   side_effect=RuntimeError("boom")):
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.fundamental_score == 0.0
            assert sig.rank == "B"
            assert sig.data_quality == "insufficient"
            assert sig.error is not None


class TestComputeForCoins:
    def test_compute_for_coins_batch(self):
        with patch("force_vector.coin_fundamental_ranker.crypto_compute_all",
                   return_value={"revenue_stability": 0.3, "mc_fees_mean_reversion": 0.2, "tvl_growth_momentum": 0.1, "revenue_quality": 0.2}), \
             patch("force_vector.coin_fundamental_ranker.stock_compute_all",
                   return_value={"revenue_stability": 0.4, "mc_fees_mean_reversion": 0.1, "tvl_growth_momentum": 0.2, "revenue_quality": 0.3}):
            results = compute_for_coins(["UNI", "NVDA", "UNKNOWN"], db_path="/fake/db.db")
            assert len(results) == 3
            assert results[0].coin == "UNI"
            assert results[1].coin == "NVDA"
            assert results[2].coin == "UNKNOWN"


class TestSwitch:
    def test_enable_switch_default_false(self):
        assert ENABLE_COIN_FUNDAMENTAL_RANKER is False
