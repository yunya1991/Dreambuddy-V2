#!/usr/bin/env python3
"""远端 MCP（Streamable HTTP）网关（P2-3 / GAP-14）。

stdio 版本见同目录 server.py；本文件只补 HTTP 传输与鉴权，工具集与执行逻辑复用 server.py。

鉴权与红线:
  - 必须显式提供 token（环境 DREAMBUDDY_MCP_TOKEN 或 --token），长度 ≥16，否则拒绝启动；
  - 每次请求必须带 `Authorization: Bearer <token>` 与 `X-Principal: <name>`；
  - 写/ui 动作额外要求 principal 在 DREAMBUDDY_MCP_PRINCIPALS 白名单内；
  - irreversible 动作永不投影（沿用 server.py 规则）。

用法:
    DREAMBUDDY_MCP_TOKEN=$(openssl rand -hex 16) python3 mcp_shells/l0_components/http_server.py --port 8765
    curl -s http://127.0.0.1:8765/healthz
    curl -s -X POST http://127.0.0.1:8765/mcp \\
      -H "Authorization: Bearer $TOKEN" -H "X-Principal: remote-agent" \\
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SERVER_DIR = Path(__file__).resolve().parent
MIN_TOKEN_LEN = 16
MAX_BODY = 1 << 20
PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,64}$")


def _load_core():
    spec = importlib.util.spec_from_file_location(
        "l0_components_server", str(SERVER_DIR / "server.py")
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("无法加载 server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load_core()


def parse_principals(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def parse_tools(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def canonical_args_hash(arguments: Any) -> str:
    payload = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_plan(signing_key: str, plan_id: str, tool: str, args_hash: str, signature: str) -> bool:
    """云端二次校验：HMAC(plan_id \\n tool \\n args_hash) 必须与本地审批后签发一致。"""
    if not (signing_key and plan_id and signature):
        return False
    message = "{}\n{}\n{}".format(plan_id, tool, args_hash).encode("utf-8")
    expected = hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def check_auth(headers: Any, token: str, require_principal: bool = True) -> Tuple[str, int, str]:
    """返回 (principal, status, error)。status=200 表示通过。"""
    authorization = str(headers.get("Authorization") or "")
    expected = "Bearer {}".format(token)
    if not token or not hmac.compare_digest(authorization, expected):
        return "", 401, "E_AUTH：缺少或错误的 Bearer token"
    principal = str(headers.get("X-Principal") or "")
    if require_principal and not PRINCIPAL_RE.fullmatch(principal):
        return "", 401, "E_PRINCIPAL：缺少或非法的 X-Principal"
    return principal, 200, ""


def write_allowed(tool: Dict[str, Any], principal: str, principals: set[str]) -> bool:
    if not tool.get("_write"):
        return True
    return principal in principals


def make_handler(
    tools: List[Dict[str, Any]],
    token: str,
    principals: set[str],
    timeout: int,
    signing_key: str = "",
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DreamBuddyMCP/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            sys.stderr.write("[mcp-http] {}\n".format(fmt % args))

        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            except (ConnectionResetError, BrokenPipeError):
                self.close_connection = True

        def _send(self, status: int, payload: Optional[Dict[str, Any]]) -> None:
            body = (
                b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/healthz":
                self._send(404, {"error": "not found"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "server": core.SERVER_NAME,
                    "version": core.SERVER_VERSION,
                    "tools": len(tools),
                    "write_tools": sum(1 for tool in tools if tool.get("_write")),
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] not in {"/mcp", "/"}:
                self._send(404, {"error": "not found"})
                return
            principal, status, error = check_auth(self.headers, token)
            if status != 200:
                self._send(status, {"error": error})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send(400, {"error": "E_BODY：非法 Content-Length"})
                return
            if length <= 0 or length > MAX_BODY:
                self._send(413 if length > MAX_BODY else 400, {"error": "E_BODY：请求体为空或过大"})
                return
            raw = self.rfile.read(length)
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "E_JSON：请求不是合法 JSON"})
                return
            if not isinstance(request, dict):
                self._send(400, {"error": "E_JSON：需要 JSON-RPC 对象"})
                return

            if request.get("method") == "tools/call":
                try:
                    tool = core.find_tool(
                        tools, str((request.get("params") or {}).get("name") or "")
                    )
                except core.RpcError as exc:
                    self._send(200, core._error(request.get("id"), exc.code, exc.message))
                    return
                if not write_allowed(tool, principal, principals):
                    self._send(
                        403,
                        {
                            "error": "E_PRINCIPAL：{} 无权调用写动作 {}".format(
                                principal, tool["name"]
                            )
                        },
                    )
                    return
                if tool.get("_write"):
                    params = request.get("params") or {}
                    plan_id = str(self.headers.get("X-Plan-Id") or "")
                    args_header = str(self.headers.get("X-Args-Sha256") or "")
                    signature = str(self.headers.get("X-Plan-Signature") or "")
                    actual = canonical_args_hash(params.get("arguments") or {})
                    if not (
                        args_header
                        and actual == args_header
                        and verify_plan(signing_key, plan_id, tool["name"], actual, signature)
                    ):
                        self._send(
                            403,
                            {
                                "error": "E_PLAN：写动作必须携带已审批计划签名（plan_id/args/signature）"
                            },
                        )
                        return
                    sys.stderr.write(
                        "[mcp-http] WRITE principal={} plan={} tool={} args={}\n".format(
                            principal, plan_id, tool["name"], actual[:16]
                        )
                    )

            started = time.time()
            response = core.handle(request, tools, timeout, principal=principal)
            if response is None:
                self._send(202, None)
                return
            sys.stderr.write(
                "[mcp-http] principal={} method={} {}ms\n".format(
                    principal, request.get("method"), int((time.time() - started) * 1000)
                )
            )
            self._send(200, response)

    return Handler


def project_tools(
    tools: List[Dict[str, Any]], allow_write: bool, write_tools: Optional[set[str]]
) -> List[Dict[str, Any]]:
    """写工具必须同时出现在白名单里才投影；未登记的一律不暴露。"""
    if not allow_write:
        return [tool for tool in tools if not tool.get("_write")]
    allowed = write_tools or set()
    return [tool for tool in tools if not tool.get("_write") or tool["name"] in allowed]


def build_server(
    host: str,
    port: int,
    token: str,
    principals: set[str],
    profile: str = "hot",
    allow_write: bool = False,
    timeout: int = 120,
    write_tools: Optional[set[str]] = None,
    signing_key: str = "",
) -> ThreadingHTTPServer:
    if len(token) < MIN_TOKEN_LEN:
        raise ValueError("E_AUTH：token 至少 {} 字符，拒绝裸奔".format(MIN_TOKEN_LEN))
    tools = project_tools(
        core.build_tools(profile, allow_write=allow_write), allow_write, write_tools
    )
    handler = make_handler(tools, token, principals, timeout, signing_key=signing_key)
    return ThreadingHTTPServer((host, port), handler)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="59 域组件 MCP HTTP 网关（需 token + principal）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--profile", choices=["hot", "all"], default="hot")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--token", default=os.environ.get("DREAMBUDDY_MCP_TOKEN", ""))
    parser.add_argument(
        "--principals",
        default=os.environ.get("DREAMBUDDY_MCP_PRINCIPALS", ""),
        help="允许写动作的 principal，逗号分隔",
    )
    parser.add_argument(
        "--write-tools",
        default=os.environ.get("DREAMBUDDY_MCP_WRITE_TOOLS", ""),
        help="允许写动作的工具名白名单，逗号分隔（未登记的不投影）",
    )
    parser.add_argument(
        "--signing-key",
        default=os.environ.get("DREAMBUDDY_MCP_SIGNING_KEY", ""),
        help="写计划 HMAC 签名密钥（与本地 apply 共享）",
    )
    args = parser.parse_args(argv)

    token = str(args.token or "")
    if len(token) < MIN_TOKEN_LEN:
        print(
            "E_AUTH：必须提供 ≥{} 字符的 DREAMBUDDY_MCP_TOKEN（可用 openssl rand -hex 16 生成）".format(
                MIN_TOKEN_LEN
            ),
            file=sys.stderr,
        )
        return 2
    principals = parse_principals(args.principals)
    write_tools = parse_tools(args.write_tools)
    if args.allow_write and not principals:
        print("E_AUTH：--allow-write 必须同时给出 --principals 白名单", file=sys.stderr)
        return 2
    if args.allow_write and (not write_tools or len(args.signing_key) < MIN_TOKEN_LEN):
        print(
            "E_AUTH：--allow-write 需要 DREAMBUDDY_MCP_WRITE_TOOLS 与 ≥{} 字符签名密钥".format(
                MIN_TOKEN_LEN
            ),
            file=sys.stderr,
        )
        return 2

    try:
        server = build_server(
            args.host,
            args.port,
            token,
            principals,
            args.profile,
            args.allow_write,
            args.timeout,
            write_tools=write_tools,
            signing_key=str(args.signing_key or ""),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(
        "[l0_components-http] listening on http://{}:{}/mcp（principal 白名单 {} 个）".format(
            host, port, len(principals)
        ),
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
