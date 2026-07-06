#!/usr/bin/env python3
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evolution version compare dashboard JSON")
    parser.add_argument("--decision-dir", default="artifacts/evolution/decision")
    parser.add_argument("--rollback-dir", default="artifacts/evolution/rollback")
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def _glob_json(base: Path, pattern: str) -> List[Path]:
    if not base.exists():
        return []
    return sorted([p for p in base.rglob(pattern) if p.is_file()])


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    decision_dir = Path(args.decision_dir)
    rollback_dir = Path(args.rollback_dir)

    decision_files = _glob_json(decision_dir, "decision-*.json")
    promotion_files = _glob_json(decision_dir, "promotion-*.json")
    rollback_pointer_files = _glob_json(rollback_dir, "rollback-pointer-*.json")

    approved = 0
    rejected = 0
    approval_reject_count = 0
    reason_counter: Counter[str] = Counter()
    for path in decision_files:
        payload = _load_json(path)
        decision = str(payload.get("decision") or "").lower()
        if decision == "approve":
            approved += 1
        elif decision == "reject":
            rejected += 1
        reasons = payload.get("reason_codes", [])
        if isinstance(reasons, list):
            for code in reasons:
                reason_counter[str(code)] += 1
                if str(code).startswith("APPROVAL_"):
                    approval_reject_count += 1

    version_counter: Counter[str] = Counter()
    for path in promotion_files:
        payload = _load_json(path)
        from_v = str(payload.get("from_version") or "")
        to_v = str(payload.get("to_version") or "")
        version_counter[f"{from_v}->{to_v}"] += 1

    dashboard = {
        "summary": {
            "total_decisions": len(decision_files),
            "approved": approved,
            "rejected": rejected,
            "promotion_count": len(promotion_files),
            "rollback_pointer_count": len(rollback_pointer_files),
            "approval_reject_count": approval_reject_count,
        },
        "top_reason_codes": [{"code": code, "count": count} for code, count in reason_counter.most_common(10)],
        "version_pairs": [{"pair": pair, "count": count} for pair, count in version_counter.most_common()],
        "schema_version": "evolution-p2-version-compare-dashboard-v0.1",
    }
    _write_json(Path(args.output_json), dashboard)
    print(json.dumps(dashboard, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
