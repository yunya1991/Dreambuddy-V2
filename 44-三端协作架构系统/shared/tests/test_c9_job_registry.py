"""C9 任务注册表 + job_runs 契约测试（进 G0-4 阻断 job）。

覆盖：声明式任务清单可解析/可查询、UTC 逻辑窗口、迟到容忍 5min、
跨窗拆 run、幂等 run key、missed_run + 连续 3 窗告警、90 天保留、
只经 Store/Event port 落库（不直连 PG/SQLite）。
"""

import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

REGISTRY_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "job_registry.yaml")

REQUIRED_FIELDS = {
    "task_key",
    "carrier",
    "unit",
    "schedule",
    "window_sec",
    "timeout_sec",
    "max_concurrency",
    "retry",
    "enabled",
    "fallback",
}
# SPEC-L0 C9：先纳管云端三条真实链路 + 本地 datacenter/dc-scheduler
MANAGED_TASK_KEYS = {
    "dc.collect.cloud",
    "dc.backfill.cloud",
    "index.reconcile.cloud",
    "dc.collect.local",
}
CARRIER_ENUM = {"systemd", "systemd-timer", "launchd", "crontab"}


def _load():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 注册表 ────────────────────────────────────────────────────────────────
def test_registry_file_exists_and_parses():
    assert os.path.exists(REGISTRY_PATH), "job_registry.yaml 未落盘"
    doc = _load()
    assert doc["schema_version"] == "1.0"
    assert isinstance(doc["tasks"], list) and doc["tasks"]
    assert doc["late_tolerance_sec"] == 300
    assert doc["retention_days"] == 90


def test_every_task_has_required_schema_fields():
    for t in _load()["tasks"]:
        missing = REQUIRED_FIELDS - set(t)
        assert not missing, f"{t.get('task_key')} 缺字段 {missing}"
        assert t["carrier"] in CARRIER_ENUM, f"{t['task_key']} carrier 非法"
        assert int(t["window_sec"]) > 0 and int(t["window_sec"]) <= 86400
        assert int(t["max_concurrency"]) >= 1 and int(t["retry"]) >= 0
        assert isinstance(t["enabled"], bool)


def test_managed_links_declared():
    keys = {t["task_key"] for t in _load()["tasks"]}
    missing = MANAGED_TASK_KEYS - keys
    assert not missing, f"未纳管链路: {missing}"
    # 41 索引对账必须从裸 crontab 迁到 systemd timer
    rec = [t for t in _load()["tasks"] if t["task_key"] == "index.reconcile.cloud"][0]
    assert rec["carrier"] == "systemd-timer"
    assert rec.get("legacy_carrier") == "crontab"


from dreambuddy_l0.scheduling.registry import TaskRegistry, TaskSpec, load_registry  # noqa: E402


def test_registry_query_and_filter():
    reg = load_registry(REGISTRY_PATH)
    assert isinstance(reg, TaskRegistry)
    spec = reg.get("dc.collect.cloud")
    assert isinstance(spec, TaskSpec) and spec.window_sec == 300
    assert reg.get("no.such.task") is None
    assert all(s.enabled for s in reg.list(enabled_only=True))
    assert len(reg.list()) >= len(reg.list(enabled_only=True))


def test_registry_rejects_duplicate_key_and_bad_carrier():
    good = dict(_load()["tasks"][0])
    dup = [good, dict(good)]
    try:
        TaskRegistry.from_dicts(dup)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("重复 task_key 未被拒绝")

    bad = dict(good)
    bad["carrier"] = "k8s-cronjob"
    try:
        TaskRegistry.from_dicts([bad])
    except ValueError as exc:
        assert "carrier" in str(exc)
    else:
        raise AssertionError("非法 carrier 未被拒绝")


# ── 窗口 math ────────────────────────────────────────────────────────────
from dreambuddy_l0.scheduling.windows import (  # noqa: E402
    is_window_closed,
    split_segments,
    window_index,
    window_start,
)


def test_window_utc_alignment():
    assert window_index(0, 3600) == 0
    assert window_index(3660, 3600) == 1
    assert window_start(3, 3600) == 10800
    # UTC 整点对齐（跨日边界）
    assert window_start(window_index(86400 + 5, 3600), 3600) == 86400
    assert window_start(window_index(86400 * 2 - 5, 3600), 3600) == 86400 * 2 - 3600


