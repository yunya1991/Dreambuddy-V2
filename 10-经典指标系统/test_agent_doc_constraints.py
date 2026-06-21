import unittest

import copy
import time
from datetime import datetime, timedelta, timezone


import ml_trade_service as svc


class TestAgentDocConstraints(unittest.TestCase):
    def test_hard_constraints_text_contains_doc_split(self) -> None:
        txt = svc._agent_chat_hard_constraints_text()
        self.assertIn("两份文档", txt)
        self.assertIn("技术文档.md", txt)

    def test_doc_policy_trading_questions_route_to_runbook(self) -> None:
        p = svc._agent_chat_doc_policy("为什么没下单/被拒绝，怎么排障？")
        self.assertEqual(p.get("primary"), "技术文档.md")
        self.assertEqual(p.get("conflict_winner"), "技术文档.md")

    def test_doc_policy_agent_questions_route_to_agent_doc(self) -> None:
        p = svc._agent_chat_doc_policy("agent/沙箱怎么门禁？如何审计回放？")
        self.assertEqual(p.get("primary"), "交易AI Agent 技术文档2.0.md")
        self.assertEqual(p.get("conflict_winner"), "技术文档.md")

    def test_doc_refs_enforced(self) -> None:
        refs = svc._agent_chat_enforce_doc_refs([])
        keys = {(str(x.get("doc_path")), str(x.get("section"))) for x in refs if isinstance(x, dict)}
        self.assertIn(("交易AI Agent 技术文档2.0.md", "1.3.1 两份文档分工（强约束）"), keys)
        self.assertIn(("技术文档.md", "(SSoT / Runbook)"), keys)

    def test_md_extract_lines_supports_range(self) -> None:
        p = svc._doc_allowed_map().get("交易AI Agent 技术文档2.0.md")
        self.assertTrue(p is not None and p.exists())
        out = svc._md_extract_lines(p, start_line=24, end_line=36, max_chars=4000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(int(out.get("start_line") or 0), 24)
        self.assertEqual(int(out.get("end_line") or 0), 36)
        self.assertIn("两份文档分工", str(out.get("text") or ""))

    def test_doc_snippet_endpoint_supports_line_range(self) -> None:
        c = svc.app.test_client()
        resp = c.get("/doc/snippet?doc=交易AI%20Agent%20技术文档2.0.md&start_line=24&end_line=36&max_chars=4000")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(bool(data.get("ok")))
        self.assertEqual(int(data.get("start_line") or 0), 24)
        self.assertEqual(int(data.get("end_line") or 0), 36)
        self.assertIn("两份文档分工", str(data.get("text") or ""))

    def test_agent_skills_include_code_tools(self) -> None:
        items = svc._agent_skills_list()
        names = {str(x.get("name")) for x in items if isinstance(x, dict)}
        self.assertIn("code.search", names)
        self.assertIn("code.lines", names)
        self.assertIn("config.get", names)
        self.assertIn("fs.glob", names)

    def test_skill_code_search_finds_gate_reason(self) -> None:
        out = svc._skill_code_search({"query": "daily_loss_limit", "files": ["ml_trade_service.py"], "max_hits": 20})
        self.assertTrue(bool(out.get("ok")))
        self.assertGreater(int(out.get("count") or 0), 0)

    def test_skill_code_lines_can_read_tracker_state(self) -> None:
        out = svc._skill_code_lines({"path": "user_data/tracker_state.json", "start_line": 1, "end_line": 5})
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(int(out.get("end_line") or 0) >= int(out.get("start_line") or 0))
        self.assertIsInstance(out.get("text"), str)

    def test_redact_sensitive_text_masks_tokens(self) -> None:
        s = "api_key=abc123\nAuthorization: Bearer sk-abcdefghijklmnopqrstuvwxyz\n-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
        out = svc._redact_sensitive_text(s)
        self.assertNotIn("abc123", out)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", out)
        self.assertIn("REDACTED", out)

    def test_loss_ladder_weekly_requires_daily_hits(self) -> None:
        old_config = copy.deepcopy(svc.CONFIG)
        old_tracker = copy.deepcopy(svc.TRACKER_STATE)
        try:
            now_ms = int(time.time() * 1000)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            wk = svc._week_key(now_ms)

            svc.CONFIG.clear()
            svc.CONFIG.update(
                {
                    "loss_gate_enabled": True,
                    "weekly_loss_requires_daily_hits": True,
                    "weekly_loss_after_daily_hit_days": 2,
                    "strategy_max_daily_loss": -0.05,
                    "strategy_max_weekly_loss": -0.12,
                    "max_daily_loss": -0.05,
                    "max_weekly_loss": -0.12,
                }
            )

            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(
                {
                    "open_positions": {},
                    "quant_open_positions": {},
                    "carry_open_positions": {},
                    "cooldowns": {},
                    "post_close_cooldowns": {},
                    "order_ts": [],
                    "gate_history": [],
                    "daily_pnl": {"strategy": {today: 0.0}},
                    "weekly_pnl": {"strategy": {wk: -0.5}},
                    "loss_ladder": {},
                }
            )

            out, _ = svc._order_gate_open("BTC/USDT", "long", now_ms, features=None, meta={"system_id": "strategy"})
            self.assertNotEqual(out.get("reason"), "weekly_loss_limit")

            d0 = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            svc._loss_ladder_daily_hit_add("strategy", wk, d0)
            svc._loss_ladder_daily_hit_add("strategy", wk, today)

            out2, _ = svc._order_gate_open("BTC/USDT", "long", now_ms, features=None, meta={"system_id": "strategy"})
            self.assertEqual(out2.get("reason"), "weekly_loss_limit")
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old_config)
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(old_tracker)

    def test_loss_gate_default_on_blocks_trading_through_losses(self) -> None:
        old_config = copy.deepcopy(svc.CONFIG)
        old_tracker = copy.deepcopy(svc.TRACKER_STATE)
        try:
            now_ms = int(time.time() * 1000)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            wk = svc._week_key(now_ms)

            svc.CONFIG.clear()
            svc.CONFIG.update(
                {
                    "strategy_max_daily_loss": -0.05,
                    "strategy_max_weekly_loss": -0.12,
                    "max_daily_loss": -0.05,
                    "max_weekly_loss": -0.12,
                }
            )

            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(
                {
                    "open_positions": {},
                    "quant_open_positions": {},
                    "carry_open_positions": {},
                    "cooldowns": {},
                    "post_close_cooldowns": {},
                    "order_ts": [],
                    "gate_history": [],
                    "daily_pnl": {"strategy": {today: -1.0}},
                    "weekly_pnl": {"strategy": {wk: -1.0}},
                    "loss_ladder": {},
                }
            )

            out, _ = svc._order_gate_open("BTC/USDT", "long", now_ms, features=None, meta={"system_id": "strategy"})
            self.assertEqual(out.get("reason"), "daily_loss_limit")
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old_config)
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(old_tracker)

    def test_agent_config_patch_validate_tighten_only_bool_allows_noop_true(self) -> None:
        old = copy.deepcopy(svc.CONFIG)
        try:
            svc.CONFIG.clear()
            svc.CONFIG.update({"live_trading_enabled": True})
            out = svc._agent_config_patch_validate({"live_trading_enabled": True})
            self.assertTrue(bool(out.get("ok")))
            patch = out.get("patch") if isinstance(out.get("patch"), dict) else {}
            self.assertIn("live_trading_enabled", patch)
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old)

    def test_agent_config_patch_validate_tighten_only_bool_blocks_enable(self) -> None:
        old = copy.deepcopy(svc.CONFIG)
        try:
            svc.CONFIG.clear()
            svc.CONFIG.update({"live_trading_enabled": False})
            out = svc._agent_config_patch_validate({"live_trading_enabled": True})
            self.assertFalse(bool(out.get("ok")))
            violations = out.get("violations") if isinstance(out.get("violations"), list) else []
            self.assertTrue(any(str(v.get("error")) == "cannot_enable" for v in violations if isinstance(v, dict)))
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old)

    def test_changeset_draft_build_rejects_non_allowlisted_patch(self) -> None:
        old_pick = svc._strategy_registry_get_entry
        try:
            svc._strategy_registry_get_entry = lambda sid, z: {"gate_result": {"ok": True}, "metrics_summary": {"profit_factor": 2.0, "max_drawdown_pct": 0.1, "trades": 120}}
            out = svc._agent_changeset_draft_build({"strategy_id": "S", "source_zip": "Z", "config_patch": {"not_allowed_key": 1}})
            self.assertFalse(bool(out.get("ok")))
            self.assertEqual(str(out.get("error")), "config_patch_rejected")
        finally:
            svc._strategy_registry_get_entry = old_pick

    def test_changeset_draft_build_emits_change_bundle_schema(self) -> None:
        old_pick = svc._strategy_registry_get_entry
        old_cfg = copy.deepcopy(svc.CONFIG)
        try:
            svc.CONFIG.clear()
            svc.CONFIG.update({"max_open_trades": 5})
            svc._strategy_registry_get_entry = lambda sid, z: {"gate_result": {"ok": True}, "metrics_summary": {"profit_factor": 2.0, "max_drawdown_pct": 0.1, "trades": 120}}
            out = svc._agent_changeset_draft_build({"strategy_id": "S", "source_zip": "Z", "config_patch": {"max_open_trades": 3}})
            self.assertTrue(bool(out.get("ok")))
            cbd = out.get("change_bundle_draft") if isinstance(out.get("change_bundle_draft"), dict) else {}
            self.assertEqual(str(cbd.get("change_type")), "param")
            self.assertTrue(bool(str(cbd.get("change_id") or "").strip()))
            self.assertIsInstance(cbd.get("change_tags"), list)
            self.assertIsInstance(cbd.get("diff_ref"), dict)
            self.assertIsInstance(cbd.get("expected_effect"), dict)
            self.assertIsInstance(cbd.get("required_gates"), dict)
            cd = cbd.get("config_diff") if isinstance(cbd.get("config_diff"), dict) else {}
            ch = cd.get("changes") if isinstance(cd.get("changes"), list) else []
            self.assertGreater(len(ch), 0)
            self.assertEqual(str((ch[0] if isinstance(ch[0], dict) else {}).get("key")), "max_open_trades")
            self.assertIn(str((ch[0] if isinstance(ch[0], dict) else {}).get("direction")), ("tighten", "loosen", "neutral"))
        finally:
            svc._strategy_registry_get_entry = old_pick
            svc.CONFIG.clear()
            svc.CONFIG.update(old_cfg)

    def test_governance_policy_eval_rejects_non_allowlisted_patch(self) -> None:
        old_pick = svc._strategy_registry_get_entry
        try:
            svc._strategy_registry_get_entry = lambda sid, z: {"gate_result": {"ok": True}, "metrics_summary": {"profit_factor": 2.0, "max_drawdown_pct": 0.1, "trades": 120}}
            pol = svc._governance_policy_resolve("gov_default")
            cs = {
                "policy_ref": "gov_default",
                "action": "config.apply",
                "strategy_id": "S",
                "source_zip": "Z",
                "doc_refs": [{"doc_path": "技术文档.md", "section": "0.3"}],
                "config_patch": {"not_allowed_key": 1},
            }
            out = svc._governance_policy_eval(policy=pol, changeset=cs)
            self.assertEqual(str(out.get("decision")), "fail")
            reasons = out.get("reasons") if isinstance(out.get("reasons"), list) else []
            self.assertIn("config_patch_rejected", [str(x) for x in reasons])
        finally:
            svc._strategy_registry_get_entry = old_pick

    def test_governance_changeset_apply_returns_fail_decision_for_bad_patch(self) -> None:
        old_pick = svc._strategy_registry_get_entry
        try:
            svc._strategy_registry_get_entry = lambda sid, z: {"gate_result": {"ok": True}, "metrics_summary": {"profit_factor": 2.0, "max_drawdown_pct": 0.1, "trades": 120}}
            c = svc.app.test_client()
            resp = c.post(
                "/governance/changeset/apply",
                json={
                    "policy_ref": "gov_default",
                    "changeset": {
                        "policy_ref": "gov_default",
                        "action": "config.apply",
                        "strategy_id": "S",
                        "source_zip": "Z",
                        "label": "t",
                        "reason": "t",
                        "doc_refs": [{"doc_path": "技术文档.md", "section": "0.3"}],
                        "config_patch": {"not_allowed_key": 1},
                    },
                },
            )
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json() or {}
            self.assertEqual(str(data.get("decision")), "fail")
            reasons = data.get("reasons") if isinstance(data.get("reasons"), list) else []
            self.assertIn("config_patch_rejected", [str(x) for x in reasons])
        finally:
            svc._strategy_registry_get_entry = old_pick

    def test_p1_exec_gate_blocks_on_consecutive_failures(self) -> None:
        old_config = copy.deepcopy(svc.CONFIG)
        old_tracker = copy.deepcopy(svc.TRACKER_STATE)
        try:
            now_ms = int(time.time() * 1000)
            svc.CONFIG.clear()
            svc.CONFIG.update({
                "p1_exec_gate_enabled": True,
                "p1_exec_order_consecutive_failures_thr": 3,
            })
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update({
                "p1_exec": {"order_events": [], "consecutive_failures": 3, "restart_events": []},
            })
            st = svc._p1_exec_gate_status(now_ms=now_ms)
            self.assertTrue(bool(st.get("blocked")))
            reasons = st.get("reasons") if isinstance(st.get("reasons"), list) else []
            self.assertIn("order_fail_streak", [str(x) for x in reasons])
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old_config)
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(old_tracker)

    def test_p1_exec_gate_blocks_on_high_fail_rate_window(self) -> None:
        old_config = copy.deepcopy(svc.CONFIG)
        old_tracker = copy.deepcopy(svc.TRACKER_STATE)
        try:
            now_ms = int(time.time() * 1000)
            svc.CONFIG.clear()
            svc.CONFIG.update({
                "p1_exec_gate_enabled": True,
                "p1_exec_order_window_sec": 30 * 60,
                "p1_exec_order_fail_rate_thr": 0.10,
            })
            events = []
            for i in range(20):
                ok = True
                if i in (0, 1, 2):
                    ok = False
                events.append({"ts": int(now_ms) - i * 60_000, "ok": bool(ok)})
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update({
                "p1_exec": {"order_events": events, "consecutive_failures": 0, "restart_events": []},
            })
            st = svc._p1_exec_gate_status(now_ms=now_ms)
            self.assertTrue(bool(st.get("blocked")))
            reasons = st.get("reasons") if isinstance(st.get("reasons"), list) else []
            self.assertIn("order_fail_rate_high", [str(x) for x in reasons])
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old_config)
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(old_tracker)

    def test_order_gate_rejects_entry_when_p1_exec_blocked(self) -> None:
        old_config = copy.deepcopy(svc.CONFIG)
        old_tracker = copy.deepcopy(svc.TRACKER_STATE)
        try:
            now_ms = int(time.time() * 1000)
            svc.CONFIG.clear()
            svc.CONFIG.update({
                "loss_gate_enabled": True,
                "macro_gate_enabled": False,
                "p1_exec_gate_enabled": True,
                "p1_exec_entry_gate_enabled": True,
                "p1_exec_order_consecutive_failures_thr": 3,
            })
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update({
                "p1_exec": {"order_events": [], "consecutive_failures": 3, "restart_events": []},
                "pnl_tracker": {},
            })
            out, _ = svc._order_gate_open("BTC/USDT", "long", now_ms, features=None, meta={"system_id": "strategy"})
            self.assertEqual(str(out.get("reason")), "p1_exec_safety")
        finally:
            svc.CONFIG.clear()
            svc.CONFIG.update(old_config)
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(old_tracker)
