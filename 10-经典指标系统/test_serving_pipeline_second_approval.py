import ml_trade_service as svc


def test_serving_pipeline_requires_second_approval_for_full(monkeypatch):
    svc.AUTOMATION["serving_pipeline"] = {
        "enabled": True,
        "phase": "shadow",
        "eval_window": 1,
        "min_eval_samples": 1,
        "min_win_rate": 0.0,
        "min_pr_auc": 0.0,
        "max_ece": 1.0,
        "max_tail_loss_p95": 999.0,
        "promote_required_consecutive_pass": 1,
        "canary_frac": 0.05,
        "canary_frac_start": 0.05,
        "pairs": [],
        "require_second_approval": True,
    }
    svc.EVAL_SAMPLES[:] = [{"features": {}, "label": 1, "targets": {"return_tk": 1.0}}]
    svc.ACTIVE_MODEL["obj"] = None

    monkeypatch.setattr(
        svc,
        "_serving_pipeline_guard_status",
        lambda *, sp, now_ms: {"pass": True, "rollback_recommended": False, "checks": {}, "thresholds": {}, "metrics": {}, "ts": int(now_ms)},
    )
    monkeypatch.setattr(svc, "_apply_serving_phase", lambda phase, canary_frac=None, pairs=None: None)
    monkeypatch.setattr(svc, "_save_config", lambda: None)

    r1 = svc._serving_pipeline_advance_impl(trace_id="t_unit_shadow_to_canary", approval_id="appr_1")
    assert bool(r1.get("ok"))
    assert str(r1.get("to")) == "canary"

    sp = svc.AUTOMATION.get("serving_pipeline") if isinstance(svc.AUTOMATION.get("serving_pipeline"), dict) else {}
    sp["phase"] = "canary"
    sp["guard_pass_consecutive"] = 0
    sp["canary_frac_current"] = 0.05
    svc.AUTOMATION["serving_pipeline"] = sp

    r2 = svc._serving_pipeline_advance_impl(trace_id="t_unit_canary_to_full_block", approval_id="appr_1")
    assert (not bool(r2.get("ok"))) and str(r2.get("error")) == "second_approval_required"
    assert int(r2.get("_http") or 0) == 412

    r3 = svc._serving_pipeline_advance_impl(trace_id="t_unit_canary_to_full_ok", approval_id="appr_2")
    assert bool(r3.get("ok"))
    assert str(r3.get("to")) == "full"
