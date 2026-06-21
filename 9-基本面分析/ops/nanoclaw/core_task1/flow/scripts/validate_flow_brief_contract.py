#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _parse_dt(raw: str) -> bool:
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def _is_str(v: Any, min_len: int = 0) -> bool:
    return isinstance(v, str) and len(v) >= min_len


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _get_errs_common(obj: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not _is_str(obj.get("trace_id"), 8):
        errs.append("trace_id invalid")
    if not _is_str(obj.get("idempotency_key"), 16):
        errs.append("idempotency_key invalid")
    return errs


def validate_request(obj: Dict[str, Any]) -> List[str]:
    errs = _get_errs_common(obj)
    if obj.get("event") != "flow.brief.generate.request":
        errs.append("event must be flow.brief.generate.request")
    if not _is_str(obj.get("requested_at"), 1) or not _parse_dt(str(obj.get("requested_at"))):
        errs.append("requested_at must be ISO date-time")
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        errs.append("payload must be object")
        return errs
    if not _is_str(payload.get("flow_root"), 1):
        errs.append("payload.flow_root invalid")
    if not isinstance(payload.get("with_news"), bool):
        errs.append("payload.with_news must be boolean")
    if payload.get("output_path") is not None and not _is_str(payload.get("output_path"), 1):
        errs.append("payload.output_path must be string or null")
    if not _is_str(payload.get("timezone"), 1):
        errs.append("payload.timezone invalid")
    if not _is_str(payload.get("policy_version"), 1):
        errs.append("payload.policy_version invalid")
    return errs


def validate_receipt(obj: Dict[str, Any]) -> List[str]:
    errs = _get_errs_common(obj)
    if obj.get("event") != "flow.brief.generate.receipt":
        errs.append("event must be flow.brief.generate.receipt")
    if not isinstance(obj.get("ok"), bool):
        errs.append("ok must be boolean")
    if not _is_str(obj.get("ts"), 1) or not _parse_dt(str(obj.get("ts"))):
        errs.append("ts must be ISO date-time")
    artifacts = obj.get("artifacts")
    if not isinstance(artifacts, dict):
        errs.append("artifacts must be object")
    else:
        if not _is_str(artifacts.get("brief_path"), 1):
            errs.append("artifacts.brief_path invalid")
        if artifacts.get("regime_path") is not None and not _is_str(artifacts.get("regime_path"), 1):
            errs.append("artifacts.regime_path must be string or null")
    summary = obj.get("summary")
    if not isinstance(summary, dict):
        errs.append("summary must be object")
    else:
        if summary.get("bias") not in {"bullish", "bearish", "neutral", "unknown"}:
            errs.append("summary.bias invalid")
        if not _is_num(summary.get("composite")):
            errs.append("summary.composite must be number")
        conf = summary.get("confidence")
        if not _is_num(conf) or float(conf) < 0 or float(conf) > 1:
            errs.append("summary.confidence out of range")
        if summary.get("filter") not in {"enable", "disable", "slowdown", "unknown"}:
            errs.append("summary.filter invalid")
    quality = obj.get("quality")
    if not isinstance(quality, dict):
        errs.append("quality must be object")
    else:
        if quality.get("overall_quality") not in {"ok", "stale", "missing", "backfilled", "suspect", "unknown"}:
            errs.append("quality.overall_quality invalid")
        cov = quality.get("coverage")
        if not _is_num(cov) or float(cov) < 0 or float(cov) > 1:
            errs.append("quality.coverage out of range")
        if not isinstance(quality.get("missing_data"), list):
            errs.append("quality.missing_data must be array")
    if not isinstance(obj.get("errors"), list):
        errs.append("errors must be array")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["request", "receipt"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--check-path", action="store_true")
    args = parser.parse_args()

    p = Path(args.input).expanduser().resolve()
    if not p.exists():
        print(f"input file not found: {p}")
        return 2

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"invalid json: {e}")
        return 2

    errs = validate_request(obj) if args.mode == "request" else validate_receipt(obj)

    if args.check_path and args.mode == "receipt" and isinstance(obj, dict):
        artifacts = obj.get("artifacts")
        if isinstance(artifacts, dict):
            bp = artifacts.get("brief_path")
            if isinstance(bp, str) and bp:
                if not os.path.exists(bp):
                    errs.append(f"artifacts.brief_path not exists: {bp}")

    if errs:
        print("contract invalid")
        for e in errs:
            print(f"- {e}")
        return 1

    print("contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
