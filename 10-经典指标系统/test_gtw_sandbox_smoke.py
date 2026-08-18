import unittest

import ml_trade_service as svc


class TestGTWSandboxSmoke(unittest.TestCase):
    def test_gtw_sandbox_smoke_endpoint_returns_table_and_trace_ids(self) -> None:
        orig_supply = getattr(svc, "automation_supply_chain_run", None)
        orig_shadow = getattr(svc, "automation_shadow_loop_run", None)
        orig_paramopt = getattr(svc, "automation_paramopt_trigger", None)

        def _stub_supply_chain_run():
            data = svc.request.get_json(force=True) or {}
            tid = str(data.get("trace_id") or "").strip() or "t_supply_stub"
            ts = int(svc._now_ms())
            svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="repo_scan", artifact={"ts": int(ts), "kind": "supply_chain.trigger", "result": {"queued": True}})
            svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="baseline_report", artifact={"ts": int(ts), "ok": True, "timerange": "20200101-20200102"})
            return svc.jsonify({"ok": True, "queued": True, "trace_id": str(tid), "ts": int(ts)}), 202

        def _stub_shadow_loop_run():
            data = svc.request.get_json(force=True) or {}
            tid = str(data.get("trace_id") or "").strip() or "t_shadow_stub"
            ts = int(svc._now_ms())
            svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="pipeline_run", artifact={"ts": int(ts), "ok": True})
            return svc.jsonify({"ok": True, "trace_id": str(tid), "ts": int(ts), "http": 200, "result": {"ok": True}}), 200

        def _stub_paramopt_trigger():
            data = svc.request.get_json(force=True) or {}
            tid = str(data.get("trace_id") or "").strip() or "t_paramopt_stub"
            ts = int(svc._now_ms())
            svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="paramopt_trigger", artifact={"ts": int(ts), "trigger": "stub"})
            return svc.jsonify({"ok": True, "trace_id": str(tid), "ts": int(ts)}), 200

        svc.automation_supply_chain_run = _stub_supply_chain_run
        svc.automation_shadow_loop_run = _stub_shadow_loop_run
        svc.automation_paramopt_trigger = _stub_paramopt_trigger
        try:
            with svc.app.test_client() as c:
                r = c.post(
                    "/automation/gtw/sandbox/smoke",
                    json={"wait_sec": 2, "poll_interval_ms": 200, "lookback_days": 60, "force_path_ids": ["strategy_supply_chain", "strategy_shadow_loop", "paramopt_automation"]},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                self.assertEqual(int(r.status_code), 200)
                d = r.get_json(force=True) or {}
                self.assertTrue(bool(d.get("ok")))
                self.assertTrue(bool(str(d.get("decision_id") or "").strip()))
                rows = d.get("rows") if isinstance(d.get("rows"), list) else []
                self.assertGreaterEqual(int(len(rows)), 4)
                md = str(d.get("table_md") or "")
                self.assertIn("| step | trace_id |", md)
        finally:
            if orig_supply is not None:
                svc.automation_supply_chain_run = orig_supply
            if orig_shadow is not None:
                svc.automation_shadow_loop_run = orig_shadow
            if orig_paramopt is not None:
                svc.automation_paramopt_trigger = orig_paramopt

