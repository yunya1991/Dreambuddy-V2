#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨资产龙头历史回填：美股（个股/ETF）+ 贵金属/工业金属（OKX）+ 能源（FRED）→ mm_metrics。

为什么需要：`l1agg/leader_registry.py` 的 BINDINGS 只覆盖 14 条序列，13 个龙头在
UNBOUND 里诚实登记为「未采集」。S2 相关性/条件收益要求每条序列 ≥250 日，
本脚本把可免费获取的部分补齐。

数据源（均免 Key，2026-11-14 云端实测可用）：
  - 美股个股/ETF：Nasdaq 公开 historical API（3 年约 971 个交易日）
  - 道指：Nasdaq 无 ^DJI 指数历史、Yahoo 对云端 IP 返回 429、FRED DJIA 已停更
    → 用 DIA（道指 ETF）作代理，`proxy=True`，偏差见绑定 note
  - 白银/铜：OKX `XAG-USDT-SWAP` / `XCU-USDT-SWAP`（2026-01/03 起，约 256~291 天）
  - 布伦特/天然气：FRED `DCOILBRENTEU` / `DHHNGSP`（fredgraph.csv 免 Key）

存储契约（与 leader_registry 一致）：
  - 价格类（nasdaq/okx）：sub_category=<SYMBOL>, metric_name=close_usd, source=<venue>
  - FRED 宏观察列：      sub_category=<SERIES_ID>, metric_name=value, source=fred

幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp)，
重复运行只做 INSERT OR REPLACE，可安全重跑与挂定时任务。

用法:
  python3 scripts/backfill_cross_asset_leaders.py --dry-run
  python3 scripts/backfill_cross_asset_leaders.py --years 3
  python3 scripts/backfill_cross_asset_leaders.py --only NVDA,XAG,BZ --json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DEFAULT_DB = os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

_NASDAQ_URL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
_OKX_URL = "https://www.okx.com/api/v5/market/history-candles"
_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
_OKX_PAGE_LIMIT = 100
_OKX_MAX_PAGES = 40
_FETCH_RETRIES = 3

# symbol → 目标定义。`storage` 为空表示按价格契约（sub_category=symbol, close_usd）
TARGETS = (
    # ── us_index（道指用 DIA 代理）──
    {"symbol": "DJIA", "venue": "nasdaq", "inst": "DIA", "assetclass": "etf", "proxy": True},
    # ── us_stock（用户口径：只要几个龙头）──
    {"symbol": "NVDA", "venue": "nasdaq", "inst": "NVDA", "assetclass": "stocks"},
    {"symbol": "AAPL", "venue": "nasdaq", "inst": "AAPL", "assetclass": "stocks"},
    {"symbol": "MSFT", "venue": "nasdaq", "inst": "MSFT", "assetclass": "stocks"},
    {"symbol": "TSLA", "venue": "nasdaq", "inst": "TSLA", "assetclass": "stocks"},
    {"symbol": "AMZN", "venue": "nasdaq", "inst": "AMZN", "assetclass": "stocks"},
    {"symbol": "GOOGL", "venue": "nasdaq", "inst": "GOOGL", "assetclass": "stocks"},
    {"symbol": "META", "venue": "nasdaq", "inst": "META", "assetclass": "stocks"},
    # ── us_etf ──
    {"symbol": "SPY", "venue": "nasdaq", "inst": "SPY", "assetclass": "etf"},
    {"symbol": "QQQ", "venue": "nasdaq", "inst": "QQQ", "assetclass": "etf"},
    # ── precious_metal / industrial_metal（OKX SWAP）──
    {"symbol": "XAG", "venue": "okx", "inst": "XAG-USDT-SWAP"},
    {"symbol": "XCU", "venue": "okx", "inst": "XCU-USDT-SWAP"},
    # ── energy（FRED 系列，存 sub_category=series_id）──
    {"symbol": "BZ", "venue": "fred", "inst": "DCOILBRENTEU", "storage": "series"},
    {"symbol": "NG", "venue": "fred", "inst": "DHHNGSP", "storage": "series"},
)


