"""SPEC-33-F T-F07：只读 git 变更考古与快照 section（RED）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.archaeology_adapter import scan_archaeology  # noqa: E402


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=True, text=True)


def _commit(root: Path, files: list[str], author: str, when: datetime) -> None:
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"# {author} {when.isoformat()}\n")
    _git(root, "add", "--", *files)
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": f"{author.lower()}@example.com",
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": f"{author.lower()}@example.com",
            "GIT_AUTHOR_DATE": when.isoformat(),
            "GIT_COMMITTER_DATE": when.isoformat(),
        }
    )
    _git(root, "commit", "-m", f"change {author} {when.date()}", env=env)


def _repo(root: Path, now: datetime) -> None:
    root.mkdir()
    _git(root, "init")
    _commit(root, ["a.py", "b.py"], "Alice", now - timedelta(days=100))
    _commit(root, ["a.py", "b.py"], "Alice", now - timedelta(days=80))
    _commit(root, ["a.py", "c.py"], "Bob", now - timedelta(days=70))
    _commit(root, ["a.py"], "Carol", now - timedelta(days=60))
    _commit(root, ["a.py"], "Bob", now - timedelta(days=50))


def test_real_git_archaeology_hotspot_cochange_bus_factor_and_radius(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    root = tmp_path / "repo"
    _repo(root, now)

    report = scan_archaeology(str(root), now=now)

    assert report["section"] == "archaeology"
    assert report["degraded"] is False
    assert report["hotspots"][0]["file"] == "a.py"
    assert report["hotspots"][0]["commits"] == 5
    assert len(report["hotspots"]) <= 20
    assert {tuple(item["files"]): item["count"] for item in report["co_change"]}[
        ("a.py", "b.py")
    ] == 2
    a_bus = next(item for item in report["bus_factor"] if item["file"] == "a.py")
    assert a_bus["factor"] == 2
    assert a_bus["authors"] == ["Alice", "Bob", "Carol"]
    a_radius = next(item for item in report["change_radius_90d"] if item["file"] == "a.py")
    assert a_radius["commits_90d"] == 4
    assert a_radius["co_changed_files"] == ["b.py", "c.py"]
    assert a_radius["radius"] == 2
    assert report["evidence"][0]["provenance"]["analysis"] == "git_archaeology"


def test_archaeology_hotspots_are_limited_to_20(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _commit(root, [f"file-{index:02d}.py" for index in range(25)], "Alice", now)

    report = scan_archaeology(str(root), now=now)

    assert len(report["hotspots"]) == 20
    assert report["bus_factor"][0]["factor"] == 1


def test_archaeology_non_repo_is_degraded(tmp_path: Path) -> None:
    report = scan_archaeology(str(tmp_path))

    assert report["degraded"] is True
    assert report["hotspots"] == []
    assert report["co_change"] == []
    assert report["known_gaps"]
    assert report["evidence"]


def test_snapshot_archaeology_section(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    now = datetime.now(timezone.utc)
    root = tmp_path / "repo"
    _repo(root, now)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    (snapshot_dir / "arch.json").write_text(
        json.dumps({"snapshot_id": "arch", "target": str(root), "raw": {}}),
        encoding="utf-8",
    )

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "arch", "section": "archaeology", "limit": 2}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert result["section"] == "archaeology"
    assert result["total"] == 3
    assert len(result["items"]) == 2
    assert result["next_cursor"] == 2
    assert result["report"]["hotspots"][0]["file"] == "a.py"
