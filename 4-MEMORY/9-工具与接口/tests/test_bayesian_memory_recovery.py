#!/usr/bin/env python3
"""bayesian_memories.json 损坏自愈：拼接残留合并恢复 / 不可恢复时备份降级。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bayesian_memory_updater import BayesianMemoryUpdater  # noqa: E402


def _entry(memory_id: str, content: str) -> dict:
    return {
        "memory_id": memory_id,
        "content": content,
        "category": "lesson",
        "confidence": 0.8,
        "quality_level": "A",
        "verify_count": 2,
        "conflict_count": 0,
        "created_at": "2026-11-01T00:00:00",
        "last_updated": "2026-11-01T00:00:00",
        "source": "test",
        "tags": ["t"],
    }


def _doc(entries: list[dict]) -> str:
    return json.dumps(
        {"schema_version": 2, "memory_count": len(entries), "memories": entries},
        ensure_ascii=False,
    )


def test_loads_valid_file(tmp_path):
    (tmp_path / "bayesian_memories.json").write_text(
        _doc([_entry("GM-1", "旧内容")]), encoding="utf-8"
    )
    updater = BayesianMemoryUpdater(tmp_path)
    assert list(updater.memories) == ["GM-1"]


def test_recovers_concatenated_documents_and_rewrites(tmp_path):
    first = _doc([_entry("GM-1", "旧内容"), _entry("GM-2", "保留")])
    second = _doc([_entry("GM-1", "新内容")])
    (tmp_path / "bayesian_memories.json").write_text(first + second, encoding="utf-8")

    updater = BayesianMemoryUpdater(tmp_path)

    assert set(updater.memories) == {"GM-1", "GM-2"}
    assert updater.memories["GM-1"].content == "新内容"  # 后写入的文档优先
    rewritten = json.loads((tmp_path / "bayesian_memories.json").read_text(encoding="utf-8"))
    assert rewritten["memory_count"] == 2
    assert any(tmp_path.glob("bayesian_memories.corrupt-*.json"))


def test_unrecoverable_file_is_backed_up_and_starts_empty(tmp_path):
    (tmp_path / "bayesian_memories.json").write_text("not a json {", encoding="utf-8")

    updater = BayesianMemoryUpdater(tmp_path)

    assert updater.memories == {}
    assert not (tmp_path / "bayesian_memories.json").exists()
    assert any(tmp_path.glob("bayesian_memories.corrupt-*.json"))
