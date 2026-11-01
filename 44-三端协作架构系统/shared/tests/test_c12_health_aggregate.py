"""C12 调度/能力健康聚合契约测试（进 G0-4 阻断 job）。

SPEC-L0 §6 C12：`job_runs` 与五能力 health 聚合进 cognitive `health`
（跑没跑/成功率/最老滞留/降级原因分布）；探测以 `capabilities.yaml`
的 `health_cmd` 为准，不依赖 systemd/launchd 内部状态；两端同口径。
"""

import json
import os
import re
import subprocess
import sys

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

REGISTRY_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "job_registry.yaml")
CAPABILITIES_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "capabilities.yaml")

from dreambuddy_l0.fakes import FakeStore  # noqa: E402
from dreambuddy_l0.scheduling.health import collect_l0_health  # noqa: E402
from dreambuddy_l0.scheduling.registry import load_registry  # noqa: E402

FIVE_CAPS = {"l0.cognition", "l0.data", "l0.search", "l0.store", "l0.rea"}


# ── 契约源头：capabilities.yaml 五能力必带 health_cmd ─────────────────────
def test_capabilities_yaml_declares_health_cmd_for_all_five():
    with open(CAPABILITIES_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    caps = {c["capability_id"]: c for c in doc["capabilities"]}
    assert set(caps) == FIVE_CAPS
    for cid, cap in caps.items():
        assert cap.get("health_cmd"), f"{cid} 缺 health_cmd（C12 探测唯一依据）"


# ── 测试夹具 ───────────────────────────────────────────────────────────────
def _registry():
    return load_registry(REGISTRY_PATH)


def _run(tk, window, state, started, finished=0.0, error=""):
    return {
        "id": f"{tk}@{window}",
        "run_id": f"{tk}@{window}",
        "task_key": tk,
        "logical_window": window,
        "state": state,
        "attempts": 1,
        "started_at": float(started),
        "heartbeat_at": float(started),
        "finished_at": float(finished),
        "error": error,
        "detail": {},
    }


def _store_with(rows):
    store = FakeStore()
    for row in rows:
        store.write("job_runs", data=row, idempotency_key=row["run_id"])
    return store


class FakeRunner:
    """health_cmd 执行器 fake：按队列返回 (exit_code, stdout) 或抛超时。"""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, cmd, *, cwd, timeout):
        self.calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout})
        outcome = self.results.pop(0) if self.results else "ok"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
        if outcome == "ok":
            return 0, "ok"
        if outcome == "missing":
            return 0, "missing"
        return 1, "boom"


def _caps_file(tmp_path, cmds):
    doc = {
        "capabilities": [
            {
                "capability_id": cid,
                "port": "store",
                "status": "available",
                "degraded_reason": "",
                "health_cmd": cmd,
            }
            for cid, cmd in cmds
        ]
    }
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


# ── 调度分项：跑没跑 / 成功率 / 最老滞留 / 状态分布 ─────────────────────────
def test_health_aggregates_job_runs_per_task():
    now = 1000.0
    store = _store_with(
        [
            _run("dc.collect.cloud", 1, "succeeded", 100, 102),
            _run("dc.collect.cloud", 2, "succeeded", 400, 402),
            _run("dc.collect.cloud", 3, "failed", 700, 705, error="boom"),
            _run("dc.collect.cloud", 4, "pending", 900),  # 开放态滞留 100s
        ]
    )
    out = collect_l0_health(
        store=store,
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=now,
        runner=FakeRunner([]),
    )
    task = out["scheduling"]["tasks"]["dc.collect.cloud"]
    assert task["has_run"] is True
    assert task["total"] == 4
    assert task["state_counts"]["succeeded"] == 2
    assert task["state_counts"]["failed"] == 1
    assert task["state_counts"]["pending"] == 1
    # 成功率只按终态计（pending 不进分母）
    assert abs(task["success_rate"] - 2 / 3) < 1e-9
    # 最老滞留 = now - 最老开放态 started_at
    assert 99.0 <= task["oldest_open_age_sec"] <= 101.0
    assert task["last_finished_at"] == 705.0


