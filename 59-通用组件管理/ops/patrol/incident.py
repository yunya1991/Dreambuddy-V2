#!/usr/bin/env python3
"""巡检事件台账：把异常持久化为可交接的工单，供 Agent 接管闭环。

事件状态：open（待接管）→ acked（Agent 已认领）→ closed（已修复/已忽略）
存储：~/.local/share/dreambuddy/patrol/incidents/<id>.json，可用 PATROL_STATE_DIR 覆盖。

用法:
    incident.py list                 # 列出所有未关闭事件
    incident.py show <id>            # 查看事件详情
    incident.py ack <id> --note "已定位到 xxx"
    incident.py close <id> --note "重启后恢复，根因 ssh 抖动"
    incident.py stats
退出码：0 成功 / 1 无此事件 / 2 参数错误
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))


def state_dir():
    return os.environ.get("PATROL_STATE_DIR") or os.path.expanduser(
        "~/.local/share/dreambuddy/patrol")


def incident_dir():
    path = os.path.join(state_dir(), "incidents")
    os.makedirs(path, exist_ok=True)
    return path


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def signature(issues):
    keys = sorted({item.get("check", "unknown") for item in issues})
    return hashlib.sha1("|".join(keys).encode()).hexdigest()[:8]


def path_of(incident_id):
    return os.path.join(incident_dir(), incident_id + ".json")


def load(incident_id):
    path = path_of(incident_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save(record):
    with open(path_of(record["id"]), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)


def all_records():
    items = []
    for name in sorted(os.listdir(incident_dir())):
        if name.endswith(".json"):
            items.append(load(name[:-5]))
    return [x for x in items if x]


def open_ids():
    return [r["id"] for r in all_records() if r.get("status") != "closed"]


def find_open(sig):
    for record in all_records():
        if record.get("signature") == sig and record.get("status") != "closed":
            return record
    return None


def report(record):
    """巡检发现异常时调用：同签名未关闭则累加，否则新建。返回 (record, is_new)。"""
    sig = signature(record.get("issues") or [])
    existing = find_open(sig)
    if existing:
        existing["last_seen"] = record.get("ts") or now()
        existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
        existing["evidence"] = {
            "issues": record.get("issues"),
            "billing": record.get("billing"),
            "upstream": record.get("upstream"),
            "diagnosis": record.get("diagnosis"),
        }
        existing["auto_fix"] = record.get("auto_fix")
        save(existing)
        return existing, False

    incident_id = "{}-{}".format(datetime.now(TZ).strftime("%Y%m%d%H%M%S"), sig)
    payload = {
        "id": incident_id,
        "status": "open",
        "signature": sig,
        "created_at": record.get("ts") or now(),
        "last_seen": record.get("ts") or now(),
        "occurrences": 1,
        "checks": sorted({i.get("check") for i in record.get("issues") or []}),
        "evidence": {
            "issues": record.get("issues"),
            "billing": record.get("billing"),
            "upstream": record.get("upstream"),
            "diagnosis": record.get("diagnosis"),
        },
        "auto_fix": record.get("auto_fix"),
        "history": [{"ts": now(), "action": "opened"}],
    }
    save(payload)
    return payload, True


def resolve_open(reason):
    """巡检恢复正常时调用：关闭所有 open/acked 事件。返回被关闭的 id 列表。"""
    closed = []
    for record in all_records():
        if record.get("status") != "closed":
            record["status"] = "closed"
            record["closed_at"] = now()
            record["close_reason"] = reason
            record.setdefault("history", []).append(
                {"ts": now(), "action": "closed_by_patrol", "note": reason})
            save(record)
            closed.append(record["id"])
    return closed


def main(argv=None):
    parser = argparse.ArgumentParser(description="巡检事件台账")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出未关闭事件")
    show = sub.add_parser("show", help="查看事件")
    show.add_argument("id")
    ack = sub.add_parser("ack", help="认领事件")
    ack.add_argument("id")
    ack.add_argument("--note", default="")
    close = sub.add_parser("close", help="关闭事件")
    close.add_argument("id")
    close.add_argument("--note", default="")
    sub.add_parser("stats", help="统计")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 2

    if args.cmd == "list":
        ids = open_ids()
        if not ids:
            print("无未关闭事件")
            return 0
        for incident_id in ids:
            record = load(incident_id)
            print("{}  [{}]  {} 次  {}  {}".format(
                record["id"], record["status"], record.get("occurrences", 1),
                record.get("last_seen"), ",".join(record.get("checks") or [])))
        return 0

    if args.cmd == "show":
        record = load(args.id)
        if not record:
            print("无此事件: " + args.id, file=sys.stderr)
            return 1
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    if args.cmd in ("ack", "close"):
        record = load(args.id)
        if not record:
            print("无此事件: " + args.id, file=sys.stderr)
            return 1
        status = "acked" if args.cmd == "ack" else "closed"
        record["status"] = status
        record["updated_at"] = now()
        if status == "closed":
            record["closed_at"] = now()
            record["close_reason"] = args.note or "agent closed"
        record.setdefault("history", []).append(
            {"ts": now(), "action": args.cmd, "note": args.note})
        save(record)
        print("{} → {}".format(args.id, status))
        return 0

    if args.cmd == "stats":
        records = all_records()
        open_count = len([r for r in records if r.get("status") != "closed"])
        closed = [r for r in records if r.get("status") == "closed"]
        print("总事件 {}  未关闭 {}  已关闭 {}".format(len(records), open_count, len(closed)))
        if records:
            latest = max(records, key=lambda r: r.get("last_seen") or "")
            print("最近一次: {}  {}  {}".format(
                latest["id"], latest.get("last_seen"), ",".join(latest.get("checks") or [])))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
