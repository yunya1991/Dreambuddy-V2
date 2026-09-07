"""Task 2 — OkxClient & PaperClient capability extensions (TDD RED → GREEN).

Extensions added by FR-2.4 (all must be backward-compatible byte-level):
  1. get_orderbook(inst_id, sz)      — new method
  2. place_order(..., max_slippage_bps=...)  — new OPTIONAL kwarg
       contract market → rewritten to price-capped LIMIT at bps offset
       default (no bps) → byte-identical request body to pre-Task-2
  3. cancel_order(inst_id, ord_id)   — new method
  4. get_order(inst_id, ord_id)      — new method

Test Requirements (tasks.md TR-2.1 .. TR-2.4):
  TR-2.1 get_orderbook mock HTTP parses correctly
  TR-2.2 place_order(buy, market, max_slippage_bps=30)  →  rewrites to LIMIT at best_ask × 1.0030
  TR-2.3 place_order(buy, market) WITHOUT max_slippage_bps → request body IDENTICAL
         (byte-equal fields and ordering) to pre-Task-2 semantics
  TR-2.4 cancel_order / get_order → correct path & params match OKX spec
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Import helpers for both clients ──────────────────────────────────
V15_DIR = Path(__file__).resolve().parents[3] / "14-V15经典马丁策略"
LIB_DIR = V15_DIR / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))


# =====================================================================
# OkxClient Task-2 tests
# =====================================================================
class TestOkxClientNewMethods:
    """All tests run against OkxClient with no credentials, so we can
    safely patch _get/_post and never hit the real network."""

    @pytest.fixture
    def client(self, monkeypatch):
        # Force no creds (use empty env) and standard cfg
        env = {k: "" for k in (
            "OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE",
            "OKX_BASE_URL", "OKX_SIMULATED", "OKX_DRY_RUN",
            "OKX_DEFAULT_INST_ID", "DEFAULT_LEVERAGE",
        )}
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        import okx_client as okx_mod
        # Reload to pick up monkeypatched env
        import importlib
        importlib.reload(okx_mod)
        # Real class name in okx_client.py is OKXSimulatedClient.
        assert hasattr(okx_mod, "OKXSimulatedClient"), (
            "okx_client module must expose OKXSimulatedClient class."
        )
        c = okx_mod.OKXSimulatedClient(config=None)
        c.dry_run = False  # disable dry_run shortcut so place_order reaches _post
        c.cfg["dry_run"] = False
        c._has_credentials = lambda: True  # override gate for reach-under-test
        return c

    # ── TR-2.1  get_orderbook ────────────────────────────────────────
    def test_get_orderbook_okx_path_and_params(self, client):
        """GET /api/v5/market/books with instId & sz=10, response parsed."""
        fake_resp = {
            "code": "0",
            "msg": "",
            "data": [{
                "asks": [
                    ["67000.1", "0.5", "1", "2"],
                    ["67001.0", "1.0", "3", "4"],
                ],
                "bids": [
                    ["66999.9", "0.4", "1", "1"],
                ],
                "ts": "1700000000000",
            }],
        }
        with patch.object(client, "_get", return_value=fake_resp) as mock_get:
            result = client.get_orderbook("BTC-USDT-SWAP", sz=10)
            args, kwargs = mock_get.call_args
            # positional: path, params
            assert args[0] == "/api/v5/market/books"
            params = args[1] if len(args) > 1 else kwargs.get("params", {})
            assert params["instId"] == "BTC-USDT-SWAP"
            assert int(params["sz"]) == 10
            assert result["ok"] is True
            assert len(result["asks"]) == 2
            assert float(result["asks"][0][0]) == pytest.approx(67000.1)
            assert float(result["asks"][0][1]) == pytest.approx(0.5)
            assert len(result["bids"]) == 1
            assert result["ts"] == "1700000000000"

    def test_get_orderbook_dryrun_uses_ticker_fallback(self, client):
        """When dry_run=True, avoid any HTTP and build a single-level
        book from get_ticker so estimator still has data to work with."""
        client.dry_run = True
        client.cfg["dry_run"] = True
        with patch.object(client, "get_ticker", return_value={
            "ok": True, "last": "67000",
            "bid": "66999", "ask": "67001",
            "bidSz": "2.0", "askSz": "1.5",
        }) as mock_ticker:
            r = client.get_orderbook("BTC-USDT-SWAP", sz=10)
            assert mock_ticker.called
            assert r["ok"] is True
            assert len(r["bids"]) >= 1 and len(r["asks"]) >= 1
            assert float(r["asks"][0][0]) == 67001.0
            assert float(r["bids"][0][0]) == 66999.0

    # ── TR-2.2  market + max_slippage_bps → limit rewrite ──────────
    def _capture_post_body(self, client, side="buy", sz=1, max_bps=None):
        captured: Dict[str, Any] = {}

        def fake_post(path, body):
            captured["path"] = path
            captured["body"] = deepcopy(body)
            # ok response shape
            return {"code": "0", "data": [{"ordId": "FAKE123"}]}

        with patch.object(client, "get_ticker", return_value={
            "ok": True, "last": "67000", "bid": "66999", "ask": "67001",
            "bidSz": "2", "askSz": "1",
        }), patch.object(client, "_post", side_effect=fake_post), \
             patch.object(client, "set_leverage", return_value={"code": "0"}):
            kwargs = dict(inst_id="BTC-USDT-SWAP", side=side,
                          ord_type="market", sz=sz, td_mode="isolated",
                          pos_side="long")
            if max_bps is not None:
                kwargs["max_slippage_bps"] = max_bps
            result = client.place_order(**kwargs)
        return captured, result

    def test_place_market_with_slippage_buy_becomes_limit(self, client):
        """Contract market BUY with bps=30 → LIMIT ask × 1.0030."""
        captured, result = self._capture_post_body(
            client, side="buy", sz=1, max_bps=30)
        assert captured["path"] == "/api/v5/trade/order"
        body = captured["body"]
        # Converted from market → limit
        assert body["ordType"] == "limit", (
            "market order with max_slippage_bps must be rewritten to limit"
        )
        # px = best_ask (67001) * 1.0030 = 67202.003
        expected_px = 67001 * 1.0030
        assert float(body["px"]) == pytest.approx(expected_px, rel=1e-8)
        assert float(body["sz"]) == 1.0
        assert result["ok"] is True
        assert result["ord_id"] == "FAKE123"

    def test_place_market_with_slippage_sell_becomes_limit(self, client):
        """Contract market SELL with bps=30 → LIMIT bid × 0.9970."""
        captured, _ = self._capture_post_body(
            client, side="sell", sz=2, max_bps=30)
        body = captured["body"]
        assert body["ordType"] == "limit"
        expected_px = 66999 * (1 - 30 / 10000.0)  # =66999*0.997=66798.003
        assert float(body["px"]) == pytest.approx(expected_px, rel=1e-8)
        assert float(body["sz"]) == 2.0

    def test_market_with_bps_ticker_unavailable_fallsback_pure_market(self, client):
        """If best bid/ask unavailable during bps-cap, fall back to pure
        market order rather than crashing."""
        captured: Dict[str, Any] = {}

        def fake_post(path, body):
            captured["path"] = path
            captured["body"] = deepcopy(body)
            return {"code": "0", "data": [{"ordId": "FAKE"}]}

        with patch.object(client, "get_ticker", return_value={"ok": True, "last": "67000"}), \
             patch.object(client, "_post", side_effect=fake_post), \
             patch.object(client, "set_leverage", return_value={"code": "0"}):
            r = client.place_order(inst_id="X", side="buy", ord_type="market",
                                   sz=1, max_slippage_bps=30,
                                   td_mode="isolated", pos_side="long")
        assert r["ok"] is True
        # Fallback: no px in body (pure market)
        assert captured["body"].get("ordType") == "market", (
            "when ticker lacks bid/ask the order must fall back to pure market"
        )
        assert "px" not in captured["body"]

    # ── TR-2.3  no max_slippage_bps → byte identical to legacy ──────
    def test_place_market_default_body_matches_legacy(self, client):
        """Without max_slippage_bps param the request body of a market
        order must match the pre-Task-2 exact field set (no extra keys)."""
        # Capture with current code (we just wrote bps support; it should
        # omit "px" if ord_type=market and omit max_slippage_bps entirely).
        captured_now, result = self._capture_post_body(
            client, side="buy", sz=1, max_bps=None)
        body = captured_now["body"]
        # Legacy (known) keys — NO "px", NO "slippagePct", NO extra bps field
        expected_key_set = {"instId", "tdMode", "side", "ordType",
                            "posSide", "tag", "sz"}
        assert set(body.keys()) == expected_key_set, (
            f"default place_order(market) should not add any new keys to "
            f"request body. Expected {sorted(expected_key_set)}, "
            f"got {sorted(body.keys())}"
        )
        assert body["ordType"] == "market"
        assert "px" not in body
        assert float(body["sz"]) == 1.0
        assert result["ok"] is True

    def test_place_limit_default_body_unchanged(self, client):
        """Limit orders (already send "px") must be unaffected by the
        max_slippage_bps support."""
        captured: Dict[str, Any] = {}

        def fake_post(path, body):
            captured["path"] = path
            captured["body"] = deepcopy(body)
            return {"code": "0", "data": [{"ordId": "LMT"}]}

        with patch.object(client, "_post", side_effect=fake_post), \
             patch.object(client, "set_leverage", return_value={"code": "0"}):
            client.place_order(inst_id="BTC", side="sell", ord_type="limit",
                               sz=2, px=68000.5, td_mode="isolated",
                               pos_side="short")
        body = captured["body"]
        assert body["ordType"] == "limit"
        assert float(body["px"]) == pytest.approx(68000.5)
        assert float(body["sz"]) == 2.0
        # must NOT silently rewrite to market or change the px
        assert "max_slippage_bps" not in json.dumps(body)

    # ── TR-2.4  cancel_order & get_order ─────────────────────────────
    def test_cancel_order_okx_path(self, client):
        captured: Dict[str, Any] = {}

        def fake_post(path, body):
            captured["path"] = path
            captured["body"] = deepcopy(body)
            return {"code": "0", "data": [{"ordId": "123"}]}

        with patch.object(client, "_post", side_effect=fake_post):
            r = client.cancel_order(inst_id="BTC-USDT-SWAP", ord_id="ORD-1")
        assert captured["path"] == "/api/v5/trade/cancel-order"
        assert captured["body"]["instId"] == "BTC-USDT-SWAP"
        assert captured["body"]["ordId"] == "ORD-1"
        assert r["ok"] is True

    def test_get_order_okx_path(self, client):
        with patch.object(client, "_get") as mock_get:
            mock_get.return_value = {
                "code": "0",
                "data": [{
                    "instId": "BTC",
                    "ordId": "O1",
                    "state": "filled",
                    "fillSz": "1",
                    "avgPx": "67000",
                    "side": "buy",
                    "posSide": "long",
                    "fee": "0",
                    "pnl": "0",
                }],
            }
            r = client.get_order("BTC-USDT-SWAP", ord_id="O1")
            args, kwargs = mock_get.call_args
            assert args[0] == "/api/v5/trade/order"
            params = args[1] if len(args) > 1 else kwargs.get("params", {})
            assert params["instId"] == "BTC-USDT-SWAP"
            assert params["ordId"] == "O1"
            # OKXSimulatedClient.get_order returns a FLATTENED dict (see okx_client.py L923).
            assert r["ok"] is True
            assert r["ord_id"] == "O1"
            assert r["state"] == "filled"
            assert r["filled_sz"] == pytest.approx(1.0)
            assert r["avg_px"] == pytest.approx(67000.0)


# =====================================================================
# PaperClient Task-2 mirror tests
#  (signature parity with OkxClient is the contract for Adapter layer)
# =====================================================================
class TestPaperClientSignatureParity:
    """PaperClient must expose the SAME 4 new method signatures as the
    real OkxClient so OkxAdapter can pass either in without branching."""

    @pytest.fixture
    def paper(self, tmp_path):
        import v15_paper_client
        import importlib
        importlib.reload(v15_paper_client)
        # V15PaperClient signature: __init__(self, ledger_path=None).
        # Use tmp_path for an isolated ledger so tests don't cross-contaminate.
        ledger = str(tmp_path / "paper_ledger.json")
        return v15_paper_client.V15PaperClient(ledger_path=ledger)

    def test_has_get_orderbook_method(self, paper):
        assert callable(getattr(paper, "get_orderbook", None))

    def test_get_orderbook_returns_shape_parity(self, paper):
        """Return shape must match OkxClient.get_orderbook (bids/asks/ts/ok)."""
        r = paper.get_orderbook("BTC-USDT-SWAP", sz=5)
        assert r["ok"] is True
        for k in ("bids", "asks", "ts"):
            assert k in r, f"paper.get_orderbook missing key '{k}'"
        assert isinstance(r["bids"], list) and isinstance(r["asks"], list)

    def test_place_order_signature_accepts_leverage_and_bps(self, paper):
        """Signature parity: place_order must accept (leverage, max_slippage_bps)
        without raising TypeError (legacy behavior unchanged otherwise)."""
        # paper has no orderbook, so slippage_bps param should be accepted
        # even if it only impacts behavior marginally; at minimum NO TypeError.
        try:
            r = paper.place_order(
                inst_id="BTC-USDT-SWAP", side="buy", ord_type="market",
                sz=1, td_mode="isolated", pos_side="long",
                leverage=5, max_slippage_bps=30,
            )
        except TypeError as exc:  # pragma: no cover
            pytest.fail(
                f"paper.place_order() rejected new kwargs: {exc}\n"
                "Signature must remain 100% forward-compatible with real client."
            )
        assert r["ok"] is True
        # And the legacy no-leverage/no-bps call must still succeed
        r2 = paper.place_order(inst_id="ETH-USDT-SWAP", side="sell",
                               ord_type="market", sz=2,
                               td_mode="isolated", pos_side="short")
        assert r2["ok"] is True

    def test_has_cancel_order_and_get_order(self, paper):
        for method in ("cancel_order", "get_order"):
            fn = getattr(paper, method, None)
            assert callable(fn), f"PaperClient missing method '{method}'"
            # Call with dummy args → must not raise TypeError / AttributeError
            r = fn(inst_id="BTC-USDT-SWAP", ord_id="SOME-ID")
            assert isinstance(r, dict)
            assert "ok" in r

    def test_paper_cancel_order_state_flow(self, paper):
        """Behavioral: live limit order exists → cancel → state canceled."""
        # Create a live limit order first
        placed = paper.place_order(inst_id="BTC-USDT-SWAP", side="buy",
                                   ord_type="limit", sz=1, px=50000,
                                   td_mode="isolated", pos_side="long")
        oid = placed["ord_id"]
        # Before cancel: get_order returns state "live"
        pre = paper.get_order("BTC-USDT-SWAP", oid)
        assert pre["ok"] is True and pre.get("state", "") != "canceled"
        # Cancel → ok
        c = paper.cancel_order("BTC-USDT-SWAP", oid)
        assert c["ok"] is True
        # After cancel: state == "canceled"
        post = paper.get_order("BTC-USDT-SWAP", oid)
        assert post["ok"] is True
        assert post.get("state") == "canceled"
