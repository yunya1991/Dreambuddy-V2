"""DirectMarket — place one single market order with optional slippage bps.

Used for the ``DIRECT`` router bucket and as the FAIL-OPEN fallback
when any part of TEE misbehaves (Task 8 / AC-6). Deliberately tiny: a
single ``place_order`` call → wait ``filled_sz`` → return result.

NFR-5 guarantee: when ``algo_params.get("direct_no_slippage_cap")`` is
True the caller is asserting ENABLE_TEE=False — the resulting
``place_order`` call is byte-identical to the legacy
``client.place_order(...)`` baseline (no max_slippage_bps kwarg).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict

from .base import AlgoRunResult, ExecutionAlgorithm


class DirectMarket(ExecutionAlgorithm):
    NAME = "direct"

    def run(
        self,
        parent_req: Dict[str, Any],
        algo_params: Dict[str, Any],
        client: Any,
        estimator: Any,
        kill_switch_cb: Callable[..., Any],
        audit_cb: Callable[..., Any],
    ) -> AlgoRunResult:
        audit_cb("DM_START", {"inst_id": parent_req.get("inst_id"),
                              "sz": parent_req.get("sz")})

        kwargs = dict(
            inst_id=parent_req["inst_id"],
            side=parent_req["side"],
            ord_type="market",
            sz=parent_req["sz"],
            td_mode=parent_req.get("td_mode", "isolated"),
            pos_side=parent_req.get("pos_side", "net"),
            tag=parent_req.get("tag", "tee_direct"),
            reason=parent_req.get("reason", "tee_direct"),
            leverage=parent_req.get("leverage"),
        )
        # When the engine is simulating ENABLE_TEE=False byte-equivalence
        # mode it explicitly opts out of max_slippage_bps (TR-2.3 baseline).
        if not algo_params.get("direct_no_slippage_cap", False):
            max_bps = algo_params.get("max_slippage_bps")
            if max_bps is not None:
                kwargs["max_slippage_bps"] = max_bps

        placed = client.place_order(**kwargs)
        if not placed.get("ok"):
            audit_cb("DM_PLACE_FAIL", {"raw": placed})
            return AlgoRunResult(
                child_orders=[], final_vwap=None,
                final_slippage_bps=None, remaining_sz=float(parent_req["sz"]),
                kvs={"error": placed.get("error") or "place_order not ok"},
            )

        ord_id = placed.get("ord_id")
        audit_cb("DM_PLACED", {"ord_id": ord_id,
                                "placed": _safe_raw_stub(placed)})

        # Wait briefly for filled state. Paper/backtest fills are instant;
        # live waits up to 5s then reports whatever partial state we have.
        total_fill, avg_px, last_state = self._wait_fill(
            client, parent_req["inst_id"], ord_id,
            timeout_sec=algo_params.get("direct_wait_sec", 5.0),
            poll_sec=0.2,
        )
        audit_cb("DM_SETTLED", {"ord_id": ord_id, "state": last_state,
                                 "filled_sz": total_fill, "avg_px": avg_px})

        remaining = max(0.0, float(parent_req["sz"]) - float(total_fill))
        decision = float(parent_req.get("decision_px") or 0.0)
        vwap = float(avg_px) if (avg_px is not None and total_fill > 0) else None
        slip_bps = None
        if vwap is not None and decision > 0:
            slip_bps = (vwap - decision) / decision * 10000.0
            if kill_switch_cb:
                fired, reason = kill_switch_cb(slip_bps, {"algo": "dm"})
                if fired:
                    audit_cb("DM_KILL_SWITCH", {"reason": reason,
                                                 "slip": slip_bps})

        return AlgoRunResult(
            child_orders=[{
                "ord_id": ord_id, "ord_type": "market",
                "px_submitted": None,
                "sz_submitted": float(parent_req["sz"]),
                "px_filled": vwap,
                "sz_filled": float(total_fill),
                "slippage_bps": slip_bps if slip_bps is not None else 0.0,
                "ts_submitted_ms": int(time.time() * 1000),
            }],
            final_vwap=vwap,
            final_slippage_bps=slip_bps,
            remaining_sz=float(remaining),
            kvs={"state": last_state},
        )

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _wait_fill(client: Any, inst_id: str, ord_id: str,
                   timeout_sec: float, poll_sec: float):
        deadline = time.time() + max(0.0, float(timeout_sec))
        last: Dict[str, Any] = {"state": "unknown"}
        filled = 0.0
        avg_px = None
        while time.time() < deadline:
            try:
                last = client.get_order(inst_id=inst_id, ord_id=ord_id) or last
            except Exception:  # noqa: BLE001
                last = {"state": "error"}
            state = str(last.get("state", "live")).lower()
            if state in ("filled", "canceled"):
                break
            # live or partial — accumulate latest totals
            try:
                filled = float(last.get("filled_sz", filled) or filled)
                avg = float(last.get("avg_px", 0) or 0)
                if filled > 0 and avg > 0:
                    avg_px = avg
            except (TypeError, ValueError):
                pass
            time.sleep(min(poll_sec, max(0.0, deadline - time.time()) + 1e-6))
        # After timeout, capture the latest state again if we still can.
        try:
            last_final = client.get_order(inst_id=inst_id, ord_id=ord_id)
            if last_final and last_final.get("ok"):
                last = last_final
        except Exception:  # noqa: BLE001
            pass
        try:
            filled = float(last.get("filled_sz", filled) or filled)
            avg = float(last.get("avg_px", 0) or 0)
            if filled > 0 and avg > 0:
                avg_px = avg
        except (TypeError, ValueError):
            pass
        return filled, avg_px, last.get("state")


def _safe_raw_stub(placed: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": placed.get("ok"), "ord_id": placed.get("ord_id"),
            "dry_run": placed.get("dry_run")}
