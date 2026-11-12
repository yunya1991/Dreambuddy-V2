#!/usr/bin/env python3
"""DSH /execute HTTP 出口 —— 云端运行主路径

把 `34-前端应用训练系统/core/dsh_frontend_bridge.call_handler` 暴露为 HTTP，
供前端 `callDshHttp`（`DSH_API_BASE` → `POST {base}/execute`）在云端直接调用，
避免云端依赖本地 spawn 解释器。

零新增依赖（stdlib http.server）；与本地 IPC 路径**共用同一 dispatcher**，不产生第二套路由。

接口：
  GET  /health   → {ok, service, capabilities, bridge, auth}
  POST /execute  body {capability, payload?, trace_id?}
       → call_handler 的返回 + 顶层 trace_id 回显

鉴权（云端必须开启）：
  设置 DSH_EXECUTE_TOKEN 后，POST /execute 必须带 `Authorization: Bearer <token>`；
  缺省/错误 → 401 unauthorized。/health 不鉴权，供负载均衡探活，且会报告 auth 状态。
  留空 DSH_EXECUTE_TOKEN 仅供本机开发（/health 显示 auth:"disabled"）。

FAIL-OPEN：
  - bridge 不可导入        → 503 bridge_unavailable
  - capability 缺失/非字符串 → 400 bad_request
  - capability 未知        → 200 {ok:false, error_code:"not_found"}（前端按 degraded 消费）
  - handler 抛异常         → 200 {ok:false, error_code:"handler_exception"}

启动：
  DSH_EXECUTE_TOKEN=... python3 execute_http_server.py [--host 127.0.0.1] [--port 8791]
  或环境变量 DSH_EXECUTE_HOST / DSH_EXECUTE_PORT
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

DEFAULT_HOST = os.environ.get("DSH_EXECUTE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("DSH_EXECUTE_PORT", "8791"))
AUTH_ENV = "DSH_EXECUTE_TOKEN"

_bridge_module: Optional[Any] = None


# ── bridge 定位（与 dsh_frontend_bridge 的路径推导方向相反，但同样相对 __file__）──


def _repo_root() -> str:
    """python-server → packages → dream-harness-bridge → 1-ARCHITECTURE → repo root"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", ".."))


def _bridge_dir() -> str:
    return os.path.join(_repo_root(), "34-前端应用训练系统", "core")


def _load_bridge() -> Optional[Any]:
    """导入 dsh_frontend_bridge；不可导入返回 None（FAIL-OPEN）。"""
    global _bridge_module
    if _bridge_module is not None:
        return _bridge_module
    bridge_dir = _bridge_dir()
    if not os.path.isdir(bridge_dir):
        return None
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    try:
        import dsh_frontend_bridge as mod  # noqa: PLC0415

        _bridge_module = mod
        return mod
    except Exception:  # noqa: BLE001 FAIL-OPEN
        return None


def list_capabilities() -> list:
    mod = _load_bridge()
    if mod is None:
        return []
    try:
        return sorted(mod.HANDLER_TO_SHELL_ID.keys())
    except Exception:  # noqa: BLE001
        return []


# ── 鉴权（每次请求读 env，便于测试与本机切换） ────────────────────────


def expected_token() -> str:
    return (os.environ.get(AUTH_ENV) or "").strip()


def check_bearer(header_value: str, expected: str) -> bool:
    """常量时间比较 Authorization: Bearer <token>。"""
    prefix = "Bearer "
    if not expected or not header_value.startswith(prefix):
        return False
    return hmac.compare_digest(header_value[len(prefix) :].strip(), expected)


def dispatch(capability: Any, payload: Any, trace_id: Any) -> Tuple[int, Dict[str, Any]]:
    """capability → 统一信封。返回 (http_status, body)。"""
    trace = trace_id if isinstance(trace_id, str) else ""
    mod = _load_bridge()
    if mod is None:
        return 503, {
            "ok": False,
            "error_code": "bridge_unavailable",
            "trace_id": trace,
            "meta": {"reason": "dsh_frontend_bridge not importable", "bridge_dir": _bridge_dir()},
        }
    if not isinstance(capability, str) or not capability:
        return 400, {
            "ok": False,
            "error_code": "bad_request",
            "trace_id": trace,
            "meta": {"reason": "capability must be a non-empty string"},
        }

    args = payload if isinstance(payload, dict) else {}
    try:
        result = mod.call_handler(capability, args)
    except Exception as exc:  # noqa: BLE001 FAIL-OPEN
        return 200, {
            "ok": False,
            "error_code": "handler_exception",
            "trace_id": trace,
            "meta": {"reason": f"{type(exc).__name__}: {exc}"},
        }

    body = dict(result) if isinstance(result, dict) else {"ok": True, "output": result}
    body["trace_id"] = trace
    return 200, body


# ── HTTP 层 ─────────────────────────────────────────────────────────


class _ExecuteHandler(BaseHTTPRequestHandler):
    server_version = "dsh-execute/1.0"
    protocol_version = "HTTP/1.1"

    def _send_json(
        self,
        status: int,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 (stdlib 命名)
        if self.path.split("?")[0] != "/health":
            self._send_json(
                404, {"ok": False, "error_code": "not_found", "meta": {"path": self.path}}
            )
            return
        self._send_json(
            200,
            {
                "ok": True,
                "service": "dsh-execute",
                "bridge": _load_bridge() is not None,
                "auth": "bearer" if expected_token() else "disabled",
                "capabilities": list_capabilities(),
            },
        )

    def do_POST(self) -> None:  # noqa: N802 (stdlib 命名)
        if self.path.split("?")[0] != "/execute":
            self._send_json(
                404, {"ok": False, "error_code": "not_found", "meta": {"path": self.path}}
            )
            return
        token = expected_token()
        if token and not check_bearer(self.headers.get("Authorization") or "", token):
            self._send_json(
                401,
                {"ok": False, "error_code": "unauthorized", "meta": {"auth": "bearer"}},
                {"WWW-Authenticate": 'Bearer realm="dsh-execute"'},
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(
                400, {"ok": False, "error_code": "bad_request", "meta": {"reason": str(exc)}}
            )
            return
        if not isinstance(body, dict):
            self._send_json(
                400,
                {
                    "ok": False,
                    "error_code": "bad_request",
                    "meta": {"reason": "body must be an object"},
                },
            )
            return
        status, payload = dispatch(
            body.get("capability"), body.get("payload"), body.get("trace_id")
        )
        self._send_json(status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默：日志由调用方观测
        return


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _ExecuteHandler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="DSH /execute HTTP server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    argv = parser.parse_args()
    server = make_server(argv.host, argv.port)
    sys.stderr.write(
        json.dumps(
            {
                "event": "dsh_execute_server_started",
                "host": argv.host,
                "port": argv.port,
                "bridge": _load_bridge() is not None,
                "capabilities": len(list_capabilities()),
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
