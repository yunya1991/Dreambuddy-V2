"""execute_http_server 的 HTTP 出口测试（B1/B3）

覆盖：
1. GET /health 返回 bridge 可用 + capability 清单 + auth 状态
2. POST /execute 未知 capability → not_found 且 trace_id 回显
3. POST /execute orchestrator → shell_degraded / dreamos_archived（B3 原因码）
4. 非法 JSON → 400 bad_request
5. 缺失 capability → 400 bad_request
6. 非 /execute 路径 → 404
7. Bearer 鉴权：配置后缺失/错误 401，正确放行；未配置时开放
8. orchestrator 异步作业：提交 → pending → done，未知 job_id → job_not_found
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import execute_http_server as srv
import pytest


@pytest.fixture(scope="module")
def base_url():
    server = srv.make_server("127.0.0.1", 0)
    host, port = server.server_address[0], server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _request(url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict]:
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    req = urllib.request.Request(
        url,
        data=body,
        headers=merged,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_health_reports_bridge_and_capabilities(base_url):
    status, body = _request(f"{base_url}/health")
    assert status == 200
    assert body["ok"] is True
    assert body["bridge"] is True
    caps = body["capabilities"]
    for name in ("technical", "sentiment", "risk", "c_drive", "synthesizer", "orchestrator"):
        assert name in caps


def test_unknown_capability_returns_not_found_with_trace(base_url):
    status, body = _request(
        f"{base_url}/execute",
        json.dumps({"capability": "no_such_cap", "payload": {}, "trace_id": "t-123"}).encode(),
    )
    assert status == 200
    assert body["ok"] is False
    assert body["error_code"] == "not_found"
    assert body["trace_id"] == "t-123"


def test_orchestrator_reports_dreamos_archived(monkeypatch):
    """B3：dreamos 根缺失时返回独立原因码（直接测分支，避免跑真实 orchestrator 的交易侧逻辑）"""
    bridge = srv._load_bridge()
    assert bridge is not None
    monkeypatch.setattr(bridge, "_resolve_dreamos_root", lambda: None)
    result = bridge._handle_orchestrator_v2({})
    assert result["ok"] is False
    assert result["error_code"] == "shell_degraded"
    assert result["meta"]["reason"] == "dreamos_archived"


def test_bad_json_is_400(base_url):
    status, body = _request(f"{base_url}/execute", b"{not-json")
    assert status == 400
    assert body["error_code"] == "bad_request"


def test_missing_capability_is_400(base_url):
    status, body = _request(f"{base_url}/execute", json.dumps({"payload": {}}).encode())
    assert status == 400
    assert body["error_code"] == "bad_request"


def test_unknown_path_is_404(base_url):
    status, body = _request(f"{base_url}/nope")
    assert status == 404
    assert body["error_code"] == "not_found"


# ── Bearer 鉴权 ───────────────────────────────────────────────────────


def test_health_reports_auth_disabled_without_token(base_url, monkeypatch):
    monkeypatch.delenv(srv.AUTH_ENV, raising=False)
    status, body = _request(f"{base_url}/health")
    assert status == 200
    assert body["auth"] == "disabled"


def test_health_reports_bearer_when_token_configured(base_url, monkeypatch):
    monkeypatch.setenv(srv.AUTH_ENV, "s3cret")
    status, body = _request(f"{base_url}/health")
    assert status == 200
    assert body["auth"] == "bearer"


def test_execute_requires_bearer_when_configured(base_url, monkeypatch):
    monkeypatch.setenv(srv.AUTH_ENV, "s3cret")
    payload = json.dumps({"capability": "technical", "payload": {}}).encode()

    status, body = _request(f"{base_url}/execute", payload)
    assert status == 401
    assert body["error_code"] == "unauthorized"

    status, body = _request(f"{base_url}/execute", payload, {"Authorization": "Bearer wrong"})
    assert status == 401
    assert body["error_code"] == "unauthorized"


def test_execute_accepts_correct_bearer(base_url, monkeypatch):
    monkeypatch.setenv(srv.AUTH_ENV, "s3cret")
    payload = json.dumps({"capability": "no_such_cap", "payload": {}}).encode()

    status, body = _request(f"{base_url}/execute", payload, {"Authorization": "Bearer s3cret"})
    assert status == 200
    # 通过鉴权后才会走到 capability 判定
    assert body["error_code"] == "not_found"


def test_execute_open_when_token_unset(base_url, monkeypatch):
    monkeypatch.delenv(srv.AUTH_ENV, raising=False)
    payload = json.dumps({"capability": "no_such_cap", "payload": {}}).encode()

    status, body = _request(f"{base_url}/execute", payload)
    assert status == 200
    assert body["error_code"] == "not_found"


# ── orchestrator 异步作业 ─────────────────────────────────────────────


def test_orchestrator_async_submit_then_done(monkeypatch):
    bridge = srv._load_bridge()
    assert bridge is not None
    monkeypatch.setattr(
        bridge,
        "_run_orchestrator_cycle",
        lambda node: {"ok": True, "data": {"direction": "LONG"}, "error_code": None, "meta": {}},
    )

    submitted = bridge._handle_orchestrator_v2({"async": True, "symbol": "BTC"})
    assert submitted["ok"] is True
    assert submitted["data"]["status"] == "accepted"
    job_id = submitted["data"]["job_id"]

    deadline = time.time() + 5
    status = None
    while time.time() < deadline:
        status = bridge._handle_orchestrator_status({"job_id": job_id})
        if status["data"]["status"] == "done":
            break
        time.sleep(0.01)

    assert status["data"]["status"] == "done"
    assert status["data"]["output"] == {
        "ok": True,
        "output": {"direction": "LONG"},
        "meta": {},
    }


def test_orchestrator_sync_default_unchanged(monkeypatch):
    bridge = srv._load_bridge()
    monkeypatch.setattr(
        bridge,
        "_run_orchestrator_cycle",
        lambda node: {"ok": True, "data": {"direction": "HOLD"}, "error_code": None, "meta": {}},
    )

    result = bridge._handle_orchestrator_v2({})
    assert result["ok"] is True
    assert result["data"]["direction"] == "HOLD"


def test_orchestrator_status_unknown_job(monkeypatch):
    bridge = srv._load_bridge()
    result = bridge._handle_orchestrator_status({"job_id": "no-such-job"})
    assert result["ok"] is False
    assert result["error_code"] == "job_not_found"

    result = bridge._handle_orchestrator_status({})
    assert result["ok"] is False
    assert result["error_code"] == "bad_request"
