"""远端 MCP HTTP 网关的鉴权与传输测试（P2-3）。"""

from __future__ import annotations

import http.client
import json
import threading
import unittest
from typing import Any, Dict

import http_server

TOKEN = "test-token-0123456789"  # secret-scan: allow


class AuthTest(unittest.TestCase):
    def test_missing_or_wrong_token_is_rejected(self):
        headers = {"Authorization": "", "X-Principal": "agent"}
        self.assertEqual(http_server.check_auth(headers, TOKEN)[1], 401)
        headers["Authorization"] = "Bearer wrong-token-0123456789"
        self.assertEqual(http_server.check_auth(headers, TOKEN)[1], 401)

    def test_missing_principal_is_rejected(self):
        headers = {"Authorization": "Bearer " + TOKEN}
        self.assertEqual(http_server.check_auth(headers, TOKEN)[1], 401)
        headers["X-Principal"] = "bad principal!"
        self.assertEqual(http_server.check_auth(headers, TOKEN)[1], 401)

    def test_valid_credentials_pass(self):
        headers = {"Authorization": "Bearer " + TOKEN, "X-Principal": "remote-agent"}
        principal, status, _ = http_server.check_auth(headers, TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(principal, "remote-agent")

    def test_short_token_refuses_to_start(self):
        with self.assertRaises(ValueError):
            http_server.build_server("127.0.0.1", 0, "short", set())

    def test_write_requires_principal_whitelist(self):
        tool = {"name": "demo_write", "_write": True}
        read = {"name": "demo_read", "_write": False}
        self.assertTrue(http_server.write_allowed(read, "anyone", set()))
        self.assertFalse(http_server.write_allowed(tool, "guest", {"ops"}))
        self.assertTrue(http_server.write_allowed(tool, "ops", {"ops"}))


class PlanSignatureTest(unittest.TestCase):
    KEY = "signing-key-0123456789"  # secret-scan: allow

    def test_args_hash_is_canonical(self):
        left = http_server.canonical_args_hash({"b": 2, "a": 1})
        right = http_server.canonical_args_hash({"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertNotEqual(left, http_server.canonical_args_hash({"a": 1}))

    def test_verify_plan_accepts_matching_signature(self):
        digest = http_server.canonical_args_hash({"series": "DGS10"})
        signature = cloud_signature(self.KEY, "plan_abc", "market_data_handoff", digest)
        self.assertTrue(
            http_server.verify_plan(self.KEY, "plan_abc", "market_data_handoff", digest, signature)
        )

    def test_verify_plan_rejects_tampering(self):
        digest = http_server.canonical_args_hash({"series": "DGS10"})
        signature = cloud_signature(self.KEY, "plan_abc", "market_data_handoff", digest)
        self.assertFalse(
            http_server.verify_plan(
                self.KEY, "plan_abc", "market_data_handoff", digest + "0", signature
            )
        )
        self.assertFalse(
            http_server.verify_plan(
                self.KEY, "plan_abc", "event_context_handoff", digest, signature
            )
        )
        self.assertFalse(
            http_server.verify_plan("", "plan_abc", "market_data_handoff", digest, signature)
        )

    def test_write_tools_not_in_allowlist_are_not_projected(self):
        tools = [
            {"name": "read_tool", "_write": False},
            {"name": "market_data_handoff", "_write": True},
            {"name": "event_context_handoff", "_write": True},
        ]
        projected = http_server.project_tools(tools, True, {"market_data_handoff"})
        self.assertEqual([item["name"] for item in projected], ["read_tool", "market_data_handoff"])
        self.assertEqual(
            [item["name"] for item in http_server.project_tools(tools, False, set())], ["read_tool"]
        )


def cloud_signature(key: str, plan_id: str, tool: str, digest: str) -> str:
    import hashlib
    import hmac

    message = "{}\n{}\n{}".format(plan_id, tool, digest).encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


class HttpTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http_server.build_server("127.0.0.1", 0, TOKEN, {"ops"}, profile="hot")
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _request(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
    ):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, json.loads(data.decode("utf-8")) if data else {}

    def _auth_headers(self, principal: str = "remote-agent") -> Dict[str, str]:
        return {"Authorization": "Bearer " + TOKEN, "X-Principal": principal}

    def test_healthz_needs_no_auth(self):
        status, payload = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["tools"], 0)

    def test_post_without_token_is_401(self):
        status, _ = self._request(
            "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        self.assertEqual(status, 401)

    def test_post_without_principal_is_401(self):
        status, _ = self._request(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"Authorization": "Bearer " + TOKEN},
        )
        self.assertEqual(status, 401)

    def test_initialize_and_tools_list(self):
        status, payload = self._request(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            self._auth_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["serverInfo"]["name"], http_server.core.SERVER_NAME)

        status, payload = self._request(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self._auth_headers(),
        )
        self.assertEqual(status, 200)
        tools = payload["result"]["tools"]
        self.assertEqual(len(tools), len(http_server.core.build_tools("hot")))
        self.assertTrue(all(item["annotations"]["readOnlyHint"] for item in tools))
        self.assertTrue(all(not item.get("_write") for item in tools))

    def test_unknown_method_returns_jsonrpc_error(self):
        status, payload = self._request(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 3, "method": "nope"},
            self._auth_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["error"]["code"], -32601)

    def test_unknown_tool_returns_jsonrpc_error(self):
        status, payload = self._request(
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "ghost_tool", "arguments": {}},
            },
            self._auth_headers(),
        )
        self.assertEqual(status, 200)
        self.assertIn("unknown tool", payload["error"]["message"])

    def test_write_without_whitelist_is_403(self):
        write_server = http_server.build_server(
            "127.0.0.1",
            0,
            TOKEN,
            {"ops"},
            profile="all",
            allow_write=True,
            write_tools={"event_context_handoff", "market_data_handoff"},
            signing_key=PlanSignatureTest.KEY,
        )
        port = write_server.server_address[1]
        thread = threading.Thread(target=write_server.serve_forever, daemon=True)
        thread.start()
        try:
            tools = http_server.core.build_tools("all", allow_write=True)
            write_tool = next(tool for tool in tools if tool.get("_write"))
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request(
                "POST",
                "/mcp",
                body=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {"name": write_tool["name"], "arguments": {}},
                    }
                ).encode("utf-8"),
                headers=self._auth_headers("guest"),
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            conn.close()
        finally:
            write_server.shutdown()
            write_server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
