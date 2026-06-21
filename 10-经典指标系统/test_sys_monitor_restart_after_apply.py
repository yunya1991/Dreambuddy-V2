import ml_trade_service as svc


def test_sys_monitor_restart_after_apply_requires_launchd(monkeypatch):
    svc.AUTOMATION["sys_monitor_restart_after_apply_enabled"] = True
    svc.AUTOMATION["sys_monitor_restart_after_apply_require_flag"] = False
    svc.AUTOMATION["sys_monitor_restart_after_apply_cooldown_sec"] = 60
    svc.AUTOMATION["sys_monitor_restart_after_apply_delay_sec"] = 0.0

    called = {"n": 0}

    def fake_schedule(*, now_ms: int, reason: str, delay_sec: float, exit_code: int):
        called["n"] += 1
        return {"ok": True, "scheduled": True, "ts": int(now_ms), "reason": reason, "delay_sec": float(delay_sec), "exit_code": int(exit_code)}

    monkeypatch.setattr(svc, "_self_restart_schedule", fake_schedule)
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    monkeypatch.delenv("LAUNCH_JOBKEY_LABEL", raising=False)

    with svc.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        rep = svc._sys_monitor_restart_after_apply_maybe(
            now_ms=1_700_000_000_000,
            changeset={"config_patch": {"x": 1}},
            label="system_monitor:auto_fix",
            reason="system_monitor",
            trace_id="t",
            approval_id=None,
        )
    assert isinstance(rep, dict)
    assert rep["skipped"] is True
    assert rep["skip_reason"] == "not_under_launchd"
    assert called["n"] == 0


def test_sys_monitor_restart_after_apply_cooldown(monkeypatch):
    svc.AUTOMATION["sys_monitor_restart_after_apply_enabled"] = True
    svc.AUTOMATION["sys_monitor_restart_after_apply_require_flag"] = False
    svc.AUTOMATION["sys_monitor_restart_after_apply_cooldown_sec"] = 1800
    svc.AUTOMATION["sys_monitor_restart_after_apply_delay_sec"] = 0.0

    called = {"n": 0}

    def fake_schedule(*, now_ms: int, reason: str, delay_sec: float, exit_code: int):
        called["n"] += 1
        return {"ok": True, "scheduled": True, "ts": int(now_ms), "reason": reason, "delay_sec": float(delay_sec), "exit_code": int(exit_code)}

    monkeypatch.setattr(svc, "_self_restart_schedule", fake_schedule)
    monkeypatch.setenv("XPC_SERVICE_NAME", "com.ft.ml_trade_service.8092")

    svc.TRACKER_STATE["sys_monitor_auto"] = {"restart_after_apply": {"last_ms": 1_700_000_000_000}}

    with svc.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        rep = svc._sys_monitor_restart_after_apply_maybe(
            now_ms=1_700_000_100_000,
            changeset={"config_patch": {"x": 1}},
            label="system_monitor:auto_fix",
            reason="system_monitor",
            trace_id="t2",
            approval_id=None,
        )
    assert isinstance(rep, dict)
    assert rep["skipped"] is True
    assert rep["skip_reason"] == "cooldown"
    assert called["n"] == 0
