#!/usr/bin/env python3
"""reflection_suggest.py — 反思建议产出器 + 做梦树消费入口（TASKS-20261116 T7-3）。

链路：
  signal_journal（T6-4 记账）→ 规则化建议（`l1agg.reflection.build_suggestions`）
  → `reports/reflection/suggestions.json`（每条带 suggestion_id + ab_slot，缺一不入库）
  → `reports/reflection/dreamer_feed.jsonl`（48 做梦树/reflector 的只读消费口）

约束：
  - 只读 journal，不写信号；`--write` 才把建议落 `reflection_suggestion` 表；
  - 不产生自由文本，建议句全部来自模板；
  - 空账本 → 0 条建议，不编造。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_L1_DIR = os.path.dirname(_SCRIPT_DIR)
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

DEFAULT_OUT_DIR = os.path.join(_L1_DIR, "reports", "reflection")
SUGGESTIONS_FILE = "suggestions.json"
DREAMER_FEED_FILE = "dreamer_feed.jsonl"
CONSUMER = "48-emergence-dreamer"


def build_document(
    rows: Iterable[Mapping[str, Any]], *, as_of: str = "", ab_slot: str = "B"
) -> Dict[str, Any]:
    """把 journal 行折叠成 `build_suggestions` 需要的门控摘要（只计数，不判定）。"""
    from l1agg.reflection import build_suggestions

    allowed: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    by_reason: Counter = Counter()
    conflicts: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if str(item.get("decision")) == "allowed":
            allowed.append(item)
            continue
        blocked.append(item)
        reasons = [str(reason) for reason in (item.get("reasons") or [])]
        by_reason.update(reasons)
        if any("conflict" in reason for reason in reasons):
            conflicts.append(item)
    document = build_suggestions(
        {"allowed": allowed, "conflicts": conflicts, "ablation": {"by_reason": dict(by_reason)}},
        as_of=as_of,
        ab_slot=ab_slot,
    )
    document["gate_summary"] = {
        "journal_rows": len(allowed) + len(blocked),
        "allowed": len(allowed),
        "blocked": len(blocked),
        "conflicts": len(conflicts),
        "by_reason": dict(sorted(by_reason.items())),
    }
    return document


def render_dreamer_feed(document: Mapping[str, Any]) -> List[str]:
    """做梦树消费格式：一行一条建议，字段与 reflection_suggestion 一致，不含自由文本。"""
    lines: List[str] = []
    for item in document.get("suggestions") or []:
        lines.append(
            json.dumps(
                {
                    "consumer": CONSUMER,
                    "suggestion_id": item["suggestion_id"],
                    "ab_slot": item["ab_slot"],
                    "type": item["type"],
                    "as_of": item["as_of"],
                    "evidence": item["evidence"],
                    "expected_effect": item["expected_effect"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return lines


def write_outputs(document: Mapping[str, Any], *, out_dir: str = DEFAULT_OUT_DIR) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    suggestions_path = os.path.join(out_dir, SUGGESTIONS_FILE)
    with open(suggestions_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    feed_path = os.path.join(out_dir, DREAMER_FEED_FILE)
    with open(feed_path, "w", encoding="utf-8") as handle:
        for line in render_dreamer_feed(document):
            handle.write(line + "\n")
    return {"suggestions": suggestions_path, "dreamer_feed": feed_path}


def run(
    *,
    as_of: str = "",
    ab_slot: str = "B",
    limit: int = 500,
    out_dir: str = DEFAULT_OUT_DIR,
    write: bool = False,
) -> Dict[str, Any]:
    from l1agg.reflection import record_suggestions, validate_suggestions
    from l1agg.signal_ledger import read_journal

    stamp = as_of or datetime.now(timezone.utc).date().isoformat()
    document = build_document(read_journal(limit=limit), as_of=stamp, ab_slot=ab_slot)
    errors = validate_suggestions(document)
    paths = write_outputs(document, out_dir=out_dir)
    result: Dict[str, Any] = {
        "ok": not errors,
        "as_of": stamp,
        "ab_slot": ab_slot,
        "suggestion_count": document.get("suggestion_count", 0),
        "gate_summary": document.get("gate_summary", {}),
        "paths": paths,
        "errors": errors,
    }
    if write and not errors:
        result["recorded"] = record_suggestions(document)
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--ab-slot", default="B", choices=("A", "B"))
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--write", action="store_true", help="同时写入 reflection_suggestion 表")
    args = parser.parse_args(argv)
    try:
        payload = run(
            as_of=args.as_of,
            ab_slot=args.ab_slot,
            limit=max(1, int(args.limit)),
            out_dir=args.out_dir,
            write=args.write,
        )
    except Exception as exc:  # FAIL-OPEN：不阻断主链路
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "suggestion_count": 0}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
