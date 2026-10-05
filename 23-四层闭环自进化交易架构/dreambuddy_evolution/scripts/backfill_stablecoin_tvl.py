#!/usr/bin/env python3
"""
backfill_stablecoin_tvl.py — 稳定币总 TVL 历史补采脚本 (Phase 3).

数据源: DefiLlama Stablecoins API (免费, 无需 Key)
  GET https://stablecoins.llama.fi/stablecoincharts/all

补采范围: 2020-12-01 至今.
返回每日 TVL (USD). 写入 19-DAL mm_metrics (sub_category=stablecoin_tvl).

FAIL-OPEN: 网络/API 异常 → 记录日志退出, 不中断.

用法:
  python backfill_stablecoin_tvl.py [--start 2020-12-01] [--end 2025-01-01]
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_stablecoin_tvl")

_API = "https://stablecoins.llama.fi/stablecoincharts/all"


def fetch_tvl() -> list[dict]:
    """拉取稳定币 TVL 历史数据."""
    try:
        resp = requests.get(_API, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("非列表响应: %s", str(data)[:200])
            return []
        return data
    except Exception as exc:
        logger.error("拉取稳定币 TVL 失败: %s", exc)
        return []


def write_to_dal(records: list[dict], start: datetime, end: datetime) -> int:
    """将 TVL 记录写入 19-DAL.

    Args:
        records: list of {"date": int (unix ts), "totalCirculatingUSD": {...}}
        start: 起始时间过滤
        end: 结束时间过滤

    Returns:
        写入条数
    """
    if not records:
        return 0
    try:
        from dreambuddy_dal import get_market_macro_repo
        repo = get_market_macro_repo(backend="sqlite_unified")
    except Exception as exc:
        logger.error("无法获取 DAL repo: %s", exc)
        return 0

    written = 0
    for rec in records:
        try:
            ts = int(rec.get("date", 0))
            if ts <= 0:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if dt < start or dt > end:
                continue
            # totalCirculatingUSD 是 dict {stablecoin_id: amount}, 求和
            circ = rec.get("totalCirculatingUSD") or {}
            if isinstance(circ, dict):
                tvl = sum(float(v) for v in circ.values() if v)
            elif isinstance(circ, (int, float)):
                tvl = float(circ)
            else:
                continue
            if tvl <= 0:
                continue
            repo.upsert_metric(
                source="defillama",
                sub_category="stablecoin_tvl",
                metric_name="total_tvl_usd",
                metric_value=tvl,
                ts=dt,
            )
            written += 1
        except Exception as exc:
            logger.debug("写入失败: %s", exc)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="稳定币 TVL 历史补采")
    parser.add_argument("--start", default="2020-12-01", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)

    logger.info("拉取稳定币 TVL: %s ~ %s", start.date(), end.date())
    records = fetch_tvl()
    logger.info("获取 %d 条原始记录", len(records))

    written = write_to_dal(records, start, end)
    logger.info("补采完成, 共写入 %d 条", written)


if __name__ == "__main__":
    main()
