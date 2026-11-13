import json

from okx_venue import LIVE_CONFIRM_PHRASE, LiveGate, VenueApp, VenueConfig
from okx_venue.credentials import UserCredentialStore


class FakeAdapter:
    def __init__(self, config):
        self.config = config
        self.orders = []

    def get_balance(self, ccy=None):
        return {"ok": True, "balance": 10.0, "ccy": ccy or "USDT", "mode": self.config.mode}

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": [], "count": 0, "mode": self.config.mode}

    def get_ticker(self, inst_id):
        return {"ok": True, "inst_id": inst_id, "last": 100.0}

    def place_order(self, inst_id, side, size, **kwargs):
        self.orders.append({"inst_id": inst_id, "side": side, "size": size, **kwargs})
        return {"ok": True, "order_id": "42", "cl_ord_id": "c-1", "s_code": "0", "s_msg": ""}


def _config(mode: str, audit_path) -> VenueConfig:
    live = mode == "live"
    return VenueConfig(
        profile="dreambuddy-user",
        mode=mode,
        allow_live_read=live,
        allow_live_write=live,
        audit_path=audit_path,
    )


def _make_app(tmp_path, *, token="t0", clock=None, intent_ttl_s=300, probe=None):
    adapters = {}

    def adapter_factory(config):
        adapters.setdefault(config.mode, FakeAdapter(config))
        return adapters[config.mode]

    app = VenueApp(
        config_factory=lambda mode: _config(mode, tmp_path / "audit.jsonl"),
        adapter_factory=adapter_factory,
        live_gate=LiveGate(clock=clock) if clock else LiveGate(),
        token=token,
        audit_path=tmp_path / "audit.jsonl",
        credential_store=UserCredentialStore(tmp_path / "user_venue"),
        probe_permission=probe,
        max_order_size=100,
        intent_ttl_s=intent_ttl_s,
        clock=clock or __import__("time").time,
    )
    return app, adapters


def _auth(token="t0"):
    return {"X-Venue-Token": token}


def test_token_is_required(tmp_path):
    app, _ = _make_app(tmp_path)
    status, payload = app.handle("GET", "/health", headers={})
    assert status == 401
    assert payload["error"]["code"] == "unauthorized"

    status, payload = app.handle("GET", "/health", headers=_auth("wrong"))
    assert status == 401

    status, payload = app.handle("GET", "/health", headers=_auth())
    assert status == 200
    assert payload["data"]["live"]["unlocked"] is False
    assert payload["data"]["config"]["mode"] == "demo"


def test_account_reads_use_demo_by_default(tmp_path):
    app, _ = _make_app(tmp_path)
    status, payload = app.handle("GET", "/account/balance", headers=_auth())
    assert status == 200
    assert payload["data"]["mode"] == "demo"


def test_intent_validation(tmp_path):
    app, _ = _make_app(tmp_path)

    status, payload = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "buy", "size": 101},
        headers=_auth(),
    )
    assert status == 400
    assert payload["error"]["code"] == "invalid_argument"

    status, _ = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "buy", "size": 1, "order_type": "limit"},
        headers=_auth(),
    )
    assert status == 400

    status, _ = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-EUR", "side": "buy", "size": 1},
        headers=_auth(),
    )
    assert status == 400

    status, _ = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "hold", "size": 1},
        headers=_auth(),
    )
    assert status == 400


def test_intent_confirm_executes_once(tmp_path):
    app, adapters = _make_app(tmp_path)
    body = {
        "inst_id": "btc-usdt-swap",
        "side": "buy",
        "size": 2,
        "order_type": "limit",
        "price": 100,
    }
    status, payload = app.handle("POST", "/order-intents", body=body, headers=_auth())
    assert status == 200
    intent = payload["data"]
    assert intent["inst_id"] == "BTC-USDT-SWAP"
    assert intent["mode"] == "demo"
    assert intent["status"] == "pending"

    status, payload = app.handle("POST", f"/order-intents/{intent['id']}/confirm", headers=_auth())
    assert status == 200
    assert payload["data"]["intent"]["status"] == "executed"
    assert payload["data"]["order"]["order_id"] == "42"

    call = adapters["demo"].orders[0]
    assert call["inst_id"] == "BTC-USDT-SWAP"
    assert call["price"] == 100.0

    status, payload = app.handle("POST", f"/order-intents/{intent['id']}/confirm", headers=_auth())
    assert status == 409
    assert payload["error"]["code"] == "intent_already_confirmed"


def test_intent_expires(tmp_path):
    now = [1000.0]
    app, _ = _make_app(tmp_path, clock=lambda: now[0], intent_ttl_s=60)
    status, payload = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "sell", "size": 1},
        headers=_auth(),
    )
    intent_id = payload["data"]["id"]
    now[0] += 61
    status, payload = app.handle("POST", f"/order-intents/{intent_id}/confirm", headers=_auth())
    assert status == 409
    assert payload["error"]["code"] == "intent_expired"


