# -*- coding: utf-8 -*-
"""延续性画像报告入口（只读 DB，产物写 reports/persistence/）。

CLI：
    python3 scripts/persistence_report.py                       # 四资产，落盘
    python3 scripts/persistence_report.py --symbols BTC --json   # 单资产 JSON 到 stdout（不落盘）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from .. import align  # noqa: F401  (保持与 profile 相同的包上下文)
from .constants import CAVEAT, KIND
from .profile import build_profile

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DB = os.path.abspath(
    os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
)


def _collect(db_path: str, symbols, days: int) -> list:
    profiles = []
    for sym in symbols:
        try:
            profiles.append(build_profile(db_path, sym, days=days))
        except Exception as exc:  # 单资产失败不阻塞其它资产
            profiles.append(
                {
                    "kind": KIND,
                    "symbol": sym.upper(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "caveat": CAVEAT,
                }
            )
    return profiles


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成延续性画像报告")
    ap.add_argument("--db", default=_DEFAULT_DB)
    ap.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "XAU"])
    ap.add_argument("--days", type=int, default=1200, help="自然日回看窗口")
    ap.add_argument("--out", default=os.path.join(_MODULE_ROOT, "reports", "persistence"))
    ap.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 到 stdout（单资产时直接输出该资产画像），不落盘",
    )
    args = ap.parse_args(argv)

    if not os.path.isfile(args.db):
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    profiles = _collect(args.db, args.symbols, args.days)
    now = datetime.datetime.now(datetime.timezone.utc)

    if args.json:
        payload = (
            profiles[0]
            if len(profiles) == 1
            else {
                "kind": KIND,
                "generated_at": now.isoformat(),
                "db": args.db,
                "days": args.days,
                "profiles": profiles,
            }
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    payload = {
        "kind": KIND,
        "generated_at": now.isoformat(),
        "db": args.db,
        "days": args.days,
        "profiles": profiles,
    }
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, now.strftime("%Y%m%d-%H%M") + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    for prof in profiles:
        print(prof.get("text") or prof.get("error"))
    print(f"\n[saved] {path}")
    return 0
