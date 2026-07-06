import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_constraint_release_snapshot_writes_target_version_file(tmp_path):
    mod = _load_module("scripts/ci/constraint_release_snapshot.py")
    source_json = tmp_path / "promotion.json"
    _write_json(
        source_json,
        {
            "candidate_id": "cand-001",
            "from_version": "v0.1",
            "to_version": "v0.1.2",
        },
    )
    out_dir = tmp_path / "releases"
    rc = mod.main(
        [
            "--source-json",
            str(source_json),
            "--release-version",
            "v0.1.2",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    out_file = out_dir / "v0.1.2.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["release_version"] == "v0.1.2"
    assert payload["candidate_id"] == "cand-001"