def test_live_unlock_controls_order_mode(tmp_path):
    now = [1000.0]
    app, adapters = _make_app(
        tmp_path, clock=lambda: now[0], probe=lambda env, demo: "read_only,trade"
    )
    app.handle("POST", "/credentials", body={**CREDS, "demo": False}, headers=_auth())

    status, payload = app.handle("POST", "/live/unlock", body={"phrase": "nope"}, headers=_auth())
    assert status == 403
    assert payload["error"]["code"] == "live_unlock_denied"

    status, payload = app.handle(
        "POST", "/live/unlock", body={"phrase": LIVE_CONFIRM_PHRASE, "ttl_s": 120}, headers=_auth()
    )
    assert status == 200
    assert payload["data"]["unlocked"] is True

    status, payload = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "buy", "size": 1},
        headers=_auth(),
    )
    assert payload["data"]["mode"] == "live"
    intent_id = payload["data"]["id"]

    status, _ = app.handle("POST", "/live/lock", headers=_auth())
    assert status == 200

    # 解锁窗口关闭后，已生成的 live intent 不允许确认
    status, payload = app.handle("POST", f"/order-intents/{intent_id}/confirm", headers=_auth())
    assert status == 403
    assert payload["error"]["code"] == "live_trading_forbidden"
    assert adapters.get("live") is None or adapters["live"].orders == []


def test_intent_confirm_is_audited(tmp_path):
    app, _ = _make_app(tmp_path)
    status, payload = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "buy", "size": 1},
        headers=_auth(),
    )
    intent_id = payload["data"]["id"]
    app.handle("POST", f"/order-intents/{intent_id}/confirm", headers=_auth())

    status, payload = app.handle("GET", "/audit", query={"limit": "5"}, headers=_auth())
    assert status == 200
    records = payload["data"]["records"]
    assert records[0]["operation"] == "order_intent_confirm"
    assert records[0]["trace_id"] == intent_id
    assert records[0]["ok"] is True
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert json.loads(raw.strip().splitlines()[-1])["operation"] == "order_intent_confirm"


def test_unknown_route(tmp_path):
    app, _ = _make_app(tmp_path)
    status, payload = app.handle("GET", "/nope", headers=_auth())
    assert status == 400
    assert payload["error"]["code"] == "invalid_argument"


CREDS = {
    "api_key": "ak-1234567890abcdef",
    "secret_key": "sk-1234567890abcdef",
    "passphrase": "passphrase-1",
}


def test_save_credentials_masks_secrets(tmp_path):
    app, adapters = _make_app(tmp_path, probe=lambda env, demo: "read_only,trade")

    status, payload = app.handle("POST", "/credentials", body=CREDS, headers=_auth())
    assert status == 200
    public = payload["data"]
    assert public["configured"] is True
    assert public["demo"] is True
    assert public["permissions"] == "read_only,trade"
    assert public["api_key_hint"] == "ak-1****cdef"
    serialized = json.dumps(payload)
    assert CREDS["secret_key"] not in serialized
    assert CREDS["passphrase"] not in serialized
    assert CREDS["api_key"] not in serialized

    status, payload = app.handle("GET", "/credentials", headers=_auth())
    assert payload["data"]["configured"] is True

    status, payload = app.handle("GET", "/health", headers=_auth())
    assert payload["data"]["credentials"]["configured"] is True
    assert payload["data"]["effective_mode"] == "demo"
    assert adapters == {}  # 保存凭证不触发交易调用


def test_withdraw_permission_is_rejected(tmp_path):
    app, _ = _make_app(tmp_path, probe=lambda env, demo: "read_only,trade,withdraw")
    status, payload = app.handle("POST", "/credentials", body=CREDS, headers=_auth())
    assert status == 400
    assert payload["error"]["code"] == "venue_credentials_invalid"
    status, payload = app.handle("GET", "/credentials", headers=_auth())
    assert payload["data"]["configured"] is False


def test_live_credentials_require_unlock_to_confirm(tmp_path):
    app, adapters = _make_app(tmp_path, probe=lambda env, demo: "read_only,trade")
    status, _ = app.handle("POST", "/credentials", body={**CREDS, "demo": False}, headers=_auth())
    assert status == 200

    status, payload = app.handle("GET", "/health", headers=_auth())
    assert payload["data"]["effective_mode"] == "live"
    assert payload["data"]["config"]["credential_source"] == "env"

    status, payload = app.handle(
        "POST",
        "/order-intents",
        body={"inst_id": "BTC-USDT", "side": "buy", "size": 1},
        headers=_auth(),
    )
    assert payload["data"]["mode"] == "live"
    intent_id = payload["data"]["id"]

    status, payload = app.handle("POST", f"/order-intents/{intent_id}/confirm", headers=_auth())
    assert status == 403
    assert payload["error"]["code"] == "live_trading_forbidden"

    app.handle("POST", "/live/unlock", body={"phrase": LIVE_CONFIRM_PHRASE}, headers=_auth())
    status, payload = app.handle("POST", f"/order-intents/{intent_id}/confirm", headers=_auth())
    assert status == 200
    assert payload["data"]["intent"]["status"] == "executed"
    assert adapters["live"].orders[0]["inst_id"] == "BTC-USDT"


def test_delete_credentials(tmp_path):
    app, _ = _make_app(tmp_path, probe=lambda env, demo: "read_only,trade")
    app.handle("POST", "/credentials", body=CREDS, headers=_auth())
    status, payload = app.handle("DELETE", "/credentials", headers=_auth())
    assert status == 200
    assert payload["data"]["configured"] is False
