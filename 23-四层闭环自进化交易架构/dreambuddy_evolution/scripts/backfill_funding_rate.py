#!/usr/bin/env python3
"""
backfill_funding_rate.py — Binance 资金费率历史补采脚本 (Phase 3).

数据源: Binance Futures API (免费, 无需 Key)
  GET https://fapi.binance.com/fapi/v1/fundingRate
  支持 startTime / endTime (ms), limit ≤ 1000.

补采范围: 2019-09-01 至今 (Binance USDT-M 期货上线).
每 8 小时一条, 约 20000 条. 分页拉取并写入 19-DAL mm_metrics.

FAIL-OPEN: 网络/API 异常 → 记录日志跳过该批次, 不中断整体补采.

用法:
  python backfill_funding_rate.py [--start 2019-09-01] [--end 2025-01-01] [--symbol BTCUSDT]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_funding_rate")

_API = "https://fapi.binance.com/fapi/v1/fundingRate"
_PAGE_SIZE = 1000
_SLEEP_BETWEEN_PAGES = 0.2  # 避免触发限速


def fetch_page(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """拉取一页资金费率数据 (最多 1000 条)."""
    params = {
        "symbol": symbol,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": _PAGE_SIZE,
    }
    try:
        resp = requests.get(_API, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            logger.warning("非列表响应: %s", str(data)[:200])
            return []
        return data
    except Exception as exc:
        logger.warning("拉取失败 [%s - %s]: %s", start_ms, end_ms, exc)
        return []


def write_to_dal(records: list[dict]) -> int:
    """将资金费率记录写入 19-DAL mm_metrics.

    Args:
        records: list of {"fundingRate": str, "fundingTime": int}

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
            rate = float(rec.get("fundingRate", 0.0))
            ts_ms = int(rec.get("fundingTime", 0))
            if ts_ms <= 0:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            repo.upsert_metric(
                source="binance_futures",
                sub_category="funding_rate",
                metric_name="funding_rate",
                metric_value=rate,
                ts=ts,
            )
            written += 1
        except Exception as exc:
            logger.debug("写入失败: %s", exc)
    return written


def backfill(symbol: str, start: datetime, end: datetime) -> None:
    """分页拉取并写入 DAL."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    total_written = 0
    cursor = start_ms

    logger.info("开始补采 %s 资金费率: %s ~ %s", symbol, start.date(), end.date())

    while cursor < end_ms:
        page_end = min(cursor + _PAGE_SIZE * 8 * 3600 * 1000, end_ms)  # 8h/条 * 1000
        page = fetch_page(symbol, cursor, page_end)
        if page:
            written = write_to_dal(page)
            total_written += written
            last_ts = page[-1].get("fundingTime", cursor)
            logger.info(
                "批次 [%s] 写入 %d 条 (累计 %d), 最后时间 %s",
                datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).date(),
                written, total_written,
                datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat(),
            )
            cursor = last_ts + 1  # 下一页从最后一条之后开始
        else:
            # 空页: 推进 cursor 避免死循环
            cursor = page_end + 1

        time.sleep(_SLEEP_BETWEEN_PAGES)

    logger.info("补采完成, 共写入 %d 条", total_written)


def main() -> None:
    parser = argparse.ArgumentParser(description="Binance 资金费率历史补采")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对 (默认 BTCUSDT)")
    parser.add_argument("--start", default="2019-09-01", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)

    backfill(args.symbol, start, end)


if __name__ == "__main__":
    main()
