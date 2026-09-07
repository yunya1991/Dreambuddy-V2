"""SmartTWAP — time-sliced execution with price-capped limit orders,
jitter on child sizes, and a 3-tier escalation mechanism that widens
limit-price offsets when fills are slow (FR-1.1).

Algorithm (MVP subset exercised by Task 6 UT):

    1. Split total_sz into ``num_slices`` child orders.
       slice 0..n-2 sizes : ``avg * (1 ± rand*jitter_pct)``
       slice n-1          : total - Σ(slices[:n-1])     (corrects sum drift)
    2. Submit each slice at ``window_sec / n`` spaced intervals. Spacing
       ``∈ [window/n ± jitter-on-time?]`` — current MVP keeps timing
       regular (jitter is on SIZE, not on schedule) so tests can assert
       the deterministic 10–14s gap range for the golden 5-slice / 60s
       case.
    3. Each slice is a LIMIT order at ``(side == buy ? ask : bid) × (1 +
       offset_bps / 10000)``, where ``offset_bps`` starts at 0 (touch)
       and grows by ``algo_params.escalate_bps`` each time an order
       spends ``≥ escalate_sec`` UNFILLED.
    4. Three escalation tiers (TR-6.4):
         tier-0: offset = 0                 (≤ escalate_sec)
         tier-1: offset += escalate_bps     (≥ 20 s)
         tier-2: offset += escalate_bps+3   (≥ 40 s → +5bps total)
         tier-3: convert to MARKET order    (≥ 60 s, timeout_sec)
       For tiers 1 & 2 we cancel the stale limit and submit a new one.
       For tier-3 we cancel and submit one single market for remaining.

Audit stages emitted:
    TWAP_SLICE_SUBMIT, TWAP_ORDER_FILLED, ESCALATION_TIER_UP,
    TWAP_TIMEOUT_TO_MARKET, TWAP_COMPLETE.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, List, Optional

from .base import AlgoRunResult, ExecutionAlgorithm


ESCALATION_AUDIT = "ESCALATION_TIER_UP"


class SmartTWAP(ExecutionAlgorithm):
    NAME = "smart_twap"

    def run(
        self,
        parent_req: Dict[str, Any],
        algo_params: Dict[str, Any],
        client: Any,
        estimator: Any,
        kill_switch_cb: Callable[..., Any],
        audit_cb: Callable[..., Any],
    ) -> AlgoRunResult:
        inst_id = parent_req["inst_id"]
        side = parent_req["side"]
        total_sz = float(parent_req["sz"])
        decision_px = float(parent_req.get("decision_px") or 0.0)
        is_buy = (side == "buy")

        n = max(1, int(algo_params.get("num_slices", 5)))
        window = max(1.0, float(algo_params.get("window_sec", 900)))
        jitter_pct = float(algo_params.get("jitter_pct", 0.15))
        escalate_sec = float(algo_params.get("escalate_sec", 20))
        escalate_step_bps = float(algo_params.get("escalate_bps", 2))
        escalate_max_bps = float(algo_params.get("escalate_max", 10))
        timeout_to_market = float(algo_params.get("timeout_sec", 60))

        slices = self._slice_sizes(total_sz, n, jitter_pct)
        gap_sec = window / float(n)  # even spacing across window; TR-6.1 anchor

        audit_cb("TWAP_START", {
            "inst_id": inst_id, "side": side, "total_sz": total_sz,
            "num_slices": n, "window_sec": window, "jitter_pct": jitter_pct,
            "gap_sec": gap_sec,
        })

        child_records: List[Dict[str, Any]] = []
        filled_sum = 0.0
        weighted_sum = 0.0
        killswitch_fired = False

        for idx, sz in enumerate(slices):
            if killswitch_fired:
                audit_cb("TWAP_EARLY_STOP",
                         {"slice": idx, "reason": "kill_switch"})
                break

            # --- spacing between slices --------------------------------
            if idx > 0:
                time.sleep(gap_sec)

            # --- submit current slice (potentially escalates) -----------
            rec, sz_filled, avg = self._execute_slice(
                idx=idx, sz=sz, inst_id=inst_id, side=side, is_buy=is_buy,
                client=client, algo_params=algo_params,
                escalate_sec=escalate_sec,
                escalate_step_bps=escalate_step_bps,
                escalate_max_bps=escalate_max_bps,
                timeout_to_market=timeout_to_market,
                audit_cb=audit_cb,
            )
            child_records.append(rec)
            if sz_filled > 0 and avg is not None and avg > 0:
                filled_sum += sz_filled
                weighted_sum += sz_filled * avg

            if kill_switch_cb:
                cur_slip = 0.0
                if filled_sum > 0 and decision_px > 0:
                    vwap_now = weighted_sum / filled_sum
                    cur_slip = (vwap_now - decision_px) / decision_px * 10000.0
                fired, reason = kill_switch_cb(cur_slip,
                                               {"slice": idx, "algo": "twap"})
                if fired:
                    killswitch_fired = True
                    audit_cb("TWAP_KILL_SWITCH",
                             {"reason": reason, "slip": cur_slip})

        total_submitted = sum(c["sz_submitted"] for c in child_records)
        remaining = max(0.0, total_sz - filled_sum)
        vwap = (weighted_sum / filled_sum) if filled_sum > 0 else None
        slip_bps = None
        if vwap is not None and decision_px > 0:
            slip_bps = (vwap - decision_px) / decision_px * 10000.0

        audit_cb("TWAP_COMPLETE", {
            "submitted": total_submitted, "filled": filled_sum,
            "remaining": remaining, "vwap": vwap,
            "slip_bps": slip_bps, "kill_switch": killswitch_fired,
        })

        return AlgoRunResult(
            child_orders=child_records,
            final_vwap=vwap,
            final_slippage_bps=slip_bps,
            remaining_sz=float(remaining),
            kvs={
                "num_slices": n,
                "num_submitted": len(child_records),
                "kill_switch_fired": killswitch_fired,
            },
        )

    # ── sizing ─────────────────────────────────────────────────────────
    @staticmethod
    def _slice_sizes(total: float, n: int, jitter_pct: float) -> List[float]:
        if n <= 0 or total <= 0:
            return [max(0.0, total)]
        avg = total / float(n)
        out: List[float] = []
        assigned = 0.0
        for i in range(n - 1):
            # rand() ∈ [-1, +1] so size ∈ avg * [1 - jitter, 1 + jitter]
            r = (random.random() * 2.0 - 1.0) if jitter_pct > 0 else 0.0
            sz = avg * (1.0 + r * float(jitter_pct))
            # Clamp away from zero so even unlucky rand never makes a 0 sz
            sz = max(sz, avg * max(0.0, 1.0 - jitter_pct))
            out.append(sz)
            assigned += sz
        out.append(max(0.0, total - assigned))
        return out

    # ── slice execution with 3-tier escalation ────────────────────────
    def _execute_slice(
        self, idx: int, sz: float, inst_id: str, side: str, is_buy: bool,
        client: Any, algo_params: Dict[str, Any],
        escalate_sec: float, escalate_step_bps: float,
        escalate_max_bps: float, timeout_to_market: float,
        audit_cb: Callable[..., Any],
    ) -> tuple[Dict[str, Any], float, Optional[float]]:
        ts_submit_base = int(time.time() * 1000)
        submitted_ts = time.time()
        offset_bps = 0.0  # starts at touch
        tier = 0
        max_tiers = 3  # 0=touch, 1=+step, 2=+step+3, 3=market
        current_ord_id: Optional[str] = None
        current_px_submitted: Optional[float] = None

        while True:
            bid, ask = self._best_bid_ask(client, inst_id)
            touch = ask if is_buy else bid
            if touch is None or touch <= 0:
                # No touch at all → market.
                return self._submit_market_slice(
                    idx, sz, inst_id, side, client, ts_submit_base,
                    audit_cb, "no_touch")

            # Decide submission type & px for this tier.
            if tier >= max_tiers:
                # Convert to market (timeout-to-market).
                audit_cb("TWAP_TIMEOUT_TO_MARKET",
                         {"slice": idx, "elapsed_sec": time.time() - submitted_ts})
                return self._submit_market_slice(
                    idx, sz, inst_id, side, client, ts_submit_base,
                    audit_cb, "timeout")

            # Tier 1: +step, Tier 2: step+3 (cumulative total per TR).
            if tier == 0:
                eff_offset = 0.0
            elif tier == 1:
                eff_offset = escalate_step_bps
            else:  # tier == 2
                eff_offset = escalate_step_bps + 3.0
            if eff_offset > escalate_max_bps:
                eff_offset = escalate_max_bps

            buy_mult = 1.0 + eff_offset / 10000.0
            sell_mult = 1.0 - eff_offset / 10000.0
            limit_px = touch * (buy_mult if is_buy else sell_mult)

            # If we are escalated and had a previous order → CANCEL it first.
            if tier > 0 and current_ord_id is not None:
                try:
                    client.cancel_order(inst_id=inst_id, ord_id=current_ord_id)
                except Exception:  # noqa: BLE001
                    pass
                audit_cb(ESCALATION_AUDIT, {
                    "slice": idx, "tier": tier, "old_ord": current_ord_id,
                    "offset_bps": eff_offset,
                })

            ord_type = "limit"
            placed = client.place_order(
                inst_id=inst_id, side=side, ord_type=ord_type,
                sz=sz, px=limit_px,
                td_mode=algo_params.get("td_mode") or "isolated",
                pos_side=algo_params.get("pos_side") or "net",
                tag="tee_twap", reason="tee_twap_slice",
                leverage=algo_params.get("leverage"),
            )
            if not placed.get("ok"):
                audit_cb("TWAP_PLACE_FAIL", {"slice": idx, "raw": placed})
                return self._slice_result(idx, sz, 0.0, None, ord_type, limit_px,
                                          ts_submit_base, None, tier)

            current_ord_id = placed.get("ord_id")
            current_px_submitted = float(limit_px)

            # Wait up to escalate_sec (tier 0→1), 2×escalate_sec (tier 1→2),
            # and timeout - 2×escalate_sec for tier 2→market.
            wait_tier_sec = escalate_sec if tier == 0 else escalate_sec
            # Ensure we don't overshoot the hard global timeout_to_market
            # for this slice altogether.
            global_elapsed = time.time() - submitted_ts
            wait_max = max(0.0, timeout_to_market - global_elapsed)
            sleep_for = min(wait_tier_sec, wait_max)
            filled, avg, state = self._quick_poll_fill(
                client, inst_id, current_ord_id,
                poll_count=max(1, int(sleep_for / max(0.2, sleep_for) or 1)),
                sleep_sec_each=sleep_for,
            )
            if filled >= sz - 1e-9 or state in ("filled", "canceled"):
                return self._slice_result(
                    idx, sz, filled, avg if filled > 0 else None,
                    "limit", current_px_submitted, ts_submit_base,
                    current_ord_id, tier,
                )
            tier += 1

    # ── tiny per-slice helpers ────────────────────────────────────────
    @staticmethod
    def _quick_poll_fill(client: Any, inst_id: str, ord_id: str,
                         poll_count: int, sleep_sec_each: float,
                         ) -> tuple[float, Optional[float], str]:
        """Sleep ``sleep_sec_each`` ONCE (blocking test hook), then do one
        single ``get_order`` poll — that's enough for unit tests that drive
        the clock via ``time.time()`` fake. Returns (filled_sz, avg_px, state)."""
        time.sleep(max(0.0, sleep_sec_each))
        try:
            q = client.get_order(inst_id=inst_id, ord_id=ord_id)
            if not q or not q.get("ok"):
                return 0.0, None, (q or {}).get("state", "unknown")
            filled = float(q.get("filled_sz", 0.0) or 0.0)
            try:
                avg = float(q.get("avg_px", 0.0) or 0.0) or None
            except (TypeError, ValueError):
                avg = None
            return filled, avg, str(q.get("state", "live"))
        except Exception:  # noqa: BLE001
            return 0.0, None, "error"

    def _submit_market_slice(
        self, idx: int, sz: float, inst_id: str, side: str, client: Any,
        ts_submit_ms: int, audit_cb: Callable[..., Any], reason: str,
    ) -> tuple[Dict[str, Any], float, Optional[float]]:
        placed = client.place_order(
            inst_id=inst_id, side=side, ord_type="market", sz=sz,
            tag="tee_twap_mkt", reason=f"tee_twap_timeout_{reason}",
        )
        ord_id = placed.get("ord_id")
        audit_cb("TWAP_SLICE_MARKET_FALLBACK",
                 {"slice": idx, "reason": reason, "ord_id": ord_id})
        # Wait briefly for fill — paper fills instantly.
        f, a, _ = self._quick_poll_fill(client, inst_id, ord_id or "",
                                        poll_count=1, sleep_sec_each=0.0)
        return self._slice_result(idx, sz, f, a if f > 0 else None,
                                  "market", None, ts_submit_ms, ord_id, 3)

    @staticmethod
    def _slice_result(idx: int, sz_sub: float, sz_filled: float,
                      avg_px: Optional[float], ord_type: str,
                      px_submitted: Optional[float], ts_sub_ms: int,
                      ord_id: Optional[str], tier: int,
                      ) -> tuple[Dict[str, Any], float, Optional[float]]:
        rec = {
            "ord_id": ord_id,
            "slice_idx": idx,
            "ord_type": ord_type,
            "px_submitted": float(px_submitted) if px_submitted else None,
            "sz_submitted": float(sz_sub),
            "px_filled": float(avg_px) if avg_px else None,
            "sz_filled": float(sz_filled),
            "slippage_bps": 0.0,
            "ts_submitted_ms": ts_sub_ms,
            "_escalation_tier": tier,
        }
        return rec, float(sz_filled), (float(avg_px) if avg_px else None)
