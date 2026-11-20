#!/usr/bin/env python3
"""可装配指针清单（handoff 契约 v1.0）。

用法:
    python3 handoff.py --subject AAPL --since 30
    python3 handoff.py --feed fed-all --since 7 --budget 800 --json
    python3 handoff.py --version

用途:
    把事件五层结果的前两层（事件 + 来源）转成「可装配指针」，装认知管家
    （CogSteward）的用户可直接交给 `cm pack` 按 token 预算装配最小上下文。

约束:
    只读、只输出指针与元数据、不写文件、不改造事件内容。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kernel import handoff  # noqa: E402

import events as ev  # noqa: E402

VERSION = "1.0.0"
HANDOFF_VERSION = handoff.HANDOFF_VERSION
LIMITS = "仅提供可装配指针，不含判断与建议。"


def to_items(rows):
    items = []
    for r in rows:
        title = r.get("title") or "{} - {}".format(
            r["type"], r["subject"].get("ticker") or r["subject"].get("name") or ""
        )
        it = {
            "id": "event:" + r["event_id"],
            "kind": "event",
            "title": title[:120],
            "license": r["license"],
            "url": r["url"],
            "event_time": r["time"],
            "source": r["source"],
            "type": r["type"],
        }
        it["estimated_tokens"] = handoff.estimate_tokens(it)
        items.append(it)
    return items


def main(argv=None):
    p = argparse.ArgumentParser(description="事件可装配指针清单（handoff v1.0）")
    p.add_argument("--subject", default=None)
    p.add_argument("--feed", default=None, choices=sorted(ev.FEEDS))
    p.add_argument("--types", default="")
    p.add_argument("--since", type=int, default=30)
    p.add_argument("--budget", type=int, default=2000)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--endpoint",
        default="auto",
        choices=["auto", "cloud", "local"],
        help="数据通道：auto 云端优先并自动回退本地",
    )
    p.add_argument("--version", action="version", version="event-context " + VERSION)
    a = p.parse_args(argv)

    ev.set_endpoint(a.endpoint)

    if bool(a.subject) == bool(a.feed):
        print("E_INPUT：--subject 与 --feed 二选一", file=sys.stderr)
        return 2
    if a.budget < 100:
        print("E_INPUT：--budget 不得小于 100", file=sys.stderr)
        return 2

    types = [x.strip() for x in a.types.split(",") if x.strip()]
    items, missing = [], []
    try:
        if a.subject:
            rows, _ = ev.company_events(a.subject, a.since, types)
        else:
            rows = ev.feed_events(a.feed, a.since)
        items = to_items(rows)
        if not items:
            missing.append(
                {"key": a.subject or a.feed, "code": "E_EMPTY", "detail": "no events in window"}
            )
    except Exception as exc:
        missing.append(
            {"key": a.subject or a.feed, "code": ev.err_code(exc), "detail": type(exc).__name__}
        )

    picked, skipped, used = handoff.pack(items, a.budget)
    result = handoff.envelope(
        skill="event-context",
        target="cogsteward/pack",
        budget=a.budget,
        items=picked,
        missing=missing,
        skipped=skipped,
        used=used,
        limits=LIMITS,
    )

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "可装配指针 · target={} · 预算 {} tokens · 已用 {}".format(
                result["target"], a.budget, used
            )
        )
        print("")
        print("| id | 标题 | 来源 | 时间 | token |")
        print("|---|---|---|---|---|")
        for it in picked:
            print(
                "| {} | {} | {} | {} | {} |".format(
                    it["id"], it["title"], it["source"], it["event_time"], it["estimated_tokens"]
                )
            )
        if missing:
            print("")
            print("缺失：{}".format("、".join(m["key"] for m in missing)))
        print("")
        print("说明：{}".format(LIMITS))

    return 0 if picked else 1


if __name__ == "__main__":
    sys.exit(main())
