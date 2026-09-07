"""Task 3 RED → GREEN tests — Protocol (TR-3.1), OkxAdapter delegation (TR-3.2),
PaperAdapter state flow (TR-3.3).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---- conftest equivalent: sys.path for v15 lib imports -------------------
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "14-V15经典马丁策略" / "lib"))
sys.path.insert(0, str(REPO / "22-执行引擎中心"))

from tee_core.core.protocol import ExchangeClient   # noqa: E402
from tee_core.adapters.okx_adapter import OkxAdapter  # noqa: E402


# =====================================================================
# TR-3.1: Protocol runtime-checkable passes for both adapter classes
# =====================================================================
class TestProtocolRuntimeCheckable:
    """Verify adapters satisfy `isinstance(..., ExchangeClient)`."""

    def test_okx_adapter_is_exchange_client(self):
        inst = OkxAdapter(MagicMock())
        assert isinstance(inst, ExchangeClient), (
            "OkxAdapter missing a method declared in ExchangeClient Protocol."
            f" MRO methods present: {[m for m in dir(inst) if not m.startswith('_')]}"
        )

    def test_paper_adapter_exists_and_is_exchange_client(self, tmp_path):
        """RED trigger: paper_adapter module must exist + class must be
        importable; the class must implement all 6 Protocol methods."""
        # RED phase: before GREEN, import raises ModuleNotFoundError.
        from tee_core.adapters.paper_adapter import PaperAdapter  # noqa

        from v15_paper_client import V15PaperClient
        paper = V15PaperClient(ledger_path=str(tmp_path / "x.json"))
        inst = PaperAdapter(paper)
        assert isinstance(inst, ExchangeClient), (
            "PaperAdapter missing a method declared in ExchangeClient Protocol."
        )

    def test_protocol_signature_parity_for_place_order(self):
        """place_order() signature must contain all 11 parameters
        (inst_id/side/ord_type/sz/px/td_mode/pos_side/tag/reason/leverage/
        max_slippage_bps) with matching names so callers don't hit
        TypeError on keyword dispatch."""
        sig = inspect.signature(ExchangeClient.place_order)
        names = list(sig.parameters.keys())
        required = [
            "self", "inst_id", "side", "ord_type", "sz", "px",
            "td_mode", "pos_side", "tag", "reason", "leverage",
            "max_slippage_bps",
        ]
        assert required == names, f"Protocol signature mismatch: {names}"


# =====================================================================
# TR-3.2: OkxAdapter delegates to raw_client with args pass-through
# =====================================================================
class TestOkxAdapterDelegation:
    @pytest.fixture
    def raw(self):
        r = MagicMock()
        # Defaults for methods that don't matter individually
        r.get_orderbook.return_value = {"ok": True, "bids": [], "asks": [], "ts": "1"}
        r.get_ticker.return_value = {"ok": True, "last": 100, "bid": 99, "ask": 101}
        r.place_order.return_value = {"ok": True, "ord_id": "X"}
        r.cancel_order.return_value = {"ok": True, "ord_id": "X"}
        r.get_order.return_value = {"ok": True, "ord_id": "X", "state": "filled"}
        r.get_contract_info.return_value = (0.01, 1.0)
        return r

    @pytest.fixture
    def adapter(self, raw):
        return OkxAdapter(raw)

    def test_get_orderbook_delegation(self, adapter, raw):
        result = adapter.get_orderbook("BTC-USDT-SWAP", sz=5)
        raw.get_orderbook.assert_called_once_with(inst_id="BTC-USDT-SWAP", sz=5)
        assert result is raw.get_orderbook.return_value  # pure pass-through

    def test_get_ticker_delegation_with_arg(self, adapter, raw):
        adapter.get_ticker("BTC")
        raw.get_ticker.assert_called_once_with("BTC")

    def test_get_ticker_delegation_none(self, adapter, raw):
        adapter.get_ticker(None)
        raw.get_ticker.assert_called_once()

    def test_place_order_all_kwargs_forwarded(self, adapter, raw):
        adapter.place_order(
            inst_id="BTC", side="buy", ord_type="limit",
            sz=2.0, px=67000.0,
            td_mode="cross", pos_side="long",
            tag="unittest", reason="delegation-check",
            leverage=3.0, max_slippage_bps=15,
        )
        raw.place_order.assert_called_once_with(
            inst_id="BTC", side="buy", ord_type="limit", sz=2.0, px=67000.0,
            td_mode="cross", pos_side="long", tag="unittest",
            reason="delegation-check", leverage=3.0, max_slippage_bps=15,
        )

    def test_place_order_max_slippage_none_not_forwarded_when_absent(self, adapter, raw):
        """Back-compat safeguard: when caller passes nothing, adapter only
        forwards explicitly-supported kwargs. Our adapter can always pass
        the kwarg now that Task2 signatures accept it; but the test checks
        that the actual call to raw.place_order() contains the right dict
        and the function actually receives `max_slippage_bps=None` as a
        positional-or-keyword parameter (it does, per Task2 signature)."""
        adapter.place_order(inst_id="BTC", side="buy", sz=1)
        called_kwargs = raw.place_order.call_args.kwargs
        # The adapter must always send leverage (even None) because
        # Task2 signature accepts leverage=None default.
        assert called_kwargs["inst_id"] == "BTC"
        assert called_kwargs["side"] == "buy"
        assert called_kwargs["sz"] == 1
        # Defaults propagated
        assert called_kwargs["ord_type"] == "market"
        assert called_kwargs["td_mode"] == "isolated"
        assert called_kwargs["pos_side"] == "net"
        # max_slippage_bps, when omitted by caller, adapter also omits
        # unless caller set it. (See implementation: conditional inclusion.)
        assert "max_slippage_bps" not in called_kwargs

    def test_cancel_order_delegation(self, adapter, raw):
        rv = adapter.cancel_order("BTC", "O-1")
        raw.cancel_order.assert_called_once_with(inst_id="BTC", ord_id="O-1")
        assert rv is raw.cancel_order.return_value

    def test_get_order_delegation(self, adapter, raw):
        rv = adapter.get_order("BTC", "O-1")
        raw.get_order.assert_called_once_with(inst_id="BTC", ord_id="O-1")
        assert rv is raw.get_order.return_value

    def test_get_contract_info_delegation(self, adapter, raw):
        rv = adapter.get_contract_info("BTC-USDT-SWAP")
        raw.get_contract_info.assert_called_once_with("BTC-USDT-SWAP")
        assert rv == (0.01, 1.0)


# =====================================================================
# TR-3.3: PaperAdapter state flow: order → live → cancel → canceled
# =====================================================================
class TestPaperAdapterStateFlow:
    def test_limit_order_lifecycle_through_paper_adapter(self, tmp_path):
        from tee_core.adapters.paper_adapter import PaperAdapter  # RED trigger
        from v15_paper_client import V15PaperClient

        pc = V15PaperClient(ledger_path=str(tmp_path / "paper.json"))
        pa = PaperAdapter(pc)

        # Submit a limit order far from mid — it should remain live.
        # Using an extreme price to avoid crossing synthetic fill window.
        open_r = pa.place_order(
            inst_id="BTC-USDT-SWAP", side="buy", ord_type="limit",
            sz=0.01, px=1.0,           # absurdly low; won't cross
            td_mode="isolated", pos_side="long", tag="ut",
        )
        assert open_r.get("ok") is True, f"paper place_order failed: {open_r}"
        ord_id = open_r.get("ord_id")
        assert ord_id, "paper adapter must return ord_id after live limit order"

        # Post-open state == live
        g1 = pa.get_order(inst_id="BTC-USDT-SWAP", ord_id=ord_id)
        assert g1["ok"] is True
        assert g1["state"] == "live", (
            f"Expected live after limit open, got {g1['state']}. "
            f"get_order payload: {g1}"
        )
        assert float(g1.get("filled_sz", 1.0)) == 0.0, (
            "far-from-mid limit should not have filled yet"
        )

        # Cancel → state transitions to canceled
        cr = pa.cancel_order(inst_id="BTC-USDT-SWAP", ord_id=ord_id)
        assert cr["ok"] is True, f"cancel failed: {cr}"

        g2 = pa.get_order(inst_id="BTC-USDT-SWAP", ord_id=ord_id)
        assert g2["ok"] is True
        assert g2["state"] == "canceled", (
            f"Expected canceled after cancel_order, got {g2['state']}"
        )
