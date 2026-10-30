"""C2 六 port 契约测试（进 G0-4 阻断 job）。

覆盖：信封 10 字段、error_code 枚举、FAIL-OPEN、幂等语义、分页、方言能力集。
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from dreambuddy_l0 import envelope, degraded, get_l0
from dreambuddy_l0.ports import (MemoryPort, CollectorPort, SearchPort, StorePort,
                                 AnalysisPort, EventPort)
from dreambuddy_l0.fakes import (FakeMemory, FakeCollector, FakeSearch, FakeStore,
                                 FakeAnalysis, FakeEvent)


def test_envelope_has_all_10_fields():
    env = envelope({"x": 1}, "t")
    required = {"ok", "data", "source", "timestamp", "degraded", "meta",
                "version", "trace_id", "idempotency_key", "error_code"}
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
    for fake, port in [(FakeMemory(), MemoryPort), (FakeCollector(), CollectorPort),
                       (FakeSearch(), SearchPort), (FakeStore(), StorePort),
                       (FakeAnalysis(), AnalysisPort), (FakeEvent(), EventPort)]:
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
