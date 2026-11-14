#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeFi TVL 历史回填：DeFiLlama 官方全链日频 → mm_metrics.chains_summary.total_tvl_bln。

背景：`defillama_tvl` 采集任务每 5 分钟写一次汇总，只从首次上线（2026-11-05）
开始累积；L1/前端按「近 90 天」出统计时实际只有 9 天样本，range/change 被误读
（SPEC §六 同一指标必须来自同一 Aggregator）。

口径（2026-11-14 修正）：DeFi TVL 以 DeFiLlama 官方首页/图表口径为准，即
`GET /charts` 每点的 `totalLiquidityUSD`（实测 147.879B）；`/v2/chains` 逐链求和
与 `/v2/historicalChainTvl` 均显著偏低（实测 73.94B / 73.74B），只作链级拆分参考，
禁止再作为总 TVL 写入。

幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp)，
重复运行只做 INSERT OR REPLACE，不产生重复行，可挂定时任务。

用法:
  python3 scripts/backfill_defillama_tvl.py --dry-run
  python3 scripts/backfill_defillama_tvl.py                    # 回填近 180 天
  python3 scripts/backfill_defillama_tvl.py --days 365 --json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_DAL_ROOT = os.path.join(_MODULE_ROOT, "..", "19-数据访问层")
for _p in (_MODULE_ROOT, _DAL_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_HIST_URL = "https://api.llama.fi/charts"
_DEFAULT_DB = os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
_SOURCE = "defillama"
_SUB_CATEGORY = "chains_summary"
_METRIC = "total_tvl_bln"


def fetch_history(url: str = _HIST_URL, timeout: float = 20.0) -> list:
    """拉官方全链日频 TVL 历史 [{date: unix_sec, totalLiquidityUSD: usd}]。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"DeFiLlama 返回非列表: {type(data).__name__}")
    return data


def run(fetch, writer, *, days: int = 180, dry_run: bool = False, now=None) -> dict:
    """回填近 days 天；writer(source, sub_category, metric_name, value, ts_datetime)。"""
    now_dt = now or datetime.datetime.now(datetime.UTC)
    cutoff = int((now_dt - datetime.timedelta(days=days)).timestamp())
    stats = {
        "ok": True,
        "days": days,
        "dry_run": dry_run,
        "cutoff_ts": cutoff,
        "fetched": 0,
        "written": 0,
        "skipped_out_of_range": 0,
        "skipped_invalid": 0,
        "first_ts": None,
        "last_ts": None,
        "errors": [],
    }
    try:
        rows = fetch()
    except Exception as exc:  # noqa: BLE001 - 网络类异常统一记录，保留已写数据
        stats["ok"] = False
        stats["errors"].append(f"fetch: {type(exc).__name__}: {exc}")
        return stats

    stamps = []
    for item in rows or []:
        try:
            ts = int(item["date"])
            tvl = float(item["totalLiquidityUSD"])
        except (KeyError, TypeError, ValueError):
            stats["skipped_invalid"] += 1
            continue
        stats["fetched"] += 1
        if ts < cutoff:
            stats["skipped_out_of_range"] += 1
            continue
        if not dry_run:
            writer(
                _SOURCE,
                _SUB_CATEGORY,
                _METRIC,
                round(tvl / 1e9, 4),
                datetime.datetime.fromtimestamp(ts, datetime.UTC),
            )
        stats["written"] += 1
        stamps.append(ts)

    if stamps:
        stats["first_ts"] = min(stamps)
        stats["last_ts"] = max(stamps)
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DeFiLlama 全局 TVL 历史回填")
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument(
        "--days", type=int, default=180, help="回填天数（默认 180，覆盖 90 天口径）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只拉不写")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    repo = SqliteMarketMacroRepository(os.path.abspath(args.db))
    result = run(fetch_history, repo.upsert_metric, days=args.days, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        span = ""
        if result["first_ts"] and result["last_ts"]:
            fmt = "%Y-%m-%d"
            span = (
                f"{datetime.datetime.fromtimestamp(result['first_ts'], datetime.UTC):{fmt}}"
                f"~{datetime.datetime.fromtimestamp(result['last_ts'], datetime.UTC):{fmt}}"
            )
        print(
            f"[DeFiLlama TVL 回填] db={os.path.abspath(args.db)} "
            f"days={result['days']} dry_run={result['dry_run']} "
            f"written={result['written']} out_of_range={result['skipped_out_of_range']} {span}"
        )
        for err in result["errors"]:
            print(f"    ! {err}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