def _get(url: str, timeout: float = 25.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _curl(url: str, timeout: float = 60.0) -> str:
    """curl 取文本。

    FRED 的 Akamai 前置有两道坑（2026-11-14 云端实测）：
      1. Python TLS 指纹（urllib/requests）直接 hang → 只能走 curl；
      2. curl 带浏览器 UA 也会被 tarpit（30s 超时），用 curl 默认 UA 则 0.3s 返回。
    所以这里不传 -A，并强制 HTTP/1.1（HTTP/2 多路复用在个别大响应上 exit=92）。
    """
    proc = subprocess.run(
        ["curl", "-s", "--http1.1", "-m", str(int(timeout)), url],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit={proc.returncode}: {(proc.stderr or '')[:120]}")
    return proc.stdout


def _retry(fn, *args, **kwargs):
    last = None
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 网络类异常统一重试
            last = exc
            if attempt < _FETCH_RETRIES:
                time.sleep(0.8 * attempt)
    raise last


def _to_float(text) -> float:
    return float(str(text).replace("$", "").replace(",", "").strip())


def fetch_nasdaq(symbol: str, assetclass: str, start: datetime.date, end: datetime.date) -> list:
    """返回 [{date: date, close: float}]，升序。"""
    url = (
        f"{_NASDAQ_URL.format(symbol=symbol)}?assetclass={assetclass}"
        f"&fromdate={start:%Y-%m-%d}&todate={end:%Y-%m-%d}&limit=1200"
    )
    body = json.loads(_retry(_get, url))
    rows = (((body.get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    out = []
    for row in rows:
        try:
            d = datetime.datetime.strptime(str(row["date"]).strip(), "%m/%d/%Y").date()
            close = _to_float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close > 0:
            out.append({"date": d, "close": close})
    out.sort(key=lambda r: r["date"])
    return out


def fetch_okx(inst_id: str, start: datetime.date, sleep_s: float = 0.12) -> list:
    """OKX history-candles 日频翻页，返回 [{date, close}]，升序。"""
    cutoff_ms = int(
        datetime.datetime.combine(start, datetime.time(), datetime.UTC).timestamp() * 1000
    )
    cursor, out = None, []
    for _ in range(_OKX_MAX_PAGES):
        params = f"instId={inst_id}&bar=1D&limit={_OKX_PAGE_LIMIT}"
        if cursor:
            params += f"&after={cursor}"
        try:
            payload = json.loads(_retry(_get, f"{_OKX_URL}?{params}"))
        except Exception:
            break  # 保留已取部分
        rows = payload.get("data") or []
        if not rows:
            break
        oldest = None
        for row in rows:
            ts_ms = int(row[0])
            oldest = ts_ms if oldest is None else min(oldest, ts_ms)
            if ts_ms < cutoff_ms:
                continue
            if len(row) > 8 and str(row[8]) == "0":
                continue  # 当日未收盘
            try:
                close = float(row[4])
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "date": datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.UTC).date(),
                    "close": close,
                }
            )
        if oldest is None or oldest < cutoff_ms or len(rows) < _OKX_PAGE_LIMIT:
            break
        cursor = oldest
        if sleep_s:
            time.sleep(sleep_s)
    out.sort(key=lambda r: r["date"])
    return out


def fetch_fred(series_id: str, start: datetime.date, api_key: str = "") -> list:
    """FRED 历史，返回 [{date, close}]，升序；缺测（空值）剔除。

    云端实测（2026-11-14）：fredgraph.csv 对该出口 IP 直接 RST（http=000），
    而 api.stlouisfed.org 正常 → 有 `FRED_API_KEY` 时优先走 API，否则回退 CSV。
    """
    key = api_key or os.environ.get("FRED_API_KEY", "")
    if key:
        url = (
            f"{_FRED_API_URL}?series_id={series_id}&api_key={key}&file_type=json"
            f"&observation_start={start:%Y-%m-%d}"
        )
        body = _retry(_curl, url, timeout=90)
        observations = (json.loads(body) or {}).get("observations") or []
        out = []
        for obs in observations:
            try:
                d = datetime.date.fromisoformat(str(obs["date"]))
                val = float(obs["value"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append({"date": d, "close": val})
        out.sort(key=lambda r: r["date"])
        return out

    body = _retry(_curl, f"{_FRED_URL}?id={series_id}", timeout=90)
    lines = body.strip().splitlines()[1:]
    out = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 2 or not parts[1].strip():
            continue
        try:
            d = datetime.date.fromisoformat(parts[0].strip())
            val = float(parts[1])
        except (TypeError, ValueError):
            continue
        if d < start:
            continue
        out.append({"date": d, "close": val})
    out.sort(key=lambda r: r["date"])
    return out


def run(
    fetchers: dict, writer, *, years: int = 3, dry_run: bool = False, only=None, today=None
) -> dict:
    """按 TARGETS 回填。fetchers = {venue: callable(target, start) -> rows}。"""
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=365 * years)
    wanted = {s.strip().upper() for s in (only or []) if s.strip()}
    results = []
    for target in TARGETS:
        if wanted and target["symbol"] not in wanted:
            continue
        venue = target["venue"]
        rec = {
            "symbol": target["symbol"],
            "venue": venue,
            "inst": target["inst"],
            "proxy": bool(target.get("proxy")),
            "fetched": 0,
            "written": 0,
            "first": "",
            "last": "",
            "errors": [],
        }
        fetcher = fetchers.get(venue)
        if fetcher is None:
            rec["errors"].append(f"no fetcher for venue={venue}")
            results.append(rec)
            continue
        try:
            rows = fetcher(target, start)
        except Exception as exc:  # noqa: BLE001 - 采集类异常记录后继续下一个标的
            rec["errors"].append(f"fetch: {type(exc).__name__}: {exc}")
            results.append(rec)
            continue
        rec["fetched"] = len(rows)
        if rows:
            rec["first"] = rows[0]["date"].isoformat()
            rec["last"] = rows[-1]["date"].isoformat()
        if target.get("storage") == "series":
            source, sub, metric = "fred", target["inst"], "value"
        else:
            source, sub, metric = (
                venue if venue == "okx" else "nasdaq",
                target["symbol"],
                "close_usd",
            )
        for row in rows:
            if not dry_run:
                writer(
                    source,
                    sub,
                    metric,
                    row["close"],
                    datetime.datetime.combine(row["date"], datetime.time(), datetime.UTC),
                )
            rec["written"] += 1
        results.append(rec)
    return {
        "ok": all(not r["errors"] for r in results),
        "years": years,
        "dry_run": dry_run,
        "start": start.isoformat(),
        "targets": results,
        "total_written": sum(r["written"] for r in results),
    }


def default_fetchers(fred_key: str = "") -> dict:
    def _nasdaq(target, start):
        return fetch_nasdaq(target["inst"], target["assetclass"], start, datetime.date.today())

    def _okx(target, start):
        return fetch_okx(target["inst"], start)

    def _fred(target, start):
        return fetch_fred(target["inst"], start, api_key=fred_key)

    return {"nasdaq": _nasdaq, "okx": _okx, "fred": _fred}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="跨资产龙头历史回填")
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--only", default="", help="逗号分隔 symbol，如 NVDA,XAG,BZ")
    parser.add_argument(
        "--fred-key",
        default="",
        help="FRED API Key（缺省读 FRED_API_KEY；云端出口 IP 无法直连 fredgraph.csv）",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    repo = SqliteMarketMacroRepository(os.path.abspath(args.db))
    result = run(
        default_fetchers(args.fred_key),
        repo.upsert_metric,
        years=args.years,
        dry_run=args.dry_run,
        only=[s for s in args.only.split(",") if s.strip()],
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(
            f"[跨资产回填] db={os.path.abspath(args.db)} dry_run={args.dry_run} since={result['start']}"
        )
        for r in result["targets"]:
            flag = "proxy" if r["proxy"] else "     "
            print(
                f"  {r['symbol']:6s} {r['venue']:6s} {flag} n={r['written']:5d} "
                f"{r['first']}~{r['last']}"
            )
            for err in r["errors"]:
                print(f"    ! {err}")
        print(f"  total_written={result['total_written']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
