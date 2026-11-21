"""发布台账与回滚建议（JSONL，append-only）。

只记录事实：谁在什么时候把哪个 SKU 的哪个版本发到哪个渠道、处于什么状态。
回滚不直接操作远端（凭据在 SkillHub CLI），只产出目标版本与可执行命令，需人工执行。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MODULE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = MODULE_ROOT / "platform" / "ops" / "releases.jsonl"
STATUSES = {
    "draft",
    "submitted",
    "in_review",
    "published",
    "rejected",
    "delisted",
    "rollback_requested",
}
CHANNELS = {"skillhub", "skillpay", "site", "mcp", "manual"}


def ledger_path() -> Path:
    return Path(os.environ.get("DREAMBUDDY_RELEASES", str(DEFAULT_LEDGER)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    sku: str,
    version: str,
    channel: str,
    status: str,
    product_id: str = "",
    operator: str = "",
    note: str = "",
) -> Dict[str, Any]:
    if not sku or not version:
        raise ValueError("E_RELEASE：sku/version 必填")
    if status not in STATUSES:
        raise ValueError("E_RELEASE：status 非法（{}）".format(status))
    if channel not in CHANNELS:
        raise ValueError("E_RELEASE：channel 非法（{}）".format(channel))
    entry = {
        "at": _now(),
        "sku": sku,
        "version": version,
        "channel": channel,
        "status": status,
        "product_id": product_id,
        "operator": operator or os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user"),
        "note": note,
    }
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def entries() -> List[Dict[str, Any]]:
    path = ledger_path()
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def latest(status: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for entry in entries():
        if status and entry.get("status") != status:
            continue
        result[str(entry.get("sku"))] = entry
    return result


def rollback(sku: str) -> Dict[str, Any]:
    history = [entry for entry in entries() if entry.get("sku") == sku]
    published = [entry for entry in history if entry.get("status") == "published"]
    if not published:
        raise ValueError("E_RELEASE：{} 没有已发布记录".format(sku))
    current = published[-1]
    previous = published[-2] if len(published) > 1 else None
    target = previous or current
    record(
        sku,
        str(target.get("version")),
        str(target.get("channel") or "skillhub"),
        "rollback_requested",
        product_id=str(target.get("product_id") or ""),
        note="rollback from {}".format(current.get("version")),
    )
    return {
        "sku": sku,
        "current": current,
        "target": target,
        "command": "python3 tools/build_product.py {sku} && skillhub publish dist/{sku}/{version}".format(
            sku=sku, version=target.get("version")
        ),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="59 域发布台账")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_record = sub.add_parser("record")
    p_record.add_argument("sku")
    p_record.add_argument("version")
    p_record.add_argument("--channel", default="skillhub")
    p_record.add_argument("--status", default="published")
    p_record.add_argument("--product-id", default="")
    p_record.add_argument("--operator", default="")
    p_record.add_argument("--note", default="")
    p_rollback = sub.add_parser("rollback")
    p_rollback.add_argument("sku")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        table = latest()
        if not table:
            print("（台账为空）")
        for sku in sorted(table):
            entry = table[sku]
            print(
                "{sku}  {version}  {channel}  {status}  {at}".format(
                    sku=sku,
                    version=entry.get("version"),
                    channel=entry.get("channel"),
                    status=entry.get("status"),
                    at=entry.get("at"),
                )
            )
        return 0
    try:
        if args.cmd == "record":
            print(
                json.dumps(
                    record(
                        args.sku,
                        args.version,
                        args.channel,
                        args.status,
                        product_id=args.product_id,
                        operator=args.operator,
                        note=args.note,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(rollback(args.sku), ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
