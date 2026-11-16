#!/usr/bin/env python3
"""capability_matrix_check.py — SPEC-54 AC1 验收矩阵。

遍历能力清单逐个 op=resolve，按 code 归类并落盘报告。
用法：
  python3 scripts/capability_matrix_check.py            # 全量 94 项
  python3 scripts/capability_matrix_check.py --limit 10 # 抽样
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
_FRONTEND_SCRIPTS = os.path.join(_REPO_ROOT, "3.1-FRONTEND", "scripts")
for _path in (_L1_DIR, _FRONTEND_SCRIPTS, _SCRIPT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import capability_resolve as cr  # noqa: E402
from l1agg.capabilities.manifest import load  # noqa: E402

REPORT_DIR = os.path.join(_L1_DIR, "reports")


def run_matrix(limit: int = 0) -> Dict[str, Any]:
    manifest = load()
    ids: List[str] = [cap.id for cap in manifest.capabilities]
    if limit:
        ids = ids[:limit]

    items = []
    for capability_id in ids:
        started = time.monotonic()
        try:
            result = cr.resolve(capability_id, {})
        except Exception as exc:  # noqa: BLE001 — 单项异常不阻断矩阵
            result = {"code": "error", "reason": f"{type(exc).__name__}: {exc}"}
        items.append(
            {
                "capability_id": capability_id,
                "code": result.get("code"),
                "n": (result.get("quality") or {}).get("n", 0),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "reason": result.get("reason") or "",
            }
        )

    by_code = Counter(item["code"] for item in items)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(items),
        "by_code": dict(sorted(by_code.items())),
        "items": items,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SPEC-54 能力矩阵验收")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    report = run_matrix(limit=args.limit)
    out_path = args.out or os.path.join(
        REPORT_DIR, f"capability_matrix_{time.strftime('%Y%m%d')}.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps(report["by_code"], ensure_ascii=False), f"total={report['total']}")
    unsupported = {
        item["capability_id"] for item in report["items"] if item["code"] == "unsupported"
    }
    # SPEC-54c：G23/A14/A16 已放开，禁用清单应为空
    expected = set()
    if unsupported != expected:
        print(f"WARN unsupported={sorted(unsupported)} expected={sorted(expected)}")
    if (report["by_code"].get("error") or 0) > 0:
        print(
            "WARN error>0: "
            + ", ".join(
                item["capability_id"] for item in report["items"] if item["code"] == "error"
            )
        )
    print(f"report={out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
