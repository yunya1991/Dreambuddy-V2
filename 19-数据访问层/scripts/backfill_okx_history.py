#!/usr/bin/env python3
"""一次性回填：OKX 公共 REST API 历史行情 → 19-DAL mm_metrics。

数据源（OKX 公共接口，无需密钥）：
  - /api/v5/market/history-candles   历史K线（OHLCV，翻页可拿数年）
  - /api/v5/public/funding-rate-history  永续资金费率历史（容错）
  - /api/v5/rubik/stat/contracts/open-interest-history  持仓量历史（容错）

设计要点：
  - 只读公共行情，不触碰账户/下单，无需 API key
  - candles 用 after 参数往前翻页，直到达到 --days 或数据耗尽
  - sub_category 命名：candles_{base} / funding_{base} / oi_{base}（base 小写）
  - 幂等：主键 (source, sub_category, metric_name, timestamp) → INSERT OR REPLACE
  - 限流：OKX 公共接口约 20 req/2s，请求间隔 0.15s，429 退避
  - funding/oi 失败仅告警，不阻断 candles 主流程

用法（在云端执行）：
    cd 19-数据访问层
    python scripts/backfill_okx_history.py --dst data/dreambuddy_core.db --days 400
    python scripts/backfill_okx_history.py --symbols BTC ETH SOL --days 400 --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DAL_ROOT = REPO_ROOT / "19-数据访问层"
DEFAULT_DST = DAL_ROOT / "data" / "dreambuddy_core.db"

_BASE = "https://www.okx.com"
_SOURCE = "okx"

# 默认回填币种（OKX base symbol，对应因子池 SECTOR_MAP + 主流币）
DEFAULT_SYMBOLS = [
    # 主流
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "ADA",
    "ZEC",
    "AVAX",
    "NEAR",
    "LINK",
    "LTC",
    # DEX
    "UNI",
    "CRV",
    "1INCH",
    "CAKE",
    "SUSHI",
    # Lending / LSD
    "AAVE",
    "COMP",
    "MKR",
    "LDO",
    # L2
    "OP",
    "ARB",
    "MATIC",
    "STX",
    # Meme
    "DOGE",
    "SHIB",
    "PEPE",
    "WIF",
    "PUMP",
    # Perp DEX
    "HYPE",
    "GMX",
    "GNS",
    "DYDX",
]

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "dreambuddy-backfill/1.0"})


def _get(path: str, params: dict, retries: int = 3) -> dict:
    """带限流退避的 GET。返回 OKX 响应 JSON。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = _SESSION.get(_BASE + path, params=params, timeout=20)
            if resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"OKX {path} 失败: {last_exc}")


def fetch_candles(symbol: str, days: int) -> list[list]:
    """翻页拉取 {symbol}-USDT 日线历史K线，返回 OKX 原始行列表（新→旧）。

    每行: [ts_ms, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    """
    inst_id = f"{symbol}-USDT"
    target_ms = days * 86400 * 1000
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - target_ms

    out: list[list] = []
    after = ""
    for _ in range(40):  # 最多 40 页 × 100 = 4000 天，足够
        params = {"instId": inst_id, "bar": "1D", "limit": "100"}
        if after:
            params["after"] = after
        data = _get("/api/v5/market/history-candles", params).get("data", [])
        if not data:
            break
        out.extend(data)
        oldest_ts = int(data[-1][0])
        if oldest_ts <= cutoff_ms:
            break
        after = data[-1][0]
        time.sleep(0.15)
    return out


def fetch_funding(symbol: str) -> list[dict]:
    """拉取 {symbol}-USDT-SWAP 资金费率历史（容错，失败返回 []）。"""
    inst_id = f"{symbol}-USDT-SWAP"
    try:
        data = _get("/api/v5/public/funding-rate-history", {"instId": inst_id, "limit": "100"}).get(
            "data", []
        )
        return data or []
    except Exception:  # noqa: BLE001
        return []


def fetch_open_interest(symbol: str) -> list:
    """拉取 {symbol}-USDT-SWAP 持仓量历史（容错，失败返回 []）。"""
    inst_id = f"{symbol}-USDT-SWAP"
    for period in ("1D", "1H"):
        try:
            data = _get(
                "/api/v5/rubik/stat/contracts/open-interest-history",
                {"instId": inst_id, "period": period},
            ).get("data", [])
            if data:
                return data
        except Exception:  # noqa: BLE001
            continue
    return []


def _candle_rows(symbol: str, raw: list[list]) -> list[tuple]:
    """K线原始行 → mm_metrics 行（OHLCV 六个 metric）。"""
    sub = f"candles_{symbol.lower()}"
    rows: list[tuple] = []
    for r in raw:
        if not isinstance(r, list) or len(r) < 6:
            continue
        try:
            ts = int(r[0]) // 1000  # 毫秒 → 秒
            o, h, low, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
            vol = float(r[5])
            vol_quote = float(r[7]) if len(r) > 7 and r[7] else 0.0
        except (ValueError, TypeError):
            continue
        for name, val in (
            ("open", o),
            ("high", h),
            ("low", low),
            ("close", c),
            ("volume", vol),
            ("vol_ccy_quote", vol_quote),
        ):
            rows.append((_SOURCE, sub, name, val, ts))
    return rows


