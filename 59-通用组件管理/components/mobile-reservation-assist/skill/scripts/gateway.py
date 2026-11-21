"""本地指令网关：手机端 Agent 轮询拉作业、回传结果；Token 鉴权。

端点：
    GET  /health                      探活（无需 Token）
    GET  /commands?device_id=&limit=   拉取并认领待执行作业 → {"jobs":[command...]}
    POST /results                      回传结果 → {"ok":true}

Token：请求头 X-MRA-Token，或查询参数 token；与状态目录 gateway_token 比对。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import executor
import security


def _extract_token(handler: BaseHTTPRequestHandler, query: dict) -> str:
    header = handler.headers.get("X-MRA-Token", "")
    if header:
        return header
    return (query.get("token") or [""])[0]


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def make_handler(store, token: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # 支持 keep-alive，避免 Auto.js(OkHttp) 连接被 reset

        def log_message(self, fmt, *args):  # 静默默认访问日志
            return

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(security.redact_obj(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, query: dict) -> bool:
            return security.token_matches(token, _extract_token(self, query))

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/health":
                self._send(200, {"ok": True})
                return
            if parsed.path == "/commands":
                if not self._authorized(query):
                    self._send(401, {"error": "unauthorized"})
                    return
                if store.get_meta("paused", "0") == "1":
                    self._send(200, {"jobs": [], "paused": True})
                    return
                device_id = (query.get("device_id") or ["unknown"])[0]
                try:
                    limit = int((query.get("limit") or ["10"])[0])
                except ValueError:
                    limit = 10
                jobs = store.claim_pending(device_id, limit=limit)
                commands = []
                for job in jobs:
                    try:
                        commands.append(executor.build_command(job))
                        store.add_event(
                            "info", "job_dispatched", job.get("task_id"), {"job_id": job["_id"]}
                        )
                    except executor.GateDenied as exc:
                        store.set_job_state(job["_id"], "failed", device_id)
                        store.add_event(
                            "warn", "dispatch_denied", job.get("task_id"), {"reason": str(exc)}
                        )
                self._send(200, {"jobs": commands, "count": len(commands)})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/results":
                self._send(404, {"error": "not_found"})
                return
            body = _read_json(self)
            if not self._authorized(query) and not security.token_matches(
                token, str(body.get("token") or "")
            ):
                self._send(401, {"error": "unauthorized"})
                return
            job_id = body.get("job_id")
            if job_id is None:
                self._send(400, {"error": "job_id_required"})
                return
            device_id = str(body.get("device_id") or "unknown")
            state = str(body.get("state") or "error")
            detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
            result = executor.apply_result(store, int(job_id), device_id, state, detail)
            self._send(200, {"ok": True, "result": result})

    return Handler


def serve(store, token: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(store, token))
    return server


def serve_in_thread(
    store, token: str, host: str = "127.0.0.1", port: int = 0
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """测试用：随机端口后台起服务。"""
    server = serve(store, token, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
