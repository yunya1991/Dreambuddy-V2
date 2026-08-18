import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import ml_trade_service as svc


class TestAgentE2EAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_config = dict(svc.CONFIG)
        self._orig_orders = dict(svc.ORDERS)
        self._orig_events = dict(svc.EVENTS)
        self._orig_eval_samples = list(svc.EVAL_SAMPLES)
        self._orig_eval_models = dict(svc.EVAL_MODELS)
        self._orig_tracker_state = dict(svc.TRACKER_STATE)

        self._orig_load_recent = getattr(svc, "_load_recent_jsonl_records", None)
        svc._load_recent_jsonl_records = lambda *_args, **_kwargs: []
        self._orig_save_config = getattr(svc, "_save_config", None)
        svc._save_config = lambda *_args, **_kwargs: None

        try:
            self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        except TypeError:
            self._td = tempfile.TemporaryDirectory()
        self._orig_outbox_env = os.environ.get("AGENT_OUTBOX_DIR")
        os.environ["AGENT_OUTBOX_DIR"] = self._td.name
        self._orig_user_data_env = os.environ.get("ML_USER_DATA_DIR")
        os.environ["ML_USER_DATA_DIR"] = self._td.name

        svc.CONFIG.update({
            "outbox_allow_test_mode": True,
            "trade_monitor_enabled": True,
            "trade_monitor_daily_full_enabled": False,
            "trade_monitor_alert_upgrade_enabled": False,
            "trade_monitor_light_trades": 1,
            "trade_monitor_full_trades": 999999,
            "trade_monitor_full_min_age_hours": 9999,
        })

        svc.ORDERS.clear()
        svc.EVENTS.clear()
        svc.EVAL_SAMPLES.clear()
        svc.EVAL_MODELS.clear()
        svc.TRACKER_STATE.clear()

    def tearDown(self) -> None:
        if self._orig_load_recent is not None:
            svc._load_recent_jsonl_records = self._orig_load_recent
        if self._orig_save_config is not None:
            svc._save_config = self._orig_save_config

        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        svc.ORDERS.clear()
        svc.ORDERS.update(self._orig_orders)
        svc.EVENTS.clear()
        svc.EVENTS.update(self._orig_events)
        svc.EVAL_SAMPLES.clear()
        svc.EVAL_SAMPLES.extend(self._orig_eval_samples)
        svc.EVAL_MODELS.clear()
        svc.EVAL_MODELS.update(self._orig_eval_models)
        svc.TRACKER_STATE.clear()
        svc.TRACKER_STATE.update(self._orig_tracker_state)

        if self._orig_outbox_env is None:
            os.environ.pop("AGENT_OUTBOX_DIR", None)
        else:
            os.environ["AGENT_OUTBOX_DIR"] = self._orig_outbox_env
        if self._orig_user_data_env is None:
            os.environ.pop("ML_USER_DATA_DIR", None)
        else:
            os.environ["ML_USER_DATA_DIR"] = self._orig_user_data_env
        self._td.cleanup()

    def _seed_eval_samples(self, *, n: int, ts0: int = 1_700_000_000_000) -> None:
        for i in range(int(n)):
            ts = int(ts0) + int(i) * 60_000
            svc.EVAL_SAMPLES.append({
                "ts": ts,
                "pair": "BTC/USDT",
                "side": "long",
                "label": 1 if (i % 2 == 0) else 0,
                "targets": {"return_tk": 0.01 if (i % 2 == 0) else -0.008},
                "features": {
                    "macro_atr_pct": 0.01 + 0.00001 * float(i),
                    "macro_trend_shape_5": "up" if (i % 3) else "down",
                    "macro_btc_time_regime": "trend" if (i % 4) else "chop",
                    "close": 100.0 + float(i),
                    "volume": 1000.0,
                    "rsi_d": 50.0,
                    "willr_d": -50.0,
                    "macd_d": 0.0,
                    "macdsignal_d": 0.0,
                    "ma_cross_fast_d": 0.0,
                    "ma_cross_slow_d": 0.0,
                },
            })

    def test_automation_shadow_switch_card_contract_and_toggles(self) -> None:
        svc.AUTOMATION["enable_shadow_automation_loop"] = False
        svc.AUTOMATION["shadow_automation_autostart"] = False

        with svc.app.test_client() as c:
            r0 = c.get("/automation/cards/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r0.status_code), 200)
            d0 = r0.get_json(force=True) or {}
            self.assertTrue(bool(d0.get("ok")))
            cards0 = d0.get("cards") if isinstance(d0.get("cards"), list) else []
            shadow0 = next((x for x in cards0 if isinstance(x, dict) and str(x.get("card_id")) == "shadow_switch"), None)
            self.assertTrue(isinstance(shadow0, dict))
            acts0 = shadow0.get("actions") if isinstance(shadow0.get("actions"), list) else []
            act_ids0 = {str(a.get("id")) for a in acts0 if isinstance(a, dict)}
            self.assertTrue("toggle_shadow" in act_ids0)
            self.assertTrue("toggle_autostart" in act_ids0)

            r1 = c.post("/automation/config", json={"trace_id": "t_shadow_1", "enable_shadow_automation_loop": True, "confirm_live": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r1.status_code), 200)
            d1 = r1.get_json(force=True) or {}
            self.assertTrue(bool(d1.get("ok")))
            self.assertTrue(bool(svc.AUTOMATION.get("enable_shadow_automation_loop")))

            r2 = c.post("/automation/config", json={"trace_id": "t_shadow_2", "shadow_automation_autostart": True, "confirm_live": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r2.status_code), 200)
            d2 = r2.get_json(force=True) or {}
            self.assertTrue(bool(d2.get("ok")))
            self.assertTrue(bool(svc.AUTOMATION.get("shadow_automation_autostart")))

            r3 = c.get("/automation/cards/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r3.status_code), 200)
            d3 = r3.get_json(force=True) or {}
            self.assertTrue(bool(d3.get("ok")))
            cards3 = d3.get("cards") if isinstance(d3.get("cards"), list) else []
            shadow3 = next((x for x in cards3 if isinstance(x, dict) and str(x.get("card_id")) == "shadow_switch"), None)
            self.assertTrue(isinstance(shadow3, dict))
            acts3 = shadow3.get("actions") if isinstance(shadow3.get("actions"), list) else []
            toggle_autostart = next((a for a in acts3 if isinstance(a, dict) and str(a.get("id")) == "toggle_autostart"), None)
            self.assertTrue(isinstance(toggle_autostart, dict))
            self.assertIn("关闭自动启动", str((toggle_autostart or {}).get("label") or ""))

    def test_automation_paramopt_card_contract_and_manual_trigger(self) -> None:
        svc.AUTOMATION["enable_shadow_automation_loop"] = False
        svc.AUTOMATION["enable_paramopt_daily"] = False

        with svc.app.test_client() as c:
            r0 = c.get("/automation/cards/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r0.status_code), 200)
            d0 = r0.get_json(force=True) or {}
            self.assertTrue(bool(d0.get("ok")))
            cards0 = d0.get("cards") if isinstance(d0.get("cards"), list) else []
            p0 = next((x for x in cards0 if isinstance(x, dict) and str(x.get("card_id")) == "paramopt_automation"), None)
            self.assertTrue(isinstance(p0, dict))
            self.assertEqual(str(p0.get("status")), "BLOCKED")
            stuck0 = p0.get("stuck") if isinstance(p0.get("stuck"), dict) else {}
            self.assertEqual(str(stuck0.get("reason_code") or ""), "shadow_disabled")

            r1 = c.post("/automation/config", json={"trace_id": "t_paramopt_bad", "enable_shadow_automation_loop": False, "enable_paramopt_daily": True, "confirm_live": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r1.status_code), 400)
            d1 = r1.get_json(force=True) or {}
            self.assertEqual(str(d1.get("error") or ""), "shadow_required_for_paramopt")

            r2 = c.post(
                "/automation/config",
                json={
                    "trace_id": "t_paramopt_enable",
                    "enable_shadow_automation_loop": True,
                    "enable_paramopt_daily": True,
                    "confirm_live": True,
                },
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(int(r2.status_code), 200)
            d2 = r2.get_json(force=True) or {}
            self.assertTrue(bool(d2.get("ok")))
            self.assertTrue(bool(svc.AUTOMATION.get("enable_shadow_automation_loop")))
            self.assertTrue(bool(svc.AUTOMATION.get("enable_paramopt_daily")))

            orig = getattr(svc, "agent_paramopt_run", None)

            def _stub_paramopt_run():
                data = svc.request.get_json(force=True) or {}
                tid = str(data.get("trace_id") or "").strip() or "t_paramopt_stub"
                ts = int(svc._now_ms())
                svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="paramopt_run", artifact={"ts": int(ts), "mode": "sandbox", "status": "DONE", "requested": (data.get("requested") if isinstance(data.get("requested"), dict) else {})})
                svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="paramopt_suggestion", artifact={"ts": int(ts), "ok": True, "mode": "sandbox", "eval_mode": "rolling", "family": "xgb", "keys": [], "gate": {"pass": True, "fails": []}})
                svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="rolling_verify", artifact={"ts": int(ts), "ok": True, "eval_mode": "rolling"})
                svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="approval_request", artifact={"ts": int(ts), "approval_id": "appr_paramopt_1", "action": "automation.paramopt.trigger"})
                svc._agent_pipeline_artifact_validate_and_emit(trace_id=str(tid), kind="config.set.result", artifact={"ts": int(ts), "ok": True, "result": {"mode": "test"}})
                return svc.jsonify({"ok": True, "trace_id": str(tid), "ts": int(ts), "mode": "sandbox"})

            svc.agent_paramopt_run = _stub_paramopt_run
            try:
                trace_id = "t_paramopt_manual_1"
                r3 = c.post("/automation/paramopt/trigger", json={"trace_id": trace_id, "confirm_live": True, "mode": "sandbox"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
                self.assertIn(int(r3.status_code), (200, 202))
                d3 = r3.get_json(force=True) or {}
                self.assertTrue(bool(d3.get("ok")))

                ok_done = False
                last_p4 = None
                for _ in range(60):
                    r4 = c.get("/automation/cards/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
                    self.assertEqual(int(r4.status_code), 200)
                    d4 = r4.get_json(force=True) or {}
                    self.assertTrue(bool(d4.get("ok")))
                    cards4 = d4.get("cards") if isinstance(d4.get("cards"), list) else []
                    p4 = next((x for x in cards4 if isinstance(x, dict) and str(x.get("card_id")) == "paramopt_automation"), None)
                    self.assertTrue(isinstance(p4, dict))
                    last_p4 = p4
                    self.assertEqual(str(p4.get("trace_id") or ""), trace_id)
                    prog = p4.get("progress") if isinstance(p4.get("progress"), dict) else {}
                    if int(prog.get("pct") or 0) >= 100:
                        steps = prog.get("steps") if isinstance(prog.get("steps"), list) else []
                        keys = [str(s.get("key") or "") for s in steps if isinstance(s, dict)]
                        self.assertTrue(all(k in keys for k in ["trigger", "run", "suggestion", "verify", "approval", "apply"]))
                        self.assertFalse(bool(p4.get("stuck")))
                        ok_done = True
                        break
                    time.sleep(0.05)
                if not ok_done:
                    self.fail(f"paramopt_automation not completed: {json.dumps(last_p4, ensure_ascii=False)[:2000]}")
            finally:
                if orig is not None:
                    svc.agent_paramopt_run = orig

    def test_config_set_allows_eval_policies_update(self) -> None:
        out, code = svc._config_set_impl(
            {
                "eval_policies": {
                    "p3_default": {
                        "min_trades": 80,
                        "max_drawdown_pct": 0.25,
                        "min_weekly_winrate": 0.45,
                        "max_daily_loss_pct": -0.05,
                        "max_weekly_loss_pct": 0.12,
                        "extra": 123,
                    },
                    "": {"min_trades": 1},
                    "x" * 100: {"min_trades": 1},
                    "bad": "not_a_dict",
                }
            },
            confirm_live=False,
            action="config.set",
        )
        self.assertEqual(int(code), 200)
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(isinstance(svc.CONFIG.get("eval_policies"), dict))
        ep = svc.CONFIG.get("eval_policies") if isinstance(svc.CONFIG.get("eval_policies"), dict) else {}
        self.assertTrue("p3_default" in ep)
        p3 = ep.get("p3_default") if isinstance(ep.get("p3_default"), dict) else {}
        self.assertEqual(int(p3.get("min_trades") or 0), 80)
        self.assertAlmostEqual(float(p3.get("max_drawdown_pct") or 0.0), 0.25, places=9)
        self.assertAlmostEqual(float(p3.get("min_weekly_winrate") or 0.0), 0.45, places=9)
        self.assertAlmostEqual(float(p3.get("max_daily_loss_pct") or 0.0), 0.05, places=9)
        self.assertAlmostEqual(float(p3.get("max_weekly_loss_pct") or 0.0), 0.12, places=9)
        self.assertFalse("extra" in p3)

    def test_automation_paramopt_explore_trigger_and_24h_auto_reject(self) -> None:
        svc.AUTOMATION["enable_shadow_automation_loop"] = True
        svc.AUTOMATION["enable_paramopt_daily"] = True
        svc.AUTOMATION["paramopt_explore_cycle_enabled"] = True
        svc.AUTOMATION["paramopt_explore_approval_ttl_hours"] = 24

        orig = getattr(svc, "_automation_paramopt_explore_cycle_run", None)

        def _stub_explore_run(now_ms: int):
            tid = "t_explore_auto_reject_1"
            old_ts = int(now_ms) - 25 * 3600 * 1000
            svc._agent_outbox_append_jsonl(
                "chat.jsonl",
                {
                    "id": "chat_explore_1",
                    "trace_id": str(tid),
                    "ts": int(old_ts),
                    "type": "automation.paramopt.explore.trigger",
                    "channel": "chat",
                    "result": {"ok": True, "trigger_event": "strategy.explore.cycle.trigger"},
                },
            )
            svc._approval_append(
                {
                    "id": "appr_explore_1",
                    "trace_id": str(tid),
                    "approver": "agent",
                    "decision": "pending",
                    "action": "config.apply",
                    "reason": "explore_pending",
                    "doc_refs": svc._doc_refs_default(),
                    "evidence": {"scenario": "A"},
                    "ts": int(old_ts),
                }
            )
            return {"ok": True, "trigger": "strategy.explore.cycle.trigger", "trace_id": str(tid), "ts": int(now_ms)}

        svc._automation_paramopt_explore_cycle_run = _stub_explore_run
        try:
            with svc.app.test_client() as c:
                r0 = c.post("/automation/paramopt/explore/trigger", json={"confirm_live": True, "mode": "sandbox"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
                self.assertIn(int(r0.status_code), (200, 202))
                d0 = r0.get_json(force=True) or {}
                self.assertTrue(bool(d0.get("ok")))

                r1 = c.get("/approvals/summary", environ_base={"REMOTE_ADDR": "127.0.0.1"})
                self.assertEqual(int(r1.status_code), 200)
                d1 = r1.get_json(force=True) or {}
                pending1 = d1.get("pending") if isinstance(d1.get("pending"), list) else []
                p1 = next((x for x in pending1 if isinstance(x, dict) and str(x.get("id") or "") == "appr_explore_1"), None)
                self.assertTrue(isinstance(p1, dict))
                self.assertTrue(bool((p1 or {}).get("is_explore")))
                self.assertEqual(str((p1 or {}).get("auto_reject_policy") or ""), "expired_24h_auto_reject")

                rep_gc = svc._approvals_auto_reject_expired_explore(now_ms=int(svc._now_ms()), ttl_hours=24)
                self.assertTrue(bool(rep_gc.get("ok")))
                self.assertGreaterEqual(int(rep_gc.get("rejected") or 0), 1)

                r2 = c.get("/approvals/get", query_string={"id": "appr_explore_1"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
                self.assertEqual(int(r2.status_code), 200)
                d2 = r2.get_json(force=True) or {}
                self.assertTrue(bool(d2.get("ok")))
                appr2 = d2.get("approval") if isinstance(d2.get("approval"), dict) else {}
                self.assertEqual(str(appr2.get("decision") or "").lower(), "rejected")
                self.assertEqual(str(appr2.get("reason") or ""), "expired_24h_auto_reject")

                r3 = c.get("/approvals/summary", environ_base={"REMOTE_ADDR": "127.0.0.1"})
                self.assertEqual(int(r3.status_code), 200)
                d3 = r3.get_json(force=True) or {}
                pending3 = d3.get("pending") if isinstance(d3.get("pending"), list) else []
                self.assertFalse(any(isinstance(x, dict) and str(x.get("id") or "") == "appr_explore_1" for x in pending3))
                auto_rej3 = d3.get("recent_auto_rejected") if isinstance(d3.get("recent_auto_rejected"), list) else []
                self.assertTrue(any(isinstance(x, dict) and str(x.get("id") or "") == "appr_explore_1" for x in auto_rej3))
        finally:
            if orig is not None:
                svc._automation_paramopt_explore_cycle_run = orig

    def test_paramopt_recent_recovers_stale_running_timeout(self) -> None:
        now_ms = int(svc._now_ms())
        stale_ts = int(now_ms - 10 * 60 * 1000)
        trace_id = "t_paramopt_stale_running_1"
        svc.CONFIG["paramopt_run_timeout_sec"] = 60
        svc._agent_pipeline_artifact_validate_and_emit(
            trace_id=str(trace_id),
            kind="paramopt_run",
            artifact={
                "ts": int(stale_ts),
                "mode": "suggest",
                "status": "RUNNING",
                "requested": {
                    "family": "xgb",
                    "eval_mode": "rolling",
                    "opt_class": "strategy",
                    "strategy_id": "Strategy005",
                },
                "opt_class": "strategy",
                "strategy_id": "Strategy005",
            },
        )

        with svc.app.test_client() as c:
            r = c.get("/agent/observability/paramopt/recent", query_string={"days": 7, "limit": 50}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(int(r.status_code), 200)
            d = r.get_json(force=True) or {}
            self.assertTrue(bool(d.get("ok")))
            rec = d.get("timeout_recovery") if isinstance(d.get("timeout_recovery"), dict) else {}
            self.assertGreaterEqual(int(rec.get("recovered_n") or 0), 1)
            items = d.get("items") if isinstance(d.get("items"), list) else []
            hit = next((x for x in items if isinstance(x, dict) and str(x.get("trace_id") or "") == trace_id), None)
            self.assertTrue(isinstance(hit, dict))
            self.assertEqual(str((hit or {}).get("opt_class") or ""), "strategy")
            self.assertEqual(str((hit or {}).get("strategy_id") or ""), "Strategy005")

        outbox = os.path.join(self._td.name, "pipeline_artifacts.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        rows_tid = [x for x in rows if isinstance(x, dict) and str(x.get("trace_id") or "") == trace_id]
        self.assertTrue(bool(rows_tid))
        failed_run = next(
            (
                x
                for x in rows_tid
                if str(x.get("kind") or "") == "paramopt_run"
                and isinstance(x.get("artifact"), dict)
                and str((x.get("artifact") or {}).get("status") or "") == "FAILED"
                and str((x.get("artifact") or {}).get("reason_code") or "") == "paramopt_run_timeout"
            ),
            None,
        )
        self.assertTrue(isinstance(failed_run, dict))
        failed_suggestion = next(
            (
                x
                for x in rows_tid
                if str(x.get("kind") or "") == "paramopt_suggestion"
                and isinstance(x.get("artifact"), dict)
                and bool((x.get("artifact") or {}).get("ok")) is False
                and str((x.get("artifact") or {}).get("reason_code") or "") == "paramopt_run_timeout"
            ),
            None,
        )
        self.assertTrue(isinstance(failed_suggestion, dict))

    def test_trade_monitor_scan_persists_report(self) -> None:
        now_ms = 1_700_000_100_000
        svc.EVENTS["e1"] = {
            "id": "e1",
            "ts": now_ms - 120_000,
            "ts_emit_ms": now_ms - 120_000,
            "decision_info": {"decision": "reject", "reason": "unit_test"},
        }
        svc.ORDERS["o1"] = {
            "id": "o1",
            "event_id": "e1",
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "system_id": "strategy",
            "ts": now_ms - 60_000,
            "side": "close",
            "action": "close",
            "status": "filled",
            "exec": {"pnl_net_u": 1.23, "fees_u": 0.01, "funding_u": 0.0},
        }

        rep = svc._trade_monitor_scan(now_ms=int(now_ms), force_full=False)
        self.assertTrue(bool(rep.get("ok")))
        self.assertTrue(bool(rep.get("did_light")))
        self.assertEqual(int(rep.get("new_close_trades") or 0), 1)
        self.assertEqual(len(rep.get("reports") or []), 1)

        outbox = os.path.join(self._td.name, "trade_monitor_reports.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(bool(rows))
        self.assertEqual(str(rows[-1].get("kind")), "light")
        sugs = rows[-1].get("suggestions") if isinstance(rows[-1], dict) else None
        self.assertTrue(isinstance(sugs, list))
        if sugs:
            s0 = sugs[0] if isinstance(sugs[0], dict) else {}
            self.assertTrue(str(s0.get("scope") or "").strip())
            self.assertTrue(str(s0.get("direction") or "").strip())
            self.assertTrue(str(s0.get("objective_profile") or "").strip())
            acts = s0.get("actions")
            self.assertTrue(isinstance(acts, list))
            self.assertTrue(bool(acts))

    def test_trade_monitor_full_report_routes_rule_suggestions(self) -> None:
        svc.CONFIG.update({
            "trade_monitor_light_trades": 1,
            "trade_monitor_full_trades": 1,
            "trade_monitor_full_min_age_hours": 0.0001,
            "trade_monitor_alert_upgrade_enabled": False,
            "trade_monitor_daily_full_enabled": False,
            "trade_monitor_baseline_rolling_enabled": True,
            "trade_monitor_throttle_skip_full_if_stable_24h": False,
            "trade_monitor_budget_max_reports_per_day": 999,
        })

        now1 = 1_700_000_400_000
        svc.EVENTS["e1"] = {"id": "e1", "ts": now1 - 2000, "ts_emit_ms": now1 - 2000, "decision_info": {"decision": "enter"}}
        svc.ORDERS["o1"] = {
            "id": "o1",
            "event_id": "e1",
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "system_id": "strategy",
            "ts": now1 - 1000,
            "side": "close",
            "action": "close",
            "status": "filled",
            "exec": {"pnl_net_u": 1.0, "fees_u": 0.01, "funding_u": 0.0},
        }

        svc.TRACKER_STATE["ab_settlements"] = []
        for i in range(50):
            pnl = 1.0 if i < 40 else -0.5
            svc.TRACKER_STATE["ab_settlements"].append(
                {"ts": now1 - (50 - i) * 60_000, "order_id": f"b{i}", "event_id": f"be{i}", "pnl_usdc": pnl, "notional_usdc": 100.0}
            )

        r1 = svc._trade_monitor_scan(now_ms=int(now1), force_full=False)
        self.assertTrue(bool(r1.get("ok")))
        self.assertTrue(bool(r1.get("did_full")))

        now2 = 1_700_000_460_000
        svc.EVENTS["e2"] = {"id": "e2", "ts": now2 - 2000, "ts_emit_ms": now2 - 2000, "decision_info": {"decision": "enter"}}
        svc.ORDERS["o2"] = {
            "id": "o2",
            "event_id": "e2",
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "system_id": "strategy",
            "ts": now2 - 1000,
            "side": "close",
            "action": "close",
            "status": "filled",
            "exec": {"pnl_net_u": -1.0, "fees_u": 0.01, "funding_u": 0.0},
        }

        svc.TRACKER_STATE["ab_settlements"] = []
        for i in range(50):
            pnl = 0.5 if i < 20 else -0.8
            svc.TRACKER_STATE["ab_settlements"].append(
                {"ts": now2 - (50 - i) * 60_000, "order_id": f"c{i}", "event_id": f"ce{i}", "pnl_usdc": pnl, "notional_usdc": 100.0}
            )

        r2 = svc._trade_monitor_scan(now_ms=int(now2), force_full=False)
        self.assertTrue(bool(r2.get("ok")))
        self.assertTrue(bool(r2.get("did_full")))

        outbox = os.path.join(self._td.name, "trade_monitor_reports.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        fulls = [x for x in rows if isinstance(x, dict) and str(x.get("kind")) == "full"]
        self.assertTrue(bool(fulls))
        rep = fulls[-1]

        rules = rep.get("trigger_rules") if isinstance(rep.get("trigger_rules"), list) else []
        self.assertTrue(any(isinstance(r, dict) and str(r.get("rule_id")) == "TM-541-PERF_DEGRADE" and bool(r.get("matched")) for r in rules))

        sugs = rep.get("suggestions") if isinstance(rep.get("suggestions"), list) else []
        s_perf = None
        for s in sugs:
            if isinstance(s, dict) and str(s.get("phenomenon_id")) == "A1_PERF_DEGRADE":
                s_perf = s
                break
        self.assertTrue(isinstance(s_perf, dict))
        self.assertTrue(str((s_perf or {}).get("scope") or "").strip())
        self.assertTrue(str((s_perf or {}).get("direction") or "").strip())
        self.assertTrue(str((s_perf or {}).get("objective_profile") or "").strip())
        acts = (s_perf or {}).get("actions")
        self.assertTrue(isinstance(acts, list))
        self.assertTrue(bool(acts))
        self.assertTrue(any(isinstance(a, dict) and str(a.get("type")) == "agent.paramopt" for a in acts))

    def test_agent_chat_sync_trade_monitor_uses_archived_orders(self) -> None:
        svc.ORDERS.clear()
        svc.EVENTS.clear()

        ds = Path(self._td.name) / "datasets"
        ds.mkdir(parents=True, exist_ok=True)
        p = ds / "unit_orders_orders.jsonl"
        now_ms = int(svc._now_ms())
        o1 = {
            "id": "arch_o1",
            "event_id": "arch_e1",
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "system_id": "strategy",
            "ab_owner": "strategy",
            "book_id": "strategy",
            "ts": now_ms - 60_000,
            "side": "close",
            "action": "close",
            "status": "filled",
            "exec": {"pnl_net_u": -1.0, "fees_u": 0.01, "funding_u": 0.0},
        }
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(o1, ensure_ascii=False) + "\n")

        with svc.app.test_client() as c:
            resp = c.post(
                "/agent/chat",
                json={
                    "sync": True,
                    "llm_enabled": False,
                    "intent": {"kind": "trade_monitor.analyze", "args": {"lookback_days": 5.0, "force_full": True}},
                },
            )
            self.assertEqual(int(resp.status_code), 200)
            obj = resp.get_json(force=True)
        self.assertTrue(bool(obj.get("ok")))
        t = str(obj.get("assistant_text") or "")
        self.assertIn("Trade Monitor", t)
        self.assertIn("trades=1", t)

    def test_agent_chat_llm_fast_path_general_assist_emits_result(self) -> None:
        orig = getattr(svc, "_agent_llm_chat", None)
        try:
            svc._agent_llm_chat = lambda *_a, **_k: {"ok": True, "data": {"message": {"role": "assistant", "content": "{\"assistant_text\":\"pong\"}"}}}
            svc._agent_chat_driver_process(
                {"trace_id": "t_fast_1", "risk_level": "P2", "intent": {"text": "hello"}, "tool_plan": []},
                {"enabled": True, "provider": "ollama", "model": "qwen2.5:7b-instruct", "timeout_sec": 60},
            )
        finally:
            if orig is not None:
                svc._agent_llm_chat = orig

        outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        hits = [r for r in rows if isinstance(r, dict) and str(r.get("trace_id")) == "t_fast_1" and str(r.get("type")) == "chat.result" and str(r.get("status")) == "succeeded"]
        self.assertTrue(bool(hits))
        last = hits[-1]
        self.assertEqual(str(last.get("assistant_text") or "").strip(), "pong")
        self.assertTrue(bool(last.get("parse_ok")))

    def test_trade_monitor_report_includes_drawdown_and_loss_pairs(self) -> None:
        now_ms = int(svc._now_ms())
        w0 = now_ms - 5 * 86400 * 1000

        svc.TRACKER_STATE["ab_settlements"] = [
            {"ts": now_ms - 120_000, "order_id": "o_win", "event_id": "e_win", "owner": "strategy", "pnl_usdc": 2.0, "notional_usdc": 100.0, "fee_abs": 0.10, "funding_abs": 0.02},
            {"ts": now_ms - 60_000, "order_id": "o_loss", "event_id": "e_loss", "owner": "strategy", "pnl_usdc": -5.0, "notional_usdc": 100.0, "fee_abs": 0.20, "funding_abs": 0.03},
        ]

        close_orders = [
            {"id": "o_win", "event_id": "e_win", "pair": "AAA/USDT", "system_id": "strategy", "ab_owner": "strategy", "ts": now_ms - 120_000, "side": "close", "action": "close", "status": "filled"},
            {"id": "o_loss", "event_id": "e_loss", "pair": "BBB/USDT", "system_id": "strategy", "ab_owner": "strategy", "ts": now_ms - 60_000, "side": "close", "action": "close", "status": "filled"},
        ]
        rep = svc._trade_monitor_build_report(
            now_ms,
            trace_id="tm_unit_metrics",
            kind="full",
            window_start_ms=int(w0),
            window_end_ms=int(now_ms),
            close_orders=close_orders,
            reject_stats={},
            context={"monitor_cost": {"api_calls_total": 0, "latency_p95_ms": {}, "token_cost_estimate": 0}},
        )
        summary = rep.get("summary") if isinstance(rep.get("summary"), dict) else {}
        self.assertEqual(int(summary.get("trades") or 0), 2)
        self.assertAlmostEqual(float(summary.get("pnl_net_u") or 0.0), -3.0, places=6)
        self.assertAlmostEqual(float(summary.get("fees_u") or 0.0), 0.30, places=6)
        self.assertAlmostEqual(float(summary.get("funding_u") or 0.0), 0.05, places=6)
        self.assertAlmostEqual(float(summary.get("max_drawdown_u") or 0.0), 5.0, places=6)

        tlp = rep.get("top_loss_pairs") if isinstance(rep.get("top_loss_pairs"), list) else []
        self.assertTrue(bool(tlp))
        self.assertEqual(str((tlp[0] or {}).get("pair")), "BBB/USDT")
        an = rep.get("analysis") if isinstance(rep.get("analysis"), dict) else {}
        text = str(an.get("text") or "")
        self.assertIn("max_drawdown_u=", text)
        self.assertIn("loss_pair=BBB/USDT", text)

    def test_system_monitor_exec_failure_emits_playbook_hit(self) -> None:
        svc.CONFIG.update({
            "system_monitor_enabled": True,
            "system_monitor_exec_failure_enabled": True,
            "system_monitor_route_inconsistency_enabled": True,
            "system_monitor_scan_period_seconds": 5,
            "system_monitor_exec_failure_window_seconds": 120,
            "system_monitor_exec_failure_min_count": 1,
            "system_monitor_exec_failure_emit_ttl_seconds": 0,
        })

        now_ms = 1_700_000_900_000
        svc.TRACKER_STATE["system_monitor_exec_failure"] = {"last_scan_ms": 0, "seen": {}}
        svc.TRACKER_STATE["system_monitor_exec_failures"] = [
            {
                "ts": now_ms - 1000,
                "trace_id": "t_execfail_1",
                "idempotency_key": "id_execfail_1",
                "http_status": 502,
                "path": "/execution/pairs/btceth/market_close",
                "tag": "unit_test",
                "pair": None,
                "pairs": ["BTC-PERP", "ETH-PERP"],
                "strategy_id": None,
                "system_id": "strategy",
                "resp": {"ok": False, "error": "unit_test_502"},
            }
        ]

        svc._system_monitor_exec_failure_process(now_ms=int(now_ms))

        outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]

        hits = []
        for r in rows:
            if not isinstance(r, dict) or str(r.get("type")) != "execution.failure.trigger":
                continue
            env = r.get("envelope") if isinstance(r.get("envelope"), dict) else {}
            out = env.get("outputs") if isinstance(env.get("outputs"), dict) else {}
            pb = out.get("playbook_hit") if isinstance(out.get("playbook_hit"), dict) else {}
            if str(pb.get("playbook_id")) == "exec_failure.endpoint.btceth_close":
                hits.append(pb)
        self.assertTrue(bool(hits))
        pb0 = hits[0]
        self.assertTrue(isinstance(pb0.get("evidence_endpoints"), list))
        self.assertTrue(isinstance(pb0.get("minimal_fix_template"), dict))

    def test_system_monitor_route_inconsistency_emits_playbook_hit_venue_only(self) -> None:
        svc.CONFIG.update({
            "system_monitor_enabled": True,
            "system_monitor_exec_failure_enabled": True,
            "system_monitor_route_inconsistency_enabled": True,
            "system_monitor_scan_period_seconds": 5,
            "system_monitor_route_inconsistency_window_seconds": 3600,
            "system_monitor_route_inconsistency_min_count": 1,
            "system_monitor_route_inconsistency_emit_ttl_seconds": 0,
        })

        now_ms = 1_700_001_000_000
        svc.TRACKER_STATE["system_monitor_route_inconsistency"] = {"last_scan_ms": 0, "seen": {}}
        svc.TRACKER_STATE["system_monitor_route_inconsistencies"] = [
            {
                "ts": now_ms - 1000,
                "trace_id": "t_route_1",
                "idempotency_key": "id_route_1",
                "http_status": 400,
                "path": "/execution/aster/market_open",
                "kind": "carry_trade_venue_hl_only",
                "tag": "unit_test",
                "pair": "BTC-PERP",
                "strategy_id": None,
                "system_id": "strategy",
                "error": "carry_trade_venue_hl_only",
                "status": None,
                "got": "aster",
                "resp": {"ok": False, "error": "carry_trade_venue_hl_only", "got": "aster"},
            }
        ]

        svc._system_monitor_route_inconsistency_process(now_ms=int(now_ms))

        outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]

        hits = []
        for r in rows:
            if not isinstance(r, dict) or str(r.get("type")) != "route.inconsistency.trigger":
                continue
            env = r.get("envelope") if isinstance(r.get("envelope"), dict) else {}
            out = env.get("outputs") if isinstance(env.get("outputs"), dict) else {}
            pb = out.get("playbook_hit") if isinstance(out.get("playbook_hit"), dict) else {}
            if str(pb.get("playbook_id")) == "route_inconsistency.venue_only":
                hits.append(pb)
        self.assertTrue(bool(hits))
        pb0 = hits[0]
        self.assertTrue(isinstance(pb0.get("evidence_endpoints"), list))
        self.assertTrue(isinstance(pb0.get("minimal_fix_template"), dict))

    def test_execution_aster_market_open_carry_records_route_inconsistency(self) -> None:
        svc.CONFIG.update({
            "system_monitor_enabled": True,
            "system_monitor_route_inconsistency_enabled": True,
        })
        svc.TRACKER_STATE["system_monitor_route_inconsistencies"] = []

        client = svc.app.test_client()
        r = client.post("/execution/aster/market_open", json={"coin": "BTC", "side": "long", "notional_usdc": 300, "ab_owner": "carry", "execute": False, "tag": "unit"})
        self.assertEqual(r.status_code, 400)
        d = r.get_json() or {}
        self.assertEqual(str(d.get("error")), "carry_trade_venue_hl_only")

        items = svc.TRACKER_STATE.get("system_monitor_route_inconsistencies")
        self.assertTrue(isinstance(items, list))
        self.assertTrue(any(isinstance(x, dict) and str(x.get("kind")) == "carry_trade_venue_hl_only" for x in items))

        outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(any(isinstance(r, dict) and str(r.get("type")) == "route.inconsistency.trigger" for r in rows))

    def test_system_monitor_link_consistency_emits_and_enqueues_alert(self) -> None:
        svc.CONFIG.update({
            "system_monitor_enabled": True,
            "system_monitor_link_consistency_enabled": True,
            "system_monitor_scan_period_seconds": 5,
            "system_monitor_link_consistency_window_seconds": 3600,
            "system_monitor_link_consistency_min_count": 1,
            "system_monitor_link_consistency_emit_ttl_seconds": 0,
        })

        now_ms = 1_700_002_000_000
        svc.TRACKER_STATE["system_monitor_link_consistency"] = {"last_scan_ms": 0, "seen": {}}
        svc.ORDERS["o_link_1"] = {
            "id": "o_link_1",
            "order_id": "o_link_1",
            "event_id": None,
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "ts": now_ms - 1000,
            "side": "open",
            "action": "open",
            "status": "filled",
            "exec": {"mid": 100.0, "px": 100.2},
        }

        svc._system_monitor_link_consistency_process(now_ms=int(now_ms))

        outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(any(isinstance(r, dict) and str(r.get("type")) == "link.consistency.trigger" for r in rows))

        alert = os.path.join(self._td.name, "alert.jsonl")
        with open(alert, "r", encoding="utf-8") as f:
            alert_rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(any(isinstance(r, dict) and str(r.get("type")) == "push.send" and "link.consistency.trigger" in str(r.get("message") or "") for r in alert_rows))

    def test_audit_execution_quality_endpoint(self) -> None:
        client = svc.app.test_client()
        now_ms = 1_700_000_200_000
        svc.EVENTS["e1"] = {"id": "e1", "ts_emit_ms": now_ms - 2000}
        svc.ORDERS["o1"] = {
            "id": "o1",
            "event_id": "e1",
            "pair": "BTC/USDT",
            "strategy_id": "Strategy005",
            "ts": now_ms - 1000,
            "side": "open",
            "action": "open",
            "status": "filled",
            "exec": {"mid": 100.0, "px": 100.2},
            "sync": {"ts": now_ms - 500},
        }
        r = client.get(f"/audit/execution-quality?start_ts={now_ms - 10_000}&end_ts={now_ms}&max_points=200")
        self.assertEqual(r.status_code, 200)
        d = r.get_json() or {}
        self.assertTrue(bool(d.get("ok")))
        self.assertGreaterEqual(int(d.get("n_orders") or 0), 1)
        slip = d.get("slippage") if isinstance(d.get("slippage"), dict) else {}
        self.assertGreaterEqual(int(slip.get("n") or 0), 1)

    def test_paramopt_run_rolling_lr(self) -> None:
        self._seed_eval_samples(n=600)
        orig_verify = getattr(svc, "_rolling_window_verify", None)
        orig_extract = getattr(svc, "_paramopt_eval_extract_rolling", None)
        orig_score = getattr(svc, "_paramopt_score_rolling", None)
        svc._rolling_window_verify = lambda **_kwargs: {"ok": True}
        svc._paramopt_eval_extract_rolling = lambda *_args, **_kwargs: {"ok": True, "stressed": {"trades_per_day": 100.0, "coverage": 1.0}}
        svc._paramopt_score_rolling = lambda *_args, **_kwargs: (1.0, {"reason": "test"})

        client = svc.app.test_client()
        r0 = client.post(
            "/agent/paramopt/search_space",
            data=json.dumps({"scopes": ["strategy"], "include_suggest_only": True}),
            content_type="application/json",
        )
        self.assertEqual(r0.status_code, 200)
        d0 = r0.get_json() or {}
        items = (((d0.get("space") or {}).get("items")) if isinstance(d0.get("space"), dict) else None) or []
        keys = [str(it.get("key")) for it in items if isinstance(it, dict) and str(it.get("type") or "").lower() in ("int", "float", "bool") and str(it.get("key") or "").strip()]
        keys = keys[:6]
        self.assertTrue(bool(keys))

        try:
            r1 = client.post(
                "/agent/paramopt/run",
                data=json.dumps({
                    "mode": "suggest",
                    "family": "lr",
                    "eval_mode": "rolling",
                    "folds": 3,
                    "n_init": 2,
                    "n_iter": 3,
                    "keys": keys,
                    "bootstrap_samples": False,
                    "skip_robustness": True,
                }),
                content_type="application/json",
            )
            self.assertEqual(r1.status_code, 200)
            d1 = r1.get_json() or {}
            self.assertTrue(bool(d1.get("ok")))
            self.assertEqual(str(d1.get("eval_mode")), "rolling")
            sel = d1.get("selected") if isinstance(d1.get("selected"), dict) else {}
            self.assertTrue(isinstance(sel.get("patch"), dict))
            self.assertTrue(isinstance(sel.get("config_suggest"), dict))
            pg = d1.get("portfolio_gate_config") if isinstance(d1.get("portfolio_gate_config"), dict) else {}
            self.assertTrue(bool(pg))
            self.assertIn("u_r_min", pg)
            self.assertIn("dd_guard", pg)
            self.assertIn("tail_guard", pg)
            self.assertIn("order_fail_delta_guard", pg)
            self.assertIn("rollback_consecutive_gate_fail_k", pg)
            r2 = client.post(
                "/agent/paramopt/run",
                data=json.dumps({
                    "mode": "suggest",
                    "family": "lr",
                    "eval_mode": "rolling",
                    "folds": 3,
                    "n_init": 1,
                    "n_iter": 1,
                    "keys": keys,
                    "bootstrap_samples": False,
                    "skip_robustness": True,
                    "portfolio_u_r_min": 0.03,
                    "portfolio_dd_guard": 0.07,
                    "portfolio_tail_guard": 0.12,
                    "portfolio_order_fail_delta_guard": 0.04,
                    "portfolio_rollback_consecutive_gate_fail_k": 3,
                }),
                content_type="application/json",
            )
            self.assertEqual(r2.status_code, 200)
            d2 = r2.get_json() or {}
            pg2 = d2.get("portfolio_gate_config") if isinstance(d2.get("portfolio_gate_config"), dict) else {}
            self.assertEqual(float(pg2.get("u_r_min") or 0.0), 0.03)
            self.assertEqual(float(pg2.get("dd_guard") or 0.0), 0.07)
            self.assertEqual(float(pg2.get("tail_guard") or 0.0), 0.12)
            self.assertEqual(float(pg2.get("order_fail_delta_guard") or 0.0), 0.04)
            self.assertEqual(int(pg2.get("rollback_consecutive_gate_fail_k") or 0), 3)
        finally:
            if orig_verify is not None:
                svc._rolling_window_verify = orig_verify
            if orig_extract is not None:
                svc._paramopt_eval_extract_rolling = orig_extract
            if orig_score is not None:
                svc._paramopt_score_rolling = orig_score

    def test_paramopt_regime_gate_fails_when_required_regime_missing(self) -> None:
        self._seed_eval_samples(n=120)
        stats = svc._paramopt_regime_stats_from_samples(
            samples=list(svc.EVAL_SAMPLES),
            required_regimes=["trend", "chop", "highvol"],
        )
        self.assertEqual(str(stats.get("ok")), "True")
        miss = stats.get("missing_required") if isinstance(stats.get("missing_required"), list) else []
        self.assertIn("highvol", miss)
        gate = svc._paramopt_regime_gate_eval(
            stats=stats,
            min_samples_per_regime=1,
            min_effective_days_per_regime=1,
            min_trades_per_regime=1,
            required_regimes=["trend", "chop", "highvol"],
        )
        self.assertFalse(bool(gate.get("pass")))
        reasons = gate.get("reason_codes") if isinstance(gate.get("reason_codes"), list) else []
        self.assertIn("missing_required_regimes", reasons)

    def test_paramopt_regime_gate_passes_with_required_regimes_and_thresholds(self) -> None:
        samples = []
        base_ts = 1_700_000_000_000
        for i in range(30):
            ts = int(base_ts) + int(i) * 86_400_000
            for reg in ("trend", "chop", "highvol"):
                samples.append(
                    {
                        "ts": ts,
                        "pair": "BTC/USDT",
                        "features": {
                            "macro_btc_time_regime": reg,
                            "macro_atr_pct": (0.03 if reg == "highvol" else 0.01),
                            "macro_trend_shape_5": ("up" if reg == "trend" else "chop"),
                        },
                    }
                )
        stats = svc._paramopt_regime_stats_from_samples(
            samples=samples,
            required_regimes=["trend", "chop", "highvol"],
        )
        gate = svc._paramopt_regime_gate_eval(
            stats=stats,
            min_samples_per_regime=10,
            min_effective_days_per_regime=10,
            min_trades_per_regime=10,
            required_regimes=["trend", "chop", "highvol"],
        )
        self.assertTrue(bool(gate.get("pass")))

    def test_paramopt_run_blocks_on_regime_gate_when_required_missing(self) -> None:
        self._seed_eval_samples(n=600)
        orig_verify = getattr(svc, "_rolling_window_verify", None)
        orig_extract = getattr(svc, "_paramopt_eval_extract_rolling", None)
        orig_score = getattr(svc, "_paramopt_score_rolling", None)
        svc._rolling_window_verify = lambda **_kwargs: {"ok": True}
        svc._paramopt_eval_extract_rolling = lambda *_args, **_kwargs: {"ok": True, "stressed": {"trades_per_day": 100.0, "coverage": 1.0}}
        svc._paramopt_score_rolling = lambda *_args, **_kwargs: (1.0, {"reason": "test"})
        client = svc.app.test_client()
        try:
            r = client.post(
                "/agent/paramopt/run",
                data=json.dumps(
                    {
                        "mode": "suggest",
                        "opt_class": "strategy",
                        "strategy_id": "Strategy005",
                        "family": "lr",
                        "eval_mode": "rolling",
                        "folds": 3,
                        "n_init": 1,
                        "n_iter": 1,
                        "skip_robustness": True,
                        "regime_gate_enabled": True,
                        "regime_required_regimes": ["trend", "chop", "highvol"],
                        "regime_min_samples_per_regime": 1,
                        "regime_min_effective_days_per_regime": 1,
                        "regime_min_trades_per_regime": 1,
                        "bootstrap_samples": False,
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(int(r.status_code), 400)
            d = r.get_json(force=True) or {}
            self.assertEqual(str(d.get("reason_code") or ""), "insufficient_regime_sample")
            self.assertEqual(str(d.get("failed_stage") or ""), "regime_gate")
        finally:
            if orig_verify is not None:
                svc._rolling_window_verify = orig_verify
            if orig_extract is not None:
                svc._paramopt_eval_extract_rolling = orig_extract
            if orig_score is not None:
                svc._paramopt_score_rolling = orig_score

    def test_paramopt_strategy_cycle_select_targets_by_loss(self) -> None:
        svc.TRACKER_STATE["strategy_weights"] = {"A": 0.9, "B": 0.8, "C": 0.7}
        svc.TRACKER_STATE["strategy_perf"] = {
            "A": {"rets": [0.01, -0.02]},
            "B": {"rets": [-0.05, -0.04]},
            "C": {"rets": [0.02, 0.01]},
        }
        out = svc._paramopt_strategy_cycle_select_targets(now_ms=1_700_000_000_000, topn=2, selector="loss")
        self.assertTrue(bool(out.get("ok")))
        targets = out.get("targets") if isinstance(out.get("targets"), list) else []
        self.assertGreaterEqual(len(targets), 2)
        self.assertEqual(str(targets[0]), "B")
        self.assertIn(str(targets[1]), ("A", "C"))

    def test_paramopt_strategy_cycle_select_targets_by_backtest(self) -> None:
        svc.TRACKER_STATE["strategy_weights"] = {"A": 0.9, "B": 0.8, "C": 0.7}
        orig_bt = getattr(svc, "_paramopt_strategy_cycle_backtest_rank_map", None)
        svc._paramopt_strategy_cycle_backtest_rank_map = lambda _ids, metric_key="profit_total_pct": {
            "A": {"score": -0.2, "metric": metric_key},
            "B": {"score": -5.0, "metric": metric_key},
            "C": {"score": 1.0, "metric": metric_key},
        }
        try:
            out = svc._paramopt_strategy_cycle_select_targets(now_ms=1_700_000_000_000, topn=2, selector="backtest")
            self.assertTrue(bool(out.get("ok")))
            self.assertEqual(str(out.get("selector") or ""), "backtest")
            targets = out.get("targets") if isinstance(out.get("targets"), list) else []
            self.assertGreaterEqual(len(targets), 2)
            self.assertEqual(str(targets[0]), "B")
            self.assertEqual(str(targets[1]), "A")
        finally:
            if orig_bt is not None:
                svc._paramopt_strategy_cycle_backtest_rank_map = orig_bt

    def test_paramopt_strategy_cycle_run_uses_selector_loss(self) -> None:
        svc.AUTOMATION["enable_paramopt_daily"] = True
        svc.AUTOMATION["enable_paramopt_strategy_cycle"] = True
        svc.AUTOMATION["paramopt_strategy_cycle_selector"] = "loss"
        svc.AUTOMATION["paramopt_strategy_cycle_topn"] = 1
        svc.TRACKER_STATE["strategy_weights"] = {"S1": 0.8, "S2": 0.7}
        svc.TRACKER_STATE["strategy_perf"] = {
            "S1": {"rets": [0.03, -0.01]},
            "S2": {"rets": [-0.06, -0.04]},
        }
        called: List[str] = []
        orig_post = getattr(svc, "_automation_local_post_json", None)
        svc._automation_local_post_json = lambda _ep, _fn, payload: (called.append(str((payload or {}).get("strategy_id") or "")) or ({"ok": True}, 200))
        try:
            rep = svc._automation_paramopt_strategy_cycle_run(1_700_000_500_000)
            self.assertTrue(bool(rep.get("ok")))
            ran = rep.get("ran") if isinstance(rep.get("ran"), list) else []
            self.assertTrue(bool(ran))
            self.assertEqual(str((ran[0] if isinstance(ran[0], dict) else {}).get("strategy_id") or ""), "S2")
            self.assertEqual(called[:1], ["S2"])
        finally:
            if orig_post is not None:
                svc._automation_local_post_json = orig_post

    def test_paramopt_strategy_cycle_mode_apply_downgrades_when_not_allowed(self) -> None:
        svc.AUTOMATION["enable_paramopt_strategy_cycle"] = True
        svc.AUTOMATION["paramopt_strategy_cycle_selector"] = "loss"
        svc.AUTOMATION["paramopt_strategy_cycle_mode"] = "apply"
        svc.AUTOMATION["paramopt_strategy_cycle_allow_apply"] = False
        svc.TRACKER_STATE["strategy_weights"] = {"S1": 0.9}
        svc.TRACKER_STATE["strategy_perf"] = {"S1": {"rets": [-0.03, -0.02]}}
        payloads: List[Dict[str, Any]] = []
        orig_post = getattr(svc, "_automation_local_post_json", None)
        svc._automation_local_post_json = lambda _ep, _fn, payload: (payloads.append(dict(payload or {})) or ({"ok": True}, 200))
        try:
            rep = svc._automation_paramopt_strategy_cycle_run(1_700_000_600_000)
            self.assertTrue(bool(rep.get("ok")))
            self.assertTrue(bool(payloads))
            p0 = payloads[0] if isinstance(payloads[0], dict) else {}
            self.assertEqual(str(p0.get("mode") or ""), "sandbox")
            self.assertTrue(p0.get("confirm_apply") is None)
        finally:
            if orig_post is not None:
                svc._automation_local_post_json = orig_post

    def test_paramopt_strategy_cycle_mode_apply_enabled_with_confirm(self) -> None:
        svc.AUTOMATION["enable_paramopt_strategy_cycle"] = True
        svc.AUTOMATION["paramopt_strategy_cycle_selector"] = "loss"
        svc.AUTOMATION["paramopt_strategy_cycle_mode"] = "apply"
        svc.AUTOMATION["paramopt_strategy_cycle_allow_apply"] = True
        svc.AUTOMATION["paramopt_strategy_cycle_apply_confirm_required"] = True
        svc.TRACKER_STATE["strategy_weights"] = {"S1": 0.9}
        svc.TRACKER_STATE["strategy_perf"] = {"S1": {"rets": [-0.03, -0.02]}}
        payloads: List[Dict[str, Any]] = []
        orig_post = getattr(svc, "_automation_local_post_json", None)
        svc._automation_local_post_json = lambda _ep, _fn, payload: (payloads.append(dict(payload or {})) or ({"ok": True}, 200))
        try:
            rep = svc._automation_paramopt_strategy_cycle_run(1_700_000_700_000)
            self.assertTrue(bool(rep.get("ok")))
            self.assertTrue(bool(payloads))
            p0 = payloads[0] if isinstance(payloads[0], dict) else {}
            self.assertEqual(str(p0.get("mode") or ""), "apply")
            self.assertTrue(bool(p0.get("confirm_apply")))
        finally:
            if orig_post is not None:
                svc._automation_local_post_json = orig_post

    def test_pnl_drawdown_trigger_emits_decision_tree_plan(self) -> None:
        now_ms = 1_700_000_300_000
        svc.CONFIG.update(
            {
                "agent_pnl_trigger_enabled": True,
                "agent_pnl_drawdown_window_sec": 86400,
                "agent_pnl_recent_trade_n": 20,
                "agent_pnl_loss_streak_k": 3,
                "agent_pnl_drawdown_thr": 0.05,
                "agent_pnl_auto_run_tasks": False,
            }
        )

        svc.TRACKER_STATE["ab_settlements"] = []
        for i in range(6):
            svc.TRACKER_STATE["ab_settlements"].append(
                {
                    "ts": now_ms - (6 - i) * 60_000,
                    "order_id": f"o{i}",
                    "event_id": f"e{i}",
                    "pnl_usdc": -10.0,
                    "notional_usdc": 100.0,
                }
            )

        svc._agent_pnl_trigger_process(now_ms=int(now_ms))

        chat_outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(chat_outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        plans = [r for r in rows if isinstance(r, dict) and str(r.get("type")) == "loss.decision_tree.plan"]
        self.assertTrue(bool(plans))
        plan = plans[-1].get("plan") if isinstance(plans[-1], dict) else {}
        actions = (plan.get("actions") if isinstance(plan, dict) else None) or []
        self.assertGreaterEqual(len(actions), 3)

        sandbox_q = os.path.join(self._td.name, "sandbox_queue.jsonl")
        with open(sandbox_q, "r", encoding="utf-8") as f:
            qrows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(bool(qrows))
        self.assertTrue(any(isinstance(r, dict) and str(r.get("type")) == "sandbox.job.request" for r in qrows))

    def test_pnl_drawdown_rate_limited_emits_loss_auto_tasks_result(self) -> None:
        now_ms = 1_700_000_310_000
        svc.CONFIG.update(
            {
                "agent_pnl_trigger_enabled": True,
                "agent_pnl_drawdown_window_sec": 86400,
                "agent_pnl_recent_trade_n": 20,
                "agent_pnl_loss_streak_k": 3,
                "agent_pnl_drawdown_thr": 0.05,
                "agent_pnl_auto_run_tasks": True,
                "agent_pnl_auto_run_min_interval_sec": 1800,
            }
        )
        svc.TRACKER_STATE["agent_pnl_trigger_state"] = {"last_auto_run_ms": int(now_ms), "seen": {}, "seen_plan": {}}

        svc.TRACKER_STATE["ab_settlements"] = []
        for i in range(6):
            svc.TRACKER_STATE["ab_settlements"].append(
                {
                    "ts": now_ms - (6 - i) * 60_000,
                    "order_id": f"o{i}",
                    "event_id": f"e{i}",
                    "pnl_usdc": -10.0,
                    "notional_usdc": 100.0,
                }
            )

        svc._agent_pnl_trigger_process(now_ms=int(now_ms))

        chat_outbox = os.path.join(self._td.name, "chat.jsonl")
        with open(chat_outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        results = [r for r in rows if isinstance(r, dict) and str(r.get("type")) == "loss.auto.tasks.result" and bool(r.get("skipped"))]
        self.assertTrue(bool(results))

    def test_sandbox_worker_processes_blocked_job(self) -> None:
        svc.CONFIG.update(
            {
                "sandbox_outbox_worker_enabled": True,
                "sandbox_worker_state": {"processed": {}, "last_offset": 0},
                "sandbox_state": {"running": 0, "queued": 0},
                "sandbox_policy": {"concurrent_limit": 2},
            }
        )

        now_ms = 1_700_000_400_000
        q_item = {
            "id": "job1",
            "trace_id": "trace1",
            "ts": now_ms,
            "type": "sandbox.job.request",
            "inputs": {"base_trace_id": "base1", "candidates": [], "gates": ["backtest", "robustness"]},
            "outputs": {"status": "blocked", "block_reasons": ["no_candidate_with_p3_gate_ok"]},
        }
        svc._agent_outbox_append_jsonl("sandbox_queue.jsonl", q_item)

        chat_outbox = os.path.join(self._td.name, "chat.jsonl")
        rep = svc._sandbox_outbox_process_queue_once(max_items=3)
        self.assertGreaterEqual(int((rep or {}).get("processed_n") or 0), 1)
        with open(chat_outbox, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.read().splitlines() if line.strip()]
        self.assertTrue(any(isinstance(r, dict) and str(r.get("type")) == "sandbox.job.result" for r in rows))

    def test_pipeline_sandbox_gate_updates_pipeline_state_and_triggers_gray_rollout(self) -> None:
        trace_id = "t_pipe_gray_1"
        client = svc.app.test_client()
        r = client.post(
            "/agent/pipeline/run",
            json={
                "trace_id": trace_id,
                "force": True,
                "idempotent": False,
                "strategy_id": "UnitStrategy",
                "source_zip": "unit.zip",
                "skip_paramopt": True,
                "baseline_enabled": False,
                "queue_sandbox": True,
                "gray_rollout_mode": "execute",
                "confirm_live": True,
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(int(r.status_code), 200)
        st0 = svc._agent_pipeline_state_find_latest(trace_id=trace_id)
        self.assertTrue(isinstance(st0, dict))
        stages0 = st0.get("stages") if isinstance(st0.get("stages"), list) else []
        sb0 = [s for s in stages0 if isinstance(s, dict) and str(s.get("name") or "") == "sandbox_validation"]
        gr0 = [s for s in stages0 if isinstance(s, dict) and str(s.get("name") or "") == "gray_rollout"]
        self.assertTrue(bool(sb0))
        self.assertTrue(bool(gr0))
        self.assertIn(str(sb0[0].get("status")), ("running", "skipped"))
        self.assertIn(str(gr0[0].get("status")), ("pending", "skipped"))

        now_ms = 1_700_000_600_000
        svc._sandbox_job_result_emit(
            trace_id=trace_id,
            now_ms=int(now_ms),
            inputs={"base_trace_id": None, "trigger_event": "unit_test", "candidates": [{"strategy_id": "UnitStrategy", "source_zip": "unit.zip"}]},
            outputs={"gate_result": {"ok": True, "decision": "pass", "reasons": ["unit_ok"], "candidates": [], "selected": {"strategy_id": "UnitStrategy", "source_zip": "unit.zip"}}},
            evidence=[],
            doc_refs=[],
        )

        st1 = svc._agent_pipeline_state_find_latest(trace_id=trace_id)
        self.assertTrue(isinstance(st1, dict))
        stages1 = st1.get("stages") if isinstance(st1.get("stages"), list) else []
        sb1 = [s for s in stages1 if isinstance(s, dict) and str(s.get("name") or "") == "sandbox_validation"]
        gr1 = [s for s in stages1 if isinstance(s, dict) and str(s.get("name") or "") == "gray_rollout"]
        self.assertTrue(bool(sb1))
        self.assertTrue(bool(gr1))
        self.assertEqual(str(sb1[0].get("status")), "success")
        self.assertIn(str(gr1[0].get("status")), ("success", "fail"))
        sp = svc.AUTOMATION.get("serving_pipeline") if isinstance(svc.AUTOMATION, dict) else {}
        self.assertTrue(isinstance(sp, dict))
        self.assertIn(str(sp.get("phase") or ""), ("canary", "shadow", "full"))

    def test_automation_cards_shadow_loop_progress_reaches_100_after_shadow_apply(self) -> None:
        trace_id = "t_auto_shadow_1"
        client = svc.app.test_client()
        svc.AUTOMATION["enable_shadow_automation_loop"] = True

        r = client.post(
            "/agent/pipeline/run",
            json={
                "trace_id": trace_id,
                "force": True,
                "idempotent": False,
                "shadow_only": True,
                "skip_paramopt": True,
                "baseline_enabled": False,
                "queue_sandbox": False,
                "gray_rollout_mode": "execute",
                "confirm_live": True,
                "strategy_id": "UnitStrategy",
                "source_zip": "unit.zip",
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(int(r.status_code), 200)

        now_ms = 1_700_000_700_000
        svc._sandbox_job_result_emit(
            trace_id=trace_id,
            now_ms=int(now_ms),
            inputs={"base_trace_id": None, "trigger_event": "unit_test", "candidates": [{"strategy_id": "UnitStrategy", "source_zip": "unit.zip"}]},
            outputs={"gate_result": {"ok": True, "decision": "pass", "reasons": ["unit_ok"], "candidates": [], "selected": {"strategy_id": "UnitStrategy", "source_zip": "unit.zip"}}},
            evidence=[],
            doc_refs=[],
        )

        c2 = svc.app.test_client()
        r2 = c2.get("/automation/cards/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r2.status_code), 200)
        d2 = r2.get_json() or {}
        self.assertTrue(bool(d2.get("ok")))
        cards = d2.get("cards") if isinstance(d2.get("cards"), list) else []
        shadow_cards = [x for x in cards if isinstance(x, dict) and str(x.get("card_id") or "") == "strategy_shadow_loop"]
        self.assertTrue(bool(shadow_cards))
        sc = shadow_cards[0]
        prog = sc.get("progress") if isinstance(sc.get("progress"), dict) else {}
        self.assertEqual(int(prog.get("pct") or 0), 100)
        steps = prog.get("steps") if isinstance(prog.get("steps"), list) else []
        by_key = {str(s.get("key")): s for s in steps if isinstance(s, dict)}
        self.assertIn(str((by_key.get("trigger") or {}).get("status")), ("DONE", "FAIL"))
        self.assertIn(str((by_key.get("gate") or {}).get("status")), ("DONE", "FAIL"))
        self.assertIn(str((by_key.get("approval") or {}).get("status")), ("DONE", "RUN", "FAIL"))
        self.assertIn(str((by_key.get("apply") or {}).get("status")), ("DONE", "FAIL"))
        acts = sc.get("actions") if isinstance(sc.get("actions"), list) else []
        act_ids = [str(a.get("id")) for a in acts if isinstance(a, dict)]
        self.assertIn("trigger_shadow_loop", act_ids)
        self.assertIn("retry_shadow_loop", act_ids)

    def test_serving_pipeline_guard_p0_loss_gate_blocks_canary_success(self) -> None:
        orig_arena = dict(svc.ARENA_STATE) if isinstance(svc.ARENA_STATE, dict) else {}
        orig_p2 = getattr(svc, "_p2_health_gate_status", None)
        orig_p1 = getattr(svc, "_p1_exec_gate_status", None)
        try:
            now_ms = 1_700_000_600_000
            svc.ARENA_STATE.clear()
            svc.ARENA_STATE.update(
                {
                    "attrib": [
                        {"ts": int(now_ms) - 10_000, "pnl_net_u": 1.0},
                        {"ts": int(now_ms) - 5_000, "pnl_net_u": -0.5},
                    ]
                }
            )
            svc._p2_health_gate_status = lambda **_kw: {"blocked": False}
            svc._p1_exec_gate_status = lambda **_kw: {"blocked": False}
            sp = {
                "phase": "canary",
                "min_eval_samples": 2,
                "profit_days": 30,
                "min_profit_factor": 0.5,
                "max_drawdown_ratio": 1.2,
                "require_exec_quality_sufficient": False,
                "require_drift_sufficient": False,
                "require_live_deviation_sufficient": False,
            }

            svc.TRACKER_STATE["gate_history"] = []
            gate0 = svc._serving_pipeline_guard_status(sp=sp, now_ms=int(now_ms))
            self.assertTrue(bool(gate0.get("pass")))
            sc0 = gate0.get("success_criteria") if isinstance(gate0.get("success_criteria"), dict) else {}
            self.assertTrue(bool(sc0.get("success")))
            self.assertTrue(bool(sc0.get("p0")))

            svc.TRACKER_STATE["gate_history"] = [{"ts": int(now_ms), "ok": False, "reason": "daily_loss_limit", "system_id": "unit"}]
            sp["canary_start_ms"] = int(now_ms) - 60_000
            gate1 = svc._serving_pipeline_guard_status(sp=sp, now_ms=int(now_ms))
            self.assertFalse(bool(gate1.get("pass")))
            checks1 = gate1.get("checks") if isinstance(gate1.get("checks"), dict) else {}
            self.assertFalse(bool(checks1.get("p0_loss")))
            sc1 = gate1.get("success_criteria") if isinstance(gate1.get("success_criteria"), dict) else {}
            self.assertFalse(bool(sc1.get("success")))
            self.assertFalse(bool(sc1.get("p0")))
            self.assertTrue(bool(gate1.get("rollback_recommended")))
        finally:
            svc.ARENA_STATE.clear()
            svc.ARENA_STATE.update(orig_arena)
            if orig_p2 is not None:
                svc._p2_health_gate_status = orig_p2
            if orig_p1 is not None:
                svc._p1_exec_gate_status = orig_p1

    def test_governance_rejected_approval_returns_403(self) -> None:
        client = svc.app.test_client()

        r0 = client.post(
            "/approvals/log",
            json={"approver": "unit", "decision": "reject", "action": "governance.changeset.apply", "reason": "unit_test"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(r0.status_code, 200)
        rid = str((r0.get_json() or {}).get("id") or "").strip()
        self.assertTrue(bool(rid))

        r1 = client.post("/governance/changeset/apply", json={"approval_id": rid}, environ_base={"REMOTE_ADDR": "8.8.8.8"})
        self.assertEqual(r1.status_code, 403)
        d1 = r1.get_json() or {}
        self.assertEqual(str(d1.get("error")), "approval_rejected")

    def test_policy_auto_approve_and_changeset_apply_level_a(self) -> None:
        store = {"entries": {}}
        orig_load = getattr(svc, "_strategy_registry_load", None)
        orig_save = getattr(svc, "_strategy_registry_save", None)
        try:
            svc._strategy_registry_load = lambda: store
            svc._strategy_registry_save = lambda _reg: True

            svc.CONFIG["serving_shadow_mode"] = True
            svc.CONFIG["max_open_trades"] = 10

            client = svc.app.test_client()

            cand = {
                "strategy_id": "CandidateStrategy",
                "source_zip": "unit_candidate.zip",
                "family": "trend",
                "stage": "deployment",
                "gate_result": {"ok": True},
                "metrics_summary": {"backtest_days": 365, "profit_factor": 1.20, "max_drawdown_pct": 0.09, "trades": 210},
                "backtest_spec": {"cost_profile_id": "unit_cost"},
            }
            base = {
                "strategy_id": "BaselineStrategy",
                "source_zip": "unit_baseline.zip",
                "family": "trend",
                "stage": "deployment",
                "gate_result": {"ok": True},
                "metrics_summary": {"backtest_days": 365, "profit_factor": 1.10, "max_drawdown_pct": 0.10, "trades": 200},
                "backtest_spec": {"cost_profile_id": "unit_cost"},
            }
            r_up = client.post("/strategy/registry/upsert", json={"items": [cand, base]}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(r_up.status_code, 200)
            self.assertEqual(int((r_up.get_json() or {}).get("saved") or 0), 2)

            changeset = {
                "policy_ref": "gov_default",
                "action": "config.apply",
                "doc_refs": [{"doc_path": "交易AI Agent 技术文档2.0.md", "section": "4.7.6", "rule": "变更包最小集合"}],
                "strategy_id": "CandidateStrategy",
                "source_zip": "unit_candidate.zip",
                "baseline_ref": "unit-baseline-ref",
                "baseline": {"strategy_id": "BaselineStrategy", "source_zip": "unit_baseline.zip"},
                "online_metrics": {"decision": "pass"},
                "direction": "param",
                "objective_profile": "risk_tighten",
                "config_patch": {"max_open_trades": 5},
            }
            r_pe = client.post("/policy/evaluate", json={"policy_ref": "gov_default", "changeset": changeset, "auto_approve": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(r_pe.status_code, 200)
            d_pe = r_pe.get_json() or {}
            self.assertEqual(str(d_pe.get("decision") or "").lower(), "pass")
            aid = str(d_pe.get("approval_id") or "").strip()
            self.assertTrue(bool(aid))
            aa = d_pe.get("auto_approve") if isinstance(d_pe.get("auto_approve"), dict) else {}
            self.assertTrue(bool(aa.get("ok")))

            r_apply = client.post(
                "/governance/changeset/apply",
                json={"policy_ref": "gov_default", "changeset": changeset, "approval_id": aid, "trace_id": "t_unit_apply"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(r_apply.status_code, 200)
            d_apply = r_apply.get_json() or {}
            self.assertTrue(bool(d_apply.get("ok")))
            self.assertEqual(str(d_apply.get("approval_id") or ""), aid)
            self.assertEqual(int(svc.CONFIG.get("max_open_trades") or 0), 5)
        finally:
            if orig_load is not None:
                svc._strategy_registry_load = orig_load
            if orig_save is not None:
                svc._strategy_registry_save = orig_save

    def test_policy_auto_approve_blocks_level_b(self) -> None:
        store = {"entries": {}}
        orig_load = getattr(svc, "_strategy_registry_load", None)
        orig_save = getattr(svc, "_strategy_registry_save", None)
        try:
            svc._strategy_registry_load = lambda: store
            svc._strategy_registry_save = lambda _reg: True

            svc.CONFIG["serving_shadow_mode"] = True

            client = svc.app.test_client()

            cand = {
                "strategy_id": "CandidateStrategyB",
                "source_zip": "unit_candidate_b.zip",
                "family": "trend",
                "stage": "deployment",
                "gate_result": {"ok": True},
                "metrics_summary": {"backtest_days": 365, "profit_factor": 1.20, "max_drawdown_pct": 0.09, "trades": 210},
                "backtest_spec": {"cost_profile_id": "unit_cost"},
            }
            base = {
                "strategy_id": "BaselineStrategyB",
                "source_zip": "unit_baseline_b.zip",
                "family": "trend",
                "stage": "deployment",
                "gate_result": {"ok": True},
                "metrics_summary": {"backtest_days": 365, "profit_factor": 1.10, "max_drawdown_pct": 0.10, "trades": 200},
                "backtest_spec": {"cost_profile_id": "unit_cost"},
            }
            r_up = client.post("/strategy/registry/upsert", json={"items": [cand, base]}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(r_up.status_code, 200)

            changeset_b = {
                "policy_ref": "gov_default",
                "action": "config.apply",
                "doc_refs": [{"doc_path": "交易AI Agent 技术文档2.0.md", "section": "4.7.6", "rule": "变更包最小集合"}],
                "strategy_id": "CandidateStrategyB",
                "source_zip": "unit_candidate_b.zip",
                "baseline_ref": "unit-baseline-ref",
                "baseline": {"strategy_id": "BaselineStrategyB", "source_zip": "unit_baseline_b.zip"},
                "online_metrics": {"decision": "pass"},
                "direction": "param",
                "objective_profile": "risk_tighten",
                "config_patch": {"serving_shadow_mode": True},
            }
            r_pe = client.post("/policy/evaluate", json={"policy_ref": "gov_default", "changeset": changeset_b, "auto_approve": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(r_pe.status_code, 200)
            d_pe = r_pe.get_json() or {}
            self.assertEqual(str(d_pe.get("decision") or "").lower(), "pass")
            aa = d_pe.get("auto_approve") if isinstance(d_pe.get("auto_approve"), dict) else {}
            self.assertFalse(bool(aa.get("ok")))
            self.assertEqual(str(aa.get("error")), "level_b_requires_manual_approval")
        finally:
            if orig_load is not None:
                svc._strategy_registry_load = orig_load
            if orig_save is not None:
                svc._strategy_registry_save = orig_save

    def test_characterization_gate_blocks_config_change_without_baseline(self) -> None:
        svc.CONFIG.update({"characterization_gate_enabled": True, "characterization_gate_bypass_in_test_mode": False})
        p = Path(self._td.name) / "datasets" / "characterization_baseline.json"
        if p.exists():
            p.unlink()

        out0, code0 = svc._config_set_impl({"signals_dedup_ttl_sec": 7200}, confirm_live=True, action="config.set")
        self.assertEqual(int(code0), 412)
        self.assertFalse(bool(out0.get("ok")))
        self.assertEqual(str(out0.get("error")), "characterization_gate_failed")

        client = svc.app.test_client()
        r_b = client.post("/governance/characterization/baseline/build", json={"write": True}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r_b.status_code, 200)
        d_b = r_b.get_json(force=True) or {}
        self.assertTrue(bool(d_b.get("ok")))

        r_c = client.post("/governance/characterization/compare", json={}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r_c.status_code, 200)
        d_c = r_c.get_json(force=True) or {}
        self.assertTrue(bool(d_c.get("ok")))

        out1, code1 = svc._config_set_impl({"signals_dedup_ttl_sec": 7200}, confirm_live=True, action="config.set")
        self.assertEqual(int(code1), 200)
        self.assertTrue(bool(out1.get("ok")))
        self.assertEqual(int(svc.CONFIG.get("signals_dedup_ttl_sec") or 0), 7200)

    def test_three_screen_daily_signal_autofill_emits_valid_event(self) -> None:
        import numpy as np
        import pandas as pd

        orig_gid = svc.CONFIG.get("three_screen_group_id_default")
        svc.CONFIG.update({"three_screen_daily_autogen_enabled": True, "three_screen_group_id_default": "ThreeScreen.test_daily_autofill"})

        orig_macro_daily = getattr(svc, "_macro_daily_df", None)
        try:
            def _stub_daily_df(_coin: str):
                n = 260
                idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
                base = 100.0 + np.linspace(0.0, 40.0, n)
                noise = np.sin(np.linspace(0.0, 16.0, n)) * 1.5
                close = base + noise
                open_ = close + np.random.default_rng(7).normal(0.0, 0.4, n)
                high = np.maximum(open_, close) + 0.8
                low = np.minimum(open_, close) - 0.8
                vol = np.random.default_rng(9).uniform(1000.0, 2000.0, n)
                return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

            svc._macro_daily_df = _stub_daily_df

            client = svc.app.test_client()
            r = client.get("/three_screen/daily/signal?pair=BTC&auto_compute=1")
            self.assertEqual(int(r.status_code), 200)
            obj = r.get_json(force=True) or {}
            self.assertTrue(bool(obj.get("ok")))
            self.assertTrue(bool(obj.get("exists")))
            self.assertIn(str(obj.get("daily_signal_dir")), ("long", "short", "neutral"))

            evt = svc._three_screen_pick_latest_event(timeframe="1d", coin="BTC", group_id=str(svc.CONFIG.get("three_screen_group_id_default") or "ThreeScreen.v0"), require_bar_closed=True)
            self.assertTrue(isinstance(evt, dict))
            payload = dict(evt or {})
            payload["trigger_decision"] = False
            err = svc._three_screen_validate_signal_v1(payload)
            self.assertIsNone(err)
        finally:
            if orig_gid is not None:
                svc.CONFIG["three_screen_group_id_default"] = orig_gid
            if orig_macro_daily is not None:
                svc._macro_daily_df = orig_macro_daily

    def test_three_screen_daily_wfo_summary_contains_folds_when_enabled(self) -> None:
        import numpy as np
        import pandas as pd

        orig_gid = svc.CONFIG.get("three_screen_group_id_default")
        svc.CONFIG.update(
            {
                "three_screen_daily_autogen_enabled": True,
                "three_screen_daily_wfo_enabled": True,
                "three_screen_daily_wfo_train_days": 180,
                "three_screen_daily_wfo_test_days": 30,
                "three_screen_daily_wfo_folds": 4,
                "three_screen_daily_wfo_gap_days": 2,
                "three_screen_group_id_default": "ThreeScreen.test_daily_wfo_unittest_001",
                "three_screen_daily_stability_min_trades": 1,
                "three_screen_daily_stability_pf_min": 0.0,
                "three_screen_daily_stability_max_dd_max": 1.0,
            }
        )

        orig_macro_daily = getattr(svc, "_macro_daily_df", None)
        try:
            def _stub_daily_df(_coin: str):
                n = 320
                idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
                base = 100.0 + np.linspace(0.0, 50.0, n)
                noise = np.sin(np.linspace(0.0, 18.0, n)) * 1.2
                close = base + noise
                open_ = close + np.random.default_rng(11).normal(0.0, 0.3, n)
                high = np.maximum(open_, close) + 0.7
                low = np.minimum(open_, close) - 0.7
                vol = np.random.default_rng(13).uniform(1000.0, 2000.0, n)
                return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

            svc._macro_daily_df = _stub_daily_df

            client = svc.app.test_client()
            r0 = client.get("/three_screen/daily/signal?pair=BTC&auto_compute=1")
            self.assertEqual(int(r0.status_code), 200)
            d0 = r0.get_json(force=True) or {}
            self.assertTrue(bool(d0.get("ok")))
            self.assertTrue(bool(d0.get("exists")))

            r1 = client.get("/three_screen/daily/wfo_summary?pair=BTC")
            self.assertEqual(int(r1.status_code), 200)
            d1 = r1.get_json(force=True) or {}
            self.assertTrue(bool(d1.get("ok")))
            self.assertTrue(bool(d1.get("exists")))
            topk = d1.get("topk") if isinstance(d1.get("topk"), list) else []
            self.assertTrue(bool(topk))
            folds = (topk[0].get("folds") if isinstance(topk[0], dict) else None)
            self.assertTrue(isinstance(folds, list) and len(folds) >= 1)
        finally:
            if orig_gid is not None:
                svc.CONFIG["three_screen_group_id_default"] = orig_gid
            if orig_macro_daily is not None:
                svc._macro_daily_df = orig_macro_daily

    def test_three_screen_daily_switch_hold_blocks_small_delta_switch(self) -> None:
        import numpy as np
        import pandas as pd

        orig_gid = svc.CONFIG.get("three_screen_group_id_default")
        svc.CONFIG.update(
            {
                "three_screen_daily_wfo_enabled": False,
                "three_screen_daily_oos_days": 180,
                "three_screen_daily_switch_min_delta": 999.0,
                "three_screen_group_id_default": "ThreeScreen.test_daily_hold",
            }
        )

        orig_macro_daily = getattr(svc, "_macro_daily_df", None)
        orig_select = getattr(svc, "_three_screen_daily_select_from_stats", None)
        try:
            def _stub_daily_df(_coin: str):
                n = 260
                idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
                base = 100.0 + np.linspace(0.0, 40.0, n)
                noise = np.sin(np.linspace(0.0, 16.0, n)) * 1.5
                close = base + noise
                open_ = close + np.random.default_rng(17).normal(0.0, 0.4, n)
                high = np.maximum(open_, close) + 0.8
                low = np.minimum(open_, close) - 0.8
                vol = np.random.default_rng(19).uniform(1000.0, 2000.0, n)
                return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

            svc._macro_daily_df = _stub_daily_df

            r0 = svc._three_screen_daily_build_and_emit(coin="BTC", group_id=str(svc.CONFIG.get("three_screen_group_id_default") or "ThreeScreen.v0"), emit=False)
            sig0 = (r0.get("signal") if isinstance(r0, dict) else None) or {}
            bar_close_ms = int(sig0.get("bar_close_ms") or 0)
            self.assertTrue(int(bar_close_ms) > 0)

            prev_evt_id = "evt_prev_daily_hold_test"
            prev_best = "rsi_meanrev_14_v1"
            svc.EVENTS[str(prev_evt_id)] = {
                "id": str(prev_evt_id),
                "ts": int(bar_close_ms - 86400 * 1000),
                "ingested_ms": int(bar_close_ms - 86400 * 1000),
                "strategy_id": "ThreeScreen",
                "strategy_version": "1.0.0",
                "group_id": str(svc.CONFIG.get("three_screen_group_id_default") or "ThreeScreen.v0"),
                "pair": "BTC/USDC",
                "timeframe": "1d",
                "action": "observe",
                "bar_open_ms": int(bar_close_ms - 2 * 86400 * 1000),
                "bar_close_ms": int(bar_close_ms - 86400 * 1000),
                "bar_closed": True,
                "features": {
                    "daily_signal_dir": "neutral",
                    "daily_signal_confidence": 0.55,
                    "daily_selection_mode": "oos_window",
                    "daily_topk_k": 1,
                    "daily_topk": [{"indicator_id": prev_best, "weight": 1.0, "oos_score": 0.0}],
                    "daily_best_indicator_id": prev_best,
                    "daily_valid_until_ms": int(bar_close_ms + 86400 * 1000),
                    "align_with_weekly": False,
                },
            }

            def _stub_select(_indicators, *, topk_k=None):
                return {
                    "ok": True,
                    "daily_topk_k": 1,
                    "daily_topk": [{"indicator_id": "ema_cross_12_26_v1", "weight": 1.0, "oos_score": 0.0}],
                    "daily_best_indicator_id": "ema_cross_12_26_v1",
                }

            svc._three_screen_daily_select_from_stats = _stub_select

            r1 = svc._three_screen_daily_build_and_emit(coin="BTC", group_id=str(svc.CONFIG.get("three_screen_group_id_default") or "ThreeScreen.v0"), emit=False)
            sig1 = (r1.get("signal") if isinstance(r1, dict) else None) or {}
            feats1 = sig1.get("features") if isinstance(sig1.get("features"), dict) else {}
            self.assertEqual(str(feats1.get("daily_best_indicator_id")), str(prev_best))
        finally:
            if orig_select is not None:
                svc._three_screen_daily_select_from_stats = orig_select
            if orig_gid is not None:
                svc.CONFIG["three_screen_group_id_default"] = orig_gid
            if orig_macro_daily is not None:
                svc._macro_daily_df = orig_macro_daily

    def test_governance_env_pilot_outbox_isolated_and_scan_enabled(self) -> None:
        orig_env = svc.CONFIG.get("governance_env")
        orig_outbox = os.environ.get("AGENT_OUTBOX_DIR")
        orig_outbox_pilot = os.environ.get("AGENT_OUTBOX_DIR_PILOT")
        try:
            svc.CONFIG["governance_env"] = "pilot"
            with tempfile.TemporaryDirectory() as td:
                os.environ.pop("AGENT_OUTBOX_DIR", None)
                os.environ["AGENT_OUTBOX_DIR_PILOT"] = td
                p = svc._agent_outbox_dir()
                self.assertTrue(str(p).endswith("/pilot") or str(p).endswith("\\pilot"))

                with svc.app.test_client() as c:
                    r = c.get("/agent/governance/scan_contamination", environ_base={"REMOTE_ADDR": "127.0.0.1"})
                    self.assertEqual(int(r.status_code), 200)
                    d = r.get_json(force=True) or {}
                    self.assertTrue(bool(d.get("ok")))
                    self.assertEqual(str(d.get("env")), "pilot")
                    self.assertFalse(bool(d.get("skipped")))
        finally:
            if orig_env is None:
                svc.CONFIG.pop("governance_env", None)
            else:
                svc.CONFIG["governance_env"] = orig_env
            if orig_outbox is None:
                os.environ.pop("AGENT_OUTBOX_DIR", None)
            else:
                os.environ["AGENT_OUTBOX_DIR"] = orig_outbox
            if orig_outbox_pilot is None:
                os.environ.pop("AGENT_OUTBOX_DIR_PILOT", None)
            else:
                os.environ["AGENT_OUTBOX_DIR_PILOT"] = orig_outbox_pilot

    def test_runtime_config_path_uses_ml_user_data_dir(self) -> None:
        orig_user_data_env = os.environ.get("ML_USER_DATA_DIR")
        orig_loaded = getattr(svc, "_CONFIG_LOADED", None)
        orig_cfg = dict(svc.CONFIG)
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["ML_USER_DATA_DIR"] = td
                p = svc._runtime_config_path()
                self.assertEqual(str(p), str(Path(td) / "ml_config.json"))

                Path(td, "ml_config.json").write_text(json.dumps({"governance_env": "pilot", "serving_canary_size_frac": 0.2}), encoding="utf-8")
                if orig_loaded is not None:
                    svc._CONFIG_LOADED = False
                svc.CONFIG.clear()
                svc._load_config()
                self.assertEqual(str(svc.CONFIG.get("governance_env")), "pilot")
                self.assertTrue(bool(svc.CONFIG.get("serving_canary_enabled")))
                self.assertLessEqual(float(svc.CONFIG.get("serving_canary_size_frac") or 0.0), 0.10)
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(orig_cfg)
            if orig_loaded is not None:
                svc._CONFIG_LOADED = orig_loaded
            if orig_user_data_env is None:
                os.environ.pop("ML_USER_DATA_DIR", None)
            else:
                os.environ["ML_USER_DATA_DIR"] = orig_user_data_env