def test_split_run_across_windows():
    segs = split_segments(3600 * 3 + 30, 3600 * 5 + 10, 3600)
    assert [s[0] for s in segs] == [3, 4, 5]
    assert segs[0][1] == 3600 * 3 + 30
    assert segs[-1][2] == 3600 * 5 + 10
    # 相邻切片连续无空洞
    for prev, nxt in zip(segs, segs[1:], strict=False):
        assert nxt[1] == prev[2]


def test_late_tolerance_5min_grace():
    start = 3600 * 2
    # 窗口 2 结束于 start+3600，再加 5min 容忍才判 closed
    assert not is_window_closed(start + 3600, start, 3600, 300)
    assert not is_window_closed(start + 3600 + 299, start, 3600, 300)
    assert is_window_closed(start + 3600 + 300, start, 3600, 300)


# ── job_runs ─────────────────────────────────────────────────────────────
from dreambuddy_l0.fakes import FakeEvent, FakeStore  # noqa: E402
from dreambuddy_l0.scheduling.job_runs import JobRunRecorder  # noqa: E402


def test_run_id_is_idempotent_across_restart():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    r1 = rec.begin("dc.collect.cloud", window=42, now=42 * 300 + 1)
    r2 = rec.begin("dc.collect.cloud", window=42, now=42 * 300 + 2)
    assert r1["run_id"] == r2["run_id"] == "dc.collect.cloud@42"
    rows = store.query("job_runs", filters={"run_id": r1["run_id"]})["rows"]
    assert len(rows) == 1


def test_run_state_machine_and_heartbeat():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    run = rec.begin("dc.backfill.cloud", window=7, now=7 * 3600 + 901)
    assert run["state"] == "running" and run["attempts"] == 1
    rec.heartbeat(run["run_id"], now=7 * 3600 + 950)
    done = rec.finish(run["run_id"], now=7 * 3600 + 999, state="succeeded")
    assert done["state"] == "succeeded"
    assert done["heartbeat_at"] >= 7 * 3600 + 950
    assert done["finished_at"] == 7 * 3600 + 999


def test_cross_window_run_split_into_multiple_rows():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    rows = rec.record_run("dc.backfill.cloud", started_ts=3600 * 3 + 30, finished_ts=3600 * 5 + 10)
    assert [r["run_id"] for r in rows] == [
        "dc.backfill.cloud@3",
        "dc.backfill.cloud@4",
        "dc.backfill.cloud@5",
    ]
    assert all(r["state"] == "succeeded" for r in rows)


def test_backfill_decoration_with_duration_marks_succeeded():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    r = rec.record_run("dc.collect.cloud", started_ts=100, finished_ts=101, error="")
    assert r[0]["state"] == "succeeded"
    r2 = rec.record_run("dc.collect.cloud", started_ts=400, finished_ts=401, error="boom")
    assert r2[0]["state"] == "failed" and r2[0]["error"] == "boom"


def test_missed_run_and_three_window_alert():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    # 窗口 100 有 run，101/102/103 连续缺失（now 已过窗口 103 的 5min 容忍）
    rec.record_run("dc.collect.cloud", started_ts=100 * 300 + 1, finished_ts=100 * 300 + 2)
    # now 已过窗口 103 的「结束 + 5min 容忍」，故 101/102/103 三窗判缺失
    now_ts = (104 * 300) + 300 + 1
    result = rec.audit(now_ts=now_ts)
    missing_windows = sorted(w for w in result["missed"]["dc.collect.cloud"])
    assert missing_windows == [101, 102, 103]
    events = event.consume(event_type="scheduling.missing_run")["events"]
    dc_events = [e for e in events if e["payload"].get("task_key") == "dc.collect.cloud"]
    assert dc_events, "dc.collect.cloud 连续 3 窗缺失未告警"
    payload = dc_events[-1]["payload"]
    assert payload["streak"] >= 3
    # missed_run 自身也落 run 记录，且重复 audit 不重复写入
    mv = {"task_key": "dc.collect.cloud", "state": "missed_run"}
    assert len(store.query("job_runs", filters=mv)["rows"]) == 3
    rec.audit(now_ts=now_ts)
    assert len(store.query("job_runs", filters=mv)["rows"]) == 3


