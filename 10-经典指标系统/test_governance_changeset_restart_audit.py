import ml_trade_service as svc


def test_governance_changeset_apply_emits_restart_after_apply_audit(monkeypatch):
    svc.AUTOMATION["sys_monitor_restart_after_apply_enabled"] = True
    svc.AUTOMATION["sys_monitor_restart_after_apply_require_flag"] = False
    svc.AUTOMATION["sys_monitor_restart_after_apply_cooldown_sec"] = 60
    svc.AUTOMATION["sys_monitor_restart_after_apply_delay_sec"] = 0.0

    monkeypatch.setenv("XPC_SERVICE_NAME", "com.ft.ml_trade_service.8092")

    monkeypatch.setattr(svc, "_governance_write_auth_ok", lambda: True)
    monkeypatch.setattr(svc, "_governance_policy_resolve", lambda ref: {"ref": ref})
    monkeypatch.setattr(
        svc,
        "_governance_policy_eval",
        lambda policy, changeset: {"ok": True, "decision": "pass", "allowed_actions": ["config.apply"], "policy_ref": str((policy or {}).get("ref") or "")},
    )
    monkeypatch.setattr(svc, "_agent_config_patch_validate", lambda patch, **_: {"ok": True, "patch": (patch if isinstance(patch, dict) else {})})
    monkeypatch.setattr(svc, "_config_set_impl", lambda patch, confirm_live, action: ({"ok": True}, 200))

    monkeypatch.setattr(
        svc,
        "_self_restart_schedule",
        lambda *, now_ms, reason, delay_sec, exit_code: {"ok": True, "scheduled": True, "ts": int(now_ms), "reason": str(reason), "delay_sec": float(delay_sec), "exit_code": int(exit_code)},
    )

    outbox = []

    def fake_outbox(name: str, item: dict) -> None:
        outbox.append({"name": str(name), "item": dict(item)})

    monkeypatch.setattr(svc, "_agent_outbox_append_jsonl", fake_outbox)

    client = svc.app.test_client()
    r = client.post(
        "/governance/changeset/apply",
        json={
            "confirm_live": True,
            "policy_ref": "gov_default",
            "changeset": {
                "config_patch": {"some_key": "some_val"},
                "label": "system_monitor_fix:demo",
                "reason": "system_monitor:demo",
                "policy_ref": "gov_default",
            },
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200

    audit_hits = [x for x in outbox if x["name"] == "audit_actions.jsonl" and x["item"].get("name") == "sys_monitor.restart_after_apply"]
    assert len(audit_hits) == 1
    payload = audit_hits[0]["item"].get("payload") or {}
    assert payload.get("trace_id")
    assert "restart_after_apply" in payload
