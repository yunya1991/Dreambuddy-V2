#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1.0-3 价格历史回填：OKX SPOT 日频 3 年 → mm_metrics。

为什么不用 okx_cli：CLI 只封装了 `market candles`（近期、单页 100 条），
回填需要 `history-candles` 的 after 反向翻页；行情为公开接口，无需签名。

幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp)，
重复运行只做 INSERT OR REPLACE，不会产生重复行。

用法:
  python3 scripts/backfill_okx_prices.py --dry-run          # 只拉不写
  python3 scripts/backfill_okx_prices.py                    # 回填全部 okx 锚定资产
  python3 scripts/backfill_okx_prices.py --only BTC,XAU
  python3 scripts/backfill_okx_prices.py --years 3 --json
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.request

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from l1agg.asset_pool import Anchor, load  # noqa: E402

_API_BASE = "https://www.okx.com/api/v5/market/history-candles"
_DEFAULT_DB = os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
_PAGE_LIMIT = 100
_MAX_PAGES = 60  # 3 年日频约 11 页，留足余量
_SLEEP_S = 0.12  # OKX 公共行情限频 20 req/2s
_FETCH_RETRIES = 3  # 公网偶发超时/tls 抖动，翻页中断会丢掉整段历史


def _fetch_once(inst_id: str, bar: str, after_ms, timeout: float):
    params = f"instId={inst_id}&bar={bar}&limit={_PAGE_LIMIT}"
    if after_ms:
        params += f"&after={after_ms}"
    req = urllib.request.Request(
        f"{_API_BASE}?{params}",
        headers={
            # OKX 对默认 python-urllib UA 返回 403
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX 返回错误: {payload.get('code')} {payload.get('msg')}")
    return payload.get("data") or []


def fetch_page(inst_id: str, bar: str, after_ms, timeout: float = 15.0):
    """拉一页日频 K 线（OKX 返回按时间倒序）。after_ms 为空表示从最新开始。"""
    last_exc = None
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            return _fetch_once(inst_id, bar, after_ms, timeout)
        except Exception as exc:  # noqa: BLE001 - 网络类异常统一重试
            last_exc = exc
            if attempt < _FETCH_RETRIES:
                time.sleep(0.6 * attempt)
    raise last_exc


def backfill_anchor(
    anchor: Anchor,
    fetch,
    cutoff_ms: int,
    writer,
    *,
    bar: str = "1D",
    dry_run: bool = False,
    sleep_s: float = _SLEEP_S,
) -> dict:
    """回填单个资产；返回统计（fetched/written/skipped/span/gaps）。"""
    inst_id = anchor.instrument_id
    sub_category, metric_close = anchor.storage_key
    metric_volume = anchor.storage_volume_metric
    stats = {
        "id": anchor.id,
        "inst_id": inst_id,
        "sub_category": sub_category,
        "pages": 0,
        "fetched": 0,
        "written": 0,
        "skipped_unconfirmed": 0,
        "skipped_out_of_range": 0,
        "first_ts": None,
        "last_ts": None,
        "gaps": 0,
        "errors": [],
    }

    cursor = None
    stamps = []
    for _ in range(_MAX_PAGES):
        try:
            rows = fetch(inst_id, bar, cursor)
        except Exception as exc:  # 网络/接口异常：结束该资产，保留已写数据
            stats["errors"].append(f"{inst_id} page={stats['pages']}: {exc}")
            break
        stats["pages"] += 1
        if not rows:
            break
        oldest = None
        for row in rows:
            ts_ms = int(row[0])
            oldest = ts_ms if oldest is None else min(oldest, ts_ms)
            if ts_ms < cutoff_ms:
                stats["skipped_out_of_range"] += 1
                continue
            stats["fetched"] += 1
            if len(row) > 8 and str(row[8]) == "0":
                stats["skipped_unconfirmed"] += 1  # 当日未收盘，避免 PIT 污染
                continue
            close = float(row[4])
            ts = datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.UTC)
            if not dry_run:
                writer("okx", sub_category, metric_close, close, ts)
                if metric_volume and len(row) > 7 and row[7]:
                    writer("okx", sub_category, metric_volume, float(row[7]), ts)
            stats["written"] += 1
            stamps.append(ts_ms)
        if oldest is None or oldest < cutoff_ms or len(rows) < _PAGE_LIMIT:
            break
        cursor = oldest
        if sleep_s:
            time.sleep(sleep_s)

    if stamps:
        stats["first_ts"] = min(stamps)
        stats["last_ts"] = max(stamps)
        expected = (stats["last_ts"] - stats["first_ts"]) // 86400000 + 1
        stats["gaps"] = max(0, expected - len(set(stamps)))
    return stats


def run(
    pool,
    writer,
    fetch=fetch_page,
    *,
    years: int = 3,
    dry_run: bool = False,
    bar: str = "1D",
    only=None,
) -> dict:
    cutoff = int(
        (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=365 * years)).timestamp()
        * 1000
    )
    targets = [a for a in pool.anchors if a.venue == "okx" and a.enabled]
    if only:
        wanted = {s.strip().upper() for s in only}
        targets = [a for a in targets if a.id.upper() in wanted]
    results = [backfill_anchor(a, fetch, cutoff, writer, bar=bar, dry_run=dry_run) for a in targets]
    return {
        "ok": all(not r["errors"] for r in results),
        "years": years,
        "dry_run": dry_run,
        "cutoff_ms": cutoff,
        "assets": results,
        "total_written": sum(r["written"] for r in results),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OKX 日频价格回填（S1.0-3）")
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--only", default="", help="逗号分隔的资产 id，如 BTC,XAU")
    parser.add_argument("--bar", default="1D")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    pool = load()
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    repo = SqliteMarketMacroRepository(os.path.abspath(args.db))
    result = run(
        pool,
        repo.upsert_metric,
        years=args.years,
        dry_run=args.dry_run,
        bar=args.bar,
        only=[s for s in args.only.split(",") if s.strip()],
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"[OKX 回填] db={os.path.abspath(args.db)} dry_run={args.dry_run}")
        for a in result["assets"]:
            span = ""
            if a["first_ts"] and a["last_ts"]:
                span = (
                    f"{datetime.datetime.fromtimestamp(a['first_ts'] / 1000, datetime.UTC).date()}"
                    f"~{datetime.datetime.fromtimestamp(a['last_ts'] / 1000, datetime.UTC).date()}"
                )
            print(
                f"  {a['id']:5s} {a['inst_id']:10s} pages={a['pages']:2d} "
                f"written={a['written']:5d} gaps={a['gaps']:3d} "
                f"unconfirmed={a['skipped_unconfirmed']:2d} {span}"
            )
            for err in a["errors"]:
                print(f"    ! {err}")
        print(f"  total_written={result['total_written']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
