"""newsflash 历史翻页回填脚本 — SPEC-D1 §2.4 路径 2 补量（P2）。

口径（预注册）：
  - 翻页 page=1..N 向前回溯，终止于 stop_date（默认 2023-01-01，对齐
    yfinance 价格覆盖起点；更早的事件无 reaction 可算，无价值）
  - 产物：backfill/newsflash_history.jsonl（每行一条 normalize 后快讯）
    + newsflash_history.state.json（断点，中断后可续跑）
  - 速率：sleep 0.4s/页（实测 limit 锁 20/页，全程 ~9000 页 ~1-2h）

用法：python scripts/backfill_newsflash_history.py [--stop-date 2023-01-01]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_center.processing.newsflash_history import (  # noqa: E402
    fetch_page,
    iter_pages,
    load_state,
    save_state,
)

OUT_DIR = ROOT / "backfill"
OUT_JSONL = OUT_DIR / "newsflash_history.jsonl"
STATE = OUT_DIR / "newsflash_history.state.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop-date", default="2023-01-01")
    ap.add_argument("--max-pages", type=int, default=12000)
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    stop_ts = int(datetime.fromisoformat(args.stop_date).replace(tzinfo=timezone.utc).timestamp())

    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        ),
    )

    done_page = load_state(STATE)
    start = done_page + 1
    print(f"resume from page={start}, stop_ts={args.stop_date}")

    import time as _t

    n = 0
    page = start
    with OUT_JSONL.open("a", encoding="utf-8") as f:

        def _fn(p: int) -> list:
            nonlocal page
            page = p
            return fetch_page(session, p)

        for rec in iter_pages(_fn, start_page=start, stop_ts=stop_ts, max_pages=args.max_pages):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 500 == 0:
                f.flush()
                save_state(STATE, page)
                ts = datetime.fromtimestamp(rec["published_ms"] / 1000, timezone.utc).date()
                print(f"  page={page} n={n} oldest={ts}", flush=True)
            _t.sleep(args.sleep if n % 20 == 0 else 0)  # 每页(20条)睡一次
    save_state(STATE, page)
    print(f"done: +{n} records → {OUT_JSONL}")


if __name__ == "__main__":
    main()
