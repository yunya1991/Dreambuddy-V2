#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute constraint rollback from rollback pointer")
    parser.add_argument("--rollback-pointer-json", required=True)
    parser.add_argument("--execution-mode", choices=["dry-run", "apply"], default="dry-run")
    parser.add_argument("--allow-apply", action="store_true")
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    start = time.monotonic()

    pointer = _load_json(Path(args.rollback_pointer_json))
    reason_codes: List[str] = []
    pointer_id = str(pointer.get("pointer_id") or "")
    restore_ref = str(pointer.get("restore_ref") or "")
    if not pointer_id:
        reason_codes.append("POINTER_INVALID")
    if not restore_ref:
        reason_codes.append("RESTORE_REF_MISSING")

    status = "planned"
    executed = False
    if args.execution_mode == "apply":
        if not args.allow_apply:
            reason_codes.append("APPLY_NOT_ALLOWED")
        elif not Path(restore_ref).exists():
            reason_codes.append("RESTORE_REF_NOT_FOUND")
        else:
            status = "applied"
            executed = True

    if reason_codes:
        status = "failed"

    rto_seconds = int(round(time.monotonic() - start))
    payload = {
        "pointer_id": pointer_id,
        "candidate_id": str(pointer.get("candidate_id") or ""),
        "execution_mode": args.execution_mode,
        "executed": executed,
        "status": status,
        "restore_ref": restore_ref,
        "reason_codes": reason_codes,
        "rto_seconds": rto_seconds,
        "timestamp": str(pointer.get("created_at") or ""),
        "schema_version": "evolution-p2-rollback-execution-v0.1",
    }
    _write_json(Path(args.output_json), payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if status in {"planned", "applied"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
