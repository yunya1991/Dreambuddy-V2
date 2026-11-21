"""P5-2 云端只读出站客户端测试：真实 HTTP 网关 + 错误码映射 + 审计。"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT = TOOLS_DIR.parent
REPO_ROOT = ROOT.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import capabilities  # noqa: E402
import cloud_client  # noqa: E402
import dreambuddy  # noqa: E402

TOKEN = "cloud-token-0123456789"  # secret-scan: allow
PRINCIPAL = "dreambuddy-test"
SERVER_PATH = REPO_ROOT / "mcp_shells" / "l0_components" / "http_server.py"


def _load_http_server():
    spec = importlib.util.spec_from_file_location("l0_http_server", str(SERVER_PATH))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CloudClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_module = _load_http_server()
        cls.server = cls.server_module.build_server(
            "127.0.0.1",
            0,
            TOKEN,
            set(),
            profile="all",
            allow_write=True,
            write_tools={"market_data_handoff"},
            signing_key="signing-key-0123456789",
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(mock.patch.stopall)
        self.env = mock.patch.dict(
            os.environ,
            {
                "DREAMBUDDY_CLOUD_BASE": "http://127.0.0.1:{}/mcp".format(self.port),
                "DREAMBUDDY_CLOUD_TOKEN": TOKEN,
                "DREAMBUDDY_CLOUD_PRINCIPAL": PRINCIPAL,
                "DREAMBUDDY_CLOUD_TIMEOUT": "5",
                "DREAMBUDDY_CLOUD_CACHE": str(Path(self.tmp.name) / "tools.json"),
                "DREAMBUDDY_CLOUD_AUDIT": str(Path(self.tmp.name) / "audit.jsonl"),
            },
            clear=False,
        )
        self.env.start()

    def test_endpoint_url_appends_mcp(self):
        self.assertEqual(cloud_client.endpoint_url("http://127.0.0.1:1"), "http://127.0.0.1:1/mcp")
        self.assertEqual(
            cloud_client.endpoint_url("https://cloud.example/api/mcp"),
            "https://cloud.example/api/mcp",
        )

    def test_fetch_tools_marks_write_and_caches(self):
        items = cloud_client.fetch_tools()
        by_name = {item["name"]: item for item in items}
        self.assertIn("market_data_macro", by_name)
        self.assertFalse(by_name["market_data_macro"]["write"])
        self.assertTrue(by_name["market_data_handoff"]["write"])
        self.assertNotIn("market_data_handoff", {item["name"] for item in cloud_client.tools()})
        cached = json.loads(Path(os.environ["DREAMBUDDY_CLOUD_CACHE"]).read_text(encoding="utf-8"))
        self.assertEqual(len(cached["tools"]), len(items))
        self.assertTrue(cached["server"])

    def test_call_unknown_tool_is_denied_client_side(self):
        cloud_client.fetch_tools()
        with self.assertRaises(cloud_client.CloudError) as ctx:
            cloud_client.call("not_registered_tool", {})
        self.assertEqual(ctx.exception.code, "E_CLOUD_DENIED")

    def test_wrong_token_maps_to_auth(self):
        with mock.patch.dict(
            os.environ, {"DREAMBUDDY_CLOUD_TOKEN": "wrong-token-000000"}, clear=False
        ):
            with self.assertRaises(cloud_client.CloudError) as ctx:
                cloud_client.fetch_tools()
        self.assertEqual(ctx.exception.code, "E_CLOUD_AUTH")

    def test_write_tool_without_principal_maps_to_denied(self):
        with self.assertRaises(cloud_client.CloudError) as ctx:
            cloud_client.rpc(
                "tools/call",
                {"name": "market_data_handoff", "arguments": {}},
                request_id=9,
            )
        self.assertEqual(ctx.exception.code, "E_CLOUD_DENIED")

    def test_failed_call_is_audited(self):
        cloud_client.fetch_tools()
        with self.assertRaises(cloud_client.CloudError):
            cloud_client.call("not_registered_tool", {})
        lines = Path(os.environ["DREAMBUDDY_CLOUD_AUDIT"]).read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        entry = json.loads(lines[-1])
        self.assertEqual(entry["tool"], "not_registered_tool")
        self.assertFalse(entry["ok"])
        self.assertNotIn(TOKEN, json.dumps(entry))

    def test_empty_config_reports_auth(self):
        buffer = io.StringIO()
        with (
            mock.patch.dict(
                os.environ,
                {
                    "DREAMBUDDY_CLOUD_BASE": "",
                    "DREAMBUDDY_CLOUD_TOKEN": "",
                    "DREAMBUDDY_CLOUD_TOKEN_FILE": "",
                },
                clear=False,
            ),
            redirect_stdout(buffer),
            redirect_stderr(buffer),
        ):
            code = cloud_client.main(["tools", "--refresh"])
        self.assertEqual(code, 2)
        self.assertIn("E_CLOUD_AUTH", buffer.getvalue())

    def test_status_cli_ok(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cloud_client.main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("已配置", buffer.getvalue())


class CloudWriteTest(unittest.TestCase):
    KEY = "signing-key-0123456789"  # secret-scan: allow

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(mock.patch.stopall)
        cache = Path(self.tmp.name) / "tools.json"
        cache.write_text(
            json.dumps(
                {
                    "tools": [
                        {"name": "demo_read", "write": False},
                        {"name": "demo_write", "write": True, "inputSchema": {}},
                    ]
                }
            ),
            encoding="utf-8",
        )
        mock.patch.dict(
            os.environ,
            {
                "DREAMBUDDY_CLOUD_BASE": "https://cloud.example/mcp",
                "DREAMBUDDY_CLOUD_TOKEN": TOKEN,
                "DREAMBUDDY_CLOUD_PRINCIPAL": PRINCIPAL,
                "DREAMBUDDY_CLOUD_CACHE": str(cache),
                "DREAMBUDDY_CLOUD_AUDIT": str(Path(self.tmp.name) / "audit.jsonl"),
                "DREAMBUDDY_CLOUD_SIGNING_KEY": self.KEY,
                "DREAMBUDDY_CLOUD_SIGNING_KEY_FILE": "",
                "DREAMBUDDY_CLOUD_ENV": str(Path(self.tmp.name) / "absent.env"),
            },
            clear=False,
        ).start()

    def test_plan_signature_is_deterministic(self):
        digest = cloud_client.args_hash({"series": "DGS10"})
        first = cloud_client.plan_signature(self.KEY, "plan_1", "demo_write", digest)
        second = cloud_client.plan_signature(self.KEY, "plan_1", "demo_write", digest)
        self.assertEqual(first, second)
        self.assertNotEqual(
            first, cloud_client.plan_signature(self.KEY, "plan_2", "demo_write", digest)
        )

    def test_call_write_requires_signing_key(self):
        with mock.patch.dict(os.environ, {"DREAMBUDDY_CLOUD_SIGNING_KEY": ""}, clear=False):
            with self.assertRaises(cloud_client.CloudError) as ctx:
                cloud_client.call_write("demo_write", {}, "plan_x")
        self.assertEqual(ctx.exception.code, "E_CLOUD_AUTH")

    def test_call_refuses_write_tool(self):
        with self.assertRaises(cloud_client.CloudError) as ctx:
            cloud_client.call("demo_write", {})
        self.assertEqual(ctx.exception.code, "E_CLOUD_DENIED")

    def test_call_write_sends_plan_headers(self):
        captured = {}

        def fake_post(payload, conf, extra_headers=None):
            captured.update(extra_headers or {})
            return {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {"content": [{"type": "text", "text": '{"ok": true}'}]},
            }

        with mock.patch.object(cloud_client, "_post", side_effect=fake_post):
            payload = cloud_client.call_write("demo_write", {"a": 1}, "plan_abc")
        digest = cloud_client.args_hash({"a": 1})
        self.assertEqual(captured["X-Plan-Id"], "plan_abc")
        self.assertEqual(captured["X-Args-Sha256"], digest)
        self.assertEqual(
            captured["X-Plan-Signature"],
            cloud_client.plan_signature(self.KEY, "plan_abc", "demo_write", digest),
        )
        self.assertEqual(payload["_meta"]["plan_id"], "plan_abc")


class CloudCapabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write_cache(self):
        path = Path(self.tmp.name) / "tools.json"
        path.write_text(
            json.dumps(
                {
                    "fetched_at": "2026-11-22T00:00:00",
                    "base": "http://cloud.example/mcp",
                    "server": {"name": "test"},
                    "tools": [
                        {
                            "name": "fake_read",
                            "description": "只读示例",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_capabilities_include_cached_cloud_tools(self):
        path = self._write_cache()
        with mock.patch.dict(os.environ, {"DREAMBUDDY_CLOUD_CACHE": str(path)}, clear=False):
            caps = capabilities.build(refresh=True)
        ids = {cap["id"] for cap in caps if cap["kind"] == "cloud"}
        self.assertIn("cloud.fake_read", ids)

    def test_plan_for_cloud(self):
        path = self._write_cache()
        with mock.patch.dict(os.environ, {"DREAMBUDDY_CLOUD_CACHE": str(path)}, clear=False):
            plan = capabilities.plan_for("cloud.fake_read", {"a": 1})
        self.assertEqual(plan["kind"], "cloud")
        self.assertEqual(plan["tool"], "fake_read")
        self.assertEqual(plan["args"], {"a": 1})

    def test_execute_plan_cloud_branch(self):
        buffer = io.StringIO()
        with (
            mock.patch.object(
                cloud_client,
                "call",
                return_value={"ok": True, "data": {}, "_meta": {"route": "cloud"}},
            ),
            redirect_stdout(buffer),
        ):
            code = dreambuddy.execute_plan({"kind": "cloud", "tool": "fake_read", "args": {}})
        self.assertEqual(code, 0)
        self.assertIn('"route": "cloud"', buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
