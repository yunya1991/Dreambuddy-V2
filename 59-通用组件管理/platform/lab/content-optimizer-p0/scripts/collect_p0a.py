#!/usr/bin/env python3
"""P0-A 采集通道验证器（外挂埋点，不改生产代码）。

职责：
- channel-check：检查网关 / adb / 设备表 / token，落 channel.check 事件；
- scout：调用现有 `mra xhs|douyin scout`，落 collect.request/result/parse 事件，
  并把回传 items 归一化写入 samples.csv（不存正文，只存长度与派生特征）。

边界：
- 仅使用标准库；不 import 任何组件代码；
- 埋点写失败必须 FAIL-OPEN，不影响主流程；
- 事件只落本地 platform/lab/content-optimizer-p0/，不上云。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

BASE = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE / "schema.json"
SAMPLES_PATH = BASE / "samples.csv"
EVENTS_PATH = BASE / "events" / "content_event.jsonl"
RAW_DIR = BASE / "raw"
STATE_DIR = Path(os.environ.get("MRA_STATE_DIR") or (Path.home() / ".mobile-reservation-assist"))
TRACE_DIR = STATE_DIR / "traces"
STATE_DB = STATE_DIR / "state.db"

GATEWAY_URL = os.environ.get("MRA_GATEWAY_URL", "http://127.0.0.1:8765")
SCHEMA_VERSION = "content_event.v1"
ERROR_CODES = {
    "NO_DEVICE",
    "GATEWAY_DOWN",
    "AUTH",
    "RATE_LIMIT",
    "LAYOUT_CHANGED",
    "TIMEOUT",
    "PARSE_ERROR",
    "",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _event(
    stage: str,
    action: str,
    *,
    trace_id: str,
    run_id: str,
    status: str,
    error_code: str = "",
    duration_ms: int = 0,
    counts: dict | None = None,
    refs: dict | None = None,
    detail: dict | None = None,
) -> dict:
    event = {
        "event_id": _sha(f"{trace_id}|{stage}|{run_id}"),
        "ts": _now(),
        "trace_id": trace_id,
        "run_id": run_id,
        "stage": stage,
        "action": action,
        "status": status,
        "error_code": error_code if error_code in ERROR_CODES else "PARSE_ERROR",
        "duration_ms": int(duration_ms),
        "counts": counts or {"in": 0, "out": 0, "dropped": 0},
        "schema_version": SCHEMA_VERSION,
        "refs": refs or {},
        "detail": detail or {},
    }
    try:
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return event


def _adb_devices() -> list[str]:
    try:
        done = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8)
    except Exception:
        return []
    devices = []
    for line in (done.stdout or "").splitlines()[1:]:
        if "\tdevice" in line:
            devices.append(line.split("\t")[0].strip())
    return devices


def _gateway_health() -> bool:
    try:
        with urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except Exception:
        return False


def _db_devices() -> int:
    try:
        conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2)
        try:
            row = conn.execute("select count(*) from devices").fetchone()
            return int(row[0] if row else 0)
        finally:
            conn.close()
    except Exception:
        return 0


def channel_check(run_id: str | None = None, *, emit: bool = True) -> dict:
    run_id = run_id or "p0a-channel-" + time.strftime("%Y%m%d-%H%M%S")
    gateway_ok = _gateway_health()
    devices = _adb_devices()
    db_devices = _db_devices()
    token_ok = (STATE_DIR / "gateway_token").exists()
    result = {
        "run_id": run_id,
        "gateway_ok": gateway_ok,
        "adb_devices": devices,
        "devices_count": max(len(devices), db_devices),
        "adb_ok": bool(devices),
        "token_ok": token_ok,
    }
    if emit:
        if not gateway_ok:
            status, error_code = "error", "GATEWAY_DOWN"
        elif result["devices_count"] <= 0:
            status, error_code = "degraded", "NO_DEVICE"
        else:
            status, error_code = "ok", ""
        _event(
            "channel.check",
            "channel",
            trace_id=run_id,
            run_id=run_id,
            status=status,
            error_code=error_code,
            detail=result,
        )
    return result


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_likes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith(("万", "w", "W")):
        multiplier, text = 10000, text[:-1]
    elif text.endswith("亿"):
        multiplier, text = 100000000, text[:-1]
    number = ""
    for char in text:
        if char.isdigit() or char == ".":
            number += char
        elif number:
            break
    try:
        return int(float(number) * multiplier) if number else None
    except ValueError:
        return None


def _title_pattern(title: str) -> str:
    if any(char.isdigit() for char in title):
        return "number"
    if any(token in title for token in ("?", "？", "吗", "怎么", "如何", "为什么")):
        return "question"
    if any(token in title for token in ("vs", "VS", "相比", "对比", "而是")):
        return "contrast"
    if any(token in title for token in ("如何", "3步", "三步", "避坑", "攻略", "清单", "方法")):
        return "benefit"
    if any(token in title for token in ("震惊", "必看", "绝了", "后悔", "救命", "别再")):
        return "emotion"
    return "statement" if title else "unknown"


def _schema_columns() -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return list(schema.get("properties", {}).keys())


def _normalize_item(platform: str, item: dict, query: str, collected_at: str) -> dict:
    title = str(item.get("title") or "").strip()[:100]
    body = str(item.get("body") or "")
    row = dict.fromkeys(_schema_columns())
    row.update(
        {
            "sample_id": _sha(f"{platform}|{title}|{item.get('author', '')}|{query}"),
            "platform": platform,
            "source_type": "public",
            "query": query or None,
            "rank_bucket": "unknown",
            "collected_at": collected_at,
            "collector": "scout",
            "author_followers_bucket": "unknown",
            "title": title or None,
            "title_len": len(title) if title else None,
            "title_pattern": _title_pattern(title),
            "body_len": len(body) if body else None,
            "likes": _parse_likes(item.get("likes")),
            "metrics_at": collected_at,
            "media_type": "unknown",
            "cover_type": "unknown",
            "missing_flags": "",
            "outlier_flags": "",
            "is_censored": False,
        }
    )
    missing = [
        key
        for key, value in row.items()
        if key not in ("missing_flags", "outlier_flags", "is_censored")
        and (value is None or str(value).strip() in ("", "[]"))
    ]
    row["missing_flags"] = ";".join(missing)
    return row


def _coverage(rows: list[dict], columns: Iterable[str]) -> dict:
    rows = rows or []
    meta = {"missing_flags", "outlier_flags", "is_censored"}
    field_list = [key for key in columns if key not in meta]
    missing: dict[str, int] = dict.fromkeys(field_list, 0)
    present_counts: list[int] = []
    for row in rows:
        present = 0
        for key in field_list:
            value = row.get(key)
            if value is not None and str(value).strip() not in ("", "[]"):
                present += 1
            else:
                missing[key] += 1
        present_counts.append(present)
    return {
        "fields_present_min": min(present_counts) if present_counts else 0,
        "fields_present_mean": (
            round(sum(present_counts) / len(present_counts), 1) if present_counts else 0
        ),
        "missing_fields": missing,
        "field_total": len(field_list),
    }


def _write_samples(rows: list[dict]) -> tuple[int, int]:
    columns = _schema_columns()
    existing: set[str] = set()
    SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SAMPLES_PATH.exists():
        try:
            with SAMPLES_PATH.open(encoding="utf-8", newline="") as handle:
                for item in csv.DictReader(handle):
                    if item.get("sample_id"):
                        existing.add(item["sample_id"])
        except OSError:
            pass
    written = skipped = 0
    with SAMPLES_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if SAMPLES_PATH.stat().st_size == 0:
            writer.writeheader()
        for row in rows:
            if row["sample_id"] in existing:
                skipped += 1
                continue
            flat = {key: ("" if row.get(key) is None else row.get(key)) for key in columns}
            for key in ("missing_flags", "outlier_flags"):
                if isinstance(flat.get(key), list):
                    flat[key] = ";".join(flat[key])
            if isinstance(flat.get("is_censored"), bool):
                flat["is_censored"] = "true" if flat["is_censored"] else "false"
            writer.writerow(flat)
            existing.add(row["sample_id"])
            written += 1
    return written, skipped


def _mra_cli() -> Path:
    candidates = [
        os.environ.get("MRA_CLI", ""),
        str(Path.home() / "Documents/顺风车业务/mobile-reservation-assist/skill/scripts/mra.py"),
        str(
            Path(__file__).resolve().parents[4]
            / "components/mobile-reservation-assist/skill/scripts/mra.py"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("找不到 mra.py；请设置 MRA_CLI")


def scout(platform: str, track: str, limit: int = 3, timeout: int = 60) -> dict:
    alias = {"xiaohongshu": "xhs", "xhs": "xhs", "douyin": "douyin"}.get(platform)
    if not alias:
        raise ValueError("platform 只能是 xiaohongshu 或 douyin")
    platform_name = "xiaohongshu" if alias == "xhs" else "douyin"
    run_id = f"p0a-{time.strftime('%Y%m%d-%H%M%S')}-{alias}"
    trace_id = f"p0a:{alias}:{int(time.time() * 1000)}"
    action = f"{alias}.scout"
    check = channel_check(run_id, emit=True)
    _event(
        "collect.request",
        action,
        trace_id=trace_id,
        run_id=run_id,
        status="requested",
        detail={"platform": platform_name, "track": track, "limit": limit, "timeout": timeout},
    )

    command = [
        sys.executable,
        str(_mra_cli()),
        alias,
        "scout",
        "--track",
        track,
        "--limit",
        str(max(1, min(8, int(limit)))),
        "--no-interact",
        "--timeout",
        str(max(1, int(timeout))),
        "--json",
    ]
    started = time.time()
    stdout = stderr = ""
    timed_out = False
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=max(5, int(timeout) + 30),
        )
        stdout, stderr = done.stdout or "", done.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    duration_ms = int((time.time() - started) * 1000)

    payload = _extract_json(stdout) or _extract_json(stderr)
    state = str(payload.get("state") or ("timeout" if timed_out else "error"))
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    items = payload.get("items") or detail.get("items") or []
    job_id = payload.get("job_id") or detail.get("job_id") or ""
    if not isinstance(items, list):
        items = []

    if timed_out or state == "timeout":
        status = "timeout"
        error_code = "NO_DEVICE" if int(check.get("devices_count") or 0) <= 0 else "TIMEOUT"
    elif state in ("done", "ok") and items:
        status, error_code = "done", ""
    elif state == "needs_human":
        status, error_code = "error", "LAYOUT_CHANGED"
    elif not check.get("gateway_ok"):
        status, error_code = "error", "GATEWAY_DOWN"
    else:
        status, error_code = "error", "PARSE_ERROR"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{run_id}.json"
    try:
        raw_path.write_text(stdout or json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        raw_ref = _sha_bytes((stdout or "").encode("utf-8"))
    except OSError:
        raw_ref = ""

    collected_at = _now()
    rows = [
        _normalize_item(platform_name, item, track, collected_at)
        for item in items
        if isinstance(item, dict)
    ]
    coverage = _coverage(rows, _schema_columns())

    _event(
        "collect.result",
        action,
        trace_id=trace_id,
        run_id=run_id,
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
        counts={"in": 0, "out": len(items), "dropped": 0},
        refs={"raw_sha256": raw_ref, "raw_path": str(raw_path), "job_id": str(job_id)},
        detail={
            "platform": platform_name,
            "track": track,
            "limit": limit,
            "state": state,
            "items_returned": len(items),
            "fields_present_min": coverage["fields_present_min"],
            "fields_present_mean": coverage["fields_present_mean"],
            "gateway_ok": check.get("gateway_ok"),
            "devices_count": check.get("devices_count"),
        },
    )
    written, skipped = _write_samples(rows)
    if rows:
        parse_status, parse_error = ("ok" if written + skipped > 0 else "empty"), ""
    elif items:
        parse_status, parse_error = "error", "PARSE_ERROR"
    else:
        parse_status, parse_error = "empty", ""
    _event(
        "collect.parse",
        action,
        trace_id=trace_id,
        run_id=run_id,
        status=parse_status,
        error_code=parse_error,
        counts={"in": len(items), "out": written, "dropped": skipped},
        refs={"samples_path": str(SAMPLES_PATH), "schema_version": SCHEMA_VERSION},
        detail={
            "rows_in": len(items),
            "rows_valid": len(rows),
            "rows_written": written,
            "duplicates_skipped": skipped,
            "missing_fields": coverage["missing_fields"],
            "field_total": coverage["field_total"],
        },
    )

    return {
        "run_id": run_id,
        "trace_id": trace_id,
        "platform": platform_name,
        "status": status,
        "error_code": error_code,
        "state": state,
        "job_id": job_id,
        "items_returned": len(items),
        "rows_written": written,
        "duplicates_skipped": skipped,
        "fields_present_min": coverage["fields_present_min"],
        "fields_present_mean": coverage["fields_present_mean"],
        "duration_ms": duration_ms,
        "samples_path": str(SAMPLES_PATH),
        "events_path": str(EVENTS_PATH),
        "raw_path": str(raw_path),
        "channel": check,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0-A 内容采集通道验证器（外挂埋点）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("channel-check", help="检查网关/adb/设备表/token")
    p_check.add_argument("--run-id", default="")

    p_scout = sub.add_parser("scout", help="调用现有 mra scout 并落事件与样本")
    p_scout.add_argument("--platform", required=True, choices=["xiaohongshu", "xhs", "douyin"])
    p_scout.add_argument("--track", required=True)
    p_scout.add_argument("--limit", type=int, default=3)
    p_scout.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "channel-check":
            result = channel_check(args.run_id or None)
        else:
            result = scout(args.platform, args.track, args.limit, args.timeout)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
