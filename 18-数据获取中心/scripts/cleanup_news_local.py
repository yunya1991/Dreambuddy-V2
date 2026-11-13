#!/usr/bin/env python3
"""本地新闻数据清理（云端同步成功后执行，bounded 磁盘占用）。

覆盖四类本地新闻数据：
  1. logs — scheduler / 同步日志按大小轮转（保留尾部）
  2. data_center/events — events.jsonl / bodies.jsonl 按保留窗口裁剪
  3. backfill/newsflash_history.jsonl — 超期快讯归档为 .gz，保留近期明文
  4. data_center.db — 删除超期新闻 records 与超期监控行（metrics/quality/alerts）

默认只看不改用 --dry-run；--vacuum 才会真正收缩 db 文件（会短暂锁库）。

用法：
  python3 scripts/cleanup_news_local.py --dry-run
  python3 scripts/cleanup_news_local.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # 18-数据获取中心
EVENTS_PATH = PROJECT / "data_center" / "events" / "events.jsonl"
BODIES_PATH = PROJECT / "data_center" / "events" / "bodies.jsonl"
NEWSFLASH_PATH = PROJECT / "backfill" / "newsflash_history.jsonl"
NEWSFLASH_ARCHIVE = PROJECT / "backfill" / "newsflash_history.archive.jsonl.gz"
DB_PATH = PROJECT / "data_center.db"

LOG_FILES = (
    "scheduler.log",
    "scheduler.err.log",
    "events_cloud_sync.log",
    "events_cloud_sync.err.log",
)

NEWS_SOURCES = (
    "panewslab",
    "odaily_newsflash",
    "theblockbeats_dataview",
    "gdelt",
    "jin10",
    "wallstreetcn",
    "cls",
    "sina_finance",
)


def mb(n: float) -> str:
    return f"{n / 1048576:.1f}MB"


def parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rotate_logs(max_bytes: int, dry_run: bool, quiet: bool) -> int:
    freed = 0
    logs_dir = PROJECT / "logs"
    for name in LOG_FILES:
        path = logs_dir / name
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size <= max_bytes:
            continue
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            tail = f.read()
        tail = tail[tail.find(b"\n") + 1 :] if b"\n" in tail else tail
        if not dry_run:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(tail)
            os.replace(tmp, path)
        freed += size - len(tail)
        if not quiet:
            print(f"[logs] {name}: {mb(size)} → {mb(len(tail))}")
    return freed


def prune_events(hours: int, dry_run: bool, quiet: bool) -> int:
    if not EVENTS_PATH.is_file():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    keep_events: list[dict] = []
    dropped = 0
    with open(EVENTS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            ts = parse_ts(row.get("event_time") or row.get("available_at") or "")
            if ts is None or ts >= cutoff:
                keep_events.append(row)
            else:
                dropped += 1
    if not dropped:
        return 0
    body_refs = {
        str(r.get("body_ref")).rsplit("#", 1)[-1] for r in keep_events if r.get("body_ref")
    }
    keep_bodies: list[dict] = []
    if BODIES_PATH.is_file():
        with open(BODIES_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("id") in body_refs:
                    keep_bodies.append(row)
    events_text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep_events)
    bodies_text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep_bodies)
    before = EVENTS_PATH.stat().st_size + (
        BODIES_PATH.stat().st_size if BODIES_PATH.is_file() else 0
    )
    if not dry_run:
        EVENTS_PATH.write_text(events_text, encoding="utf-8")
        BODIES_PATH.write_text(bodies_text, encoding="utf-8")
    after = len(events_text.encode("utf-8")) + len(bodies_text.encode("utf-8"))
    freed = before - after
    if not quiet:
        print(
            f"[events] 丢弃 {dropped} 条超 {hours}h 事件，保留 {len(keep_events)} 事件/"
            f"{len(keep_bodies)} 正文，释放 {mb(max(freed, 0))}"
        )
    return max(freed, 0)


def prune_newsflash(days: int, dry_run: bool, quiet: bool) -> int:
    if not NEWSFLASH_PATH.is_file():
        return 0
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    keep: list[str] = []
    archive: list[str] = []
    with open(NEWSFLASH_PATH, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                ts = int(json.loads(line).get("published_ms") or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                ts = 0
            (keep if ts >= cutoff_ms else archive).append(
                line if line.endswith("\n") else line + "\n"
            )
    if not archive:
        return 0
    before = NEWSFLASH_PATH.stat().st_size
    after = len("".join(keep).encode("utf-8"))
    if not dry_run:
        if NEWSFLASH_ARCHIVE.is_file():
            # 追加写 gz：重新压缩历史 + 本次归档
            with gzip.open(NEWSFLASH_ARCHIVE, "rb") as g:
                old = g.read()
        else:
            old = b""
        with gzip.open(NEWSFLASH_ARCHIVE, "wb", compresslevel=6) as g:
            g.write(old)
            g.write("".join(archive).encode("utf-8"))
        NEWSFLASH_PATH.write_text("".join(keep), encoding="utf-8")
    if not quiet:
        print(
            f"[newsflash] 归档 {len(archive)} 条超 {days}d 快讯 → {NEWSFLASH_ARCHIVE.name}，"
            f"明文 {mb(before)} → {mb(after)}"
        )
    return max(before - after, 0)


def prune_db(news_days: int, monitor_days: int, vacuum: bool, dry_run: bool, quiet: bool) -> int:
    if not DB_PATH.is_file():
        return 0
    before = DB_PATH.stat().st_size
    news_cutoff = (datetime.now(timezone.utc) - timedelta(days=news_days)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    mon_cutoff = (datetime.now(timezone.utc) - timedelta(days=monitor_days)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    placeholders = ",".join("?" for _ in NEWS_SOURCES)
    news_sql = (
        "delete from records where (category = 'news' or source in "
        f"({placeholders})) and substr(timestamp,1,19) < ?"
    )
    mon_sql = {
        "metrics": "delete from metrics where substr(ts,1,19) < ?",
        "quality_issues": "delete from quality_issues where substr(ts,1,19) < ?",
        "alerts": "delete from alerts where substr(ts,1,19) < ?",
    }
    deleted = 0
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        cur = conn.cursor()
        cur.execute(news_sql, (*NEWS_SOURCES, news_cutoff))
        news_deleted = cur.rowcount
        cur.execute("select count(*) from metrics where substr(ts,1,19) < ?", (mon_cutoff,))
        mon_deleted = cur.fetchone()[0]
        for sql in mon_sql.values():
            cur.execute(sql, (mon_cutoff,))
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
            if (news_deleted or mon_deleted) and vacuum:
                cur.execute("VACUUM")
        conn.close()
        deleted = max(news_deleted, 0) + max(mon_deleted, 0)
    except sqlite3.Error as exc:
        if not quiet:
            print(f"[db] 跳过（{exc}）")
        return 0
    after = DB_PATH.stat().st_size
    if not quiet and (deleted or before != after):
        print(
            f"[db] 删除新闻 records={news_deleted}、监控行={mon_deleted}，"
            f"文件 {mb(before)} → {mb(after)}" + ("（已 VACUUM）" if vacuum and not dry_run else "")
        )
    return max(before - after, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="本地新闻数据清理")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-max-mb", type=int, default=5)
    parser.add_argument("--events-retention-hours", type=int, default=48)
    parser.add_argument("--newsflash-retention-days", type=int, default=365)
    parser.add_argument("--db-news-days", type=int, default=7)
    parser.add_argument("--db-monitor-days", type=int, default=30)
    parser.add_argument("--vacuum", action="store_true", help="删除后 VACUUM 收缩 db（会短暂锁库）")
    parser.add_argument("--skip-newsflash", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    started = time.time()
    total = 0
    total += rotate_logs(args.log_max_mb * 1048576, args.dry_run, args.quiet)
    total += prune_events(args.events_retention_hours, args.dry_run, args.quiet)
    if not args.skip_newsflash:
        total += prune_newsflash(args.newsflash_retention_days, args.dry_run, args.quiet)
    total += prune_db(
        args.db_news_days, args.db_monitor_days, args.vacuum, args.dry_run, args.quiet
    )
    if not args.quiet:
        mode = "DRY-RUN 预计" if args.dry_run else "实际"
        print(f"[cleanup] {mode}释放 {mb(total)}，耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
