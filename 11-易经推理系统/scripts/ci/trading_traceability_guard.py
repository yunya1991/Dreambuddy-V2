#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_FIELDS = (
    "stage_id",
    "trace_id",
    "constraint_version",
    "memory_refs",
    "evidence_refs",
    "producer",
    "schema_version",
)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(doc.get("payload"), dict):
        return doc["payload"]
    return doc


def _validate_payload(payload: Dict[str, Any], rel_path: str) -> List[str]:
    violations: List[str] = []
    for key in REQUIRED_FIELDS:
        value = payload.get(key)
        if value is None or value == "":
            violations.append(f"{rel_path}: missing `{key}`")
    if "memory_refs" in payload and not isinstance(payload.get("memory_refs"), list):
        violations.append(f"{rel_path}: `memory_refs` must be list")
    if "evidence_refs" in payload and not isinstance(payload.get("evidence_refs"), list):
        violations.append(f"{rel_path}: `evidence_refs` must be list")
    return violations


def audit_artifacts(artifacts_dir: Path, min_files: int = 1) -> List[str]:
    if not artifacts_dir.exists():
        return [f"artifacts directory not found: {artifacts_dir}"]
    files = sorted([p for p in artifacts_dir.rglob("*.json") if p.is_file()])
    if len(files) < min_files:
        return [f"expected at least {min_files} json artifact(s), got {len(files)}"]

    violations: List[str] = []
    for path in files:
        rel_path = str(path.relative_to(artifacts_dir))
        try:
            doc = _load_json(path)
            payload = _payload(doc)
            if not isinstance(payload, dict):
                violations.append(f"{rel_path}: payload is not object")
                continue
            violations.extend(_validate_payload(payload, rel_path))
        except Exception as exc:  # noqa: BLE001
            violations.append(f"{rel_path}: invalid json ({exc})")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit trading artifacts contract traceability fields.")
    parser.add_argument("--artifacts-dir", default="artifacts/trading")
    parser.add_argument("--min-files", type=int, default=1)
    args = parser.parse_args()

    violations = audit_artifacts(Path(args.artifacts_dir), min_files=max(1, int(args.min_files)))
    if violations:
        print("Trading traceability guard failed:", file=sys.stderr)
        for item in violations:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("Trading traceability guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
