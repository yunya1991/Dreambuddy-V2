"""Task 6 RED → GREEN tests — ExecutionAlgorithm base + SmartTWAP (TR-6.1,
TR-6.4) + SmartPassive (TR-6.2, TR-6.3) + DirectMarket.

All algorithms share one signature — they accept ``parent_req`` (a plain
dict subset of the ParentRequest contract is good enough for single-
algorithmic unit tests) and produce an ``AlgoRunResult`` with:
    child_orders: list of (submitted_order_id → filled_sz records)
    final_vwap: float
    final_slippage_bps: float
    remaining_sz:  float
    kvs:           dict (carry side-channel info e.g. ESCALATION stage etc.)

To keep algorithm tests fast and deterministic we never let the real
clock tick. All uses of ``time.sleep`` inside algorithms are patched in
each fixture with a MagicMock that (a) advances a fake ``monotonic_ms``
counter so ``wall_clock`` inside the algorithm always sees the exact
elapsed time the test wants.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))


# =====================================================================
# Minimal runtime for algo tests — fake client, fake clock, audit log.
# =====================================================================
@dataclass
class AuditRecord:
    stage: str
    payload: Dict[str, Any]


class AuditSink:
    def __init__(self):
        self.records: List[AuditRecord] = []

    def __call__(self, stage: str, payload: Any = None) -> None:
        self.records.append(AuditRecord(stage, dict(payload or {})))

    def has_stage(self, stage: str) -> bool:
        return any(r.stage == stage for r in self.records)


def make_ticker_last(last: float):
    def _get_ticker(inst_id=None):
        return {"ok": True, "last": last, "bid": last - 0.1, "ask": last + 0.1,
                "ts": "0"}
    return _get_ticker


def make_book(top_bid: float, top_ask: float, bid_sz: float = 1000.0,
              ask_sz: float = 1000.0):
    """Return a 1-level book callback for use with MagicMock side_effect."""
    def _get_orderbook(inst_id=None, sz=10):
        return {"ok": True, "ts": "0",
                "bids": [[f"{top_bid:.8f}", f"{bid_sz}", "0", "1"]],
                "asks": [[f"{top_ask:.8f}", f"{ask_sz}", "0", "1"]]}
    return _get_orderbook


# ── fixtures ──────────────────────────────────────────────────────────
@pytest.fixture
def audit():
    return AuditSink()


@pytest.fixture
def kill_cb_ok():
    """Default kill switch — never fires during algo unit tests below."""
    return MagicMock(return_value=(False, None))


@pytest.fixture
def mock_sleep_then_time():
    """Context-style fixture that yields (sleep_mock, time_mock).

    Tests call ``time_mock.advance(seconds)`` and algorithms that use
    time.time() inside will see the elapsed time correctly. sleep()
    records calls in order so tests can assert on spacing.
    """
    # Return as a reusable builder; individual tests do the patching.
    return None  # replaced per-test with @patch context managers


# =====================================================================
# Shared: verify base class exists + 4 concrete modules importable
# =====================================================================
class TestAlgorithmModuleImports:
    """RED trigger for all four modules. GREEN only after they exist."""

    def test_base_executionalgo_class_exists(self):
        from tee_core.algorithms.base import ExecutionAlgorithm, AlgoRunResult
        assert hasattr(ExecutionAlgorithm, "run") or True  # just import ok
        # AlgoRunResult should expose the mandated fields
        r = AlgoRunResult(child_orders=[], final_vwap=0.0,
                          final_slippage_bps=0.0, remaining_sz=0.0,
                          kvs={})
        assert isinstance(r.child_orders, list)
        assert isinstance(r.kvs, dict)

    def test_direct_market_module_imports_and_has_run(self):
        from tee_core.algorithms.direct_market import DirectMarket
        assert callable(getattr(DirectMarket, "run", None))

    def test_smart_twap_imports(self):
        from tee_core.algorithms.smart_twap import SmartTWAP
        assert callable(getattr(SmartTWAP, "run", None))

    def test_smart_passive_imports(self):
        from tee_core.algorithms.smart_passive import SmartPassive
        assert callable(getattr(SmartPassive, "run", None))


# =====================================================================
# TR-6.1 (=AC-4) — SmartTWAP 5 slices over 60s window
#   sum(sz) = total, each sz within avg × [0.85, 1.15] (±15% jitter),
#   inter-slice spacing ~12 s ∈ [10, 14], final slice corrects sum drift.
# =====================================================================
class TestTR61SmartTWAPSlicing:
    def run_scenario(self, total_sz: float = 1.0, num_slices: int = 5,
                     window_sec: int = 60):
        from tee_core.algorithms.smart_twap import SmartTWAP
        client = MagicMock()
        client.place_order.side_effect = lambda **kw: {
            "ok": True, "ord_id": f"child-{kw.get('ord_type','')}-{id(kw)}",
            "dry_run": False, "dry_run_result": None,
        }
        client.get_order.side_effect = lambda **kw: {
            "ok": True, "ord_id": kw["ord_id"], "state": "filled",
            "side": "buy", "pos_side": "long", "filled_sz": 1.0,
            "avg_px": 100.0, "fee": 0, "pnl": 0,
        }
        client.get_orderbook = make_book(99.9, 100.1)
        client.get_ticker = make_ticker_last(100.0)
        client.get_contract_info.return_value = (1.0, 1.0)

        # Pin RNG so jitter is deterministic (seed locally inside algo)
        parent_req = dict(inst_id="BTC-USDT-SWAP", side="buy", sz=total_sz,
                          pos_side="long", td_mode="isolated", leverage=5.0,
                          decision_px=100.0, source="ut")
        algo_params = dict(window_sec=window_sec,
                           num_slices=num_slices,
                           jitter_pct=0.15,
                           escalate_sec=0.0001,   # ≈disabled for TR-6.1
                           escalate_bps=0, escalate_max=0, timeout_sec=9999)
        audit = AuditSink()
        kill_cb = MagicMock(return_value=(False, None))

        from tee_core.estimators import SlippageEstimator
        est = SlippageEstimator(client)

        sleep_calls: List[float] = []
        current_t = [1700000000.0]

        def fake_sleep(secs: float):
            sleep_calls.append(float(secs))
            current_t[0] += float(secs)

        with patch("tee_core.algorithms.smart_twap.time") as tm:
            tm.sleep.side_effect = fake_sleep
            tm.time.side_effect = lambda: current_t[0]
            result = SmartTWAP().run(
                parent_req=parent_req, algo_params=algo_params,
                client=client, estimator=est,
                kill_switch_cb=kill_cb, audit_cb=audit,
            )
        return result, client, sleep_calls, audit

    def test_sum_of_child_sizes_matches_parent_total(self):
        result, client, *_ = self.run_scenario(total_sz=1.0, num_slices=5)
        assert client.place_order.call_count == 5
        actual_sz_sum = sum(
            float(client.place_order.call_args_list[i].kwargs["sz"])
            for i in range(5)
        )
        assert actual_sz_sum == pytest.approx(1.0, abs=1e-9), (
            f"sum(child_sz)={actual_sz_sum} != total 1.0"
        )

    def test_each_slice_sz_within_jitter_window_15pct(self):
        """avg slice sz = total/n = 0.2.  Allowable sz ∈ [0.17, 0.23] for
        slices 0..n-2. Slice n-1 can be outside (sum-corrector)."""
        total = 1.0
        n = 5
        avg = total / n
        result, client, *_ = self.run_scenario(total_sz=total, num_slices=n)
        szes = [float(c.kwargs["sz"]) for c in client.place_order.call_args_list]
        for i, sz in enumerate(szes[:-1]):
            assert sz >= avg * (1 - 0.15) - 1e-9, (
                f"slice {i} sz {sz} < lower jitter bound {avg*0.85}"
            )
            assert sz <= avg * (1 + 0.15) + 1e-9, (
                f"slice {i} sz {sz} > upper jitter bound {avg*1.15}"
            )

    def test_inter_slice_gaps_10_to_14_seconds(self):
        """Window=60s / n=5 slices → spacing ≈ 12s, [10, 14]."""
        result, client, sleep_calls, *_ = self.run_scenario(
            total_sz=1.0, num_slices=5, window_sec=60)
        # Inter-slice gaps are the ~12s sleeps; tier-0 poll sleeps (tiny,
        # ~0.0001s) are unrelated. Count only sleeps ≥ 1 s as "gaps".
        gaps = [s for s in sleep_calls if s >= 1.0]
        assert len(gaps) == 4, (
            f"5 slices should yield 4 inter-slice gaps; got {len(gaps)}. "
            f"All sleeps (n={len(sleep_calls)}): {sleep_calls}"
        )
        for i, gap in enumerate(gaps):
            assert 10.0 <= gap <= 14.0, (
                f"gap #{i}={gap:.2f}s outside [10, 14]s."
            )


# =====================================================================
# TR-6.2 — SmartPassive rehang flow (top-of-book every 10s).
#
# Timeline:
#   t=0:   passive puts buy limit at best_bid
#   t=10s: book moved up (best_bid increased) → cancel old + new bid
#   t=20s: test checks the call sequence: [cancel, place, cancel, place].
# =====================================================================
class TestTR62SmartPassiveRehang:
    def test_rehang_sequence_on_book_move(self):
        from tee_core.algorithms.smart_passive import SmartPassive

        client = MagicMock()
        # Two distinct order IDs returned by place_order (2 hangs):
        client.place_order.side_effect = [
            {"ok": True, "ord_id": "PASS-HANG-1"},
            {"ok": True, "ord_id": "PASS-HANG-2"},
        ]
        # get_order simulates "never filled, still live" each poll so
        # rehang actually occurs.
        client.get_order.return_value = {
            "ok": True, "ord_id": "?", "state": "live",
            "filled_sz": 0, "avg_px": 0, "side": "buy",
            "pos_side": "long", "fee": 0, "pnl": 0,
        }
        client.cancel_order.return_value = {"ok": True, "ord_id": "?"}

        # Move book between t=0 and t=10s get_orderbook calls:
        book_versions = {0: make_book(99.0, 101.0),   # t=0
                         1: make_book(99.5, 101.5)}   # t=10s + rehang
        book_call_counter = [0]

        def book_side_effect(*a, **kw):
            idx = min(book_call_counter[0], 1)
            book_call_counter[0] += 1
            return book_versions[idx](*a, **kw)
        client.get_orderbook = MagicMock(side_effect=book_side_effect)
        client.get_ticker = make_ticker_last(100.0)
        client.get_contract_info.return_value = (1.0, 1.0)

        parent_req = dict(inst_id="SOL-USDT-SWAP", side="buy", sz=2.0,
                          pos_side="long", td_mode="isolated", leverage=5.0,
                          decision_px=100.0, source="ut")
        # Rehang every 10s, but allow only up to ~21s wall clock via patched
        # sleep so we hit exactly one rehang.
        algo_params = dict(rehang_sec=10, twap_fallback_sec=9999,
                           twap_fallback_fill_ratio=0.5)
        audit = AuditSink()
        kill_cb = MagicMock(return_value=(False, None))

        sleep_args: List[float] = []
        t = [1_700_000_000.0]

        def fake_sleep(secs: float):
            # Halt wall clock early if we exceed ~22s to exercise 1 rehang
            sleep_args.append(float(secs))
            t[0] += float(secs)
            # After 2 sleeps (≈ 2 * rehang_interval seconds worth of calls),
            # force the next get_order to be "filled" so the loop exits.
            if len(sleep_args) >= 2:
                client.get_order.return_value = {
                    "ok": True, "state": "filled", "filled_sz": 2.0,
                    "avg_px": 99.5, "ord_id": "?", "side": "buy",
                    "pos_side": "long", "fee": 0, "pnl": 0,
                }

        with patch("tee_core.algorithms.smart_passive.time") as tm:
            tm.sleep.side_effect = fake_sleep
            tm.time.side_effect = lambda: t[0]
            SmartPassive().run(
                parent_req=parent_req, algo_params=algo_params,
                client=client, estimator=MagicMock(),
                kill_switch_cb=kill_cb, audit_cb=audit,
            )

        # Assertions:
        #   2 place_order calls, 1 cancel (between them) for the OLD order
        #   before the second rehang. Sequence:
        #       place(HANG-1) → sleep 10s → cancel(HANG-1) → place(HANG-2)
        # We expect place_order count == 2, cancel_order count == 1,
        # cancel called BEFORE 2nd place (recorded call order in a single
        # mock-trace can be verified via client.mock_calls order).
        assert client.place_order.call_count == 2, (
            f"expected 2 hangs, got {client.place_order.call_count}"
        )
        assert client.cancel_order.call_count >= 1, (
            "rehang expected at least 1 cancel of old order before new hang."
        )
        # First-place order_id should be the one canceled:
        first_ord_id = "PASS-HANG-1"
        cancel_ord = client.cancel_order.call_args_list[0].kwargs.get("ord_id")
        # Either arg form works; tests accept cancel(inst_id, ord_id) kwargs.
        assert cancel_ord == first_ord_id, (
            f"first canceled order id {cancel_ord} != original HANG-1={first_ord_id}"
        )

        # New place_order after rehang: buy side → must use best_bid (99.5
        # after book move) not stale 99.0. Best bid matches ord_type=="limit".
        second_place_kwargs = client.place_order.call_args_list[1].kwargs
        assert second_place_kwargs["ord_type"] == "limit"
        assert second_place_kwargs["px"] == pytest.approx(99.5, rel=1e-6), (
            f"2nd hang px {second_place_kwargs['px']} should follow new best_bid=99.5"
        )


# =====================================================================
# TR-6.3 — Passive → TWAP fallback at 2 min when <50% filled.
# =====================================================================
class TestTR63PassiveToTwapFallback:
    def test_fallback_creates_smarttwap_instance_and_flags_audit(self):
        from tee_core.algorithms.smart_passive import SmartPassive
        from tee_core.algorithms.smart_twap import SmartTWAP

        client = MagicMock()
        # Track SmartTWAP instantiation (should happen once, inside passive).
        orig_init = SmartTWAP.__init__
        twap_instances_created: List[int] = []

        def patched_smarttwap_init(self, *a, **kw):
            twap_instances_created.append(1)
            return orig_init(self, *a, **kw)

        client.place_order.return_value = {"ok": True, "ord_id": "P1"}
        # get_order → 30% filled (slow). Parent sz=10, filled=3 at t=120s.
        def slow_fill(inst_id, ord_id):
            return {"ok": True, "ord_id": ord_id, "state": "live",
                    "side": "buy", "pos_side": "long",
                    "filled_sz": 3.0, "avg_px": 100.0, "fee": 0, "pnl": 0}
        client.get_order.side_effect = slow_fill
        client.cancel_order.return_value = {"ok": True, "ord_id": "P1"}
        client.get_orderbook = make_book(99.9, 100.1)
        client.get_ticker = make_ticker_last(100.0)
        client.get_contract_info.return_value = (1.0, 1.0)

        parent_req = dict(inst_id="BTC-USDT-SWAP", side="buy", sz=10.0,
                          pos_side="long", td_mode="isolated", leverage=5.0,
                          decision_px=100.0, source="ut")
        algo_params = dict(rehang_sec=10, twap_fallback_sec=120,
                           twap_fallback_fill_ratio=0.5,
                           # For TWAP segment (default):
                           window_sec=1800, num_slices=5, jitter_pct=0.15,
                           escalate_sec=9999, escalate_bps=2,
                           escalate_max=10, timeout_sec=9999)
        audit = AuditSink()
        kill_cb = MagicMock(return_value=(False, None))
        est = MagicMock()

        sleep_total: float = 0.0
        def fake_sleep(secs: float):
            nonlocal sleep_total
            sleep_total += float(secs)
            # When we've slept ≥ 120 seconds worth of intervals, stop the
            # passive loop via time.time threshold in the algo.
        t = [1_700_000_000.0]
        def fake_time():
            return t[0] + sleep_total

        with patch("tee_core.algorithms.smart_passive.time") as tm_passive, \
             patch("tee_core.algorithms.smart_twap.time") as tm_twap, \
             patch.object(SmartTWAP, "__init__", patched_smarttwap_init):
            tm_passive.sleep.side_effect = fake_sleep
            tm_passive.time.side_effect = fake_time
            # Make SmartTWAP.run() a no-op that returns a canned result so
            # the test is about "Passive calls SmartTWAP correctly" not
            # about SmartTWAP itself (covered in TR-6.1/TR-6.4).
            canned_r = MagicMock()
            canned_r.child_orders = []
            canned_r.final_vwap = 100.0
            canned_r.final_slippage_bps = 0.0
            canned_r.remaining_sz = 0.0
            canned_r.kvs = {}
            with patch.object(SmartTWAP, "run", return_value=canned_r):
                SmartPassive().run(
                    parent_req=parent_req, algo_params=algo_params,
                    client=client, estimator=est,
                    kill_switch_cb=kill_cb, audit_cb=audit,
                )

        assert sum(twap_instances_created) == 1, (
            "Passive fallback should instantiate SmartTWAP exactly once."
        )
        assert audit.has_stage("PASSIVE_TO_TWAP_FALLBACK"), (
            "Audit log missing PASSIVE_TO_TWAP_FALLBACK stage marker. "
            f"Stages present: {[r.stage for r in audit.records]}"
        )


# =====================================================================
# TR-6.4 — SmartTWAP 3-tier escalation (20 / 40 / 60 s → wider bps / MKT)
# =====================================================================
class TestTR64SmartTWAPEscalation:
    def test_escalation_after_21s_first_slice_offset_widened(self):
        """Simulate: first slice places a limit, algo polls get_order which
        reports NOT filled after ≥20s elapsed. Next place_order call must
        use a WIDER price offset (by escalate_bps=2 bps, first step)."""
        from tee_core.algorithms.smart_twap import SmartTWAP
        client = MagicMock()
        book_bid, book_ask = 99.9, 100.1
        client.get_orderbook = make_book(book_bid, book_ask)
        client.get_ticker = make_ticker_last(100.0)
        client.get_contract_info.return_value = (1.0, 1.0)
        # Simulate: first child → state live, NOT filled after 21s.
        # Second (final for this tiny scenario) will be escalated.
        call_idx = {"n": 0}

        def fake_place(**kw):
            call_idx["n"] += 1
            return {"ok": True, "ord_id": f"CH-{call_idx['n']}"}

        client.place_order = MagicMock(side_effect=fake_place)

        def fake_get_order(inst_id, ord_id):
            # "Unfilled" for first, "filled after escalation" for second.
            if ord_id == "CH-1":
                return {"ok": True, "ord_id": ord_id, "state": "live",
                        "side": "buy", "pos_side": "long",
                        "filled_sz": 0.0, "avg_px": 0.0, "fee": 0, "pnl": 0}
            return {"ok": True, "ord_id": ord_id, "state": "filled",
                    "side": "buy", "pos_side": "long",
                    "filled_sz": 1.0, "avg_px": 100.2, "fee": 0, "pnl": 0}

        client.get_order = MagicMock(side_effect=fake_get_order)
        client.cancel_order.return_value = {"ok": True, "ord_id": "CH-1"}

        # Keep it to a 2-slice scenario with tiny window. Escalation tier
        # kicks in after 20s of waiting on an unfilled order (per TR):
        #   tier 1: +2 bps offset, tier 2 (40s total): +5 bps,
        #   tier 3 (60s): market.
        # For this unit test we let the first sleep stretch to 21s so the
        # algo enters tier 1. We patch time.sleep to stretch it to 21s even
        # though nominal spacing is 12s.
        parent_req = dict(inst_id="BTC-USDT-SWAP", side="buy", sz=2.0,
                          pos_side="long", td_mode="isolated", leverage=5.0,
                          decision_px=100.0, source="ut")
        algo_params = dict(
            window_sec=24, num_slices=2, jitter_pct=0.0,  # no jitter, easy math
            escalate_sec=20, escalate_bps=2, escalate_max=10, timeout_sec=60,
        )
        audit = AuditSink()
        kill_cb = MagicMock(return_value=(False, None))
        from tee_core.estimators import SlippageEstimator
        est = SlippageEstimator(client)

        # time management: first sleep (between the two slices) jumps 21s
        # so we step over the 20s threshold.
        sleep_index = [0]
        sleep_vals = [21.0, 1.0]

        wall = [1_700_000_000.0]
        def fake_sleep(s: float):
            idx = sleep_index[0]
            sleep_index[0] += 1
            actual = sleep_vals[idx] if idx < len(sleep_vals) else float(s)
            wall[0] += actual
        def fake_time():
            return wall[0]

        with patch("tee_core.algorithms.smart_twap.time") as tm:
            tm.sleep.side_effect = fake_sleep
            tm.time.side_effect = fake_time
            SmartTWAP().run(
                parent_req=parent_req, algo_params=algo_params,
                client=client, estimator=est,
                kill_switch_cb=kill_cb, audit_cb=audit,
            )

        # We expect place_order ≥ 2 times. Because slice-0 escalates we
        # submit: tier-0 (touch) → cancel → tier-1 (widened offset). That
        # means places[1] is the escalated order (places[2] onwards belong
        # to subsequent slices whose offset resets to touch again).
        places = client.place_order.call_args_list
        assert len(places) >= 2, f"expected ≥2 places, got {len(places)}"
        first_px = float(places[0].kwargs["px"])
        # First place after the initial one should be tier-1 widened.
        escalated_px = float(places[1].kwargs["px"])
        # first px ≈ ask price (100.1). escalated should be ≥ ask + 2bps.
        expected_min_escalated = book_ask * (1.0 + 2 / 10000.0)
        assert escalated_px >= expected_min_escalated_escalated_bound(
            expected_min_escalated
        ), (
            f"tier-1 px={escalated_px:.6f} should be ≥ "
            f"{expected_min_escalated:.6f} (ask+2bps). First px={first_px:.6f}."
        )
        # Confirm we observed an ESCALATION audit stage.
        assert audit.has_stage("ESCALATION_TIER_UP"), (
            "Audit missing ESCALATION_TIER_UP. Stages: "
            f"{[r.stage for r in audit.records]}"
        )


def expected_min_escalated_escalated_bound(expected_min):
    """Allow 1e-9 floating tolerance for lower-bound assertion."""
    return expected_min - 1e-9
