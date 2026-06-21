import json
import os
import unittest

import ml_trade_service as svc


class TestLiveSpotOrderSmoke(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_spot_order = getattr(svc, "_aster_spot_market_order", None)
        self._orig_token = os.environ.get("WEBHOOK_EXECUTE_TOKEN")

        os.environ["WEBHOOK_EXECUTE_TOKEN"] = "testtoken"

        svc.CONFIG.update({
            "execution_venue": "aster",
            "dry_run": False,
            "live_trading_enabled": True,
            "aster_trading_enabled": True,
            "aster_spot_trading_enabled": True,
            "execute_guard_enabled": True,
            "live_execute_allow_remote": False,
            "book_execution_account_id_by_venue": {"strategy": {"aster": "ut_strategy_aster"}},
        })

        def _stub_spot_market_order(symbol: str, side: str, quote_qty=None, qty=None, timeout_sec: float = 10.0):
            _ = (quote_qty, qty, timeout_sec)
            return {"orderId": 123456789, "symbol": symbol, "side": side, "status": "FILLED"}

        svc._aster_spot_market_order = _stub_spot_market_order

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        if self._orig_spot_order is not None:
            svc._aster_spot_market_order = self._orig_spot_order
        if self._orig_token is None:
            os.environ.pop("WEBHOOK_EXECUTE_TOKEN", None)
        else:
            os.environ["WEBHOOK_EXECUTE_TOKEN"] = self._orig_token

    def test_spot_market_open_execute_true_with_token_and_idempotency(self):
        client = svc.app.test_client()
        payload = {
            "coin": "BTC",
            "notional_usd": 10,
            "execute": True,
            "confirm_execute": True,
            "idempotency_key": "test|spot|buy|btc|10",
            "tag": "pytest_spot_live_smoke",
        }

        r1 = client.post(
            "/execution/aster/spot/market_open",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-Webhook-Token": "testtoken"},
        )
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json() or {}
        self.assertTrue(bool(d1.get("ok")))
        self.assertEqual(d1.get("order_id"), 123456789)

        r2 = client.post(
            "/execution/aster/spot/market_open",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-Webhook-Token": "testtoken"},
        )
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json() or {}
        self.assertEqual(d2.get("order_id"), 123456789)
        self.assertEqual(d1.get("tag"), d2.get("tag"))

    def test_spot_market_open_marks_inflight_before_internal(self):
        client = svc.app.test_client()
        payload = {
            "coin": "BTC",
            "notional_usd": 10,
            "execute": True,
            "confirm_execute": True,
            "idempotency_key": "test|spot|buy|btc|10|inflight",
            "tag": "pytest_spot_live_smoke",
        }

        old = svc.aster_spot_market_open_internal

        def _wrap(**kwargs):
            ent = (svc.TRACKER_STATE.get("execute_idempotency") or {}).get(str(payload.get("idempotency_key")) or "") or {}
            self.assertEqual(str(ent.get("state") or ""), "inflight")
            return old(**kwargs)

        svc.aster_spot_market_open_internal = _wrap
        try:
            r = client.post(
                "/execution/aster/spot/market_open",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-Webhook-Token": "testtoken"},
            )
            self.assertEqual(r.status_code, 200)
            d = r.get_json() or {}
            self.assertTrue(bool(d.get("ok")))
        finally:
            svc.aster_spot_market_open_internal = old
