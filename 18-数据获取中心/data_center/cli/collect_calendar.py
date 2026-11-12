"""经济日历日程采集入口（未来已公布日程，独立于事件流）。

与 `collect_events` 的区别：这里额外采集「尚未发生、但已官方公布」的日程
（FOMC 会议、BLS 的 CPI/非农/PPI 发布日），写入独立的
`data_center/events/calendar_schedule.jsonl`。

为什么不写进 events.jsonl：事件流是回测可用性（available_at）事实源，
掺入未来事件会污染 39 语义事件与 24h 计数；日历只用于前端展示。

用法（在 18-数据获取中心 目录下）：
  python3 -m data_center.cli.collect_calendar --ahead-days 90
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from data_center.collectors.tradefin import fed_calendar_collector, macro_calendar_collector
from data_center.events.store import append_events, load_events

SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "events" / "calendar_schedule.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="经济日历未来日程采集")
    parser.add_argument("--days", type=int, default=30, help="回看窗口（天）")
    parser.add_argument("--ahead-days", type=int, default=90, help="未来日程窗口（天）")
    parser.add_argument("--output", default=str(SCHEDULE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    fetched: dict[str, list[dict]] = {}
    for name, module in (
        ("fed_calendar", fed_calendar_collector),
        ("macro_calendar", macro_calendar_collector),
    ):
        try:
            fetched[name] = module.fetch(days=args.days, ahead_days=args.ahead_days, now=now)
        except Exception as e:  # noqa: BLE001 — 单源失败不影响其他源
            print(f"[WARN] {name} 采集失败：{type(e).__name__}: {e}")
            fetched[name] = []

    merged = [row for rows in fetched.values() for row in rows]
    if args.dry_run:
        added = skipped = 0
    else:
        added, skipped = append_events(merged, path=args.output)

    records = load_events(args.output) if not args.dry_run else merged
    upcoming = sum(
        1 for r in records if r.get("event_time", "") >= now.isoformat().replace("+00:00", "Z")
    )
    print(f"[collect_calendar] window=-{args.days}d/+{args.ahead_days}d output={args.output}")
    for name, rows in fetched.items():
        print(f"  {name:<16}: {len(rows)} events")
    print(f"  appended={added} skipped(dup)={skipped} total={len(records)} upcoming={upcoming}")
    print(f"  by_type={json.dumps(_by_type(records), ensure_ascii=False)}")
    return 0


def _by_type(records: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        t = r.get("type", "")
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
