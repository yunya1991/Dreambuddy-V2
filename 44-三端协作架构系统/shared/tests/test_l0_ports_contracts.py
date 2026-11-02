"""C2 六 port 契约测试（进 G0-4 阻断 job）。

覆盖：信封 10 字段、error_code 枚举、FAIL-OPEN、幂等语义、分页、方言能力集。
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from dreambuddy_l0 import degraded, envelope, get_l0  # noqa: E402
from dreambuddy_l0.fakes import (  # noqa: E402
    FakeAnalysis,
    FakeCollector,
    FakeEvent,
    FakeMemory,
    FakeSearch,
    FakeStore,
)
from dreambuddy_l0.ports import (  # noqa: E402
    AnalysisPort,
    CollectorPort,
    EventPort,
    MemoryPort,
    SearchPort,
    StorePort,
)


def test_envelope_has_all_10_fields():
    env = envelope({"x": 1}, "t")
    required = {
        "ok",
        "data",
        "source",
        "timestamp",
        "degraded",
        "meta",
        "version",
        "trace_id",
        "idempotency_key",
        "error_code",
    }
    assert required <= set(env.keys())


def test_degraded_error_code_enum():
    deg = degraded("t", "unavailable", "boom")
    assert deg["degraded"] is True
    assert deg["error_code"] == "unavailable"
    # 非法 error_code 收敛为 degraded
    deg2 = degraded("t", "free_text_reason")
    assert deg2["error_code"] == "degraded"


def test_facade_fail_open_unknown_scope():
    r = get_l0().fetch_context("no.such.scope")
    assert r["degraded"] is True and r["error_code"] == "unknown_scope"


def test_six_fakes_satisfy_port_protocols():
    for fake, port in [
        (FakeMemory(), MemoryPort),
        (FakeCollector(), CollectorPort),
        (FakeSearch(), SearchPort),
        (FakeStore(), StorePort),
        (FakeAnalysis(), AnalysisPort),
        (FakeEvent(), EventPort),
    ]:
        assert isinstance(fake, port), f"{type(fake).__name__} 不满足 {port.__name__}"


def test_memory_fake_idempotent_external_id():
    m = FakeMemory()
    id1 = m.record("A", external_id="e1")
    id2 = m.record("B", external_id="e1")
    assert id1 == id2


def test_store_fake_idempotency_key():
    s = FakeStore()
    assert s.write("t", data={"id": 1}, idempotency_key="k1")
    assert s.write("t", data={"id": 2}, idempotency_key="k1")
    rows = s.query("t")["rows"]
    assert len(rows) == 1


def test_store_fake_pagination_limit():
    s = FakeStore()
    for i in range(10):
        s.write("t", data={"id": i})
    assert len(s.query("t", limit=3)["rows"]) == 3


def test_store_dialect_capabilities_declared():
    from dreambuddy_l0.fakes.store import DIALECT_CAPABILITIES

    assert "operators" in DIALECT_CAPABILITIES and "type_mapping" in DIALECT_CAPABILITIES


def test_store_read_not_found():
    r = FakeStore().read("t", key="missing")
    assert r["row"] is None and r["error_code"] == "not_found"


# ── M4⑪ Memory port bulk-read（export/list）契约 ──────────────────────
_ENTRY_FIELDS = {
    "id",
    "content",
    "quality_level",
    "confidence",
    "tags",
    "memory_type",
    "source",
    "created_at",
    "updated_at",
    "verify_count",
    "level",
    "known_gaps",
    "observations",
}


def test_memory_port_declares_bulk_read():
    """M4⑪：Memory port 必须具备 bulk-read 语义（export_entries / list_ids）。"""
    assert callable(getattr(MemoryPort, "export_entries", None))
    assert callable(getattr(MemoryPort, "list_ids", None))


def test_memory_fake_export_entries_quality_filter():
    """质量过滤：min_quality=B 只返回 S/A/B（字母序不可直接比较）。"""
    m = FakeMemory()
    for q in ("S", "A", "B", "C", "D"):
        m.record(f"内容-{q}", quality=q)
    r = m.export_entries(min_quality="B")
    assert {e["quality_level"] for e in r["entries"]} == {"S", "A", "B"}
    assert r["cursor"] is None


def test_memory_fake_export_entries_pagination_cursor():
    """分页边界：limit 截断 + cursor 续页，最后一页 cursor=None，无重复/遗漏。"""
    m = FakeMemory()
    for i in range(7):
        m.record(f"c{i}")
    first = m.export_entries(min_quality="C", limit=3)
    assert len(first["entries"]) == 3 and first["cursor"] == "3"
    second = m.export_entries(min_quality="C", limit=3, cursor=first["cursor"])
    assert len(second["entries"]) == 3 and second["cursor"] == "6"
    last = m.export_entries(min_quality="C", limit=3, cursor=second["cursor"])
    assert len(last["entries"]) == 1 and last["cursor"] is None
    ids = [e["id"] for e in first["entries"] + second["entries"] + last["entries"]]
    assert len(ids) == len(set(ids)) == 7


def test_memory_fake_export_entries_empty_envelope():
    """空库：仍返回统一信封（entries=[] + cursor=None），不抛异常。"""
    r = FakeMemory().export_entries(min_quality="B")
    assert r == {"entries": [], "cursor": None}


def test_memory_fake_export_entries_entry_fields():
    """统一信封：每条 entry 的字段集与 recall/record 的认知记忆形状一致。"""
    m = FakeMemory()
    m.record("字段校验")
    entry = m.export_entries(min_quality="D")["entries"][0]
    assert _ENTRY_FIELDS <= set(entry.keys())
    assert isinstance(entry["tags"], list)


def test_memory_fake_export_entries_since_filter():
    """增量过滤：since(ISO) 只返回 created_at 严格更大的条目。"""
    m = FakeMemory()
    m.record("旧", created_at="2026-10-01T00:00:00+00:00")
    m.record("新", created_at="2026-10-05T00:00:00+00:00")
    r = m.export_entries(min_quality="C", since="2026-10-03T00:00:00+00:00")
    assert [e["content"] for e in r["entries"]] == ["新"]


def test_memory_fake_list_ids_matches_export_entries():
    """list_ids 与 export_entries 必须同序同集（同一过滤条件下）。"""
    m = FakeMemory()
    for q in ("S", "B", "C"):
        m.record(f"内容-{q}", quality=q)
    ids = m.list_ids(min_quality="B")
    entries = m.export_entries(min_quality="B")
    assert ids["ids"] == [e["id"] for e in entries["entries"]]
    assert ids["cursor"] is None


def test_memory_read_adapter_bulk_read_real_impl(tmp_path):
    """真实 adapter：经 VectorMemoryInterface 批量读（质量过滤 + 分页 + 空库）。"""
    from dreambuddy_l0.adapters.cognitive import MemoryReadAdapter, load_vector_memory

    vm = load_vector_memory(storage_path=str(tmp_path / "bulk.db"))
    try:
        port = MemoryReadAdapter(vm)
        assert port.export_entries(min_quality="B") == {"entries": [], "cursor": None}
        for q in ("S", "A", "B", "C", "D"):
            vm.add(f"真实-{q}", quality_level=q, tags=["bulk", q])
        r = port.export_entries(min_quality="B", limit=2)
        assert len(r["entries"]) == 2
        assert {e["quality_level"] for e in r["entries"]} <= {"S", "A", "B"}
        assert r["cursor"] == "2"
        rest = port.export_entries(min_quality="B", limit=2, cursor=r["cursor"])
        assert rest["cursor"] is None
        all_ids = [e["id"] for e in r["entries"] + rest["entries"]]
        assert len(all_ids) == len(set(all_ids)) == 3
        assert port.list_ids(min_quality="B")["ids"] == all_ids
    finally:
        vm.close()
