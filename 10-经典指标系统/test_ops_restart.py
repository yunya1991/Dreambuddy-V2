import ml_trade_service as svc


def test_ops_restart_dry_run_is_local_only(monkeypatch):
    client = svc.app.test_client()
    r = client.post("/ops/restart", json={"dry_run": True})
    assert r.status_code == 200
    body = r.get_json(force=True)
    assert body["ok"] is True
    assert body["dry_run"] is True

    r2 = client.post("/ops/restart", json={"dry_run": True}, environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert r2.status_code == 403
