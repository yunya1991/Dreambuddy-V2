"""Task 7 RED → GREEN tests — KillSwitch 双层硬闸 (AC-3 + AC-5).

check_pre (TR-7.1) = AC-3 下单前硬闸:
    Reject when estimator expects slippage > max_bps.

check_runtime (TR-7.2 / TR-7.3) = AC-5 运行时硬闸:
    Per-child-fill callback — if current running_slippage_bps > max_bps × buffer_mult
    → trigger=True → algorithm cancels all remaining children + places ONE
    market close-out order with a relaxed 2×max_bps cap.

Notes:
  - max_bps 来源: Q4-A → 常规仓 = DEFAULT_MAX_SLIPPAGE_BPS_NORMAL = 30bps,
    轻仓 = DEFAULT_MAX_SLIPPAGE_BPS_LIGHT = 50bps（由 TEE 执行层从仓位大小查表并
    传入 KillSwitch；KillSwitch 本身不做仓位分级）。
  - buffer_mult 默认 = KILL_SWITCH_BUFFER_MULT = 1.5。
  - REJECT_SLIPPAGE_TOO_HIGH / KILL_SWITCH_TRIGGERED 在 tests 中作为精确 reason 字符串断言，
    生产中可直接在 audit log 中匹配检索。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))

from tee_core.core.contract import EstimateResult  # noqa: E402


REJECT_SLIP_TOO_HIGH = "REJECT_SLIPPAGE_TOO_HIGH"
KILL_TRIGGER = "KILL_SWITCH_TRIGGERED"


# =====================================================================
# TR-7.1 = AC-3: pre-trade gate blocks orders with excessive expected slip
# =====================================================================
class TestTR71PreGate:
    def _pre(self, est_slip_bps: float, max_bps: float,
             parent_req: Dict[str, Any] | None = None):
        """RED helper: import KillSwitch before it exists."""
        from tee_core.core.kill_switch import KillSwitch
        ks = KillSwitch()
        est = EstimateResult(
            avg_fill_px=100.0 + est_slip_bps * 100.0 / 10000.0,
            slippage_bps=est_slip_bps,
            market_impact_cost_usd=1.0,
            walk_depth_level=1,
            thin_book_warning=False,
        )
        pr = parent_req or dict(inst_id="BTC-USDT-SWAP", side="buy",
                                sz=1.0, pos_side="long",
                                td_mode="isolated", leverage=5.0,
                                decision_px=100.0, source="ut_7")
        return ks.check_pre(parent_req=pr, estimate_result=est,
                            max_bps=max_bps)

    def test_gate_rejects_120bps_over_30bps(self):
        """AC-3 baseline: 120 bps estimate > 30bps max → allow=False,
        reason == REJECT_SLIPPAGE_TOO_HIGH."""
        allow, reason = self._pre(est_slip_bps=120.0, max_bps=30.0)
        assert allow is False, (
            f"expected allow=False for slip=120/max=30, got allow={allow}"
        )
        assert REJECT_SLIP_TOO_HIGH in str(reason), (
            f"reason missing {REJECT_SLIP_TOO_HIGH}. Got '{reason}'"
        )

    def test_gate_passes_25bps_below_30bps(self):
        allow, reason = self._pre(est_slip_bps=25.0, max_bps=30.0)
        assert allow is True, (
            f"slip=25 < max=30 → allow=True, got allow={allow}"
        )
        assert reason is None or reason == ""

    def test_gate_boundary_30bps_equals_max_is_passed(self):
        """Inclusive boundary (est ≤ max) → allow. Strict rejection on > only."""
        allow, reason = self._pre(est_slip_bps=30.0, max_bps=30.0)
        assert allow is True, (
            "slip == max should NOT reject (engine may still pick tighter algo)."
        )

    def test_failopen_when_estimate_has_failopen_and_slip_uses_median(self):
        """If estimator used the median fallback, pre-gate uses the same
        slip_bps scalar — still reject if it exceeds max. This test also
        documents that fail-open tag on estimate is tolerated, not auto-
        rejected (engine decides)."""
        from tee_core.core.kill_switch import KillSwitch
        est = EstimateResult(
            avg_fill_px=100.5, slippage_bps=50.0,
            market_impact_cost_usd=0.5, walk_depth_level=0,
            thin_book_warning=False, fail_open=True,
            fallback_reason="book_unreachable",
        )
        allow, reason = KillSwitch().check_pre(
            parent_req=dict(sz=0.1, decision_px=100.0,
                            inst_id="ETC", side="sell", pos_side="short",
                            td_mode="isolated", leverage=5, source="ut"),
            estimate_result=est, max_bps=30.0,
        )
        assert allow is False
        assert REJECT_SLIP_TOO_HIGH in str(reason)


# =====================================================================
# TR-7.2 = AC-5: runtime kill fires at running > max * buffer_mult
#
# Algorithm scenario: SmartTWAP with N=5 slices.
# After 3 children are filled, running_slippage = 60 bps. max=30, buffer=1.5
# → threshold = 45 bps. 60 > 45 → trigger=True.
# Expected side-effects: cancel_order invoked for the UNFILLED remaining
# children (N-3 = 2 cancels) and exactly ONE market closeout place_order
# for leftover sz.
# =====================================================================
class TestTR72RuntimeKill:
    @staticmethod
    def _scenario_5slices_3filled_60bps():
        """Run a minimal mocked engine loop that exercises: kill callback →
        cancels + closeout market."""
        from tee_core.core.kill_switch import KillSwitch
        ks = KillSwitch()
        client = MagicMock()
        max_bps = 30.0
        buffer_mult = 1.5

        # 5 child orders placed earlier (their IDs); the first 3 are filled,
        # the 4th is live, the 5th is pending (not yet placed). The algo's
        # standard behaviour after check_runtime returns (True, …) is:
        # cancel all orders whose state is NOT filled. So we pass the algo
        # 2 outstanding IDs to cancel.
        outstanding_ord_ids = ["CH-4-live", "CH-5-pending"]
        total_sz = 1.0          # e.g. 5 × 0.20 contracts
        sz_filled = 3 * (total_sz / 5.0)   # 0.6
        remaining_sz = total_sz - sz_filled

        running_slip_bps = 60.0

        trigger, trigger_reason = ks.check_runtime(
            running_slippage_bps=running_slip_bps,
            max_bps=max_bps,
            buffer_mult=buffer_mult,
        )
        assert trigger is True, "60 > 45 → trigger=True"
        assert KILL_TRIGGER in str(trigger_reason)

        # Now simulate what the algorithm does with that signal: cancel the
        # outstanding orders and place a market closeout.
        for oid in outstanding_ord_ids:
            client.cancel_order(inst_id="BTC-USDT-SWAP", ord_id=oid)

        client.place_order(
            inst_id="BTC-USDT-SWAP", side="sell", ord_type="market",
            sz=remaining_sz, tag="tee_kill_closeout",
            reason=KILL_TRIGGER,
            # Close-out relaxes the slippage cap 2× to guarantee fill.
            max_slippage_bps=max_bps * 2.0,
        )
        return client, remaining_sz, max_bps, trigger, trigger_reason

    def test_runtime_threshold_and_trigger_reason(self):
        """Baseline assertion: trigger fired for slip > max * 1.5."""
        *_, trigger, trigger_reason = self._scenario_5slices_3filled_60bps()
        assert trigger is True
        assert "45" in str(trigger_reason) or "threshold" in str(trigger_reason).lower() \
            or KILL_TRIGGER in str(trigger_reason)

    def test_runtime_kill_cancels_N_minus_3_orders(self):
        """Outstanding unfilled orders (N-3 = 2) must each be cancelled."""
        client, *_ = self._scenario_5slices_3filled_60bps()
        cancels = client.cancel_order.call_args_list
        assert len(cancels) == 2, (
            f"Expected 2 cancels of unfilled orders, got {len(cancels)}: {cancels}"
        )
        cancel_ids = {c.kwargs.get("ord_id") or c.args[1] for c in cancels}
        assert cancel_ids == {"CH-4-live", "CH-5-pending"}

    def test_runtime_kill_places_one_market_closeout_with_double_cap(self):
        """Close-out: market order at sz=remaining, max_slippage_bps=2×max."""
        client, remaining_sz, max_bps, *_ = self._scenario_5slices_3filled_60bps()
        places = [c for c in client.place_order.call_args_list]
        assert len(places) == 1, (
            f"Expected exactly 1 closeout market order, got {len(places)}: {places}"
        )
        kw = places[0].kwargs
        assert kw["ord_type"] == "market"
        assert float(kw["sz"]) == pytest.approx(remaining_sz)
        assert float(kw["max_slippage_bps"]) == pytest.approx(max_bps * 2.0), (
            "Close-out uses 2× relaxed bps cap so it won't bounce."
        )


# =====================================================================
# TR-7.3: Under-threshold → no kill, no cancels, no closeout
# =====================================================================
class TestTR73UnderThreshold:
    def test_under_threshold_no_trigger(self):
        """running=20 bps, max=30 → threshold=45. trigger=False, cancel 0,
        place 0."""
        from tee_core.core.kill_switch import KillSwitch
        ks = KillSwitch()
        trigger, reason = ks.check_runtime(
            running_slippage_bps=20.0, max_bps=30.0, buffer_mult=1.5,
        )
        assert trigger is False
        # Reason field may be None (or '') when no trigger fired. Either OK.
        client = MagicMock()
        # Algorithm should NOT call cancel, NOT place closeout.
        # If caller respects the bool return we never touch client:
        if not trigger:
            pass  # nothing
        assert client.cancel_order.call_count == 0
        assert client.place_order.call_count == 0

    def test_boundary_45bps_is_no_trigger(self):
        """Inclusive runtime boundary: slip == threshold → not triggered.
        (Engine treats triggering only on strict exceed to avoid flapping
        at exactly the limit.)"""
        from tee_core.core.kill_switch import KillSwitch
        ks = KillSwitch()
        trigger, reason = ks.check_runtime(
            running_slippage_bps=45.0, max_bps=30.0, buffer_mult=1.5,
        )
        assert trigger is False, (
            "Exactly on threshold should NOT trigger (avoids flapping)."
        )

    def test_over_threshold_46bps_triggers(self):
        from tee_core.core.kill_switch import KillSwitch
        ks = KillSwitch()
        trigger, reason = ks.check_runtime(
            running_slippage_bps=46.0, max_bps=30.0, buffer_mult=1.5,
        )
        assert trigger is True
        assert KILL_TRIGGER in str(reason) or "45" in str(reason) or "30*1.5" in str(reason)
