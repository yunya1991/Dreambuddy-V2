#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 回流：已发布台账 + 流量快照 → P0 自有样本（source_type=own）。

口径来源：docs/SPEC-20261124-内容优化引擎-content-optimizer-P0可行性验证-v0.1.md
  - §17.2 S2 段：`published.jsonl` 台账 + `fixed/metrics.json` 回流
  - §17.8 S2 回流口径：字段映射、sample_id、幂等、is_censored

约束：
  - 只读台账与 metrics，只写 samples.csv；
  - 缺失一律 null（CSV 空串），禁止补 0；
  - 幂等：保留全部 public 行，own 行整批重建后原子替换；
  - 不写 run_id / profile（schema additionalProperties=false）。

用法：
    cd platform/lab/content-optimizer-p0 && python3 scripts/ingest_own.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_p0b as p0b  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))
COLUMNS = list(p0b.ANALYSIS_FIELDS) + ["missing_flags", "outlier_flags", "is_censored"]

CHANNEL_PLATFORMS = {
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "douyin": "douyin",
}
MEDIA_TYPE = {"xiaohongshu": "image", "douyin": "video"}

# (样本列, metrics 键, 类型)
METRIC_FIELDS = [
    ("likes", "likes", int),
    ("saves", "collects", int),
    ("comments", "comments", int),
    ("shares", "shares", int),
    ("views", "views", int),
    ("impressions", "impressions", int),
    ("cover_ctr", "cover_ctr", float),
    ("avg_watch_sec", "avg_watch_sec", float),
    ("completion_rate", "completion_rate", float),
    ("two_sec_bounce", "two_sec_bounce", float),
    ("follows", "follows", int),
]

CENSOR_WINDOW_DAYS = 7


def _to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, CN_TZ).isoformat(timespec="seconds")


def _blank_row() -> dict:
    return dict.fromkeys(COLUMNS)


def _candidates(ledger_rows: list[dict]) -> tuple[list[dict], int]:
    """展开台账为 (platform, ts) 候选；同一 (run_id, platform) 只留 ts 最新一条。"""
    expanded = []
    skipped = 0
    for row in ledger_rows:
        channels = row.get("channels") or {}
        matched = 0
        for channel, state in channels.items():
            platform = CHANNEL_PLATFORMS.get(str(channel).strip().lower())
            if not platform or str(state or "").strip().lower() != "done":
                continue
            expanded.append(
                {
                    "platform": platform,
                    "ts": _to_int(row.get("ts")),
                    "run_id": str(row.get("run_id") or ""),
                    "row": row,
                }
            )
            matched += 1
        if not matched:
            skipped += 1

    latest = {}
    order = []
    for item in expanded:
        key = (item["run_id"], item["platform"])
        if key not in latest:
            order.append(key)
        current = latest.get(key)
        if current is None or (item["ts"] or -1) >= (current["ts"] or -1):
            latest[key] = item
    skipped += len(expanded) - len(latest)
    return [latest[key] for key in order], skipped


def build_own_row(item: dict, metrics: dict, now: datetime) -> dict:
    """单条候选 → samples.csv 行（缺失记 None）。"""
    ledger = item["row"]
    platform = item["platform"]
    ts = item["ts"]
    title = str(ledger.get("title") or "").strip()
    topics = [str(topic).strip() for topic in (ledger.get("topics") or []) if str(topic).strip()]
    snapshot = metrics.get(title) or {}
    published_at = _iso(ts)

    row = _blank_row()
    row["sample_id"] = (
        "own-"
        + hashlib.sha256(
            "{}|{}|{}|{}".format(platform, item["run_id"], title, published_at or "").encode(
                "utf-8"
            )
        ).hexdigest()[:12]
    )
    row["platform"] = platform
    row["source_type"] = "own"
    row["rank_bucket"] = "unknown"
    row["collected_at"] = now.isoformat(timespec="seconds")
    row["collector"] = "creator_export"
    row["author_followers_bucket"] = "unknown"
    row["published_at"] = published_at
    if ts is not None:
        point = datetime.fromtimestamp(ts, CN_TZ)
        row["publish_hour"] = point.hour
        row["weekday"] = point.isoweekday()
    row["title"] = title or None
    row["title_len"] = len(title) if title else None
    row["title_pattern"] = p0b.derive_title_pattern(title) if title else None
    row["cover_type"] = "unknown"
    row["media_type"] = MEDIA_TYPE[platform]
    row["topic_count"] = len(topics)
    row["hashtag_count"] = len(topics)

    missing = []
    if not title:
        missing.append("title")
    if ts is None:
        missing.append("ts")
    if not topics:
        missing.append("topics")
    for column, metric_key, caster in METRIC_FIELDS:
        raw = snapshot.get(metric_key)
        value = _to_int(raw) if caster is int else _to_float(raw)
        row[column] = value
        if value is None:
            missing.append(metric_key)
    row["metrics_at"] = snapshot.get("updated_at") or None

    now_ts = now.timestamp()
    row["is_censored"] = bool(ts is not None and (now_ts - ts) < CENSOR_WINDOW_DAYS * 86400)
    row["missing_flags"] = ";".join(missing)
    row["outlier_flags"] = ""
    return row


def ingest(
    ledger_rows: list[dict],
    metrics: dict,
    existing_rows: list[dict],
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    """纯函数：返回新样本行（public 保留在前、own 重建在后）与统计。"""
    now = now or datetime.now(CN_TZ)
    public_rows = [
        dict(row) for row in existing_rows if str(row.get("source_type") or "public") != "own"
    ]
    old_own = sum(1 for row in existing_rows if str(row.get("source_type")) == "own")
    candidates, skipped = _candidates(ledger_rows)
    own_rows = [build_own_row(item, metrics, now) for item in candidates]
    rows = public_rows + own_rows
    stats = {
        "added": len(own_rows),
        "replaced": old_own,
        "skipped": skipped,
        "samples": len(rows),
        "own_total": len(own_rows),
    }
    return rows, stats


def read_csv_rows(path: str) -> tuple[list[dict], list[str]]:
    if not os.path.isfile(path):
        return [], list(COLUMNS)
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or COLUMNS)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_csv_rows(path: str, rows: list[dict], columns: list[str]) -> str:
    """原子写：同目录临时文件 + os.replace。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".samples-", suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _cell(row.get(column)) for column in columns})
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return path


def _read_json(path: Path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="S2 回流：台账 + metrics → samples.csv")
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("MRA_STATE_DIR") or str(Path.home() / ".mobile-reservation-assist"),
        help="顺风车状态目录（含 fixed/published.jsonl 与 fixed/metrics.json）",
    )
    parser.add_argument("--samples", default=p0b.SAMPLES_PATH, help="样本 CSV 路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    args = parser.parse_args(argv)

    fixed = Path(args.state_dir) / "fixed"
    ledger_rows = _read_ledger(fixed / "published.jsonl")
    metrics = _read_json(fixed / "metrics.json")
    existing_rows, columns = read_csv_rows(args.samples)
    rows, stats = ingest(ledger_rows, metrics, existing_rows)
    if not args.dry_run:
        write_csv_rows(args.samples, rows, columns)
    result = dict(stats)
    result.update(
        {
            "path": args.samples,
            "ledger": len(ledger_rows),
            "metrics": len(metrics),
            "dry_run": bool(args.dry_run),
        }
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
