"""N-P1b 隔离区集成 recall 测试（RED 阶段）。

文档要求：
- 隔离记忆不进默认 recall
- include_quarantined=True 可显式查询
- 恢复后 confidence 重初始化
"""
import os
import sys
import pytest

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_SCRIPT_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)


def _make_cle(tmp_path):
    from cognitive_loop_entry import CognitiveLoopEntry
    db_path = str(tmp_path / "test_mem.db")
    cle = CognitiveLoopEntry(storage_path=db_path, memory_id="test-quarantine-recall")
    return cle


def test_recall_excludes_quarantined_by_default(tmp_path):
    """默认 recall 不应返回隔离区记忆。"""
    cle = _make_cle(tmp_path)
    try:
        # 创建两条记忆
        mid1 = cle.record("test content A", quality_level="B")
        mid2 = cle.record("test content B", quality_level="B")

        # 隔离第一条
        cle._quarantine.quarantine(mid1)

        results = cle.recall("test content", top_k=10)
        ids = [r["id"] for r in results]
        assert mid1 not in ids  # 隔离的不返回
        assert mid2 in ids  # 未隔离的返回
    finally:
        cle.close()


def test_recall_include_quarantined(tmp_path):
    """include_quarantined=True 时返回隔离记忆。"""
    cle = _make_cle(tmp_path)
    try:
        mid1 = cle.record("test content A", quality_level="B")
        mid2 = cle.record("test content B", quality_level="B")

        cle._quarantine.quarantine(mid1)

        results = cle.recall("test content", top_k=10, include_quarantined=True)
        ids = [r["id"] for r in results]
        assert mid1 in ids  # 显式请求时返回
        assert mid2 in ids
    finally:
        cle.close()


def test_restore_from_quarantine_resets_confidence(tmp_path):
    """从隔离区恢复后，confidence 应重初始化到 C 档基线。"""
    cle = _make_cle(tmp_path)
    try:
        mid1 = cle.record("test content A", quality_level="C")

        # 隔离
        cle._quarantine.quarantine(mid1)
        assert cle._quarantine.is_quarantined(mid1)

        # 恢复
        cle.restore_from_quarantine(mid1)
        assert not cle._quarantine.is_quarantined(mid1)

        # 恢复后 confidence 应为 C 档基线（约 0.4）
        mem = cle._vm.get(mid1)
        if mem is not None:
            conf = getattr(mem, "confidence", None)
            if conf is not None:
                assert 0.3 <= conf <= 0.5  # C 档基线范围
    finally:
        cle.close()


def test_quarantine_status(tmp_path):
    cle = _make_cle(tmp_path)
    try:
        mid1 = cle.record("test", quality_level="C")
        cle._quarantine.quarantine(mid1)
        status = cle.quarantine_status()
        assert status["quarantined_count"] >= 1
    finally:
        cle.close()
