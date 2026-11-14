# -*- coding: utf-8 -*-
"""方法评估 CLI：跑 harness 并落 JSON 报告。

用法：
    python scripts/method_audit.py
    python scripts/method_audit.py --methods M01 M11 M25 --null-trials 200
    python scripts/method_audit.py --out docs/method_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.eval.harness import audit  # noqa: E402

DEFAULT_OUT = os.path.join(_MODULE_ROOT, "docs", "method_audit.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="L1 方法评估 harness")
    ap.add_argument("--methods", nargs="*", help="只评估指定 method_id")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--null-trials", type=int, default=100)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument(
        "--scope",
        default="core",
        choices=["core", "research", "all"],
        help="校验范围：core(238)/research(149)/all(387)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    report = audit(args.methods, seed=args.seed, null_trials=args.null_trials, scope=args.scope)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    s = report["summary"]
    if not args.quiet:
        print(
            f"catalog={s['catalog_total']} implemented={s['implemented']} "
            f"passed={s['passed']} failed={s['failed']}"
        )
        for item in report["methods"]:
            if not item["implemented"]:
                continue
            mark = "PASS" if item["passed"] else "FAIL"
            marks = ",".join(
                f"{c['name']}:{'skip' if c['skipped'] else ('ok' if c['passed'] else 'x')}"
                for c in item["checks"]
            )
            print(f"  [{mark}] {item['method_id']:<4} {item['name']}  {marks}")
        if report["failed"]:
            print(f"failed: {', '.join(report['failed'])}")
    print(f"report -> {args.out}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
