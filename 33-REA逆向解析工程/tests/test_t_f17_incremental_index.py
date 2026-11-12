"""SPEC-33-F T-F17：增量索引（文件级 Merkle + 跨版本 diff）。

验收：
  - 同内容同路径 → root_hash 稳定；改动/增删 → 精确失效清单。
  - 索引缺失/损坏 → FAIL-OPEN（按首次构建，不抛异常）。
  - analyze(incremental=true) 只附加 diff，不改变分析结果。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
from core.incremental_index import (  # noqa: E402
    build_merkle,
    diff_merkle,
    load_index,
)


def _seed(root: Path) -> None:
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")


def test_merkle_diff_added_modified_removed(tmp_path):
    _seed(tmp_path)
    first = build_merkle(tmp_path)
    assert first["count"] == 2

    same = build_merkle(tmp_path)
    assert same["root_hash"] == first["root_hash"]

    (tmp_path / "a.py").write_text("x = 42\n", encoding="utf-8")
    (tmp_path / "b.py").unlink()
    (tmp_path / "c.py").write_text("z = 3\n", encoding="utf-8")
    second = build_merkle(tmp_path)

    diff = diff_merkle(first, second)
    assert diff["added"] == ["c.py"]
    assert diff["modified"] == ["a.py"]
    assert diff["removed"] == ["b.py"]
    assert diff["invalidated_files"] == ["a.py", "b.py", "c.py"]
    assert diff["unchanged"] == 0
    assert diff["first_build"] is False


def test_first_build_and_corrupt_index(tmp_path):
    index_path = tmp_path / "idx.json"
    previous, gaps = load_index(index_path)
    assert previous is None
    assert gaps

    index_path.write_text("{broken", encoding="utf-8")
    previous, gaps = load_index(index_path)
    assert previous is None
    assert any("损坏" in gap for gap in gaps)


def test_node_persists_and_reports_invalidated(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _seed(root)
    index_path = tmp_path / "idx.json"

    first = dsh_nodes.S33_rea_incremental_index(
        {"target": str(root), "index_path": str(index_path)}
    )
    assert first["ok"] is True
    assert first["result"]["stats"]["files"] == 2
    assert first["result"]["stats"]["added"] == 2
    assert first["result"]["persisted"] is True
    assert index_path.is_file()

    (root / "a.py").write_text("x = 99\n", encoding="utf-8")
    second = dsh_nodes.S33_rea_incremental_index(
        {"target": str(root), "index_path": str(index_path)}
    )
    stats = second["result"]["stats"]
    assert stats["modified"] == 1
    assert stats["unchanged"] == 1
    assert second["result"]["invalidated_files"] == ["a.py"]
    assert second["result"]["diff"]["previous_root_hash"] == first["result"]["root_hash"]


def test_node_missing_target():
    out = dsh_nodes.S33_rea_incremental_index({"target": "/nonexistent/rea-index-probe"})
    assert out["ok"] is False
    assert out["error"] == "missing_target"


def test_analyze_incremental_attaches_diff(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _seed(root)
    index_path = tmp_path / "idx.json"

    out = dsh_nodes.S33_rea_analyze(
        {"target": str(root), "incremental": True, "index_path": str(index_path)}
    )
    assert out["ok"] is True
    block = out["result"]["incremental"]
    assert block["mode"] == "incremental_index"
    assert block["stats"]["files"] == 2
    assert json.loads(index_path.read_text(encoding="utf-8"))["root_hash"] == block["root_hash"]
