"""Task 4 RED → GREEN tests — SlippageEstimator (AC-1: hand-calculated slip).

FR-0.1: estimator consumes top-N orderbook, walks through levels on the
requested side, produces an EstimateResult with:
  avg_fill_px / slippage_bps / market_impact_cost_usd / walk_depth_level /
  thin_book_warning / fail_open / bids_consumed / asks_consumed.

Coin derivation convention for DEFAULT_SLIPPAGE_MEDIAN_BPS lookup:
  Given inst_id = "BTC-USDT-SWAP" or "BTC/USDT" or "BTC-USDT" the first
  dash-separated token is the base coin. Implementation must do:
  ``inst_id.split("-" or "/")[0]``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))


# =====================================================================
# Fixtures: reusable orderbook mock with deterministic 3-level ladder
# =====================================================================
@pytest.fixture
def adapter_3_level_book():
    """Book snapshot for a coin where mid ≈ 100 (ct_val=1 → 1 contract = 1 coin).
    Asks (buy side eats asks) = [100.1 sz=2, 100.2 sz=3, 100.3 sz=5]
    Bids (sell side eats bids) = [99.9 sz=2,  99.8 sz=3,  99.7 sz=5]
    """
    from tee_core.adapters.okx_adapter import OkxAdapter
    raw = MagicMock()
    raw.get_orderbook.return_value = {
        "ok": True, "ts": "1700000000000",
        "bids": [
            ["99.9", "2", "0", "1"],
            ["99.8", "3", "0", "1"],
            ["99.7", "5", "0", "1"],
        ],
        "asks": [
            ["100.1", "2", "0", "1"],
            ["100.2", "3", "0", "1"],
            ["100.3", "5", "0", "1"],
        ],
    }
    raw.get_contract_info.return_value = (0.01, 1.0)   # lot_sz=0.01, ct_val=1
    return OkxAdapter(raw)


@pytest.fixture
def estimator(adapter_3_level_book):
    # RED: raises until we create estimators/slippage.py module
    from tee_core.estimators.slippage import SlippageEstimator  # noqa
    return SlippageEstimator(client=adapter_3_level_book)


# =====================================================================
# TR-4.1: 手算滑点 — buy sz=4 contracts
#
# Book asks: [100.1 × 2, 100.2 × 3, 100.3 × 5] (ask px × level sz [coins])
# Contract: lot_sz = 0.01 (BTC), ct_val = 1 (1 contract = 0.01 BTC).
# Therefore sz_user = 4 (contracts) = 4 × 0.01 = 0.04 BTC ≈ $4 at $100/BTC.
# The estimator walks levels in COIN units: level sz_coin = level["sz_str"] * ct_val.
# But OKX standard orderbook uses sz as base-coin qty (sz_coin); here we match the
# paper adapter which uses "1.0" meaning 1 base-coin. To keep the math clean and
# aligned with the hand-calculation narrative in AC-1 we treat the level sz as
# *base-coin* and the parent sz we pass is also *base-coin* via a wrapper param.
#
# For this test we pass the equivalent in contracts by scaling:
#   want_coin = 4 (coins)  → sz_contracts = 4 / ct_val / lot_sz
#
# ct_val=1, lot_sz=1 (we'll override get_contract_info for this narrative so
# the math matches 2100.1 + 2100.2 hand calc exactly).
# =====================================================================
class TestHandCalculatedSlippageBuy:
    def test_ac1_buy_4_contracts_hpx_hcalc(self):
        """AC-1 example: buy 4 coins, lot=1 ct=1. Exact slip hand calc."""
        from tee_core.adapters.okx_adapter import OkxAdapter
        from tee_core.estimators.slippage import SlippageEstimator

        raw = MagicMock()
        # Asks coin-level: sz are coins directly (lot=1, ct=1)
        raw.get_orderbook.return_value = {
            "ok": True, "ts": "1",
            "bids": [["99", "10", "0", "1"]],
            "asks": [
                ["100.1", "2", "0", "1"],
                ["100.2", "3", "0", "1"],
                ["100.3", "5", "0", "1"],
            ],
        }
        raw.get_contract_info.return_value = (1.0, 1.0)   # lot_sz=1 ct_val=1

        est = SlippageEstimator(OkxAdapter(raw))
        r = est.estimate(inst_id="X-USDT-SWAP", notional_usdt=None,
                         sz_contracts=4.0, side="buy", decision_px=100.0)

        # Hand calc:
        #   level 0: fill 2 coins @ 100.1  → cost = 200.2
        #   level 1: fill 2 coins @ 100.2  → cost = 200.4 (partial)
        #   total coins = 4, total cost = 400.6 → avg = 100.15
        #   slippage = (100.15 - 100)/100 * 10000 = 15 bps
        assert r.avg_fill_px == pytest.approx(100.15, rel=1e-8), (
            f"avg_fill_px hand-mismatch. Got {r.avg_fill_px}"
        )
        assert r.slippage_bps == pytest.approx(15.0, rel=1e-6), (
            f"slippage_bps hand-mismatch. Got {r.slippage_bps}"
        )
        # market_impact = (avg - decision) * sz_contracts * ct_val
        #               = 0.15 * 4 * 1 = 0.6 base-coin units → $ at decision mid?
        # We'll define impact = sum over each fill (fill_px - decision_px) * fill_coin
        #                    = 0.10*2 + 0.20*2 = 0.20+0.40 = 0.60 coin-dollars
        # i.e. $0.60 if decision_px is 100 and quote is USD. We compute as
        # base-coin impact * decision_px * ct_val = $60… or simpler: in USDT
        # the impact is straightforward: extra paid vs decision:
        #     total_paid - sz_coins * decision_px = 400.6 - 4*100 = $0.60
        assert r.market_impact_cost_usd == pytest.approx(0.60, rel=1e-6)
        assert r.walk_depth_level == 2          # consumed depths 0 and 1
        assert r.thin_book_warning is False     # 4 < (2+3+5=10) book coins
        assert r.fail_open is False
        assert len(r.asks_consumed) > 0         # side=buy → eats asks

    def test_ac1_sell_4_contracts_hand_calc(self):
        """Mirror: sell 4 coins eats bids. Expected avg_fill_px = 99.85,
        slip = (99.85 - 100)/100*10000 = -15 bps (negative = execution gain)."""
        from tee_core.adapters.okx_adapter import OkxAdapter
        from tee_core.estimators.slippage import SlippageEstimator

        raw = MagicMock()
        raw.get_orderbook.return_value = {
            "ok": True, "ts": "1",
            "bids": [
                ["99.9", "2", "0", "1"],
                ["99.8", "3", "0", "1"],
                ["99.7", "5", "0", "1"],
            ],
            "asks": [["101", "10", "0", "1"]],
        }
        raw.get_contract_info.return_value = (1.0, 1.0)

        est = SlippageEstimator(OkxAdapter(raw))
        r = est.estimate(inst_id="X-USDT-SWAP", notional_usdt=None,
                         sz_contracts=4.0, side="sell", decision_px=100.0)

        # Hand calc:
        #   level 0: 2 coins @ 99.9 → 199.8
        #   level 1: 2 coins @ 99.8 → 199.6
        #   total = 399.4 → avg = 99.85
        #   slip = (99.85 - 100)/10010000 = -15 bps
        #   impact = 400 - 399.4 = $0.60 saved → use negative impact for sells
        #   Estimator impact defined as positive = worse than decision (costs
        #   more / receives less). For sell: impact = szdec - received
        #         = 400 - 399.4 = $0.60.
        assert r.avg_fill_px == pytest.approx(99.85, rel=1e-8)
        assert r.slippage_bps == pytest.approx(-15.0, rel=1e-6)
        assert r.market_impact_cost_usd == pytest.approx(0.60, rel=1e-6)
        assert r.walk_depth_level == 2
        assert r.thin_book_warning is False
        assert len(r.bids_consumed) > 0


# =====================================================================
# TR-4.2: thin_book_warning — parent sz exceeds total ask depth
# =====================================================================
class TestThinBookWarning:
    def test_buy_depletes_book_raises_flag(self):
        from tee_core.adapters.okx_adapter import OkxAdapter
        from tee_core.estimators.slippage import SlippageEstimator

        raw = MagicMock()
        # asks total = 2 + 3 + 5 = 10 coins. Request = 20 → thin.
        raw.get_orderbook.return_value = {
            "ok": True, "ts": "1",
            "bids": [],
            "asks": [
                ["100.1", "2", "0", "1"],
                ["100.2", "3", "0", "1"],
                ["100.3", "5", "0", "1"],
            ],
        }
        raw.get_contract_info.return_value = (1.0, 1.0)
        est = SlippageEstimator(OkxAdapter(raw))
        r = est.estimate(inst_id="X", sz_contracts=20.0, side="buy",
                         notional_usdt=None, decision_px=100.0)

        # Only 10 coins can fill: avg_fill_px = last vwap of full 10 coins
        #   vwap = (2100.1 + 3100.2 + 5100.3) / 10 = (200.2+300.6+501.5)/10 = 1002.3/10 = 100.23
        assert r.avg_fill_px == pytest.approx(100.23, rel=1e-8)
        assert r.walk_depth_level == 3
        assert r.thin_book_warning is True, "order bigger than book → flag must be set"


# =====================================================================
# TR-4.3: FAIL-OPEN orderbook call fails → use median bps fallback
# =====================================================================
class TestFailOpenMedian:
    def test_orderbook_raises_uses_default_btc_2bps(self):
        from tee_core.adapters.okx_adapter import OkxAdapter
        from tee_core.estimators.slippage import SlippageEstimator

        raw = MagicMock()
        raw.get_orderbook.side_effect = RuntimeError("503 unavailable")
        raw.get_contract_info.return_value = (0.01, 1.0)
        raw.get_ticker.return_value = {"ok": True, "last": 70000.0,
                                        "bid": 69999.0, "ask": 70001.0}

        est = SlippageEstimator(OkxAdapter(raw))
        r = est.estimate(inst_id="BTC-USDT-SWAP", sz_contracts=1.0,
                         side="buy", notional_usdt=None, decision_px=70000.0)

        assert r.fail_open is True, "median fallback path must set fail_open=True"
        assert r.fallback_reason is not None
        # BTC median = 2 bps per config DEFAULT_SLIPPAGE_MEDIAN_BPS
        # avg_fill_px = ask (70001) + 2 bps ≈ 70001 * 1.0002 = 70015.0002
        # or decision_px * (1 + median_bps/10000). AC-1 defines slip_bps only.
        assert r.slippage_bps == pytest.approx(2.0, rel=1e-6), (
            f"BTC median slip is 2 bps, got {r.slippage_bps}"
        )
        # thin_book_warning should be False for median fallback (we have no
        # depth info to claim book thin; we just gave up and used median.)
        assert r.thin_book_warning is False

    def test_orderbook_returns_not_ok_uses_default_10bps_for_unknown(self):
        from tee_core.adapters.okx_adapter import OkxAdapter
        from tee_core.estimators.slippage import SlippageEstimator

        raw = MagicMock()
        raw.get_orderbook.return_value = {"ok": False, "error": "bad",
                                          "bids": [], "asks": [], "ts": "0"}
        raw.get_contract_info.return_value = (1.0, 1.0)
        raw.get_ticker.return_value = {"ok": True, "last": 2.0}

        est = SlippageEstimator(OkxAdapter(raw))
        r = est.estimate(inst_id="PEPE2-USDT-SWAP", sz_contracts=100,
                         side="sell", notional_usdt=None, decision_px=2.0)
        assert r.fail_open is True
        # __DEFAULT__ median = 10 bps; slip reported as negative for sell
        assert abs(r.slippage_bps) == pytest.approx(10.0, rel=1e-6), (
            f"unknown coin slip is 10 bps abs, got {r.slippage_bps}"
        )