def test_health_success_rate_none_without_terminal_runs():
    now = 1000.0
    store = _store_with([_run("dc.collect.cloud", 4, "running", 900)])
    out = collect_l0_health(
        store=store,
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=now,
        runner=FakeRunner([]),
    )
    task = out["scheduling"]["tasks"]["dc.collect.cloud"]
    assert task["success_rate"] is None
    assert 99.0 <= task["oldest_open_age_sec"] <= 101.0


def test_health_oldest_open_age_none_when_no_open_runs():
    now = 1000.0
    store = _store_with([_run("dc.collect.cloud", 1, "succeeded", 100, 102)])
    out = collect_l0_health(
        store=store,
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=now,
        runner=FakeRunner([]),
    )
    assert out["scheduling"]["tasks"]["dc.collect.cloud"]["oldest_open_age_sec"] is None


def test_health_missed_run_streak_alerts():
    now = 100000.0
    store = _store_with(
        [
            _run("dc.collect.cloud", 1, "succeeded", 300, 302),
            _run("dc.collect.cloud", 2, "missed_run", 600),
            _run("dc.collect.cloud", 3, "missed_run", 900),
            _run("dc.collect.cloud", 4, "missed_run", 1200),
        ]
    )
    out = collect_l0_health(
        store=store,
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=now,
        runner=FakeRunner([]),
    )
    task = out["scheduling"]["tasks"]["dc.collect.cloud"]
    assert task["missed_streak"] == 3
    assert task["alert"] is True
    assert out["degraded"] is True
    assert out["error_code"] == "scheduling_missed_run"
    assert out["degraded_reasons"]["job:missed_run"] == 3


# ── 能力分项：health_cmd 探活（ok/missing/error/timeout）────────────────────
def test_health_capabilities_probe_statuses(tmp_path):
    caps = _caps_file(
        tmp_path,
        [
            ("cap.ok", "cmd-ok"),
            ("cap.missing", "cmd-missing"),
            ("cap.error", "cmd-error"),
            ("cap.timeout", "cmd-timeout"),
        ],
    )
    runner = FakeRunner(["ok", "missing", "error", "timeout"])
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=caps,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=runner,
    )
    health = {cid: c["health"] for cid, c in out["capabilities"].items()}
    assert health == {
        "cap.ok": "ok",
        "cap.missing": "missing",
        "cap.error": "error",
        "cap.timeout": "timeout",
    }
    assert len(runner.calls) == 4
    assert out["degraded"] is True
    assert out["error_code"] == "capability_unhealthy"
    assert out["degraded_reasons"]["capability:cap.missing:missing"] == 1
    assert out["degraded_reasons"]["capability:cap.timeout:timeout"] == 1


def test_health_probes_all_five_capabilities_from_yaml():
    runner = FakeRunner([])
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=runner,
    )
    assert set(out["capabilities"]) == FIVE_CAPS
    # 探测命令必须逐字来自 capabilities.yaml（唯一事实源），不得硬编码
    with open(CAPABILITIES_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    declared = {c["health_cmd"] for c in doc["capabilities"]}
    assert {c["cmd"] for c in runner.calls} == declared


def test_health_cmd_executed_from_repo_root(tmp_path):
    caps = _caps_file(tmp_path, [("cap.one", "python3 -c \"print('ok')\"")])
    runner = FakeRunner(["ok"])
    collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=caps,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=runner,
    )
    # 两端同口径：health_cmd 一律以仓库根为 cwd（相对路径解析一致）
    assert runner.calls[0]["cwd"] == REPO_ROOT


def test_health_all_ok_when_store_empty_and_caps_healthy(tmp_path):
    caps = _caps_file(tmp_path, [("cap.one", "cmd")])
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=caps,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=FakeRunner(["ok"]),
    )
    assert out["degraded"] is False
    assert out["ok"] is True
    assert out["error_code"] == ""


