# -*- coding: utf-8 -*-
"""P0 向量索引修复：fail-loud + 级联删除 + recall 回写/降级信封。

覆盖四条硬约束：
1. engine 不一致（索引需要 sqlite_vec，实际 numpy）时 add() 必须抛异常，不再静默跳过；
2. 256 维向量对 512 维索引被 assert_embed_consistency 拦截；
3. delete() 后 vec 表无孤儿行（任何引擎都级联删除）；
4. recall 命中后 access_count 递增 / last_used_at 写入；0 命中返回 degraded=True。

所有用例只用 pytest 的 tmp_path 临时库，禁止触碰 4-MEMORY/data/cognitive_memory.db。
"""

import sqlite3
import sys
from pathlib import Path

import pytest

_COG_DIR = Path(__file__).resolve().parent.parent
if str(_COG_DIR) not in sys.path:
    sys.path.insert(0, str(_COG_DIR))

from cognitive_loop_entry import CognitiveLoopEntry  # noqa: E402
from vector_memory_interface import VectorMemoryInterface  # noqa: E402


def _make_numpy_interface(db_file: Path, **kwargs) -> VectorMemoryInterface:
    """临时文件库 + numpy 引擎（不依赖 sqlite-vec 扩展）。"""
    return VectorMemoryInterface(storage_path=str(db_file), engine="numpy", **kwargs)


