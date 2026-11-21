"""本地指令网关：手机端 Agent 轮询拉作业、回传结果；Token 鉴权。

端点：
    GET  /health                      探活（无需 Token）
    GET  /commands?device_id=&limit=   拉取并认领待执行作业 → {"jobs":[command...]}
    POST /results                      回传结果 → {"ok":true}
    GET  /explore?device_id=           当前录制会话 → {"exploration": {...}|null}
    POST /snapshots                    上传探索快照 → {"ok":true,"seq":n}
    POST /locate                       选择器失效时按意图定位节点 → locator.v1
    POST /vision/locate                无障碍树缺失时用 OCR 块定位 → vision.v1

Token：请求头 X-MRA-Token，或查询参数 token；与状态目录 gateway_token 比对。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import executor
import locator
import security
import vision

# 设备超过该秒数无心跳即视为掉线，未完成作业自动回收
STALE_DEVICE_SECONDS = 90


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
                store.touch_device(device_id, "polling")
                try:
                    store.requeue_stale(device_ttl_seconds=STALE_DEVICE_SECONDS)
                except Exception:  # 回收失败不能阻断派发
                    pass
                jobs = store.claim_pending(device_id, limit=limit)
                commands = []
                for job in jobs:
                    try:
                        command = executor.build_command(job)
                        store.update_job_trace(job["_id"], command["trace_id"])
                        commands.append(command)
                        store.add_event("info", "job_dispatched", job.get("task_id"), {"job_id": job["_id"], "trace_id": command["trace_id"]})
                    except executor.GateDenied as exc:
                        store.set_job_state(job["_id"], "failed", device_id)
                        store.add_event("warn", "dispatch_denied", job.get("task_id"), {"reason": str(exc)})
                self._send(200, {"jobs": commands, "count": len(commands)})
                return
            if parsed.path == "/explore":
                if not self._authorized(query):
                    self._send(401, {"error": "unauthorized"})
                    return
                device_id = (query.get("device_id") or [""])[0]
                if device_id:
                    store.touch_device(device_id, "exploring")
                self._send(
                    200,
                    {"exploration": store.get_active_exploration(device_id or None), "interval_ms": 1500},
                )
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path not in ("/results", "/snapshots", "/locate", "/vision/locate"):
                self._send(404, {"error": "not_found"})
                return
            body = _read_json(self)
            if not self._authorized(query) and not security.token_matches(
                token, str(body.get("token") or "")
            ):
                self._send(401, {"error": "unauthorized"})
                return
            if parsed.path == "/snapshots":
                self._handle_snapshot(body)
                return
            if parsed.path == "/vision/locate":
                self._handle_vision_locate(body)
                return
            if parsed.path == "/locate":
                self._handle_locate(body)
                return
            job_id = body.get("job_id")
            if job_id is None:
                self._send(400, {"error": "job_id_required"})
                return
            device_id = str(body.get("device_id") or "unknown")
            state = str(body.get("state") or "error")
            store.touch_device(device_id, "reporting")
            detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
            # 兼容把 trace_id 放在回执顶层：统一并入 detail，供结构化落库
            if body.get("trace_id") and not detail.get("trace_id"):
                detail["trace_id"] = str(body["trace_id"])
            result = executor.apply_result(store, int(job_id), device_id, state, detail)
            self._send(200, {"ok": True, "result": result})

        def _handle_vision_locate(self, body: dict) -> None:
            intent = str(body.get("intent") or "").strip()
            blocks = body.get("blocks") if isinstance(body.get("blocks"), list) else []
            if not intent:
                self._send(400, {"error": "intent_required"})
                return
            if not blocks:
                self._send(400, {"error": "blocks_required"})
                return
            self._send(200, vision.locate(intent, blocks))

        def _handle_locate(self, body: dict) -> None:
            intent = str(body.get("intent") or "").strip()
            nodes = body.get("nodes") if isinstance(body.get("nodes"), list) else []
            if not intent:
                self._send(400, {"error": "intent_required"})
                return
            if not nodes:
                self._send(400, {"error": "nodes_required"})
                return
            result = locator.locate(intent, nodes, use_model=bool(body.get("use_model", True)))
            self._send(200, result)

        def _handle_snapshot(self, body: dict) -> None:
            exploration_id = body.get("exploration_id")
            if exploration_id is None:
                self._send(400, {"error": "exploration_id_required"})
                return
            exploration = store.get_exploration(int(exploration_id))
            if exploration is None:
                self._send(404, {"error": "exploration_not_found"})
                return
            if exploration["state"] != "recording":
                self._send(409, {"error": "exploration_not_recording"})
                return
            nodes = body.get("nodes") if isinstance(body.get("nodes"), list) else []
            if body.get("device_id"):
                store.touch_device(str(body["device_id"]), "recording")
            saved = store.add_snapshot(
                int(exploration_id),
                package=str(body.get("package") or ""),
                activity=str(body.get("activity") or ""),
                page_text=str(body.get("page_text") or ""),
                screenshot=str(body.get("screenshot") or ""),
                nodes=nodes,
            )
            self._send(200, {"ok": True, "seq": saved["seq"], "duplicate": saved["duplicate"]})

    return Handler


def serve(store, token: str, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(store, token))
    return server


def serve_in_thread(store, token: str, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """测试用：随机端口后台起服务。"""
    server = serve(store, token, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
