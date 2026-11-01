"""C13 OS 层定时逻辑只读旁路契约测试（进 G0-4 阻断 job）。

SPEC-L0 §6 C13：每端各 1 个非实盘周期任务（本地 com.dreambuddy.dbsync 经 launchd、
云端 memory-cleanup.timer 经 systemd timer）通过只读旁路解析状态记账入 job_runs；
不改 ExecStart/plist；实盘进程不内嵌记账。
"""

import os
import re
import sys

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

REGISTRY_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "job_registry.yaml")

from dreambuddy_l0.fakes import FakeEvent, FakeStore  # noqa: E402
from dreambuddy_l0.scheduling.job_runs import JobRunRecorder  # noqa: E402
from dreambuddy_l0.scheduling.registry import load_registry  # noqa: E402
from dreambuddy_l0.scheduling.sidecar import (  # noqa: E402
    probe_launchd_agent,
    probe_systemd_timer,
    sync_sidecar,
)


def _registry():
    return load_registry(REGISTRY_PATH)


class FakeRunner:
    """按命令前缀映射 stdout 的 fake 执行器。"""

    def __init__(self, outputs=None, boom=False):
        self.outputs = outputs or {}
        self.boom = boom
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.boom:
            raise RuntimeError("cmd down")
        key = " ".join(cmd)
        for prefix, out in self.outputs.items():
            if key.startswith(prefix):
                return out
        return ""


# ── 注册表契约：两个 C13 任务与 SPEC 口径一致 ──────────────────────────────
def test_registry_declares_c13_sidecar_tasks():
    reg = _registry()
    dbsync = reg.get("os.dbsync.local")
    assert dbsync is not None, "注册表缺 os.dbsync.local"
    assert dbsync.carrier == "launchd" and dbsync.host == "local"
    assert dbsync.unit == "com.dreambuddy.dbsync"
    assert dbsync.window_sec == 600  # plist StartInterval=600（只读口径）
    cleanup = reg.get("os.memory-cleanup.cloud")
    assert cleanup is not None, "注册表缺 os.memory-cleanup.cloud"
    assert cleanup.carrier == "systemd-timer" and cleanup.host == "cloud"
    assert cleanup.unit == "memory-cleanup.timer"
    assert cleanup.window_sec == 21600  # 6h 周期


def test_c13_tasks_not_search_trigger_targets():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    targets = {r["task_key"] for r in doc.get("search_triggers") or []}
    assert "os.dbsync.local" not in targets
    assert "os.memory-cleanup.cloud" not in targets


# ── systemd 探针解析 ────────────────────────────────────────────────────────
SYSTEMD_SHOW = """\
ExecMainStatus=0
Result=success
"""

SYSTEMD_SHOW_FAILED = """\
ExecMainStatus=3
Result=exit-code
"""


def test_probe_systemd_timer_parses_trigger_and_result():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "1793503205000000\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    out = probe_systemd_timer("memory-cleanup.timer", runner=runner)
    assert out["ok"] is True and out["triggered"] is True
    assert out["started_ts"] == 1793503205.0
    assert out["exit_code"] == 0
    assert out["result"] == "success"


def test_probe_systemd_timer_parses_formatted_timestamp():
    # systemd 新版（255+）LastTriggerUSec 输出本地格式化时间而非 µs 整数
    # （云端实测："Sun 2026-11-01 02:05:01 CST"）；按本机本地时间解释。
    import time as _time

    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "Sun 2026-11-01 02:05:01 CST\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    out = probe_systemd_timer("memory-cleanup.timer", runner=runner)
    assert out["ok"] is True and out["triggered"] is True
    expect = _time.mktime(_time.strptime("2026-11-01 02:05:01", "%Y-%m-%d %H:%M:%S"))
    assert out["started_ts"] == expect


def test_probe_systemd_timer_never_triggered():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "0\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    out = probe_systemd_timer("memory-cleanup.timer", runner=runner)
    assert out["ok"] is True and out["triggered"] is False


def test_probe_systemd_timer_fail_open_on_error():
    out = probe_systemd_timer("memory-cleanup.timer", runner=FakeRunner(boom=True))
    assert out["ok"] is False and out["triggered"] is False
    assert out["reason"]


# ── launchd 探针解析（plist 事实源 + LastExitStatus + 日志 mtime）────────────
def test_probe_launchd_agent_parses_status_and_log_mtime(tmp_path):
    import plistlib

    log = tmp_path / "dbsync.launchd.log"
    log.write_text("sync done\n", encoding="utf-8")
    os.utime(log, (1700000000, 1700000000))
    plist = tmp_path / "com.dreambuddy.dbsync.plist"
    plist.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.dreambuddy.dbsync",
                "StandardOutPath": str(log),
                "StartInterval": 600,
            }
        )
    )
    runner = FakeRunner(
        {"launchctl list com.dreambuddy.dbsync": '{\n    "LastExitStatus" = 0;\n};\n'}
    )
    out = probe_launchd_agent("com.dreambuddy.dbsync", runner=runner, plist_path=str(plist))
    assert out["ok"] is True and out["triggered"] is True
    assert out["started_ts"] == 1700000000.0
    assert out["exit_code"] == 0


