"""P3：CLI 多轮会话 / 多域路由 / 19-DAL 数据桥的回归测试。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import data_bridge  # noqa: E402
import dreambuddy  # noqa: E402
import trading_bridge  # noqa: E402


class RouterCatalogTest(unittest.TestCase):
    def test_catalog_covers_all_domains(self):
        catalog = dreambuddy.route_catalog()
        data_names = {item["name"] for item in catalog["data_read"]}
        self.assertIn("data_store_read", data_names)
        self.assertNotIn("data_store_write", data_names)
        self.assertIn("jobs", catalog["mobile_read"])
        self.assertNotIn("dispatch", catalog["mobile_read"])
        self.assertIn("daily-market-brief", catalog["workflows"])
        self.assertEqual(catalog["schedule_read"], ["list"])
        self.assertTrue(
            any(item["component"] == "market-data" for item in catalog["component_actions"])
        )

    def test_history_is_trimmed_and_filtered(self):
        history = [{"role": "user", "content": "第{}轮".format(i)} for i in range(10)]
        history.insert(1, {"role": "system", "content": "忽略"})
        trimmed = dreambuddy.trim_history(history, limit=4)
        self.assertEqual(len(trimmed), 4)
        self.assertEqual(trimmed[-1]["content"], "第9轮")
        self.assertTrue(all(turn["role"] in {"user", "assistant"} for turn in trimmed))

    def test_rule_plan_routes_workflow_and_data(self):
        self.assertEqual(dreambuddy.rule_plan("跑一下市场日报")["kind"], "workflow")
        self.assertEqual(dreambuddy.rule_plan("我想设置定时任务")["kind"], "answer")
        self.assertEqual(dreambuddy.rule_plan("查本地库指标历史")["kind"], "answer")

    def test_nl_plan_falls_back_when_qwen_missing(self):
        with mock.patch.object(dreambuddy, "qwen_ready", return_value=False):
            plan, source = dreambuddy.nl_plan("查询贵州茅台股价")
        self.assertEqual(source, "rule")
        self.assertEqual(plan["component"], "market-data")
        self.assertEqual(plan["action"], "quotes")

    def test_execute_plan_data_branch(self):
        buffer = io.StringIO()
        with (
            mock.patch("data_bridge.call", return_value={"ok": True, "data": {"rows": []}}),
            redirect_stdout(buffer),
        ):
            code = dreambuddy.execute_plan(
                {"kind": "data", "tool": "data_store_read", "args": {"table": "mm_metrics"}}
            )
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', buffer.getvalue())

    def test_execute_plan_data_failure_exit_code(self):
        with (
            mock.patch("data_bridge.call", return_value={"ok": False}),
            redirect_stdout(io.StringIO()),
        ):
            code = dreambuddy.execute_plan({"kind": "data", "tool": "data_fetch", "args": {}})
        self.assertEqual(code, 1)

    def test_execute_plan_blocks_mobile_write_commands(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = dreambuddy.execute_plan({"kind": "mobile", "command": "dispatch", "args": []})
        self.assertEqual(code, 3)
        self.assertIn("E_GUARD", buffer.getvalue())


class SessionTest(unittest.TestCase):
    def test_resolve_session_name_and_path(self):
        self.assertEqual(
            dreambuddy.resolve_session("morning").name,
            "morning.jsonl",
        )
        explicit = dreambuddy.resolve_session("/tmp/demo/session.jsonl")
        self.assertEqual(explicit, Path("/tmp/demo/session.jsonl"))

    def test_session_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            dreambuddy.append_session(path, {"role": "user", "content": "你好", "at": "t"})
            dreambuddy.append_session(
                path, {"role": "assistant", "content": "[data] ok", "at": "t"}
            )
            turns = dreambuddy.load_session(path)
            self.assertEqual([turn["role"] for turn in turns], ["user", "assistant"])
            self.assertEqual(turns[0]["content"], "你好")

    def test_session_ignores_broken_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text('{"role":"user","content":"ok"}\nnot-json\n', encoding="utf-8")
            self.assertEqual(len(dreambuddy.load_session(path)), 1)


class TradingBridgeTest(unittest.TestCase):
    def test_only_read_tools_are_exposed(self):
        names = {item["name"] for item in trading_bridge.tools()}
        self.assertEqual(names, set(trading_bridge.READ_TOOLS))
        self.assertNotIn("forward_signal", names)

    def test_forward_signal_is_rejected(self):
        with self.assertRaises(ValueError):
            trading_bridge.call("forward_signal", {"paper_execute": False})

    def test_catalog_registers_trading_ids(self):
        import capabilities

        caps = capabilities.build(refresh=True)
        ids = {cap["id"] for cap in caps if cap["kind"] == "trading"}
        self.assertIn("trading.get_signal_state", ids)
        self.assertIn("trading.get_positions", ids)
        legacy = capabilities.legacy_catalog()
        self.assertTrue(any(item["name"] == "get_balance" for item in legacy["trading_read"]))

    def test_plan_for_trading(self):
        import capabilities

        plan = capabilities.plan_for("trading.get_cycle_state", {})
        self.assertEqual(plan["kind"], "trading")
        self.assertEqual(plan["tool"], "get_cycle_state")

    def test_execute_plan_trading_branch(self):
        buffer = io.StringIO()
        with (
            mock.patch("trading_bridge.call", return_value={"ok": True, "data": {"state": "idle"}}),
            redirect_stdout(buffer),
        ):
            code = dreambuddy.execute_plan(
                {"kind": "trading", "tool": "get_signal_state", "args": {}}
            )
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', buffer.getvalue())

    def test_rule_plan_routes_trading(self):
        self.assertEqual(dreambuddy.rule_plan("看一下我的持仓")["tool"], "get_positions")
        self.assertEqual(dreambuddy.rule_plan("交易信号现在是什么")["tool"], "get_signal_state")


class DataBridgeTest(unittest.TestCase):
    def test_read_tools_only(self):
        names = [item["name"] for item in data_bridge.tools()]
        self.assertEqual(sorted(names), sorted(data_bridge.READ_TOOLS))
        self.assertNotIn("data_store_write", names)

    def test_call_rejects_write_tool(self):
        with self.assertRaises(ValueError):
            data_bridge.call("data_store_write", {"table": "mm_metrics", "data": {}})

    def test_call_parses_envelope(self):
        fake = mock.Mock()
        fake.TOOL_HANDLERS = {
            "data_store_read": lambda args: json.dumps({"ok": True, "data": args})
        }
        with mock.patch.object(data_bridge, "load_core", return_value=fake):
            payload = data_bridge.call("data_store_read", {"table": "mm_metrics"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["table"], "mm_metrics")


if __name__ == "__main__":
    unittest.main()