def _create_fake_vec_table(conn: sqlite3.Connection) -> None:
    """模拟「索引已存在 vec 表」的场景（普通表即可，无需加载 vec0 扩展）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vec_memories("
        "rowid INTEGER PRIMARY KEY, embedding BLOB, memory_id TEXT, quality TEXT)"
    )
    conn.commit()


# ============================================================
# 1. engine 不一致 → add() fail-loud
# ============================================================


def test_add_raises_when_engine_cannot_write_vec_table(tmp_path):
    """索引需要 sqlite_vec 但当前 engine=numpy → add() 抛 RuntimeError（不再静默）。"""
    db_file = tmp_path / "engine_mismatch.db"

    # 先用一个独立连接造出 vec_memories，使接口判定「索引存在、需要写 vec 表」
    pre = sqlite3.connect(str(db_file))
    _create_fake_vec_table(pre)
    pre.close()

    iface = _make_numpy_interface(db_file)
    try:
        assert iface._has_legacy_vec_memories is True
        with pytest.raises(RuntimeError) as excinfo:
            iface.add(content="engine 不一致必须失败", quality_level="C")
        msg = str(excinfo.value)
        assert "sqlite_vec" in msg and "numpy" in msg, msg
    finally:
        iface.db.close()


def test_allow_degraded_switch_permits_engine_mismatch(tmp_path):
    """显式 allow_degraded=True 时才允许降级写入，且 meta 标记 degraded=True。"""
    db_file = tmp_path / "engine_mismatch_degraded.db"
    pre = sqlite3.connect(str(db_file))
    _create_fake_vec_table(pre)
    pre.close()

    iface = _make_numpy_interface(db_file, allow_degraded=True)
    try:
        mem_id = iface.add(content="显式降级写入", quality_level="C")
        assert mem_id
        meta = iface.stats()
        assert meta["degraded"] is True
        assert meta["degraded_reason"] == "engine_mismatch"
    finally:
        iface.db.close()


# ============================================================
# 2. 维度不一致 → assert_embed_consistency 拦截
# ============================================================


def test_assert_embed_consistency_blocks_256_against_512_index(tmp_path):
    """256 维向量对 meta.embed_dim=512 索引必须抛异常（禁止混维写入）。"""
    iface = _make_numpy_interface(tmp_path / "dim_mismatch.db")
    try:
        iface.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('embed_dim', '512')")
        iface.db.commit()
        with pytest.raises(RuntimeError) as excinfo:
            iface.assert_embed_consistency([0.0] * 256)
        assert "512" in str(excinfo.value) and "256" in str(excinfo.value)

        # add() 写入路径同样被拦截
        with pytest.raises(RuntimeError):
            iface.add(content="混维写入必须失败", quality_level="C")
        assert iface.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
    finally:
        iface.db.close()


def test_assert_embed_consistency_passes_when_dim_matches(tmp_path):
    """维度一致时不抛异常（避免误伤正常写入）。"""
    iface = _make_numpy_interface(tmp_path / "dim_ok.db")
    try:
        iface.db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('embed_dim', ?)",
            [str(iface.vector_dim)],
        )
        iface.db.commit()
        iface.assert_embed_consistency()
        assert iface.add(content="维度一致可写入", quality_level="C")
    finally:
        iface.db.close()


# ============================================================
# 3. 删除级联 → vec 表无孤儿
# ============================================================


def test_delete_removes_vec_rows_on_numpy_engine(tmp_path):
    """numpy 引擎下 delete() 也必须清理 vec 表对应行，不留孤儿。"""
    db_file = tmp_path / "delete_cascade.db"
    pre = sqlite3.connect(str(db_file))
    _create_fake_vec_table(pre)
    pre.close()

    iface = _make_numpy_interface(db_file, allow_degraded=True)
    try:
        mem_id = iface.add(content="待删除记忆", quality_level="C")
        # 手工写入 vec 行（模拟历史遗留/其他进程写入的向量）
        iface.db.execute(
            "INSERT OR REPLACE INTO vec_memories(rowid, embedding, memory_id, quality) "
            "VALUES (?, ?, ?, ?)",
            [iface._get_rowid(mem_id), b"\x00" * 16, mem_id, "C"],
        )
        iface.db.commit()
        assert iface.db.execute("SELECT COUNT(*) FROM vec_memories").fetchone()[0] == 1

        assert iface.delete(mem_id) is True

        orphan = iface.db.execute(
            "SELECT COUNT(*) FROM vec_memories WHERE rowid=? OR memory_id=?",
            [iface._get_rowid(mem_id), mem_id],
        ).fetchone()[0]
        assert orphan == 0, "delete 后 vec 表仍有孤儿行"
        assert iface.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
    finally:
        iface.db.close()


# ============================================================
# 4. recall 回写 + 降级信封
# ============================================================


def _make_cle(db_file: Path) -> CognitiveLoopEntry:
    return CognitiveLoopEntry(
        storage_path=str(db_file),
        memory_id="AM-TEST-P0",
        enable_distill=False,
        poe_enforcement="off",  # 关掉 PoE 降权，避免影响命中判定
    )


def test_recall_writeback_increments_access_count(tmp_path):
    """recall 命中后 access_count+1、last_used_at 写入（R1 升级路径可达）。"""
    cle = _make_cle(tmp_path / "recall_hit.db")
    try:
        mem_id = cle._vm.add(
            content="BTC 趋势策略：突破后跟涨效果好", quality_level="C", tags=["BTC"]
        )
        results = cle.recall("BTC 趋势突破策略", top_k=5)
        assert results, "库内已有记忆，recall 不应 0 命中"

        row = cle._vm.db.execute(
            "SELECT access_count, last_used_at FROM memories WHERE id=?", [mem_id]
        ).fetchone()
        assert row["access_count"] >= 1
        assert isinstance(row["last_used_at"], int) and row["last_used_at"] > 0

        # 二次命中继续累加
        cle.recall("BTC 趋势突破策略", top_k=5)
        again = cle._vm.db.execute(
            "SELECT access_count FROM memories WHERE id=?", [mem_id]
        ).fetchone()
        assert again["access_count"] >= 2
    finally:
        cle.close()


def test_recall_zero_hit_returns_degraded_envelope(tmp_path):
    """0 命中时返回体带 degraded=True + degraded_reason。"""
    cle = _make_cle(tmp_path / "recall_empty.db")
    try:
        results = cle.recall("空库检索", top_k=3)
        assert len(results) == 0
        assert getattr(results, "degraded", False) is True
        assert getattr(results, "degraded_reason", "") in ("no_hit", "index_inconsistent")
        assert results.envelope()["degraded"] is True
    finally:
        cle.close()


def test_recall_writeback_failure_does_not_break_return(tmp_path):
    """回写失败必须 FAIL-OPEN：recall 仍返回命中结果，不抛异常。"""
    cle = _make_cle(tmp_path / "recall_writeback_fail.db")
    try:
        cle._vm.add(content="回写失败也要能召回", quality_level="C")
        # 模拟不具备 access_count 列的旧库：回写 SQL 报错
        cle._vm.db.execute("ALTER TABLE memories RENAME COLUMN access_count TO _tmp_ac")
        cle._vm.db.commit()
        results = cle.recall("回写失败", top_k=3)
        assert results, "回写失败不应吞掉 recall 结果"
    finally:
        cle.close()
