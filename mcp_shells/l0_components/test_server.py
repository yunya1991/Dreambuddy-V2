"""l0_components MCP 投影单测（P1）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


class ToolListTest(unittest.TestCase):
    def test_hot_tools_are_readonly_and_json(self):
        tools = server.build_tools("hot")
        names = {tool["name"] for tool in tools}
        self.assertEqual(
            names,
            {
                "a_share_quote",
                "market_data_macro",
                "sec_filing_reader",
                "market_data_onchain",
                "a_share_index_facts",
                "official_fed_sec_event_search",
                "ticket_reservation",
                "reservation_job_list",
            },
        )
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])

    def test_all_profile_adds_extended_context_tool(self):
        names = {tool["name"] for tool in server.build_tools("all")}
        self.assertIn("event_context_context", names)
        self.assertIn("a_share_quote", names)

    def test_schema_properties_match_declared_params(self):
        for tool in server.build_tools("all", allow_write=True):
            declared = [p["name"] for p in tool["_action"].get("params") or []]
            if tool["_write"]:
                declared = declared + ["confirm"]
            self.assertEqual(
                list(tool["inputSchema"]["properties"].keys()),
                declared,
                msg="{} 的 inputSchema 与 component.yaml 不一致".format(tool["name"]),
            )


class WriteGateTest(unittest.TestCase):
    def test_write_hidden_by_default(self):
        names = {tool["name"] for tool in server.build_tools("all")}
        self.assertNotIn("market_data_handoff", names)

    def test_write_listed_with_flag_and_requires_confirm(self):
        tools = {tool["name"]: tool for tool in server.build_tools("all", allow_write=True)}
        self.assertIn("market_data_handoff", tools)
        self.assertFalse(tools["market_data_handoff"]["annotations"]["readOnlyHint"])
        self.assertIn("confirm", tools["market_data_handoff"]["inputSchema"]["required"])

    def test_write_requires_principal(self):
        tools = {tool["name"]: tool for tool in server.build_tools("all", allow_write=True)}
        result = server.run_tool(tools["market_data_handoff"], {"confirm": True}, timeout=5)
        self.assertTrue(result["isError"])
        self.assertIn("E_MANDATE", result["content"][0]["text"])

    def test_write_requires_confirm(self):
        tools = {tool["name"]: tool for tool in server.build_tools("all", allow_write=True)}
        result = server.run_tool(tools["market_data_handoff"], {}, timeout=5, principal="tester")
        self.assertTrue(result["isError"])
        self.assertIn("E_CONFIRM", result["content"][0]["text"])

    def test_audit_appends_jsonl(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "audit.jsonl"
            old = os.environ.get("DREAMBUDDY_AUDIT_LOG")
            os.environ["DREAMBUDDY_AUDIT_LOG"] = str(log)
            try:
                server._audit_write("tester", "demo_tool", {"a": 1}, ["python", "x.py"], 0, 12)
            finally:
                if old is None:
                    os.environ.pop("DREAMBUDDY_AUDIT_LOG", None)
                else:
                    os.environ["DREAMBUDDY_AUDIT_LOG"] = old
            record = __import__("json").loads(log.read_text(encoding="utf-8").strip())
            self.assertEqual(record["principal"], "tester")
            self.assertEqual(record["tool"], "demo_tool")
            self.assertEqual(record["exit_code"], 0)


class BuildArgvTest(unittest.TestCase):
    def setUp(self):
        self.tools = {tool["name"]: tool for tool in server.build_tools("all")}

    def test_quotes_builds_flag_and_json(self):
        argv = server.build_argv(self.tools["a_share_quote"], {"symbols": "sh600519,sz000001"})
        self.assertIn("--symbols", argv)
        self.assertIn("sh600519,sz000001", argv)
        self.assertEqual(argv[-1], "--json")

    def test_ask_uses_positional_text(self):
        argv = server.build_argv(self.tools["ticket_reservation"], {"text": "预约 12 月 25 日内场"})
        self.assertIn("ask", argv)
        self.assertIn("预约 12 月 25 日内场", argv)
        self.assertEqual(argv[-1], "--json")
        self.assertLess(argv.index("预约 12 月 25 日内场"), argv.index("--json"))

    def test_missing_required_argument_rejected(self):
        with self.assertRaises(server.RpcError):
            server.build_argv(self.tools["sec_filing_reader"], {})

    def test_unknown_argument_rejected(self):
        with self.assertRaises(server.RpcError):
            server.build_argv(self.tools["market_data_macro"], {"nope": 1})


if __name__ == "__main__":
    unittest.main()
