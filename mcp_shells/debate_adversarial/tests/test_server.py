"""debate_adversarial MCP shell smoke tests (no real LLM)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells._shared.shell_runtime import build_tool_list, handle_request  # noqa: E402
from mcp_shells.debate_adversarial import server  # noqa: E402


def _payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def _handle(req: dict):
    return handle_request(
        req,
        shell_id=server.SHELL_SOURCE,
        tools=build_tool_list(server.SHELL_SOURCE, server.TOOL_DEFS),
        handlers=server._TOOL_HANDLERS,
    )


def test_tools_list_has_three_tools():
    resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in resp["result"]["tools"]}
    assert names == {"start_debate", "get_debate_result", "debate_health"}


def test_initialize_and_ping():
    init = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["protocolVersion"]
    ping = _handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping["result"] == {}


def test_health_without_deep_check():
    text = server.debate_health({"deep": False})
    payload = json.loads(text)
    assert payload["ok"] is True
    assert payload["source"] == "agent.debate.mcp"
    assert payload["data"]["shell"] == "agent.debate.mcp"


def test_start_debate_and_poll(monkeypatch):
    server._reset_governance()

    def fake_run_job(*args, **kwargs):
        debate_id, mode, topic = args[0], args[1], args[2]
        rounds = args[4]
        server._write_job(
            debate_id,
            {
                "debate_id": debate_id,
                "status": "completed",
                "mode": mode,
                "topic": topic,
                "rounds": rounds,
                "result": {"topic": topic, "verdict": {"winner": "bear"}},
            },
        )

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    start = json.loads(server.start_debate({"topic": "测试", "rounds": 1}))
    assert start["ok"] is True
    debate_id = start["data"]["debate_id"]

    job = None
    for _ in range(50):
        job = json.loads(server.get_debate_result({"debate_id": debate_id}))
        if job["data"].get("status") == "completed":
            break
        time.sleep(0.01)
    assert job["data"]["status"] == "completed"
    assert job["data"]["result"]["verdict"]["winner"] == "bear"


def test_missing_debate_returns_not_found():
    job = json.loads(server.get_debate_result({"debate_id": "does-not-exist"}))
    assert job["ok"] is False
    assert job["error_code"] == "not_found"


def test_topic_required():
    payload = json.loads(server.start_debate({}))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_invalid_profile_returns_invalid():
    payload = json.loads(server.start_debate({"topic": "t", "profile": "nope"}))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_technical_profile_rejected_for_fast_mode():
    payload = json.loads(
        server.start_debate(
            {
                "topic": "t",
                "mode": "fast",
                "profile": "technical",
            }
        )
    )
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_profile_passed_to_job(monkeypatch):
    server._reset_governance()
    captured = {}

    def fake_run_job(*args, **kwargs):
        captured["args"] = args
        debate_id = args[0]
        server._write_job(
            debate_id,
            {
                "debate_id": debate_id,
                "status": "completed",
            },
        )

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    server.start_debate({"topic": "t", "mode": "fast", "profile": "signal"})
    assert captured["args"][-1] == "signal"


def test_fast_and_deep_modes_start_jobs(monkeypatch):
    server._reset_governance()

    def fake_run_job(*args, **kwargs):
        debate_id, mode, topic = args[0], args[1], args[2]
        server._write_job(
            debate_id,
            {
                "debate_id": debate_id,
                "status": "completed",
                "mode": mode,
                "topic": topic,
                "result": {"topic": topic},
            },
        )

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    for mode in ("fast", "deep"):
        payload = json.loads(server.start_debate({"topic": "测试", "mode": mode}))
        assert payload["ok"] is True
        assert payload["data"]["status"] == "running"


# ── Phase 4：model_pair / plancards 可选参数（向后兼容） ──────────


def test_model_pair_same_model_rejected():
    """铁律⑤：壳层强制拒绝同模型开题。"""
    payload = json.loads(
        server.start_debate({"topic": "t", "model_pair": ["qwen-plus", "qwen-plus"]})
    )
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"
    assert "铁律⑤" in payload["meta"]["reason"]


def test_model_pair_distinct_models_accepted(monkeypatch):
    server._reset_governance()

    def fake_run_job(*args, **kwargs):
        debate_id = args[0]
        server._write_job(debate_id, {"debate_id": debate_id, "status": "completed"})

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    payload = json.loads(
        server.start_debate({"topic": "t", "model_pair": ["qwen-plus", "claude-sonnet-4"]})
    )
    assert payload["ok"] is True


def test_model_pair_wrong_shape_rejected():
    payload = json.loads(server.start_debate({"topic": "t", "model_pair": ["only-one"]}))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_plancards_prepended_to_background(monkeypatch):
    server._reset_governance()
    captured = {}

    def fake_run_job(*args, **kwargs):
        captured["background"] = args[3]
        debate_id = args[0]
        server._write_job(debate_id, {"debate_id": debate_id, "status": "completed"})

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    cards = [{"id": "pc-a", "intent": "A 方案"}, {"id": "pc-b", "intent": "B 方案"}]
    payload = json.loads(
        server.start_debate({"topic": "t", "background": "原始背景", "plancards": cards})
    )
    assert payload["ok"] is True
    assert captured["background"].startswith("【PlanCard 交接】")
    assert "pc-a" in captured["background"] and "pc-b" in captured["background"]
    assert captured["background"].endswith("原始背景")


def test_plancards_wrong_shape_rejected():
    payload = json.loads(server.start_debate({"topic": "t", "plancards": [{"id": "pc-a"}]}))
    assert payload["ok"] is False
    assert payload["error_code"] == "invalid"


def test_optional_params_default_do_not_break(monkeypatch):
    """不传 model_pair / plancards 时行为与旧版一致。"""
    server._reset_governance()
    captured = {}

    def fake_run_job(*args, **kwargs):
        captured["background"] = args[3]
        debate_id = args[0]
        server._write_job(debate_id, {"debate_id": debate_id, "status": "completed"})

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    payload = json.loads(server.start_debate({"topic": "t", "background": "b"}))
    assert payload["ok"] is True
    assert captured["background"] == "b"


# ── M10 频控 / 并发 / TTL 测试 ─────────────────────────────────


def test_rate_limit_blocks_third_call(monkeypatch):
    """≤2 次/分钟：第 3 次 start_debate 返回 timeout。"""
    server._reset_governance()

    def fake_run_job(*args, **kwargs):
        debate_id = args[0]
        server._write_job(debate_id, {"debate_id": debate_id, "status": "completed"})

    monkeypatch.setattr(server, "_run_job", fake_run_job)
    # 前两次成功
    for _ in range(2):
        payload = json.loads(server.start_debate({"topic": "t"}))
        assert payload["ok"] is True
    # 第三次被限流
    payload = json.loads(server.start_debate({"topic": "t"}))
    assert payload["ok"] is False
    assert payload["error_code"] == "timeout"
    assert "rate_limited" in payload["meta"]["reason"]


def test_concurrency_limit_blocks_third_running(monkeypatch):
    """并发 ≤2：第 3 个同时运行的 job 返回 timeout。"""
    server._reset_governance()
    # 直接占用 2 个并发槽
    assert server._concurrent_acquire() is True
    assert server._concurrent_acquire() is True
    # 第 3 个被拒
    assert server._concurrent_acquire() is False
    server._concurrent_release()
    server._concurrent_release()
    assert server._concurrent_count == 0


def test_expired_job_returns_not_found(monkeypatch):
    """TTL 过期的 job 返回 not_found 并删除文件。"""
    server._reset_governance()
    debate_id = "expired-test-001"
    from datetime import datetime, timedelta

    old_created = (datetime.now() - timedelta(days=2)).isoformat()
    server._write_job(
        debate_id,
        {
            "debate_id": debate_id,
            "status": "completed",
            "created_at": old_created,
            "result": {"topic": "t"},
        },
    )
    payload = json.loads(server.get_debate_result({"debate_id": debate_id}))
    assert payload["ok"] is False
    assert payload["error_code"] == "not_found"
    assert payload["meta"].get("reason") == "expired"
    # 文件已删除
    assert not server._job_path(debate_id).exists()


def test_result_truncation_when_over_limit(monkeypatch):
    """单 job 结果 > _MAX_RESULT_BYTES 时截断并标记 degraded。"""
    server._reset_governance()
    monkeypatch.setattr(server, "_MAX_RESULT_BYTES", 200)
    big_result = {"data": "x" * 5000, "schema_version": "debate-result-v1"}
    payload = {"status": "completed", "result": big_result}
    slim, truncated = server._truncate_result(payload)
    assert truncated is True
    assert slim.get("degraded") is True
    assert slim["result"].get("truncated") is True
    assert len(json.dumps(slim, ensure_ascii=False).encode("utf-8")) <= 200


def test_sweep_jobs_removes_expired(monkeypatch, tmp_path):
    """_sweep_jobs 删除过期文件并裁剪到 _MAX_JOBS。"""
    import time as _time

    monkeypatch.setattr(server, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(server, "_MAX_JOBS", 2)
    # 创建 3 个文件，其中 1 个过期
    (tmp_path / "old.json").write_text("{}", encoding="utf-8")
    old_ts = _time.time() - server._JOB_TTL_SEC - 10
    import os

    os.utime(tmp_path / "old.json", (old_ts, old_ts))
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    server._sweep_jobs()
    remaining = sorted(p.name for p in tmp_path.glob("*.json"))
    # 过期的 old.json 被删，剩下 ≤2 个
    assert "old.json" not in remaining
    assert len(remaining) <= 2


def test_health_exposes_m10_limits():
    """health 返回 M10 频控/TTL 配置。"""
    text = server.debate_health({"deep": False})
    payload = json.loads(text)
    data = payload["data"]
    assert data["m10_rate_limit_per_min"] == server._RATE_LIMIT_PER_MIN
    assert data["m10_max_concurrent"] == server._MAX_CONCURRENT
    assert data["m10_job_ttl_sec"] == server._JOB_TTL_SEC
    assert data["m10_max_jobs"] == server._MAX_JOBS
    assert data["m10_max_result_bytes"] == server._MAX_RESULT_BYTES
