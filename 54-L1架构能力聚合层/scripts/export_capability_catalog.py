# -*- coding: utf-8 -*-
"""导出能力目录快照（TASKS-20261116 T0-1）。

定位：把 `capability_manifest.yaml` 投影成前端/插件可直接消费的目录 JSON。
只读 manifest，不执行任何能力、不读库、不写注册表。

用法：

    python3 scripts/export_capability_catalog.py
    python3 scripts/export_capability_catalog.py --check   # 与现有快照比对，不一致退出 1
    python3 scripts/export_capability_catalog.py --out /tmp/catalog.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities.manifest import load as load_manifest  # noqa: E402
from l1agg.capabilities.stats import supported  # noqa: E402

SCHEMA_VERSION = "1.0"
DEFAULT_OUT = os.path.join(_MODULE_ROOT, "artifacts", "capability_catalog.json")


def _domain(capability_id: str) -> str:
    """`D-A01` → `A`；无连字符则回落 `OTHER`（不臆造域）。"""
    parts = capability_id.split("-")
    return parts[1][:1] if len(parts) > 1 and parts[1] else "OTHER"


def build_catalog() -> Dict[str, Any]:
    manifest = load_manifest()
    executed = set(supported())
    items: List[Dict[str, Any]] = []
    for cap in sorted(manifest.capabilities, key=lambda c: c.id):
        items.append(
            {
                "capability_id": cap.id,
                "domain": _domain(cap.id),
                "intent": cap.intent,
                "mode": cap.mode,
                "min_n": cap.min_n,
                "min_span_days": cap.min_span_days,
                "methods": list(cap.methods),
                "data_scope": list(cap.data_scope),
                "visibility": cap.visibility,
                "method_binding": cap.method_binding,
                "executable": cap.id in executed,
            }
        )
    domains: Dict[str, int] = {}
    for item in items:
        domains[item["domain"]] = domains.get(item["domain"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": manifest.version,
        "manifest_updated": manifest.updated,
        "count": len(items),
        "executable_count": sum(1 for item in items if item["executable"]),
        "domains": [{"domain": key, "count": domains[key]} for key in sorted(domains)],
        "items": items,
    }


def render(catalog: Dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="导出能力目录快照")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="只比对，不写盘")
    args = parser.parse_args(list(argv) if argv is not None else None)

    catalog = build_catalog()
    text = render(catalog)

    if args.check:
        if not os.path.isfile(args.out):
            print(f"missing snapshot: {args.out}")
            return 1
        with open(args.out, "r", encoding="utf-8") as fh:
            current = fh.read()
        if current != text:
            print("catalog drift detected")
            return 1
        print(f"ok: {catalog['count']} capabilities")
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, args.out)
    print(
        json.dumps(
            {
                "ok": True,
                "out": args.out,
                "count": catalog["count"],
                "executable": catalog["executable_count"],
                "manifest_version": catalog["manifest_version"],
                "domains": catalog["domains"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
