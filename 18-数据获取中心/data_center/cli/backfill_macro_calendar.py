"""宏观事件历史回填入口（FOMC + BLS，2015 起）。

落盘到独立历史事件流（append-only、event_id 幂等），不污染当天事件流：

    data_center/events/macro_calendar_history.jsonl

用法（在 18-数据获取中心 目录下）：
  python3 -m data_center.cli.backfill_macro_calendar --start-year 2015 --end-year 2026
"""

from __future__ import annotations

import argparse
import json

from data_center.collectors.tradefin.macro_history_backfill import HISTORY_PATH, backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="宏观事件历史回填")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--output", default=str(HISTORY_PATH))
    args = parser.parse_args(argv)

    result = backfill(args.start_year, args.end_year, args.output)
    print(f"[backfill_macro_calendar] {json.dumps(result, ensure_ascii=False)}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
