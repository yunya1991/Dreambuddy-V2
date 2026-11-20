#!/usr/bin/env python3
"""事件上下文五层装配（只装配不评价）。

用法:
    python3 context.py --subject AAPL --latest
    python3 context.py --event-id <id> --subject AAPL
    python3 context.py --event-id <id> --feed fed-all
    python3 context.py --subject AAPL --since 60 --json

五层: event / entities / analogues / sources / assembly
约束: 不做解读、不做方向判断、不给建议；输出前自检红线词表。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events as ev  # noqa: E402
import cloud  # noqa: E402

VERSION = "1.0.0"
RULE_VERSION = "v1"
LIMITS = "仅装配已发生事实与同类事件次数，不含影响判断、方向判断或建议。"

BANNED = ["利多", "利空", "利好", "看多", "看空", "看涨", "看跌", "强势", "弱势",
          "机会", "值得关注", "影响有限", "建议买入", "建议卖出", "目标价", "评级",
          "推荐", "优选", "最佳", "首选", "明日", "后市", "预计", "有望"]


def scan(obj):
    text = json.dumps(obj, ensure_ascii=False)
    hits = [w for w in BANNED if w in text]
    return hits


def find_event(event_id, subject, feed, since, types):
    if subject:
        rows, info = ev.company_events(subject, since, types)
        for r in rows:
            if r["event_id"] == event_id:
                return r, info
        return None, info
    if feed:
        for r in ev.feed_events(feed, max(since, 730)):
            if r["event_id"] == event_id:
                return r, None
        return None, None
    for f in ev.FEEDS:
        for r in ev.feed_events(f, max(since, 730)):
            if r["event_id"] == event_id:
                return r, None
    return None, None


def count_analogues(row, info, subject, since):
    """同类事件次数：同 source + 同 type（同一级事项），观察窗 24 个月。"""
    item = None
    for f in row["facts"]:
        m = re.search(r"事项编号\s+([0-9.]+)", f)
        if m:
            item = m.group(1)
            break
    months = max(since, 730)
    if row["source_key"] == "sec-submissions" and info is not None:
        recent = info.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        since_date = (datetime.now() - timedelta(days=months)).strftime("%Y-%m-%d")
        n = 0
        for i, form in enumerate(forms):
            if form != row["type"]:
                continue
            if recent["filingDate"][i] < since_date:
                continue
            if item:
                items = (recent.get("items", [""] * len(forms))[i] or "")
                if item not in items:
                    continue
            n += 1
        return {"key": {"source": row["source"], "type": row["type"], "item": item},
                "n": n, "window": "24m", "stat": None, "stat_window": "T+5",
                "note": "n 为同类事件次数；收益类统计依赖行情授权，本期未启用"}
    if row["source_key"] in ev.FEEDS:
        n = 0
        for r in ev.feed_events(row["source_key"], months):
            if r["type"] == row["type"]:
                n += 1
        return {"key": {"source": row["source"], "type": row["type"], "item": None},
                "n": n, "window": "24m", "stat": None, "stat_window": "T+5",
                "note": "n 为已发布条目数；收益类统计依赖行情授权，本期未启用"}
    return {"key": {"source": row["source"], "type": row["type"], "item": item}, "n": 0,
            "window": "24m", "stat": None, "stat_window": "T+5", "note": "无法统计同类事件"}


def build(row, info, subject, since):
    entities = {"tickers": [], "sector": None, "supply_chain": [],
                "entity_source": "SEC company_tickers / SIC"}
    if row["subject"].get("ticker"):
        entities["tickers"] = [row["subject"]["ticker"]]
    if info and info.get("sicDescription"):
        entities["sector"] = {"code": info.get("sic"), "label": info.get("sicDescription")}

    analogues = count_analogues(row, info, subject, since)
    title = row.get("title") or "{} - {}".format(row["type"], row["subject"].get("name", ""))
    payload = {
        "skill": "event-context",
        "version": VERSION,
        "event_id": row["event_id"],
        "data_route": "local",
        "event": {
            "time": row["time"],
            "source": row["source"],
            "type": row["type"],
            "subject": row["subject"],
            "headline_facts": row["facts"],
            "url": row["url"],
        },
        "entities": entities,
        "analogues": analogues,
        "sources": [{
            "title": title[:120],
            "url": row["url"],
            "license": row["license"],
            "retrieved_at": ev.iso_now(),
        }],
        "assembly": {
            "rule_version": RULE_VERSION,
            "fields_filled": 0,
            "fields_empty": [],
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        },
        "limits": LIMITS,
    }
    empty = []
    if not entities["tickers"]:
        empty.append("entities.tickers")
    if not entities["sector"]:
        empty.append("entities.sector")
    if not entities["supply_chain"]:
        empty.append("entities.supply_chain")
    if payload["analogues"]["stat"] is None:
        empty.append("analogues.stat")
    payload["assembly"]["fields_empty"] = empty
    payload["assembly"]["fields_filled"] = 5 - (1 if empty else 0)
    return payload


def render(p, data_date):
    e = p["event"]
    out = [
        "事件上下文 · {} · 生成于 {}".format(e["time"], datetime.now().strftime("%Y-%m-%d %H:%M")),
        "",
        "## 1 事件",
        "| 项 | 值 |",
        "|---|---|",
        "| event_id | {} |".format(p["event_id"]),
        "| 时间 | {} |".format(e["time"]),
        "| 来源 | {} |".format(e["source"]),
        "| 类型 | {} |".format(e["type"]),
        "| 主体 | {} |".format(e["subject"].get("ticker") or e["subject"].get("name") or "—"),
        "| 链接 | {} |".format(e["url"]),
        "",
        "事实要点：",
    ]
    for f in e["headline_facts"]:
        out.append("- " + f)
    out += ["", "## 2 实体"]
    ent = p["entities"]
    out.append("- 标的：{}".format("、".join(ent["tickers"]) if ent["tickers"] else "—"))
    out.append("- 行业：{}".format(ent["sector"]["label"] if ent["sector"] else "—"))
    out.append("- 上下游：{}".format("、".join(ent["supply_chain"]) if ent["supply_chain"] else "未提供"))
    a = p["analogues"]
    out += ["", "## 3 同类事件",
            "- 计数口径：{} 内 {} 类事件共 {} 次".format(a["window"], a["key"]["type"], a["n"]),
            "- 收益统计：{}".format("未启用（需行情授权）" if a["stat"] is None else a["stat"]),
            "- 说明：{}".format(a["note"]),
            "", "## 4 来源"]
    for s in p["sources"]:
        out.append("- {}（{}）".format(s["title"], s["license"]))
        out.append("  {}".format(s["url"]))
    out += ["", "## 5 边界", p["limits"],
            "- 数据通道：{}".format("云端" if p.get("data_route") == "cloud" else "本地直连")]
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="事件上下文五层装配")
    p.add_argument("--event-id", default=None)
    p.add_argument("--subject", default=None)
    p.add_argument("--feed", default=None, choices=sorted(ev.FEEDS))
    p.add_argument("--latest", action="store_true")
    p.add_argument("--types", default="")
    p.add_argument("--since", type=int, default=60)
    p.add_argument("--json", action="store_true")
    p.add_argument("--endpoint", default="auto", choices=["auto", "cloud", "local"],
                   help="数据通道：auto 云端优先并自动回退本地")
    p.add_argument("--version", action="version", version="event-context " + VERSION)
    a = p.parse_args(argv)

    if a.endpoint != "local":
        cp = cloud.call("event-context", {
            "event_id": a.event_id, "subject": a.subject, "feed": a.feed,
            "latest": 1 if a.latest else None, "since": a.since, "types": a.types})
        if cp and cp.get("event"):
            cp["data_route"] = "cloud"
            hits = scan(cp)
            if hits:
                print("E_SCHEMA：装配结果命中红线词表（{}），已拒绝输出".format("、".join(hits)),
                      file=sys.stderr)
                return 1
            print(json.dumps(cp, ensure_ascii=False, indent=2) if a.json
                  else render(cp, cp["event"]["time"]))
            return 0
        if a.endpoint == "cloud":
            print("数据不可用：云端通道不可用（{}）".format(cloud.describe()))
            return 1
    ev.set_endpoint("local")

    types = [x.strip() for x in a.types.split(",") if x.strip()]
    row, info, missing = None, None, []

    try:
        if a.event_id:
            row, info = find_event(a.event_id, a.subject, a.feed, a.since, types)
            if row is None:
                print("E_INPUT：未找到该 event_id；请补充范围提示（--subject 或 --feed），"
                      "或用 events.py 重新列出事件", file=sys.stderr)
                return 2
        elif a.subject and a.latest:
            rows, info = ev.company_events(a.subject, a.since, types)
            if not rows:
                missing.append({"key": a.subject, "code": "E_EMPTY", "detail": "no events"})
            else:
                row = rows[0]
        elif a.feed and a.latest:
            rows = ev.feed_events(a.feed, a.since)
            if not rows:
                missing.append({"key": a.feed, "code": "E_EMPTY", "detail": "no events"})
            else:
                row = rows[0]
        else:
            print("E_INPUT：用法为 --subject X --latest 或 --event-id <id> [--subject X|--feed F]",
                  file=sys.stderr)
            return 2
    except ev.UnknownTicker:
        print("E_INPUT：未收录的 ticker「{}」，请使用美股代码，如 AAPL / MSFT".format(a.subject),
              file=sys.stderr)
        return 2
    except Exception as exc:
        missing.append({"key": a.subject or a.feed, "code": ev.err_code(exc),
                        "detail": type(exc).__name__})

    if row is None:
        if a.json:
            print(json.dumps({"skill": "event-context", "version": VERSION, "rows": [],
                              "missing": missing, "limits": LIMITS}, ensure_ascii=False, indent=2))
        else:
            print("数据不可用：{}".format("、".join(m["key"] for m in missing) or "无匹配事件"))
        return 1

    payload = build(row, info, a.subject, a.since)
    hits = scan(payload)
    if hits:
        print("E_SCHEMA：装配结果命中红线词表（{}），已拒绝输出，请修复模板".format("、".join(hits)),
              file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(payload, payload["event"]["time"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
