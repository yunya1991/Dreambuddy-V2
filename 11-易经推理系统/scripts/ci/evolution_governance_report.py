#!/usr/bin/env python3
import argparse
import glob
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_iso_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evolution weekly/monthly governance report")
    parser.add_argument("--decision-glob", default="artifacts/evolution/**/decision-*.json")
    parser.add_argument("--rollback-exec-glob", default="artifacts/evolution/rollback/executions/*.json")
    parser.add_argument("--period", choices=["week", "month"], default="week")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--now-iso", default="")
    return parser.parse_args(argv)


def _window_start(period: str, now: datetime) -> datetime:
    return now - (timedelta(days=7) if period == "week" else timedelta(days=30))


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    now = _parse_iso_utc(args.now_iso) or datetime.now(timezone.utc)
    start = _window_start(args.period, now)

    approve_count = 0
    reject_count = 0
    reason_counter: Counter[str] = Counter()
    decisions_total = 0

    for path_str in glob.glob(args.decision_glob, recursive=True):
        payload = _load_json(Path(path_str))
        ts = _parse_iso_utc(str(payload.get("timestamp") or ""))
        if ts is None or ts < start or ts > now:
            continue
        decisions_total += 1
        decision = str(payload.get("decision") or "").strip().lower()
        if decision == "approve":
            approve_count += 1
        else:
            reject_count += 1
        reasons = payload.get("reason_codes", [])
        if isinstance(reasons, list):
            for item in reasons:
                reason_counter[str(item)] += 1

    rollback_count = 0
    rollback_success = 0
    rto_values: List[int] = []
    for path_str in glob.glob(args.rollback_exec_glob, recursive=True):
        payload = _load_json(Path(path_str))
        rollback_count += 1
        status = str(payload.get("status") or "")
        if status == "applied":
            rollback_success += 1
        rto = payload.get("rto_seconds")
        if isinstance(rto, int):
            rto_values.append(rto)

    avg_rto = int(sum(rto_values) / len(rto_values)) if rto_values else 0
    report = {
        "period": args.period,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "window_end": now.isoformat().replace("+00:00", "Z"),
        "summary": {
            "total_decisions": decisions_total,
            "approve_count": approve_count,
            "reject_count": reject_count,
            "approval_reject_count": sum(count for code, count in reason_counter.items() if code.startswith("APPROVAL_")),
            "rollback_execution_count": rollback_count,
            "rollback_applied_count": rollback_success,
            "avg_rto_seconds": avg_rto,
        },
        "top_reason_codes": [{"code": code, "count": count} for code, count in reason_counter.most_common(10)],
        "schema_version": "evolution-p2-governance-report-v0.1",
    }
    _write_json(Path(args.output_json), report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
