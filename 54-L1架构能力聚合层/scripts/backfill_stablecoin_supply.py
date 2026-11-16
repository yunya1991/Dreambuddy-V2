# -*- coding: utf-8 -*-
"""稳定币总供给历史回填（SPEC-54c / D-A16 数据源）。

为什么需要：`stablecoins_top_10.total_circulating_usd_bln` 仅 2026-09-28 起约 49 天，
D-A16 的 7/30 日增速虽可算，但无长历史对照。本脚本用 DefiLlama 免费接口
（`https://stablecoins.llama.fi/stablecoincharts/all`，免 Key）补齐日频长历史，
写入**独立子类**，不覆盖既有短序列：

    source=defillama_stablecoins, sub_category=stablecoin_supply,
    metric=total_circulating_usd / total_circulating_usd_bln

幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp)，可安全重跑。

用法：
    python3 scripts/backfill_stablecoin_supply.py --dry-run
    python3 scripts/backfill_stablecoin_supply.py --days 2000
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

_MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_REPO_ROOT = os.path.normpath(os.path.join(_MODULE_ROOT, ".."))
for _p in (_MODULE_ROOT, os.path.join(_REPO_ROOT, "19-数据访问层")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_DB = os.path.join(_REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db")
SOURCE = "defillama_stablecoins"
SUB_CATEGORY = "stablecoin_supply"
URL = "https://stablecoins.llama.fi/stablecoincharts/all"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
DEFAULT_DAYS = 1095


def fetch(stablecoin_id: Optional[int] = None, timeout: int = 30) -> List[Dict[str, Any]]:
    """拉取全量稳定币日频总供给；返回 [{ts, values:{...}}]。"""
    url = URL if stablecoin_id is None else f"{URL}?stablecoin={int(stablecoin_id)}"
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — 固定 https
        payload = json.loads(response.read().decode("utf-8"))
    rows: List[Dict[str, Any]] = []
    for point in payload or []:
        try:
            ts = int(point["date"])
        except (KeyError, TypeError, ValueError):
            continue
        circulating = point.get("totalCirculating") or {}
        usd = point.get("totalCirculatingUSD") or {}
        value = usd.get("peggedUSD", circulating.get("peggedUSD"))
        if value is None:
            total = sum(float(v) for v in circulating.values() if v is not None)
            value = total or None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        rows.append(
            {
                "ts": _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).replace(tzinfo=None),
                "values": {
                    "total_circulating_usd": amount,
                    "total_circulating_usd_bln": round(amount / 1e9, 6),
                },
            }
        )
    rows.sort(key=lambda item: item["ts"])
    return rows


def run(writer, *, days: int = DEFAULT_DAYS, dry_run: bool = False, today=None) -> Dict[str, Any]:
    today = today or _dt.date.today()
    cutoff = today - _dt.timedelta(days=int(days))
    rows = [row for row in fetch() if row["ts"].date() >= cutoff]
    written = 0
    for row in rows:
        for metric, value in row["values"].items():
            if not dry_run:
                writer(SOURCE, SUB_CATEGORY, metric, float(value), row["ts"])
            written += 1
    return {
        "source": SOURCE,
        "sub_category": SUB_CATEGORY,
        "days": int(days),
        "dry_run": dry_run,
        "fetched": len(rows),
        "written": written,
        "first": rows[0]["ts"].date().isoformat() if rows else "",
        "last": rows[-1]["ts"].date().isoformat() if rows else "",
        "ok": bool(rows),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="稳定币总供给历史回填")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import (
        SqliteMarketMacroRepository,
    )

    repo = SqliteMarketMacroRepository(os.path.abspath(args.db))
    result = run(repo.upsert_metric, days=args.days, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"[稳定币供给回填] db={os.path.abspath(args.db)} dry_run={args.dry_run}")
        print(
            f"  {result['sub_category']:20s} n={result['written']:6d} "
            f"{result['first']}~{result['last']} [{'ok' if result['ok'] else 'empty'}]"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
