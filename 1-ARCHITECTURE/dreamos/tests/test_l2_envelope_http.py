"""P0-1：DreamOS HTTP 出口附加 L2Envelope（增量、不改既有键）。

覆盖:
  - 静态端点（health/budget）返回 meta/trace/quality，tokens=0 且 model=none
  - 推理端点沿用 run 结果快照：tokens_used 与 budget_remaining 同源
  - 失败出口 ok=false + error_code，且 HTTP 状态码不变
  - 既有响应键全部保留（兼容 3.1 前端）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.apps.api_server import create_app  # noqa: E402
from dreamos.core.capability import l2_http_envelope as l2env  # noqa: E402

RUN_RESULT = {
    "cycle_id": "cycle-test-001",
    "intent": {"type": "analyze", "confidence": 0.8},
    "plan": {"chain": "A", "nodes": ["A1"]},
    "execution": {"nodes_executed": 1, "total_tokens": 120},
    "action": "HOLD",
    "confidence": 0.55,
    "tokens_used": 120,
    "latency_ms": 33.5,
    "budget_status": {"per_day": {"remaining": 880}, "per_cycle": {"remaining": 6000}},
}


class _Budget:
    def status(self):
        return {"mode": "standard", "per_day": {"remaining": 880}}

    def reset(self):
        return None


class _Registry:
    def list_nodes(self):
        return []


class _Agent:
    def __init__(self, fail: bool = False):
        self.budget = _Budget()
        self.registry = _Registry()
        self._fail = fail

    def run(self, **_kwargs):
        if self._fail:
            raise RuntimeError("节点爆炸")
        return dict(RUN_RESULT)

    def chat(self, **_kwargs):
        return self.run()

    def status(self):
        return {"status": "idle"}

    def history(self, limit=10):
        return []


@pytest.fixture()
def client():
    l2env._MODULE = None  # 每次重新按路径加载 56 契约实现，确保测到真实模块
    app = create_app(agent=_Agent())
    return app.test_client()


def _assert_parts(meta, trace, quality):
    module = l2env._l2()
    assert module is not None, "56 l2_envelope 运行时不可用"
    assert module.validate_envelope_parts({"meta": meta, "trace": trace, "quality": quality}) == []


def test_static_endpoint_carries_envelope(client):
    body = client.get("/api/v1/health").get_json()
    assert body["status"] == "ok"  # 既有键保留
    assert body["ok"] is True
    assert body["meta"]["layer"] == "L2"
    assert body["meta"]["model"] == "none"
    assert body["meta"]["tokens_used"] == 0
    assert body["meta"]["budget_remaining"] == 880
    assert body["trace"]["route"] == "L1_DIRECT"
    _assert_parts(body["meta"], body["trace"], body["quality"])


def test_run_endpoint_uses_single_result_snapshot(client, monkeypatch):
    monkeypatch.setattr(l2env, "resolve_model_name", lambda: "qwen-max")
    body = client.post("/api/v1/run", json={"user_input": "分析 BTC"}).get_json()
    assert body["cycle_id"] == "cycle-test-001"  # 既有键保留
    assert body["action"] == "HOLD"
    assert body["meta"]["model"] == "qwen-max"
    assert body["meta"]["tokens_used"] == 120
    assert body["meta"]["budget_remaining"] == 880
    assert body["trace"]["route"] == "L2_HANDOFF"
    assert body["trace"]["sagc"] == {"S": "done", "A": "done", "C": "done", "G": "done"}
    _assert_parts(body["meta"], body["trace"], body["quality"])


def test_no_model_reports_zero_tokens(client, monkeypatch):
    monkeypatch.setattr(l2env, "resolve_model_name", lambda: "none")
    body = client.post("/api/v1/chat", json={"message": "BTC 怎么看"}).get_json()
    assert body["meta"]["model"] == "none"
    assert body["meta"]["tokens_used"] == 0


def test_error_path_is_ok_false_with_code(client):
    app = create_app(agent=_Agent(fail=True))
    resp = app.test_client().post("/api/v1/run", json={"user_input": "分析 BTC"})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error_code"] == "unavailable"
    assert "执行失败" in body["error"]
    _assert_parts(body["meta"], body["trace"], body["quality"])


def test_validation_error_keeps_http_400(client):
    resp = client.post("/api/v1/run", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error_code"] == "invalid"


def test_unknown_route_marks_not_found(client):
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error_code"] == "not_found"
