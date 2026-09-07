"""PaperAdapter — wraps a V15PaperClient instance to satisfy the
ExchangeClient Protocol.

Dependency-injected just like :class:`OkxAdapter`: callers construct the
raw V15PaperClient outside TEE, hand it in here. This keeps TEE core free
of any strategy-package imports (NFR-4).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


class PaperAdapter:
    """Protocol-compliant wrapper around a ``V15PaperClient``.

    PaperClient already exposes all five trading+market methods after
    Task-2 signature parity. This adapter is intentionally a pure
    pass-through so that existing V15PaperClient state transitions (live
    → filled / live → canceled) flow through unchanged.

    The one translation it performs is ``get_contract_info`` →
    ``V15PaperClient.get_instrument``, which returns a different key set.
    """

    def __init__(self, raw_client: Any) -> None:
        self._raw = raw_client

    # ── market data ────────────────────────────────────────────────────
    def get_orderbook(self, inst_id: str, sz: int = 10) -> Dict[str, Any]:
        return self._raw.get_orderbook(inst_id=inst_id, sz=sz)

    def get_ticker(self, inst_id: Optional[str] = None) -> Dict[str, Any]:
        if inst_id is None:
            return self._raw.get_ticker()
        return self._raw.get_ticker(inst_id)

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
        return self._raw.place_order(
            inst_id=inst_id, side=side, ord_type=ord_type, sz=sz, px=px,
            td_mode=td_mode, pos_side=pos_side, tag=tag, reason=reason,
            leverage=leverage, max_slippage_bps=max_slippage_bps,
        )

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        return self._raw.cancel_order(inst_id=inst_id, ord_id=ord_id)

    def get_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        return self._raw.get_order(inst_id=inst_id, ord_id=ord_id)

    # ── contract info ──────────────────────────────────────────────────
    def get_contract_info(self, inst_id: str) -> Tuple[float, float]:
        """Return (lot_sz, ct_val) via V15PaperClient.get_instrument.

        Paper does not expose ``get_contract_info`` directly; its
        analogue is ``get_instrument`` which returns ``{lot_sz, ct_val}``
        under different keys. We translate here so the rest of TEE sees
        one consistent (lot_sz, ct_val) tuple across all adapters.
        """
        # Duck-dispatch: prefer a direct get_contract_info method if any
        # paper subclass adds it in the future.
        fn = getattr(self._raw, "get_contract_info", None)
        if callable(fn):
            return fn(inst_id)
        info = self._raw.get_instrument(inst_id)
        if not info.get("ok"):
            return (1.0, 1.0)  # safe neutral fallback matching OkxAdapter
        return (
            float(info.get("lot_sz", 1.0)),
            float(info.get("ct_val", 1.0)),
        )
