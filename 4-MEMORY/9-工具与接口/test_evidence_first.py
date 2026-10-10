"""RED 测试：Evidence-First 增强 — record 工具支持 level/known_gaps/observations。

借鉴 33-REA 的 Evidence 结构（4层事实分级 + provenance + known_gaps）。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 将 9-工具与接口 加入 path
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture
def temp_vm():
    """创建临时 VectorMemoryInterface 实例。"""
    from vector_memory_interface import VectorMemoryInterface

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_memory.db")
    vm = VectorMemoryInterface(storage_path=db_path, engine="numpy", vector_dim=8)
    yield vm
    vm.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_add_supports_evidence_fields(temp_vm):
    """RED: add() 应支持 level/known_gaps/observations 参数并存储。"""
    mem_id = temp_vm.add(
        content="测试证据记忆",
        quality_level="B",
        confidence=0.8,
        tags=["test"],
        source="mcp",
        level="derivation",
        known_gaps=["动态调用无法静态解析"],
        observations=[{"type": "import", "file": "x.py", "line": 1}],
    )

    # 查询数据库验证字段被存储
    row = temp_vm.db.execute(
        "SELECT level, known_gaps, observations FROM memories WHERE id = ?",
        [mem_id],
    ).fetchone()

    assert row is not None
    assert row[0] == "derivation"
    assert json.loads(row[1]) == ["动态调用无法静态解析"]
    assert json.loads(row[2]) == [{"type": "import", "file": "x.py", "line": 1}]


def test_add_default_evidence_fields(temp_vm):
    """RED: 不传新参数时，level 默认 observation，known_gaps/observations 默认空。"""
    mem_id = temp_vm.add(
        content="默认证据记忆",
        quality_level="C",
        tags=["test"],
    )

    row = temp_vm.db.execute(
        "SELECT level, known_gaps, observations FROM memories WHERE id = ?",
        [mem_id],
    ).fetchone()

    assert row is not None
    assert row[0] == "observation"
    assert json.loads(row[1]) == []
    assert json.loads(row[2]) == []


def test_add_rejects_invalid_level(temp_vm):
    """RED: level 取值非法时 FAIL-OPEN 回退到 observation。"""
    mem_id = temp_vm.add(
        content="非法 level",
        level="invalid_level",
    )

    row = temp_vm.db.execute(
        "SELECT level FROM memories WHERE id = ?", [mem_id]
    ).fetchone()

    assert row[0] == "observation"  # FAIL-OPEN 回退
