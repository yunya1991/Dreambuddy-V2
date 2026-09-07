"""Task 5 RED → GREEN tests — OrderRouter (AC-2: 4x3=12 threshold matrix).

Router API:
    from tee_core.core.router import OrderRouter, RouterDecision
    from tee_core.core.contract import AlgoName, Urgency

    r = OrderRouter(client=exchange_client_proto)        # for compute_size_ratio()
    decision = r.decide(size_ratio=0.05, urgency=Urgency.MEDIUM,
                        override=None)
    decision.algo        # AlgoName enum (DIRECT/TWAP15/TWAP60/PASSIVE)
    decision.params      # dict hint (slices, window, escalate cfg, …)
    decision.is_direct   # bool (True when algo==DIRECT)

Threshold defaults (Q3-A):
    DIRECT < 0.5%  , TWAP15 ∈[0.5%, 3%), TWAP60 ∈[3%, 10%), PASSIVE ≥ 10%

Urgency shifts the decision one row:
    LOW    : go one tier more passive (less market impact, more split)
    MEDIUM : use thresholds as-is
    HIGH   : go one tier more aggressive (less split, near-direct)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))

from tee_core.core.contract import AlgoName, Urgency  # noqa: E402


# =====================================================================
# TR-5.1 — 4 size_ratio × 3 urgency = 12 golden mappings
# =====================================================================
# (size_ratio (float fraction), urgency, expected_algo)
TR_5_1_GOLDEN: list[tuple[float, Urgency, AlgoName]] = [
    # bin: DIRECT (< 0.5 %) ------------------------------------------------------------------
    (0.002, Urgency.LOW,    AlgoName.TWAP15),   # downgrade one tier
    (0.002, Urgency.MEDIUM, AlgoName.DIRECT),   # as-threshold
    (0.002, Urgency.HIGH,   AlgoName.DIRECT),   # can't go higher than DIRECT
    # bin: TWAP15 ([0.5%, 3%)) ---------------------------------------------------------------
    (0.01,  Urgency.LOW,    AlgoName.TWAP60),   # downgrade → TWAP60
    (0.01,  Urgency.MEDIUM, AlgoName.TWAP15),
    (0.01,  Urgency.HIGH,   AlgoName.DIRECT),   # upgrade → DIRECT
    # bin: TWAP60 ([3%, 10%)) ---------------------------------------------------------------
    (0.05,  Urgency.LOW,    AlgoName.PASSIVE),  # downgrade → PASSIVE
    (0.05,  Urgency.MEDIUM, AlgoName.TWAP60),
    (0.05,  Urgency.HIGH,   AlgoName.TWAP15),   # upgrade → TWAP15
    # bin: PASSIVE (≥ 10%) -------------------------------------------------------------------
    (0.20,  Urgency.LOW,    AlgoName.PASSIVE),  # can't go more passive
    (0.20,  Urgency.MEDIUM, AlgoName.PASSIVE),
    (0.20,  Urgency.HIGH,   AlgoName.TWAP60),   # upgrade one tier
]


class TestTR51ThresholdMatrix:
    @pytest.mark.parametrize("ratio,urgency,expected", TR_5_1_GOLDEN,
                             ids=[f"ratio={r} u={u.value} → {e.value}"
                                  for (r, u, e) in TR_5_1_GOLDEN])
    def test_12_combos_golden_match(self, ratio, urgency, expected):
        # RED trigger: router module / class / method not-yet-created
        from tee_core.core.router import OrderRouter
        router = OrderRouter(client=MagicMock())
        decision = router.decide(size_ratio=ratio, urgency=urgency)
        assert decision.algo is expected, (
            f"Router.decide(ratio={ratio}, urgency={urgency.value}) = "
            f"{decision.algo.value}, but expected {expected.value}"
        )
        # Convenience flag matches the algo enum
        assert decision.is_direct is (expected is AlgoName.DIRECT)
        # params dict always has algo_params (even if empty) for downstream
        assert isinstance(decision.params, dict)

    def test_boundary_at_0p5_exactly_goes_twap15(self):
        """0.5% is inclusive bottom of TWAP15."""
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        assert r.decide(0.005, Urgency.MEDIUM).algo is AlgoName.TWAP15

    def test_boundary_at_3pct_exactly_goes_twap60(self):
        """3% is inclusive bottom of TWAP60."""
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        assert r.decide(0.03, Urgency.MEDIUM).algo is AlgoName.TWAP60

    def test_boundary_at_10pct_exactly_goes_passive(self):
        """10% is inclusive bottom of PASSIVE."""
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        assert r.decide(0.10, Urgency.MEDIUM).algo is AlgoName.PASSIVE

    def test_urgency_shift_applied_before_quantisation(self):
        """Edge: ratio=0.4% and urgency=LOW should land at TWAP15.
        We first bin the ratio (DIRECT), then shift one tier passive.
        DIRECT shifted passive = TWAP15 (already tested). But we also
        need a test that covers: LOW on 0.49% → TWAP15 via shift, not via
        direct threshold hit. This here only documents semantics; the
        parameterised test above already asserts it for ratio=0.2%."""
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        # 0.0049 < 0.005 so bin = DIRECT
        d = r.decide(0.0049, Urgency.LOW)
        assert d.algo is AlgoName.TWAP15


# =====================================================================
# TR-5.2 — Override bypasses the matrix
# =====================================================================
class TestTR52OverrideBypass:
    @pytest.mark.parametrize("override,expected_algo", [
        ("direct",  AlgoName.DIRECT),
        ("twap",    AlgoName.TWAP15),    # alias "twap" → TWAP15
        ("twap15",  AlgoName.TWAP15),
        ("twap60",  AlgoName.TWAP60),
        ("passive", AlgoName.PASSIVE),
    ])
    def test_override_forces_algo_regardless_of_ratio(self, override, expected_algo):
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        # Use a ratio / urgency that would NEVER map to expected_algo on
        # its own — override must dominate the decision.
        ratio_if_passive_expected = 0.0001          # DIRECT bin normally
        urgency_wrong_direction = Urgency.HIGH
        d = r.decide(size_ratio=ratio_if_passive_expected,
                     urgency=urgency_wrong_direction,
                     override=override)
        assert d.algo is expected_algo, (
            f"override='{override}' → expected {expected_algo.value}, got "
            f"{d.algo.value}"
        )

    def test_override_unknown_raises_valueerror(self):
        """Bad overrides should fail fast (no silent fall-through)."""
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        with pytest.raises((ValueError, KeyError)):
            r.decide(size_ratio=0.01, urgency=Urgency.MEDIUM,
                     override="no_such_algo")

    def test_override_none_is_same_as_absent(self):
        from tee_core.core.router import OrderRouter
        r = OrderRouter(client=MagicMock())
        a = r.decide(0.01, Urgency.MEDIUM, override=None).algo
        b = r.decide(0.01, Urgency.MEDIUM).algo
        assert a is b is AlgoName.TWAP15


# =====================================================================
# TR-5.3 — compute_size_ratio FAIL-OPEN via DEFAULT_1MIN_VOLUME_USDT
# =====================================================================
class TestTR53VolumeFailOpen:
    def test_kline_ok_uses_5bar_avg(self):
        """Happy path: sum 5 × 1m bars' (vol × avg close) = USDT notional."""
        from tee_core.core.router import OrderRouter
        client = MagicMock()
        # vol is quoted in base coin (per OKX standard get_kline convention:
        # [ts, o, h, l, c, vol, volCcy]. avg USDT per bar ≈ c × vol.
        client.get_kline.return_value = {
            "ok": True,
            "bars": [
                # 5 bars with c=100, vol=1000 (coin) each → 100k USDT/bar
                {"ts": "1", "c": "100", "vol": "1000"},
                {"ts": "2", "c": "100", "vol": "1000"},
                {"ts": "3", "c": "100", "vol": "1000"},
                {"ts": "4", "c": "100", "vol": "1000"},
                {"ts": "5", "c": "100", "vol": "1000"},
            ],
        }
        r = OrderRouter(client=client)
        ratio = r.compute_size_ratio(inst_id="ETH-USDT-SWAP",
                                     notional_usdt=250_000.0)
        # avg per-bar USDT = 100*1000=100_000. ratio = 250000/100000 = 2.5
        assert ratio == pytest.approx(2.5, rel=1e-6), (
            f"Expected 2.5x 1min avg volume, got {ratio}"
        )

    def test_kline_raises_fallback_to_median_btc_5mio(self):
        """Timeout → ratio computed from DEFAULT_1MIN_VOLUME_USDT."""
        from tee_core.core.router import OrderRouter
        client = MagicMock()
        client.get_kline.side_effect = TimeoutError("simulated 504")
        r = OrderRouter(client=client)
        # BTC default 1-min = 5_000_000 USDT. order = 500k USDT → 0.1
        ratio = r.compute_size_ratio(inst_id="BTC-USDT-SWAP",
                                     notional_usdt=500_000.0)
        assert ratio == pytest.approx(500_000 / 5_000_000.0, rel=1e-6), (
            f"BTC fallback expected 0.1, got {ratio}"
        )

    def test_kline_not_ok_uses_default_100k_for_unknown_coin(self):
        from tee_core.core.router import OrderRouter
        client = MagicMock()
        client.get_kline.return_value = {"ok": False, "error": "not found"}
        r = OrderRouter(client=client)
        ratio = r.compute_size_ratio(inst_id="SHITCOIN-USDT-SWAP",
                                     notional_usdt=200_000.0)
        # __DEFAULT__ 1-min = 100k. order = 200k → ratio = 2.0
        assert ratio == pytest.approx(2.0, rel=1e-6), (
            f"unknown-coin fallback expected 2.0, got {ratio}"
        )

    def test_kline_returns_fewer_than_5_bars_uses_nonempty_mean(self):
        """Fewer than 5 bars available: take mean of whatever we actually
        have (FAIL-SAFE, never divide by zero)."""
        from tee_core.core.router import OrderRouter
        client = MagicMock()
        client.get_kline.return_value = {
            "ok": True, "bars": [
                {"ts": "1", "c": "200", "vol": "500"},  # 100k USDT
                {"ts": "2", "c": "200", "vol": "500"},  # 100k USDT
            ],
        }
        r = OrderRouter(client=client)
        ratio = r.compute_size_ratio(inst_id="ETC-USDT-SWAP",
                                     notional_usdt=50_000.0)
        # avg 1-min = 100_000. order = 50k → ratio = 0.5
        assert ratio == pytest.approx(0.5, rel=1e-6)