def test_probe_launchd_agent_not_loaded_is_not_triggered(tmp_path):
    runner = FakeRunner(
        {
            "launchctl list ghost.label": 'Could not find service "ghost.label" in domain for system\n'
        }
    )
    out = probe_launchd_agent(
        "ghost.label", runner=runner, plist_path=str(tmp_path / "ghost.plist")
    )
    assert out["ok"] is True and out["triggered"] is False


# ── 旁路记账：探测 → job_runs ──────────────────────────────────────────────
def _sync(task_key, runner, store=None, **kw):
    store = store or FakeStore()
    rec = JobRunRecorder(store=store, event=FakeEvent(), registry=_registry())
    out = sync_sidecar(task_key, recorder=rec, registry=_registry(), runner=runner, **kw)
    return out, store


def test_sync_sidecar_records_systemd_run():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "1793503200000000\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    out, store = _sync("os.memory-cleanup.cloud", runner)
    assert out["degraded"] is False and out["recorded"] is True
    rows = store.query("job_runs", limit=10)["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["task_key"] == "os.memory-cleanup.cloud"
    assert row["state"] == "succeeded"
    # 21600s 窗口对齐：window = ts // 21600
    assert row["logical_window"] == int(1793503200 // 21600)


def test_sync_sidecar_idempotent_within_window():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "1793503200000000\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    store = FakeStore()
    _sync("os.memory-cleanup.cloud", runner, store)
    out, _ = _sync("os.memory-cleanup.cloud", runner, store)
    assert out["recorded"] is False and out["reason"] == "duplicate"
    assert len(store.query("job_runs", limit=10)["rows"]) == 1


def test_sync_sidecar_failed_run_recorded_as_failed():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "1793503200000000\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW_FAILED,
        }
    )
    out, store = _sync("os.memory-cleanup.cloud", runner)
    assert out["recorded"] is True
    row = store.query("job_runs", limit=10)["rows"][0]
    assert row["state"] == "failed"
    assert "exit" in row["error"] or "result" in row["error"]


def test_sync_sidecar_launchd_records_local_run(tmp_path):
    log = tmp_path / "dbsync.log"
    log.write_text("ok\n", encoding="utf-8")
    ts = 1793503200.0
    os.utime(log, (ts, ts))
    import plistlib

    plist = tmp_path / "com.dreambuddy.dbsync.plist"
    plist.write_bytes(
        plistlib.dumps({"Label": "com.dreambuddy.dbsync", "StandardOutPath": str(log)})
    )
    runner = FakeRunner(
        {"launchctl list com.dreambuddy.dbsync": '{\n    "LastExitStatus" = 0;\n};\n'}
    )
    out, store = _sync("os.dbsync.local", runner, plist_path=str(plist))
    assert out["degraded"] is False and out["recorded"] is True
    row = store.query("job_runs", limit=10)["rows"][0]
    assert row["task_key"] == "os.dbsync.local"
    assert row["state"] == "succeeded"
    assert row["logical_window"] == int(ts // 600)


def test_sync_sidecar_fail_open_when_probe_fails():
    out, store = _sync("os.memory-cleanup.cloud", FakeRunner(boom=True))
    assert out["degraded"] is True and out["error_code"]
    assert store.query("job_runs", limit=10)["rows"] == []


def test_sync_sidecar_unregistered_task_fail_open():
    out, _ = _sync("ghost.task", FakeRunner())
    assert out["degraded"] is True
    assert out["error_code"] == "task_unavailable"


def test_sync_sidecar_never_triggered_records_nothing():
    runner = FakeRunner(
        {
            "systemctl show memory-cleanup.timer -p LastTriggerUSec --value": "0\n",
            "systemctl show memory-cleanup.service": SYSTEMD_SHOW,
        }
    )
    out, store = _sync("os.memory-cleanup.cloud", runner)
    assert out["degraded"] is False and out["recorded"] is False
    assert out["reason"] == "never_triggered"
    assert store.query("job_runs", limit=10)["rows"] == []


# ── 红线：只读旁路，禁写操作、禁直连 DB ─────────────────────────────────────
def test_sidecar_module_is_read_only_and_port_only():
    path = os.path.join(REPO_ROOT, "dreambuddy_l0", "scheduling", "sidecar.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 禁止改 OS 单元定义（SPEC：改 ExecStart/plist = 违规）
    banned_write = re.compile(
        r"systemctl\s+(edit|enable|disable|mask|daemon-reload)|"
        r"launchctl\s+(load|unload|bootstrap|bootout)|"
        r"crontab|"
        r"ExecStart\s*="
    )
    assert not banned_write.search(text), "sidecar 出现写 OS 单元操作（C13 红线）"
    banned_db = re.compile(r"\b(sqlite3|psycopg2?|asyncpg|pymysql|mysql\.connector)\b")
    assert not banned_db.search(text), "sidecar 直连数据库（违反 L0-P 约束）"
