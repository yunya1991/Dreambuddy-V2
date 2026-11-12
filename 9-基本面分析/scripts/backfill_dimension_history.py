#!/usr/bin/env python3
"""云端历史回填入口；本地默认不运行。当前仅 fear_greed 有足额真实历史源。

示例（云端执行）：
  python scripts/backfill_dimension_history.py --module fear_greed --dry-run
  python scripts/backfill_dimension_history.py --module fear_greed
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from engines.fear_greed_history import backfill_fear_greed  # noqa: E402


def _day(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须为 YYYY-MM-DD") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="9 域 DimensionHistory 云端回填")
    parser.add_argument("--module", choices=("fear_greed",), required=True)
    parser.add_argument("--start", type=_day, help="起始日，默认 1970-01-01")
    parser.add_argument("--end", type=_day, help="结束时刻（不含），默认当前时刻")
    parser.add_argument(
        "--base-dir",
        type=Path,
        help="dimension_history 的父目录；缺省写 9 域 storage/dimension_history",
    )
    parser.add_argument("--dry-run", action="store_true", help="只读取和转换，不写历史文件")
    args = parser.parse_args(argv)

    try:
        result = backfill_fear_greed(
            start=args.start,
            end=args.end,
            base_dir=args.base_dir,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 CLI 边界如实返回非零，不写伪结果
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
