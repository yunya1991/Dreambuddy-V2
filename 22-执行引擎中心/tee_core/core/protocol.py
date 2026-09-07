"""ExchangeClient Protocol — dependency-inversion boundary.

TEE core never depends on any concrete exchange client. It only depends on
this runtime-checkable Protocol.

Adapters live in `tee_core/adapters/` (okx_adapter, paper_adapter, …).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class ExchangeClient(Protocol):
    """Minimum exchange surface required by TradeExecutionEngine."""

    # ── market data ────────────────────────────────────────────────────
    def get_orderbook(self, inst_id: str, sz: int = 10) -> Dict[str, Any]:
        """Top-N order book.

        Expected return shape::

            {
                "bids": [[px, sz, liq_orders, ord_count], ...],   # best first
                "asks": [[px, sz, liq_orders, ord_count], ...],   # best first
                "ts":   "epoch_ms_or_iso_string",
                "ok":   True,   # False if endpoint errored
            }

        For FAIL-OPEN paths a single-level synthetic book is acceptable.
        """
        ...

    def get_ticker(self, inst_id: Optional[str] = None) -> Dict[str, Any]:
        """Best bid/ask + last price (same contract as existing OkxClient)."""
        ...

    # ── trading ────────────────────────────────────────────────────────
    def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str = "market",
        sz: Optional[float] = None,
        px: Optional[float] = None,
        td_mode: str = "isolated",
        pos_side: str = "net",
        tag: str = "tee",
        reason: str = "",
        leverage: Optional[float] = None,
        max_slippage_bps: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Single order dispatch. With slippage cap the implementation
        rewrites market orders to capped-price limits."""
        ...

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        """Cancel a single order by id."""
        ...

    def get_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        """Fetch current state / filled sz / avg fill px for order."""
        ...

    # ── contract metadata ──────────────────────────────────────────────
    def get_contract_info(self, inst_id: str) -> Tuple[float, float]:
        """Return (lot_sz, ct_val). Used to align notional ↔ lot sz."""
        ...
