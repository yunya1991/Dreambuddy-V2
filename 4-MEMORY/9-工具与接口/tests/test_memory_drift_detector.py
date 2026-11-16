#!/usr/bin/env python3
"""漂移检测单测：锚点缺失 / 文件晚于记忆 / 未漂移 / 轨迹排除 / 锚点抽取 / dry-run 不写。"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_drift_detector import detect_drift, extract_anchors  # noqa: E402

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def _mkdb(tmp_path: Path, rows: list[tuple]) -> Path:
    db = tmp_path / "mem.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, quality_level TEXT, source TEXT,"
        " created_at TEXT, content TEXT, tags TEXT)"
    )
    con.executemany("INSERT INTO memories VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def _mkfile(root: Path, rel: str, mtime: datetime) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    ts = mtime.timestamp()
    os.utime(p, (ts, ts))


def test_anchor_missing_is_drift(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db = _mkdb(
        tmp_path,
        [("m1", "A", "manual", NOW.isoformat(), "见 4-MEMORY/9-工具与接口/gone.py 的结论", "")],
    )
    out = detect_drift(db_path=db, repo_root=repo)
    assert out["ok"] and out["drifted"] == 1
    assert out["items"][0]["drift"][0]["reason"] == "anchor_missing"


def test_file_newer_than_memory_is_drift(tmp_path):
    repo = tmp_path / "repo"
    _mkfile(repo, "pkg/mod.py", NOW + timedelta(days=3))
    db = _mkdb(tmp_path, [("m1", "A", "manual", NOW.isoformat(), "结论写在 pkg/mod.py", "")])
    out = detect_drift(db_path=db, repo_root=repo)
    assert out["drifted"] == 1
    assert out["items"][0]["drift"][0]["reason"] == "file_changed_after_memory"


def test_file_older_than_memory_is_clean(tmp_path):
    repo = tmp_path / "repo"
    _mkfile(repo, "pkg/mod.py", NOW - timedelta(days=30))
    db = _mkdb(tmp_path, [("m1", "A", "manual", NOW.isoformat(), "结论写在 pkg/mod.py", "")])
    out = detect_drift(db_path=db, repo_root=repo)
    assert out["with_anchors"] == 1
    assert out["drifted"] == 0


def test_trajectory_sources_excluded(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db = _mkdb(
        tmp_path,
        [("m1", "A", "rag-bridge", NOW.isoformat(), "见 gone/x.py", "")],
    )
    out = detect_drift(db_path=db, repo_root=repo)
    assert out["scanned"] == 0 and out["drifted"] == 0


def test_dry_run_never_applies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db = _mkdb(tmp_path, [("m1", "A", "manual", NOW.isoformat(), "见 gone/x.py", "")])
    out = detect_drift(db_path=db, repo_root=repo, dry_run=True)
    assert out["applied"] == 0 and out["dry_run"] is True


def test_extract_anchors_requires_directory_and_extension():
    text = "见 4-MEMORY/9-工具与接口/memory_tree.py 与 src/components/LightsView.tsx，参考 a.py"
    anchors = extract_anchors(text)
    assert "4-MEMORY/9-工具与接口/memory_tree.py" in anchors
    assert "src/components/LightsView.tsx" in anchors
    assert "a.py" not in anchors, "无目录的裸文件名不当作锚点"


def test_db_missing_degrades(tmp_path):
    out = detect_drift(db_path=tmp_path / "nope.db", repo_root=tmp_path)
    assert out["ok"] is False and out["degraded_reason"] == "db_missing"
