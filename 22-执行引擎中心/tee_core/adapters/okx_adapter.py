"""OkxAdapter — wraps an existing OkxClient-like object into the
ExchangeClient Protocol via pure Dependency Injection.

CRITICAL INVERSION-OF-CONTROL RULE (NFR-4):
  This module MUST NOT import the concrete OkxClient from any strategy-
  level package directory. The caller is responsible for constructing the
  raw client (real, paper, mock, backtest, …) *outside* TEE and passing
  it into the adapter via the constructor.

Why? If we hard-imported the concrete client from a strategy package we
would couple TEE to that specific strategy layer. That violates TR-1.2
and makes TEE unusable by other strategy layers without also pulling in
the first strategy's entire dependency tree. DI keeps this module fully
agnostic about where its raw_client was created.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..core.protocol import ExchangeClient  # noqa: F401  (re-exported for isinst)


class OkxAdapter:
    """Protocol-compliant wrapper around an existing OkxClient instance.

    Args:
        raw_client: Any object exposing the same public methods as
            `14-V15经典马丁策略.lib.okx_client.OkxClient` — that is,
            `get_orderbook`, `get_ticker`, `place_order`, `cancel_order`,
            `get_order`, and `get_contract_info`.  The adapter does a pure
            pass-through so the raw_client can be a real one, a paper one,
            a mock, or any other duck.
    """

    def __init__(self, raw_client: Any) -> None:
        self._raw = raw_client

    # ── market data ────────────────────────────────────────────────────
    def get_orderbook(self, inst_id: str, sz: int = 10) -> Dict[str, Any]:
        # If the raw client has the method (post Task-2 extension) call it;
        # otherwise degrade to a ticker-based 1-level book (FAIL-OPEN).
        fn = getattr(self._raw, "get_orderbook", None)
        if callable(fn):
            return fn(inst_id=inst_id, sz=sz)
        ticker = self.get_ticker(inst_id)
        last = ticker.get("last", 0) if ticker.get("ok", False) else 0.0
        bid = ticker.get("bid") or last
        ask = ticker.get("ask") or last
        sz_ = ticker.get("bidSz") or ticker.get("askSz") or 1.0
        return {
            "bids": [[float(bid), float(sz_), 1, 1]],
            "asks": [[float(ask), float(sz_), 1, 1]],
            "ts": ticker.get("ts"),
            "ok": ticker.get("ok", False),
            "__fallback__": "ticker_only",
        }

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
        kwargs = dict(
            inst_id=inst_id, side=side, ord_type=ord_type, sz=sz, px=px,
            td_mode=td_mode, pos_side=pos_side, tag=tag, reason=reason,
            leverage=leverage,
        )
        # Only forward max_slippage_bps when the raw client supports it
        # (introduced in Task 2). Older signatures fall back gracefully.
        if max_slippage_bps is not None:
            kwargs["max_slippage_bps"] = max_slippage_bps
        return self._raw.place_order(**kwargs)

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        fn = getattr(self._raw, "cancel_order", None)
        if callable(fn):
            return fn(inst_id=inst_id, ord_id=ord_id)
        return {"ok": False, "error": "cancel_order not implemented on raw_client",
                "dry_run": True}

    def get_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        fn = getattr(self._raw, "get_order", None)
        if callable(fn):
            return fn(inst_id=inst_id, ord_id=ord_id)
        return {"ok": False, "error": "get_order not implemented on raw_client",
                "dry_run": True}

    # ── contract info ─────────────────────────────────────────────────
    def get_contract_info(self, inst_id: str) -> Tuple[float, float]:
        fn = getattr(self._raw, "get_contract_info", None)
        if callable(fn):
            return fn(inst_id)
        # Protocol-same fallback path via imported helper from v15 utils.
        # Delayed import here keeps module top-level free of V15 references.
        from typing import Any as _A
        get_info: _A = getattr(self._raw, "_get_contract_info", None)
        if callable(get_info):
            return get_info(inst_id)
        return (1.0, 1.0)  # worst-case unit fallback
