import unittest

import ml_trade_service as svc


class TestAutomationControlPlaneOrchestratorSkill(unittest.TestCase):
    def test_skill_registered(self):
        self.assertIn("automation.control_plane.orchestrator", svc._AGENT_SKILLS_REGISTRY)

    def test_plan_only_trigger_paramopt_explore(self):
        out = svc._skill_automation_control_plane_orchestrator(
            {"intent": "trigger", "target": "paramopt_explore", "params": {"force": True}}
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("mode"), "plan_only")
        steps = out.get("tool_plan")
        self.assertIsInstance(steps, list)
        tools = [str(s.get("tool") or "") for s in steps if isinstance(s, dict)]
        self.assertIn("qwen.control.paramopt_explore_trigger", tools)

        allowed = {
            "metrics.recent",
            "tracker.stats",
            "agent.trace.replay",
            "audit.alerts_evaluate",
            "audit.data_quality",
            "audit.execution_quality",
            "sandbox.backtest",
            "sandbox.robustness",
            "qwen.control.gtw_run",
            "qwen.control.shadow_loop_run",
            "qwen.control.paramopt_trigger",
            "qwen.control.paramopt_explore_trigger",
            "qwen.control.system_monitor_run",
        }
        for t in tools:
            self.assertIn(t, allowed)

    def test_template_strategy_explore_has_baseline_first(self):
        out = svc._skill_automation_control_plane_orchestrator({"template": "strategy_explore_8h_with_baseline"})
        self.assertTrue(bool(out.get("ok")))
        steps = out.get("tool_plan")
        tools = [str(s.get("tool") or "") for s in steps if isinstance(s, dict)]
        self.assertIn("sandbox.backtest", tools)
        self.assertIn("qwen.control.paramopt_explore_trigger", tools)
        self.assertLess(tools.index("sandbox.backtest"), tools.index("qwen.control.paramopt_explore_trigger"))

    def test_template_system_kpi_conservative_paramopt(self):
        out = svc._skill_automation_control_plane_orchestrator({"template": "system_kpi_conservative_paramopt"})
        self.assertTrue(bool(out.get("ok")))
        steps = out.get("tool_plan")
        tools = [str(s.get("tool") or "") for s in steps if isinstance(s, dict)]
        self.assertIn("qwen.control.paramopt_trigger", tools)
        idx = tools.index("qwen.control.paramopt_trigger")
        step = steps[idx]
        self.assertIsInstance(step, dict)
        inp = step.get("input")
        self.assertIsInstance(inp, dict)
        self.assertEqual(inp.get("presets"), ["o6"])

    def test_template_auto_system_kpi_decision_picks_paramopt_on_trigger(self):
        orig = svc._agent_pnl_trigger_eval
        try:
            svc._agent_pnl_trigger_eval = lambda now_ms: [{"trigger": "loss.streak.trigger"}]
            out = svc._skill_automation_control_plane_orchestrator({"template": "auto_system_kpi_decision"})
            self.assertTrue(bool(out.get("ok")))
            tools = [str(s.get("tool") or "") for s in out.get("tool_plan") if isinstance(s, dict)]
            self.assertIn("qwen.control.paramopt_trigger", tools)
            self.assertNotIn("qwen.control.paramopt_explore_trigger", tools)
            auto = out.get("auto_decision")
            self.assertIsInstance(auto, dict)
            self.assertTrue(bool(auto.get("is_bad")))
        finally:
            svc._agent_pnl_trigger_eval = orig

    def test_template_auto_system_kpi_decision_picks_explore_when_ok(self):
        orig = svc._agent_pnl_trigger_eval
        try:
            svc._agent_pnl_trigger_eval = lambda now_ms: []
            out = svc._skill_automation_control_plane_orchestrator({"template": "auto_system_kpi_decision"})
            self.assertTrue(bool(out.get("ok")))
            tools = [str(s.get("tool") or "") for s in out.get("tool_plan") if isinstance(s, dict)]
            self.assertIn("qwen.control.paramopt_explore_trigger", tools)
            auto = out.get("auto_decision")
            self.assertIsInstance(auto, dict)
            self.assertFalse(bool(auto.get("is_bad")))
        finally:
            svc._agent_pnl_trigger_eval = orig

    def test_template_auto_system_kpi_decision_threshold_override_uses_settlements(self):
        orig_eval = svc._agent_pnl_trigger_eval
        orig_sett = svc._ab_settlements_get
        try:
            svc._agent_pnl_trigger_eval = lambda now_ms: []
            now_ms = int(svc._now_ms())
            svc._ab_settlements_get = lambda: [
                {"ts": now_ms - 10_000, "event_id": "e1", "order_id": "o1", "pnl_usdc": -10.0, "notional_usdc": 100.0},
                {"ts": now_ms - 5_000, "event_id": "e2", "order_id": "o2", "pnl_usdc": -5.0, "notional_usdc": 100.0},
            ]
            out = svc._skill_automation_control_plane_orchestrator(
                {
                    "template": "auto_system_kpi_decision",
                    "template_overrides": {"decision": {"loss_streak_k": 2, "window_sec": 86400}},
                }
            )
            self.assertTrue(bool(out.get("ok")))
            auto = out.get("auto_decision")
            self.assertIsInstance(auto, dict)
            self.assertTrue(bool(auto.get("override_enabled")))
            self.assertTrue(bool(auto.get("is_bad")))
            tools = [str(s.get("tool") or "") for s in out.get("tool_plan") if isinstance(s, dict)]
            self.assertIn("qwen.control.paramopt_trigger", tools)
        finally:
            svc._agent_pnl_trigger_eval = orig_eval
            svc._ab_settlements_get = orig_sett
