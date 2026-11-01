"""C8 事件互通契约测试（进 G0-4 阻断 job）。

SPEC-L0 §6 P2 C8：`job_runs` 终态后同进程回调 → 认知 record（`external_id=run_id` 幂等）。
覆盖：
  - 一次采集 run 可 recall 到事件；
  - 重复执行不产生重复记忆（external_id=run_id）；
  - 消费失败（认知侧异常）不阻断主流程，只告警；
  - record 不触发实时重建（P0-11 已由 G0-8 去抖，C8 不再直连 Popen）；
  - 只经 Memory/Event port，不直连 DB。
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

REGISTRY_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "job_registry.yaml")

from dreambuddy_l0.fakes import FakeEvent, FakeMemory, FakeStore  # noqa: E402
from dreambuddy_l0.scheduling import load_registry  # noqa: E402
from dreambuddy_l0.scheduling.event_bridge import (  # noqa: E402
    TERMINAL_STATES,
    JobRunEventBridge,
    memory_enabled,
    run_event_content,
)
from dreambuddy_l0.scheduling.job_runs import JobRunRecorder  # noqa: E402


def _recorder(memory=None, *, store=None, event=None):
    return JobRunRecorder(
        store=store or FakeStore(),
        event=event or FakeEvent(),
        memory=memory,
        registry=load_registry(REGISTRY_PATH),
    )


class SpyMemory(FakeMemory):
    """记录 record() 入参，用于断言 external_id 契约。"""

    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, content, *, tags=None, source="", external_id=None):
        self.calls.append(
            {
                "content": content,
                "tags": list(tags or []),
                "source": source,
                "external_id": external_id,
            }
        )
        return super().record(content, tags=tags, source=source, external_id=external_id)


class BoomMemory(FakeMemory):
    def record(self, *a, **kw):
        raise RuntimeError("memory down")


# ── 主链路：run 终态 → 认知记录 ──────────────────────────────────────────
def test_terminal_run_creates_recallable_record():
    mem = FakeMemory()
    rec = _recorder(mem)
    rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    hits = mem.recall("dc.collect.cloud", top_k=5, min_quality="C")
    assert len(hits) == 1, "一次采集未产出可 recall 的认知记录"
    text = hits[0]["content"]
    assert "dc.collect.cloud" in text and "succeeded" in text


def test_external_id_is_run_id():
    mem = SpyMemory()
    rec = _recorder(mem)
    rows = rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    assert mem.calls, "C8：终态未回调认知 record"
    call = mem.calls[0]
    assert call["external_id"] == rows[0]["run_id"] == "dc.collect.cloud@0"
    assert call["source"] == "l0.scheduler"
    assert "dc.collect.cloud" in call["tags"]
    assert "succeeded" in call["tags"]


def test_repeat_run_across_restart_does_not_duplicate_memory():
    """重启后重复执行同一窗口：run 幂等 + 认知 external_id 幂等，记忆只有 1 条。"""
    store, event, mem = FakeStore(), FakeEvent(), FakeMemory()
    first = _recorder(mem, store=store, event=event)
    first.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    # 新实例模拟重启（共享落库与认知库）
    second = _recorder(mem, store=store, event=event)
    second.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    assert len(mem.recall("dc.collect.cloud", top_k=10, min_quality="C")) == 1


def test_failed_run_record_carries_error():
    mem = SpyMemory()
    rec = _recorder(mem)
    rec.record_run("dc.backfill.cloud", started_ts=3600, finished_ts=3601, error="boom")
    call = mem.calls[-1]
    assert "state=failed" in call["content"] and "error=boom" in call["content"]
    assert "failed" in call["tags"]


def test_non_terminal_state_not_recorded():
    mem = FakeMemory()
    rec = _recorder(mem)
    rec.begin("dc.collect.cloud", window=3, now=901)
    assert mem.recall("dc.collect.cloud", top_k=10, min_quality="C") == []
    rec.begin("dc.collect.cloud", window=3, now=902)
    rec.finish("dc.collect.cloud@3", now=903, state="running")
    assert mem.recall("dc.collect.cloud", top_k=10, min_quality="C") == []
    assert "running" not in TERMINAL_STATES


# ── 降级与 FAIL-OPEN ─────────────────────────────────────────────────────
def test_memory_failure_does_not_block_run():
    store, event = FakeStore(), FakeEvent()
    rec = _recorder(BoomMemory(), store=store, event=event)
    rows = rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    assert rows[0]["state"] == "succeeded", "认知侧失败不得回滚 run"
    assert rows[0]["bridge"]["recorded"] is False
    assert rows[0]["bridge"]["error_code"] == "memory_record_failed"
    assert store.query("job_runs", filters={"run_id": rows[0]["run_id"]})["rows"], "run 未落库"


def test_memory_failure_publishes_alert_event():
    event = FakeEvent()
    rec = _recorder(BoomMemory(), event=event)
    rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
    alerts = event.consume(event_type="scheduling.memory_record_failed")["events"]
    assert alerts, "record 失败未告警"
    assert alerts[0]["payload"]["run_id"] == "dc.collect.cloud@0"


def test_no_memory_port_keeps_scheduler_compatible():
    """未注入 Memory port 时（默认关闭）不回调认知，调度行为不变。"""
    rec = _recorder(None)
    rows = rec.record_run("dc.collect.local", started_ts=1, finished_ts=2)
    assert rows[0]["state"] == "succeeded"
    assert rows[0]["bridge"]["skipped"] is True


def test_bridge_on_terminal_ignores_unknown_state():
    bridge = JobRunEventBridge(memory=FakeMemory(), event=FakeEvent())
    res = bridge.on_terminal(
        {"run_id": "k@1", "task_key": "dc.collect.cloud", "state": "missed_run"}
    )
    assert res["recorded"] is False and res["skipped"] is True


def test_memory_switch_defaults_on_cloud_only():
    """本地默认关闭（认知权威库在云端，本地只读镜像），显式开关优先。"""
    assert memory_enabled({"DATA_CENTER_BACKEND": "postgres"}) is True
    assert memory_enabled({"DATA_CENTER_BACKEND": "sqlite"}) is False
    assert memory_enabled({}) is False
    assert memory_enabled({"JOB_RUNS_MEMORY": "1", "DATA_CENTER_BACKEND": "sqlite"}) is True
    assert memory_enabled({"JOB_RUNS_MEMORY": "0", "DATA_CENTER_BACKEND": "postgres"}) is False


def test_datacenter_scheduler_wires_memory_port():
    """18 采集调度器必须按开关注入 Memory port（落点：18 scheduler + 认知）。"""
    path = REPO_ROOT / "18-数据获取中心" / "data_center_scheduler.py"
    text = path.read_text(encoding="utf-8")
    assert "memory_enabled" in text and "from_cognitive_loop" in text
    assert "memory=" in text, "C8：JobRunRecorder 未注入 Memory port"


# ── P0-11：record 不触发实时重建；只经 port ──────────────────────────────
def test_event_bridge_has_no_realtime_index_rebuild_or_db_direct_access():
    path = REPO_ROOT / "dreambuddy_l0" / "scheduling" / "event_bridge.py"
    text = path.read_text(encoding="utf-8")
    banned = re.compile(r"\b(sqlite3|psycopg2?|asyncpg|subprocess|Popen|index_rebuild)\b")
    assert not banned.search(text), "C8：事件互通不得直连 DB / 触发实时索引重建"
    assert "..ports" in text, "C8：事件互通必须经 L0 port"


def test_adapter_uses_no_module_level_sys_path_hack():
    path = REPO_ROOT / "dreambuddy_l0" / "adapters" / "cognitive.py"
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        assert not line.startswith("sys.path.insert"), "G0-2：禁止模块级 sys.path.insert"
    assert "DREAMBUDDY_MEMORY_DIR" in text, "G0-2：认知目录必须可外置"


# ── MemoryPort adapter ───────────────────────────────────────────────────
from dreambuddy_l0.adapters.cognitive import CognitiveMemoryAdapter  # noqa: E402
from dreambuddy_l0.ports import MemoryPort  # noqa: E402


class _EntrySpy:
    def __init__(self):
        self.recorded = []
        self.verified = []

    def recall(self, context, top_k=5, min_quality="C"):
        return [{"id": "M1", "content": context}]

    def record(self, content, *, quality_level="C", tags=None, source="", external_id=None):
        self.recorded.append({"external_id": external_id, "source": source, "content": content})
        return "M1"

    def verify(self, memory_id, success=True):
        self.verified.append((memory_id, success))
        return {"success": success}


def test_cognitive_adapter_is_memory_port_and_passes_external_id():
    entry = _EntrySpy()
    adapter = CognitiveMemoryAdapter(entry)
    assert isinstance(adapter, MemoryPort)
    assert (
        adapter.record("run event", tags=["job_runs"], source="l0.scheduler", external_id="run-1")
        == "M1"
    )
    assert entry.recorded[0]["external_id"] == "run-1"
    assert adapter.recall("job_runs", top_k=3) == [{"id": "M1", "content": "job_runs"}]
    assert adapter.verify("M1", success=True) is True
    assert entry.verified == [("M1", True)]


# ── 内容契约 ─────────────────────────────────────────────────────────────
def test_run_event_content_format():
    text = run_event_content(
        {
            "run_id": "dc.collect.cloud@7",
            "task_key": "dc.collect.cloud",
            "logical_window": 7,
            "state": "succeeded",
            "started_at": 100.0,
            "finished_at": 102.5,
        }
    )
    assert text.startswith("[L0调度][job_runs]")
    assert "run_id=dc.collect.cloud@7" in text
    assert "duration=2.5s" in text


# ── 真实认知库：external_id 幂等（数据侧实证）─────────────────────────────
def test_real_cognitive_store_dedupes_by_run_id(tmp_path):
    import pytest

    pytest.importorskip("numpy")
    memory_dir = REPO_ROOT / "4-MEMORY" / "9-工具与接口"
    sys.path.insert(0, str(memory_dir))
    from vector_memory_interface import VectorMemoryInterface  # noqa: E402

    vm = VectorMemoryInterface(storage_path=str(tmp_path / "c8.db"), engine="numpy")
    try:

        class _VmEntry:
            def record(self, content, *, quality_level="C", tags=None, source="", external_id=None):
                return vm.add(
                    content=content,
                    quality_level=quality_level,
                    confidence=0.3,
                    tags=list(tags or []),
                    source=source,
                    external_id=external_id,
                )

        adapter = CognitiveMemoryAdapter(_VmEntry())
        rec = _recorder(adapter)
        rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
        rec.record_run("dc.collect.cloud", started_ts=1, finished_ts=2)
        assert vm.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    finally:
        vm.db.close()