# ── FAIL-OPEN：单项故障不拖垮整体 ──────────────────────────────────────────
def test_health_store_unavailable_fail_open():
    class BoomStore(FakeStore):
        def query(self, *a, **kw):
            raise RuntimeError("store down")

    out = collect_l0_health(
        store=BoomStore(),
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=FakeRunner([]),
    )
    assert out["degraded"] is True
    assert out["error_code"] == "store_unavailable"
    # 能力探测不受 store 故障影响，仍完整返回
    assert set(out["capabilities"]) == FIVE_CAPS


def test_health_missing_capabilities_file_fail_open(tmp_path):
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=str(tmp_path / "nope.yaml"),
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=FakeRunner([]),
    )
    assert out["degraded"] is True
    assert out["capabilities"] == {}
    # 调度分项不受能力声明缺失影响
    assert "dc.collect.cloud" in out["scheduling"]["tasks"]


# ── host 过滤：云端聚合不得统计 local 任务 ─────────────────────────────────
def test_health_host_filter_cloud_excludes_local():
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="cloud",
        now=1000.0,
        runner=FakeRunner([]),
    )
    keys = set(out["scheduling"]["tasks"])
    assert "dc.collect.cloud" in keys
    assert "dc.collect.local" not in keys


def test_health_host_filter_local_only_local():
    out = collect_l0_health(
        store=FakeStore(),
        registry=_registry(),
        capabilities_path=CAPABILITIES_PATH,
        repo_root=REPO_ROOT,
        host="local",
        now=1000.0,
        runner=FakeRunner([]),
    )
    keys = set(out["scheduling"]["tasks"])
    assert keys == {"dc.collect.local"}


# ── 接入 cognitive MCP health（两端同口径出口）─────────────────────────────
def _import_mcp_server():
    server_dir = os.path.join(REPO_ROOT, "4-MEMORY", "9-工具与接口")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    import cognitive_mcp_server

    return cognitive_mcp_server


class _StubCLE:
    def healthcheck(self):
        return {
            "memory": {"status": "healthy"},
            "distill": {"status": "disabled"},
            "consolidation": {"status": "healthy"},
        }


def test_mcp_health_includes_l0_section(monkeypatch, tmp_path):
    srv = _import_mcp_server()
    monkeypatch.setattr(srv, "_get_cle", lambda: _StubCLE())
    monkeypatch.setenv("JOB_RUNS_PATH", str(tmp_path / "job_runs.jsonl"))
    out = json.loads(srv._handle_health({}))
    # 基础健康载荷不丢（零回归）
    assert out["memory"]["status"] == "healthy"
    assert "distill" in out and "consolidation" in out
    # l0 分项：五能力 + 调度
    l0 = out["l0"]
    assert set(l0["capabilities"]) == FIVE_CAPS
    for cap in l0["capabilities"].values():
        assert cap["health"] in ("ok", "missing", "error", "timeout")
    assert "tasks" in l0["scheduling"]
    # 自洽：degraded 与 error_code 一致
    assert l0["degraded"] == (not l0["ok"])
    assert (l0["error_code"] == "") == (not l0["degraded"])


def test_mcp_health_l0_fail_open(monkeypatch):
    srv = _import_mcp_server()
    monkeypatch.setattr(srv, "_get_cle", lambda: _StubCLE())

    import dreambuddy_l0.scheduling.health as health_mod

    def _boom(**kw):
        raise RuntimeError("l0 boom")

    monkeypatch.setattr(health_mod, "collect_l0_health", _boom)
    out = json.loads(srv._handle_health({}))
    # L0 聚合失败不得拖垮认知基础健康
    assert out["memory"]["status"] == "healthy"
    assert out["l0"]["degraded"] is True
    assert out["l0"]["ok"] is False
    assert out["l0"]["error_code"]


# ── 落库纪律：只经 port + subprocess 探测，不直连 DB ───────────────────────
def test_health_module_does_not_import_db_drivers():
    banned = re.compile(r"\b(sqlite3|psycopg2?|asyncpg|pymysql|mysql\.connector)\b")
    path = os.path.join(REPO_ROOT, "dreambuddy_l0", "scheduling", "health.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert not banned.search(text), "health.py 直连数据库（违反 L0-P 约束）"
    # 不依赖 systemd/launchd 内部状态（SPEC C12 硬约束）
    assert "systemctl" not in text and "launchctl" not in text
