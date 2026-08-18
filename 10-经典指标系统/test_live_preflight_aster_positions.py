import ml_trade_service as svc


def test_live_preflight_aster_empty_positions_without_errors_not_blocked(monkeypatch):
    monkeypatch.setitem(svc.CONFIG, "execution_venue", "aster")
    monkeypatch.setitem(svc.CONFIG, "live_trading_enabled", True)
    monkeypatch.setitem(svc.CONFIG, "dry_run", False)
    monkeypatch.setitem(svc.CONFIG, "aster_trading_enabled", True)
    monkeypatch.setitem(svc.CONFIG, "tracker_autosync_aster_enabled", True)
    monkeypatch.setitem(svc.CONFIG, "live_preflight_timeout_sec", 3.0)

    monkeypatch.setattr(svc, "_aster_enabled_for_trading_for_owner", lambda owner=None: True)
    monkeypatch.setattr(svc, "_aster_auth_mode", lambda owner=None: "v1")
    monkeypatch.setattr(svc, "_aster_api_key", lambda owner=None: "k")
    monkeypatch.setattr(svc, "_aster_secret_key", lambda owner=None: "s")
    monkeypatch.setattr(svc, "_aster_user", lambda owner=None: "")
    monkeypatch.setattr(svc, "_aster_signer", lambda owner=None: "")
    monkeypatch.setattr(svc, "_aster_signer_private_key", lambda owner=None: "")
    monkeypatch.setattr(svc, "_aster_ping_payload", lambda owner=None: {"ok": True})
    monkeypatch.setattr(svc, "_aster_fetch_positions", lambda owner=None: ([], None))

    with svc.app.test_request_context("/live/preflight"):
        resp = svc.live_preflight()
        payload = resp.get_json()

    blockers = payload.get("blockers") or []
    assert "aster_positions_unavailable" not in blockers
    assert (payload.get("aster") or {}).get("positions_error") is None
