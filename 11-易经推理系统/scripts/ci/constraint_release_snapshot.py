#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build constraint release snapshot JSON")
    parser.add_argument("--source-json", required=True, help="Source decision/promotion JSON")
    parser.add_argument("--release-version", required=True, help="Release version, e.g. v0.1.2")
    parser.add_argument("--output-dir", default="constraints/releases")
    parser.add_argument("--output-json", default="")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    source_path = Path(args.source_json)
    source_payload = _load_json(source_path)
    source_text = json.dumps(source_payload, ensure_ascii=False, sort_keys=True)
    source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    release_version = str(args.release_version).strip()
    if not release_version:
        raise ValueError("release-version must not be empty")

    output_path = Path(args.output_json) if str(args.output_json).strip() else Path(args.output_dir) / f"{release_version}.json"
    snapshot = {
        "release_version": release_version,
        "generated_at": _now_iso(),
        "source_ref": str(source_path),
        "source_sha256": source_sha,
        "candidate_id": str(source_payload.get("candidate_id") or ""),
        "from_version": str(source_payload.get("from_version") or source_payload.get("constraint_version_base") or ""),
        "to_version": str(source_payload.get("to_version") or release_version),
        "schema_version": "evolution-p2-constraint-release-snapshot-v0.1",
    }
    _write_json(output_path, snapshot)
    print(json.dumps(snapshot, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
