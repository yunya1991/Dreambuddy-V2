"""Base interface shared by all TEE execution algorithms.

Every concrete algorithm subclasses :class:`ExecutionAlgorithm`,
implements :meth:`run`, and returns an :class:`AlgoRunResult`. The base
class itself only holds pure helpers (nothing exchange-specific) so it
can be unit-tested without any strategy-package imports (NFR-4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable


# ── return shape (mandated fields by FR-2.1 / spec) ───────────────────
@dataclass
class AlgoRunResult:
    """Uniform result shape for every algorithm's ``run`` method."""
    child_orders: List[Dict[str, Any]] = field(default_factory=list)
    final_vwap: Optional[float] = None
    final_slippage_bps: Optional[float] = None
    remaining_sz: float = 0.0
    kvs: Dict[str, Any] = field(default_factory=dict)


# ── protocol-typing of the two callbacks so IDEs see signatures ───────
@runtime_checkable
class KillSwitchCb(Protocol):
    def __call__(self, running_slippage_bps: float,
                 extra: Optional[Dict[str, Any]] = None) -> tuple[bool, Optional[str]]:
        ...


@runtime_checkable
class AuditCb(Protocol):
    def __call__(self, stage: str,
                 payload: Optional[Dict[str, Any]] = None) -> None:
        ...


# ── base class ─────────────────────────────────────────────────────────
class ExecutionAlgorithm(ABC):
    """Polymorphic entry point for the engine algorithm dispatch loop."""

    NAME: str = "base"

    @abstractmethod
    def run(
        self,
        parent_req: Dict[str, Any],
        algo_params: Dict[str, Any],
        client: Any,
        estimator: Any,
        kill_switch_cb: Callable[..., Any],
        audit_cb: Callable[..., Any],
    ) -> AlgoRunResult:  # pragma: no cover - pure abstract
        """Execute the parent order using this algorithm.

        Args:
            parent_req:        dict-shaped ParentRequest (inst_id, side, sz,
                               decision_px, …).
            algo_params:       router-provided hints dict (window_sec,
                               num_slices, escalate_*, rehang_sec, …).
            client:            ExchangeClient Protocol duck.
            estimator:         SlippageEstimator-like (unused in MVP but
                               reserved for future POV behaviour).
            kill_switch_cb(running_slip_bps, extra) -> (trigger, reason):
                               Called after every de-fill event. Return
                               (True, reason) → cancel outstanding children
                               and stop NOW (returns non-zero remaining_sz).
            audit_cb(stage, payload):
                               Structured event stream — appended to the
                               parent-order JSONL line by the engine.

        Returns:
            A filled :class:`AlgoRunResult`. The ``.kvs`` dict may
            optionally carry algorithm-specific diagnostics (e.g. which
            escalation tier was reached, passive→twap fallback observed
            fill-rate, …).
        """
        raise NotImplementedError

    # ── common helpers available to all subclasses ────────────────────
    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    @staticmethod
    def _best_bid_ask(client: Any, inst_id: str) -> tuple[Optional[float], Optional[float]]:
        """Cheap top-of-book lookup — book ok → bid[0]/ask[0], else ticker."""
        bid = ask = None
        try:
            b = client.get_orderbook(inst_id, sz=1)
            if b.get("ok") and b.get("asks") and b.get("bids"):
                try:
                    bid = float(b["bids"][0][0])
                    ask = float(b["asks"][0][0])
                except (TypeError, ValueError, IndexError, KeyError):
                    bid = ask = None
        except Exception:  # noqa: BLE001
            bid = ask = None
        if bid is None or ask is None:
            try:
                t = client.get_ticker(inst_id)
                if t.get("ok"):
                    if bid is None:
                        bid = t.get("bid") if isinstance(t.get("bid"), (int, float)) else None
                    if ask is None:
                        ask = t.get("ask") if isinstance(t.get("ask"), (int, float)) else None
            except Exception:  # noqa: BLE001
                pass
        # Ticker fallback returns strings sometimes; coerce once.
        if isinstance(bid, (int, float, str)):
            try: bid = float(bid)  # type: ignore[arg-type]
            except (TypeError, ValueError): bid = None
        if isinstance(ask, (int, float, str)):
            try: ask = float(ask)  # type: ignore[arg-type]
            except (TypeError, ValueError): ask = None
        return bid, ask
