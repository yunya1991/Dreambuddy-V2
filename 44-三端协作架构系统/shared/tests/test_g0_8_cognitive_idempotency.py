"""G0-8 认知幂等 + P0-11 索引重建去抖契约测试（进 l0-contracts 阻断 job）。

G0-8 是 C8（事件互通，`external_id=run_id`）的开工前置：
- 认知表必须有 `external_id` 列 + 唯一索引；
- 同一 key 重复 record 只产生 1 条记忆（幂等）；
- `record(idempotency_key=)` 为 SPEC 契约入口。

P0-11：`record()` 不得每条记忆都 Popen 41 重建，必须去抖。
"""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MEMORY_DIR = REPO_ROOT / "4-MEMORY" / "9-工具与接口"
sys.path.insert(0, str(MEMORY_DIR))

import index_rebuild_trigger  # noqa: E402
from vector_memory_interface import VectorMemoryInterface  # noqa: E402

ENTRY_SRC = (MEMORY_DIR / "cognitive_loop_entry.py").read_text(encoding="utf-8")
TRIGGER_SRC = (MEMORY_DIR / "index_rebuild_trigger.py").read_text(encoding="utf-8")

# 只看 record() 方法体（recall 的 D6 文档通道另有搜索，与 P0-11 无关）
_record_start = ENTRY_SRC.index("    def record(")
_record_end = ENTRY_SRC.index("# 实践层：验证与更新")
RECORD_SRC = ENTRY_SRC[_record_start:_record_end]


def _fresh_db() -> VectorMemoryInterface:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return VectorMemoryInterface(storage_path=tmp.name, engine="numpy")


def test_memories_schema_has_external_id_and_unique_index():
    vm = _fresh_db()
    try:
        cols = {r[1] for r in vm.db.execute("PRAGMA table_info(memories)")}
        assert "external_id" in cols, "G0-8：memories 表缺少 external_id 列"
        indexes = {r[1] for r in vm.db.execute("PRAGMA index_list(memories)")}
        assert "idx_external_id" in indexes, "G0-8：缺少 external_id 唯一索引"
    finally:
        vm.db.close()


def test_same_external_id_is_idempotent():
    vm = _fresh_db()
    try:
        id1 = vm.add("A", external_id="run-1")
        id2 = vm.add("B", external_id="run-1")
        assert id1 == id2, "G0-8：同一 external_id 应复用同一记忆 ID"
        assert vm.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    finally:
        vm.db.close()


def test_distinct_external_id_creates_two_rows():
    vm = _fresh_db()
    try:
        vm.add("A", external_id="run-1")
        vm.add("B", external_id="run-2")
        assert vm.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
    finally:
        vm.db.close()


def test_null_external_id_not_constrained():
    """存量记忆（external_id=NULL）不受部分唯一索引约束。"""
    vm = _fresh_db()
    try:
        vm.add("A")
        vm.add("B")
        assert vm.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
    finally:
        vm.db.close()


def test_record_exposes_idempotency_key_contract():
    assert (
        "idempotency_key: Optional[str] = None" in RECORD_SRC
    ), "G0-8：record() 缺少 idempotency_key 入参"
    assert (
        "external_id = external_id or idempotency_key" in RECORD_SRC
    ), "G0-8：idempotency_key 未落为 external_id"


def test_index_rebuild_debounced_within_window():
    calls = []
    index_rebuild_trigger.reset()
    assert index_rebuild_trigger.trigger(lambda: calls.append(1), now=100.0, interval=60.0) is True
    assert index_rebuild_trigger.trigger(lambda: calls.append(1), now=130.0, interval=60.0) is False
    assert index_rebuild_trigger.trigger(lambda: calls.append(1), now=161.0, interval=60.0) is True
    assert len(calls) == 2, "P0-11：窗口内重复触发未去抖"


def test_index_rebuild_fail_open():
    """runner 抛错时 trigger 不抛出，且不影响调用方（FAIL-OPEN）。"""
    index_rebuild_trigger.reset()

    def boom():
        raise RuntimeError("boom")

    assert index_rebuild_trigger.trigger(boom, now=200.0, interval=0.0) is False


def test_record_no_longer_popens_index_rebuild_directly():
    assert "subprocess" not in RECORD_SRC, "P0-11：record() 仍直接 Popen 41 重建"
    assert (
        "from index_rebuild_trigger import trigger" in RECORD_SRC
    ), "P0-11：record() 未接入去抖触发器"


def test_fis_p0_path_externalized_in_trigger():
    assert "/home/ubuntu/fis-p0" not in RECORD_SRC, "G0-2：record() 硬编码 fis-p0 路径"
    assert "FIS_P0_HOME" in TRIGGER_SRC, "G0-2：触发器缺少 FIS_P0_HOME 配置入口"
