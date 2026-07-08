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


def test_constraint_rollback_dry_run_succeeds(tmp_path):
    mod = _load_module("scripts/ci/constraint_rollback.py")
    pointer_path = tmp_path / "pointer.json"
    restore_ref = tmp_path / "constraints" / "releases" / "v0.1.json"
    restore_ref.parent.mkdir(parents=True, exist_ok=True)
    restore_ref.write_text("{}", encoding="utf-8")
    _write_json(
        pointer_path,
        {
            "pointer_id": "rp-1",
            "candidate_id": "cand-1",
            "restore_ref": str(restore_ref),
            "from_version": "v0.1",
            "to_version": "v0.1.2",
        },
    )
    output_path = tmp_path / "exec.json"
    rc = mod.main(
        [
            "--rollback-pointer-json",
            str(pointer_path),
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "planned"
    assert payload["execution_mode"] == "dry-run"


def test_constraint_rollback_apply_requires_allow_flag(tmp_path):
    mod = _load_module("scripts/ci/constraint_rollback.py")
    pointer_path = tmp_path / "pointer.json"
    _write_json(
        pointer_path,
        {
            "pointer_id": "rp-2",
            "candidate_id": "cand-2",
            "restore_ref": "/tmp/not-used.json",
            "from_version": "v0.1",
            "to_version": "v0.1.2",
        },
    )
    output_path = tmp_path / "exec.json"
    rc = mod.main(
        [
            "--rollback-pointer-json",
            str(pointer_path),
            "--execution-mode",
            "apply",
            "--output-json",
            str(output_path),
        ]
    )
    assert rc == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "APPLY_NOT_ALLOWED" in payload["reason_codes"]
