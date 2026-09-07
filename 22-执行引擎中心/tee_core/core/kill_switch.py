"""Kill-Switch two-tier hard gate (AC-3 pre-trade, AC-5 runtime).

Two independent checkpoints guard every parent order:

1. :meth:`check_pre` runs BEFORE any child is placed.
   Rejects orders where *expected* slippage (from SlippageEstimator) already
   exceeds `max_bps`. Purpose: early-fail an order that the estimator
   already knows will get terrible fills.

2. :meth:`check_runtime` runs AFTER EACH child fill using the *current*
   running VWAP vs decision price (not estimate).
   Triggers when `running_slippage_bps > max_bps × buffer_mult` (default
   buffer_mult = 1.5, per spec Q4-A = kill switch flapping buffer).
   When triggered the calling algorithm is responsible for:
     (a) cancelling any remaining unfilled children
     (b) issuing ONE market close-out with 2× the bps cap to guarantee
         fill — we provide a convenience :meth:`close_out_suggestion`
         returning the parameters (sz, tag, reason, 2×bps) so algorithms
         don't each have to re-derive them.

Constants are driven from the global config (Q4 hard constraints).
All methods are pure — no I/O — so unit tests don't need a clock/mock
exchange. Side effects (cancel orders + market close-out) are documented
via ``REJECT_SLIPPAGE_TOO_HIGH`` / ``KILL_SWITCH_TRIGGERED`` sentinel
reason strings that engine + algorithms match on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from . import config as _cfg
from ..core.contract import EstimateResult, ParentRequest


# ── sentinel reason strings shared with audit_cb log consumers ────────
REJECT_SLIPPAGE_TOO_HIGH: str = "REJECT_SLIPPAGE_TOO_HIGH"
KILL_SWITCH_TRIGGERED: str = "KILL_SWITCH_TRIGGERED"


@dataclass
class CloseOutSuggestion:
    """Recommended close-out market order parameters."""
    ord_type: str = "market"
    tag: str = "tee_kill_closeout"
    reason: str = KILL_SWITCH_TRIGGERED
    # Close-out cap is 2× the normal max to guarantee a fill even under
    # stressed orderbook — the engine already lost the slippage battle, so
    # we just need out, not perfect pricing per contract spec AC-5.
    max_slippage_bps_multiplier: float = 2.0

    def bps(self, max_bps: float) -> float:
        return float(max_bps) * float(self.max_slippage_bps_multiplier)


class KillSwitch:
    """Two-tier slippage enforcement (AC-3 + AC-5). Pure functions."""

    REJECT_SLIPPAGE_TOO_HIGH = REJECT_SLIPPAGE_TOO_HIGH
    KILL_SWITCH_TRIGGERED = KILL_SWITCH_TRIGGERED

    def __init__(
        self,
        default_buffer_mult: Optional[float] = None,
        default_max_normal_bps: Optional[float] = None,
        default_max_light_bps: Optional[float] = None,
    ) -> None:
        """Overridable defaults (tests/engine can inject custom values).
        When ``None`` the matching config constant is used."""
        self.default_buffer_mult = (
            float(default_buffer_mult)
            if default_buffer_mult is not None
            else _cfg.KILL_SWITCH_BUFFER_MULT
        )
        self.default_max_normal_bps = (
            float(default_max_normal_bps)
            if default_max_normal_bps is not None
            else _cfg.DEFAULT_MAX_SLIPPAGE_BPS_NORMAL
        )
        self.default_max_light_bps = (
            float(default_max_light_bps)
            if default_max_light_bps is not None
            else _cfg.DEFAULT_MAX_SLIPPAGE_BPS_LIGHT
        )

    # ── Tier 1: pre-trade gate (AC-3) ─────────────────────────────────
    def check_pre(
        self,
        parent_req: Any,   # ParentRequest or dict — both OK
        estimate_result: EstimateResult,
        max_bps: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Allow or reject a parent order based on ESTIMATED slippage.

        Returns:
            (allow=True,  None)         → proceed to algorithm selection.
            (allow=False, reason_str)   → caller returns reject result
                                          (no child orders placed).

        Rejection condition is STRICT: estimate.slippage_bps > max_bps.
        Equality passes (so borderline orders still proceed and can be
        handled by a more-passive router bucket).
        """
        effective_max = self._resolve_max_normal(max_bps)
        est_slip = float(getattr(estimate_result, "slippage_bps", 0.0) or 0.0)

        if effective_max <= 0:
            # Degenerate 0 / negative max — treat everything as reject.
            return False, (
                f"{REJECT_SLIPPAGE_TOO_HIGH}: max_bps={effective_max:.3f}"
            )

        if est_slip > effective_max + 1e-12:
            reason = (
                f"{REJECT_SLIPPAGE_TOO_HIGH}: "
                f"estimated_slippage={est_slip:.3f} bps > "
                f"max_bps={effective_max:.3f} bps"
                + (f" [fail_open={estimate_result.fail_open}]"
                   if getattr(estimate_result, "fail_open", False) else "")
            )
            return False, reason
        return True, None

    # ── Tier 2: runtime gate (AC-5) ───────────────────────────────────
    def check_runtime(
        self,
        running_slippage_bps: float,
        max_bps: Optional[float] = None,
        buffer_mult: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Return True if current realized slippage exceeds the kill
        threshold (max_bps × buffer_mult).

        Inclusive behaviour: threshold boundary is PASS, not trigger.
        This avoids flapping between kill / no-kill when slip dances
        around the exact value. Strict greater-than only triggers kill.
        """
        effective_max = self._resolve_max_normal(max_bps)
        effective_buf = (
            float(buffer_mult)
            if buffer_mult is not None
            else self.default_buffer_mult
        )
        threshold = effective_max * max(0.0, effective_buf)
        slip = float(running_slippage_bps or 0.0)

        if slip > threshold + 1e-12:
            reason = (
                f"{KILL_SWITCH_TRIGGERED}: running_slippage={slip:.3f} bps > "
                f"threshold({effective_max:.3f} bps × {effective_buf:.2f} = "
                f"{threshold:.3f} bps)"
            )
            return True, reason
        return False, None

    # ── helpers ────────────────────────────────────────────────────────
    def _resolve_max_normal(self, max_bps: Optional[float]) -> float:
        if max_bps is None:
            return self.default_max_normal_bps
        return float(max_bps)

    # ── convenience for algorithm close-out construction ──────────────
    def close_out_suggestion(
        self,
        remaining_sz: float,
        max_bps: Optional[float] = None,
        *,
        tag: Optional[str] = None,
        reason_extra: str = "",
        suggestion: Optional[CloseOutSuggestion] = None,
    ) -> Dict[str, Any]:
        """Return kwargs for DirectMarket/place_order that close the
        remaining size. Caller is responsible for side/inst_id/pos_side."""
        s = suggestion or CloseOutSuggestion()
        bps = s.bps(max_bps or self.default_max_normal_bps)
        return {
            "ord_type": s.ord_type,
            "sz": float(remaining_sz),
            "tag": tag or s.tag,
            "reason": s.reason + (f": {reason_extra}" if reason_extra else ""),
            "max_slippage_bps": bps,
            "_suggestion_meta": {
                "multiplier": s.max_slippage_bps_multiplier,
                "effective_max_bps": max_bps or self.default_max_normal_bps,
            },
        }