def _funding_rows(symbol: str, raw: list[dict]) -> list[tuple]:
    sub = f"funding_{symbol.lower()}"
    rows: list[tuple] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        try:
            ts = int(p["fundingTime"]) // 1000
            rate = float(p["fundingRate"])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append((_SOURCE, sub, "funding_rate", rate, ts))
    return rows


def _oi_rows(symbol: str, raw: list) -> list[tuple]:
    sub = f"oi_{symbol.lower()}"
    rows: list[tuple] = []
    for p in raw:
        # rubik 返回 [ts_ms, oi] 或 [ts_ms, oiCcy, oiUsd]
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                ts = int(p[0]) // 1000
                val = float(p[-1])
            except (ValueError, TypeError):
                continue
            rows.append((_SOURCE, sub, "open_interest", val, ts))
        elif isinstance(p, dict):
            try:
                ts = int(p.get("ts", 0)) // 1000
                val = float(p.get("oi", p.get("oiCcy", 0)))
            except (ValueError, TypeError):
                continue
            rows.append((_SOURCE, sub, "open_interest", val, ts))
    return rows


def backfill(
    dst_db: str, symbols: list[str], days: int, dry_run: bool, with_derivatives: bool
) -> dict:
    all_rows: list[tuple] = []
    stats: dict[str, dict] = {}

    for sym in symbols:
        entry: dict[str, int] = {}
        # 1. K线（主流程）
        try:
            raw = fetch_candles(sym, days)
            rows = _candle_rows(sym, raw)
            all_rows.extend(rows)
            entry["candle_points"] = len(raw)
            entry["candle_rows"] = len(rows)
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] {sym} candles 失败: {e}")
            entry["candle_points"] = 0
        print(
            f"  {sym:8s} candles: {entry.get('candle_points', 0)} 点 / {entry.get('candle_rows', 0)} 行"
        )
        time.sleep(0.15)

        # 2. 衍生品维度（容错）
        if with_derivatives:
            fr = fetch_funding(sym)
            frows = _funding_rows(sym, fr)
            all_rows.extend(frows)
            entry["funding_points"] = len(fr)
            oi = fetch_open_interest(sym)
            orows = _oi_rows(sym, oi)
            all_rows.extend(orows)
            entry["oi_points"] = len(oi)
            print(f"  {sym:8s} funding: {len(fr)} 点, oi: {len(oi)} 点")
            time.sleep(0.15)

        stats[sym] = entry

    total = len(all_rows)
    if dry_run:
        return {"total_metric_rows": total, "per_symbol": stats, "dry_run": True, "dst_db": dst_db}

    Path(dst_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dst_db)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mm_metrics (
                source TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (source, sub_category, metric_name, timestamp)
            ) WITHOUT ROWID
            """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mm_metrics_query
            ON mm_metrics (sub_category, metric_name, timestamp)
            """)
        inserted = 0
        for i in range(0, total, 5000):
            batch = all_rows[i : i + 5000]
            conn.executemany(
                """INSERT OR REPLACE INTO mm_metrics
                   (source, sub_category, metric_name, metric_value, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                batch,
            )
            inserted += len(batch)
        conn.commit()
        db_count = conn.execute("SELECT COUNT(*) FROM mm_metrics WHERE source='okx'").fetchone()[0]
    finally:
        conn.close()

    return {
        "total_metric_rows": total,
        "inserted_or_replaced": inserted,
        "per_symbol": stats,
        "db_okx_rows": db_count,
        "dry_run": False,
        "dst_db": dst_db,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill OKX public history into 19-DAL mm_metrics")
    ap.add_argument("--dst", default=str(DEFAULT_DST))
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument(
        "--with-derivatives", action="store_true", help="同时拉 funding-rate / open-interest"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(
        f"[backfill_okx] dst={args.dst} days={args.days} symbols={len(args.symbols)} "
        f"derivatives={args.with_derivatives} dry_run={args.dry_run}"
    )
    print(f"[backfill_okx] started={datetime.now(timezone.utc).isoformat()}")

    stats = backfill(args.dst, args.symbols, args.days, args.dry_run, args.with_derivatives)
    print("\n=== 回填结果 ===")
    print(f"  total_metric_rows: {stats['total_metric_rows']}")
    if not args.dry_run:
        print(f"  inserted_or_replaced: {stats.get('inserted_or_replaced')}")
        print(f"  db_okx_rows: {stats.get('db_okx_rows')}")
    if not args.dry_run and stats.get("db_okx_rows", 0) > 0:
        print("\n[OK] OKX 历史行情 → 19-DAL mm_metrics 回填完成。")


if __name__ == "__main__":
    main()
