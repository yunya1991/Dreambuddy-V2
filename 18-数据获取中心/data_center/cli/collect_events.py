"""事件回填/增量采集入口（SPEC §3.1 / §3.2 / §10.1）。

用法（在 18-数据获取中心 目录下）：
  python3 -m data_center.cli.collect_events --days 30           # 官方源 30 天回填
  python3 -m data_center.cli.collect_events --days 2            # 日常增量
  python3 -m data_center.cli.collect_events --source fed_calendar --days 30
  python3 -m data_center.cli.collect_events --source cn --days 3 # P1-A 四中文源

输出：正文追加写入 data_center/events/bodies.jsonl，事件追加写入
data_center/events/events.jsonl（均 append-only、幂等），并打印
`available_at` 完整率（P0-C 验收 100%）与各源请求失败率（P1-A 验收 <30%）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from data_center.collectors.tradefin import (
    cls_telegraph_collector,
    fed_calendar_collector,
    jin10_collector,
    macro_calendar_collector,
    sec_edgar_collector,
    sina_finance_collector,
    wallstreetcn_collector,
)
from data_center.collectors.tradefin._result import CollectResult
from data_center.events.body_store import BODIES_PATH, append_bodies, load_bodies
from data_center.events.store import EVENTS_PATH, append_events, audit_events, load_events

COLLECTORS = {
    "sec_edgar": sec_edgar_collector,
    "fed_calendar": fed_calendar_collector,
    "macro_calendar": macro_calendar_collector,
    "sina_finance": sina_finance_collector,
    "wallstreetcn": wallstreetcn_collector,
    "cls": cls_telegraph_collector,
    "jin10": jin10_collector,
}

CN_SOURCES = ("sina_finance", "wallstreetcn", "cls", "jin10")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="传统金融事件采集（P0-C + P1-A）")
    parser.add_argument("--days", type=int, default=30, help="回填窗口（天）")
    parser.add_argument(
        "--source",
        choices=["all", "cn", *COLLECTORS],
        default="all",
        help="采集源（cn = 四个中文财经源）",
    )
    parser.add_argument("--output", default=str(EVENTS_PATH), help="events.jsonl 路径")
    parser.add_argument("--bodies-output", default=str(BODIES_PATH), help="bodies.jsonl 路径")
    parser.add_argument("--dry-run", action="store_true", help="只采集不落盘")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="失败率 ≥30% 时返回非 0（默认仅告警，FAIL-OPEN）",
    )
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if args.source == "cn":
        names = list(CN_SOURCES)
    elif args.source == "all":
        names = list(COLLECTORS)
    else:
        names = [args.source]

    known_bodies = set(load_bodies(args.bodies_output))
    collected: dict[str, list[dict]] = {}
    bodies: list[dict] = []
    for name in names:
        module = COLLECTORS[name]
        try:
            kwargs = {"days": args.days, "now": now}
            if name == "wallstreetcn":
                kwargs["known_body_ids"] = known_bodies
            result = module.fetch(**kwargs)
        except Exception as e:  # noqa: BLE001 — 单源失败不影响其他源
            print(f"[WARN] {name} 采集失败：{e}", file=sys.stderr)
            result = CollectResult()

        if isinstance(result, CollectResult):
            collected[name] = result.events
            bodies.extend(result.bodies)
        else:
            collected[name] = result

    merged = [row for rows in collected.values() for row in rows]

    if args.dry_run:
        added, skipped = 0, 0
        body_added, body_skipped = 0, 0
    else:
        body_added, body_skipped = append_bodies(bodies, path=args.bodies_output)
        added, skipped = append_events(merged, path=args.output)

    records = load_events(args.output) if not args.dry_run else merged
    audit = audit_events(records)

    print(f"[collect_events] window={args.days}d end={now.isoformat()} output={args.output}")
    total_req = total_fail = 0
    for name in names:
        stats = _guard_stats(COLLECTORS[name])
        total_req += stats.get("requests", 0)
        total_fail += stats.get("failures", 0)
        guard_note = ""
        if stats:
            guard_note = (
                f" req={stats.get('requests', 0)} fail={stats.get('failures', 0)}"
                f" rate={stats.get('failure_rate', 0.0):.0%}"
                f" circuit={'OPEN' if stats.get('circuit_open') else 'closed'}"
            )
        print(f"  {name:<16}: {len(collected[name])} events{guard_note}")
    print(f"  bodies: appended={body_added} skipped(dup)={body_skipped} total={len(bodies)}")
    print(f"  appended={added} skipped(dup)={skipped}")
    print(
        f"  file total={audit['total']} "
        f"available_at={audit['available_at_completeness']:.2%} "
        f"forward_violations={audit['available_at_before_event_time']}"
    )
    print(f"  by_source={json.dumps(audit['by_source'], ensure_ascii=False)}")
    print(f"  by_type={json.dumps(audit['by_type'], ensure_ascii=False)}")

    failure_rate = total_fail / total_req if total_req else 0.0
    print(f"  [P1-A] fetch_failure_rate={failure_rate:.2%} (requests={total_req})")

    failed = False
    if not args.dry_run and audit["total"] and audit["available_at_completeness"] < 1.0:
        print("[FAIL] available_at 完整率 < 100%（P0-C 验收不通过）", file=sys.stderr)
        failed = True
    if failure_rate >= 0.3:
        msg = f"[WARN] 抓取失败率 {failure_rate:.0%} ≥ 30%，已触发熔断/降级（P1-A 验收不通过）"
        print(msg, file=sys.stderr)
        failed = failed or args.strict
    return 1 if failed else 0


def _guard_stats(module) -> dict:
    getter = getattr(module, "guard_stats", None)
    if not callable(getter):
        return {}
    try:
        return getter() or {}
    except Exception:  # noqa: BLE001 — 统计失败不影响主流程
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