def test_audit_scoped_by_host_ignores_other_host_tasks():
    """云端审计只能判定本机任务，否则 local 任务会被误判为连续缺失。"""
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    now_ts = (104 * 300) + 300 + 1
    r = rec.audit(now_ts=now_ts, host="cloud")
    assert "dc.collect.cloud" in r["missed"]
    assert "dc.collect.local" not in r["missed"]
    mv = {"task_key": "dc.collect.local", "state": "missed_run"}
    assert store.query("job_runs", filters=mv)["rows"] == []
    local_events = [
        e
        for e in event.consume(event_type="scheduling.missing_run")["events"]
        if e["payload"].get("task_key") == "dc.collect.local"
    ]
    assert local_events == []


def test_audit_fail_open_when_store_unavailable():
    class BoomStore(FakeStore):
        def query(self, *a, **kw):
            raise RuntimeError("store down")

    rec = JobRunRecorder(
        store=BoomStore(), event=FakeEvent(), registry=load_registry(REGISTRY_PATH)
    )
    r = rec.audit(now_ts=10_000_000)
    assert r["degraded"] is True and r["error_code"]


def test_retention_90_days():
    store, event = FakeStore(), FakeEvent()
    rec = JobRunRecorder(store=store, event=event, registry=load_registry(REGISTRY_PATH))
    now = 1_700_000_000
    old = now - 91 * 86400
    rec.record_run("dc.collect.cloud", started_ts=old, finished_ts=old + 1)
    fresh = now - 10 * 86400
    rec.record_run("dc.collect.cloud", started_ts=fresh, finished_ts=fresh + 1)
    r = rec.prune(now_ts=now)
    # FakeStore 无 delete → FAIL-OPEN，不抛错且报告到期条数
    assert r["due"] >= 1 and r["error_code"] == "port_delete_unavailable"
    assert event.consume(event_type="job_runs.prune_due")["events"]


# ── 落库纪律：只经 port，不直连 DB ──────────────────────────────────────
def test_scheduling_modules_do_not_import_db_drivers():
    banned = re.compile(r"\b(sqlite3|psycopg2?|asyncpg|pymysql|mysql\.connector)\b")
    for name in ("registry.py", "windows.py", "job_runs.py", "cli.py"):
        path = os.path.join(REPO_ROOT, "dreambuddy_l0", "scheduling", name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert not banned.search(text), f"{name} 直连数据库（违反顺序风险约束）"
        if name in ("job_runs.py", "cli.py"):
            assert (
                "dreambuddy_l0" in text or "..ports" in text or "..adapters" in text
            ), f"{name} 未复用 L0 包内 port/adapter"


def test_registry_declares_utc_window_semantics():
    doc = _load()
    assert doc.get("window_timezone") == "UTC"
    assert doc.get("late_tolerance_sec") == 300
    assert doc.get("retention_days") == 90


# ── 可执行落库 adapter + CLI ─────────────────────────────────────────────
from dreambuddy_l0.adapters.jsonl import JsonlEvent, JsonlStore  # noqa: E402


def test_jsonl_adapter_is_store_and_event_port():
    from dreambuddy_l0.ports import EventPort, StorePort

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "job_runs.jsonl")
        store = JsonlStore(p)
        event = JsonlEvent(p)
        assert isinstance(store, StorePort) and isinstance(event, EventPort)
        assert store.write("job_runs", data={"id": "k1"}, idempotency_key="k1")
        assert store.write("job_runs", data={"id": "k1", "state": "succeeded"})
        rows = store.query("job_runs")["rows"]
        assert len(rows) == 1 and rows[0]["state"] == "succeeded"
        assert store.delete("job_runs", ids=["k1"]) == 1
        assert store.query("job_runs")["rows"] == []


def test_cli_run_and_audit_exit_zero():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "job_runs.jsonl")
        env = dict(os.environ, JOB_RUNS_PATH=path, PYTHONPATH=REPO_ROOT)
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "dreambuddy_l0.scheduling.cli",
                "run",
                "--task-key",
                "dc.backfill.cloud",
                "--now",
                "3600",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out["rows"][0]["task_key"] == "dc.backfill.cloud"
        r2 = subprocess.run(
            [sys.executable, "-m", "dreambuddy_l0.scheduling.cli", "list"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert r2.returncode == 0
        assert len(json.loads(r2.stdout.strip().splitlines()[-1])["tasks"]) >= 4
