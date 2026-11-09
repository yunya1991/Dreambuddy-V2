"""newsflash × 日K 对齐回填脚本 — SPEC-D1 §2.4 路径 2（P2）。

数据源合并口径（预注册）：
  - yfinance BTC-USD 日线（2023-01 起，长历史）
  - ccxt BTC/USDT ticker 快照按 UTC 日聚合取最后价（覆盖 2026-08-25→10-29，
    补齐 yfinance 2026-09-10 之后的缺口）
  - 冲突日 ccxt 优先（更接近真实事件日行情）

产出：18-数据获取中心/backfill/events_d1.jsonl（EventStore 幂等）
用法：python scripts/backfill_newsflash_events.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_center.processing.event_store import EventStore  # noqa: E402
from data_center.processing.newsflash_events import build_events_from_newsflash  # noqa: E402

DB = ROOT / "data_center.db"
OUT = ROOT / "backfill" / "events_d1.jsonl"
HISTORY = ROOT / "backfill" / "newsflash_history.jsonl"


def _day_ts(ts: int) -> int:
    return ts - (ts % 86400)


def load_yfinance_daily(conn: sqlite3.Connection) -> dict[int, float]:
    out: dict[int, float] = {}
    for (m,) in conn.execute(
        "SELECT metrics FROM records WHERE source='yfinance' AND sub_category='BTC-USD'"
    ):
        d = json.loads(m)
        if "value" not in d or "date" not in d:
            continue
        ts = int(datetime.fromisoformat(d["date"]).replace(tzinfo=timezone.utc).timestamp())
        out[_day_ts(ts)] = float(d["value"])
    return out


def load_ccxt_daily(conn: sqlite3.Connection) -> dict[int, float]:
    """ticker 快照 → UTC 日收盘（每日最后一条 last）。"""
    out: dict[int, float] = {}
    for ts_s, m in conn.execute(
        "SELECT timestamp, metrics FROM records WHERE source='ccxt' AND sub_category='BTC/USDT' ORDER BY timestamp"
    ):
        d = json.loads(m)
        if "last" not in d:
            continue
        try:
            ts = int(datetime.fromisoformat(ts_s.replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
        out[_day_ts(ts)] = float(d["last"])  # 按时间序覆盖 → 每日最后价
    return out


def main() -> None:
    conn = sqlite3.connect(DB)
    merged = load_yfinance_daily(conn)
    n_yf = len(merged)
    merged.update(load_ccxt_daily(conn))  # ccxt 冲突日优先
    prices = sorted((ts, c) for ts, c in merged.items())
    print(
        f"prices: yfinance={n_yf} + ccxt → merged={len(prices)} days, "
        f"{datetime.fromtimestamp(prices[0][0]).date()} → {datetime.fromtimestamp(prices[-1][0]).date()}"
    )

    recs = []
    db_ids: set[int] = set()
    for ts_s, m, raw_s in conn.execute(
        "SELECT timestamp, metrics, raw FROM records WHERE source='odaily_newsflash'"
    ):
        d = json.loads(m)
        # 2317/3048 条 description/publishTimestamp 只在 raw 列 → 回退补齐
        try:
            raw = json.loads(raw_s) if raw_s else {}
        except ValueError:
            raw = {}
        d.setdefault("description", raw.get("description", ""))
        if not d.get("published_ms") and raw.get("publishTimestamp"):
            d["published_ms"] = str(raw["publishTimestamp"])
        d["_fallback_ts"] = ts_s  # 2096/3048 缺 published_ms，回退记录时间戳
        if d.get("od_source_id"):
            db_ids.add(int(d["od_source_id"]))
        recs.append(d)
    print(f"newsflash records (DB): {len(recs)}")

    # 历史翻页回填合并（按 id 去重 DB 已有条目）
    n_hist = 0
    if HISTORY.exists():
        for line in HISTORY.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                h = json.loads(line)
            except ValueError:
                continue
            if int(h.get("id") or 0) in db_ids:
                continue
            recs.append(
                {
                    "od_event_type": h.get("od_event_type", ""),
                    "description": h.get("description", ""),
                    "published_ms": str(h.get("published_ms", 0)),
                }
            )
            n_hist += 1
    print(f"newsflash records (history merged): +{n_hist} → total {len(recs)}")

    if OUT.exists():  # 幂等重跑：清空重建（EventStore 内部也按 event_id 幂等）
        os.remove(OUT)
    store = EventStore(OUT)
    stats = build_events_from_newsflash(recs, prices, store)
    print(f"build stats: {stats}")

    events = store.load()
    n_full = sum(1 for e in events if e["reaction"])
    print(f"events: {len(events)}, reaction 非空: {n_full} ({n_full / max(len(events), 1):.0%})")
    from collections import Counter

    print("types:", dict(Counter(e["event_type"] for e in events)))
    for e in events[:5]:
        print(" ", datetime.fromtimestamp(e["trigger_ts"]).date(), e["event_type"], e["reaction"])
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
