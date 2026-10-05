"""A1 历史外生数据采集 (2017-2024) → 19-DAL mm_metrics.

数据源:
  - FRED (宏观, 月度): CPIAUCSL, FEDFUNDS, M2SL
  - yfinance (宏观, 日线): DX-Y.NYB (DXY)
  - blockchain.info (链上, 日线): active_addresses, hash_rate, market_cap
  - Binance (funding rate, 尽力而为)

写入 19-DAL mm_metrics (sub_category.metric_name), 供 ExogenousDataBridge.fetch() 读取.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DAL_DIR = REPO.parent / "19-数据访问层"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(DAL_DIR) not in sys.path:
    sys.path.insert(0, str(DAL_DIR))
os.environ.setdefault("DATA_DIR", str(DAL_DIR / "data"))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from dreambuddy_dal import get_market_macro_repo  # noqa: E402

START = datetime(2017, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 12, 31, tzinfo=timezone.utc)


def collect_fred(repo) -> int:
    """采集 FRED 宏观数据 (CPI, FEDFUNDS, M2) 月度."""
    from fredapi import Fred
    api_key = os.environ.get("FRED_API_KEY", "2288a615aff3cf44117c0ef3cfabd61c")
    fred = Fred(api_key=api_key)
    n = 0

    # CPI (月度)
    cpi = fred.get_series("CPIAUCSL", observation_start=START.strftime("%Y-%m-%d"),
                          observation_end=END.strftime("%Y-%m-%d")).dropna()
    for dt, val in cpi.items():
        ts = dt.replace(tzinfo=timezone.utc)
        repo.upsert_metric("fred", "cpi", "actual", float(val), ts)
        n += 1
    logger.info("CPI: %d 月度点", len(cpi))

    # FEDFUNDS (月度) → 派生 hike_prob + rate_change + monetary_cycle
    ff = fred.get_series("FEDFUNDS", observation_start=START.strftime("%Y-%m-%d"),
                         observation_end=END.strftime("%Y-%m-%d")).dropna()
    prev = None
    for dt, val in ff.items():
        ts = dt.replace(tzinfo=timezone.utc)
        repo.upsert_metric("fred", "fomc_decision", "rate", float(val), ts)
        if prev is not None:
            change = float(val) - prev
            repo.upsert_metric("fred", "fomc_decision", "rate_change", round(change, 4), ts)
            hike_prob = 1.0 if change > 0.001 else (0.0 if change < -0.001 else 0.5)
            repo.upsert_metric("fred", "fedwatch", "hike_prob", hike_prob, ts)
            cut_prob = 1.0 - hike_prob if abs(change) > 0.001 else 0.5
            repo.upsert_metric("fred", "fedwatch", "cut_prob", cut_prob, ts)
            n += 3
        prev = float(val)
    logger.info("FEDFUNDS: %d 月度点 (派生 hike_prob/cut_prob/rate_change)", len(ff))

    # M2 (月度)
    m2 = fred.get_series("M2SL", observation_start=START.strftime("%Y-%m-%d"),
                         observation_end=END.strftime("%Y-%m-%d")).dropna()
    for dt, val in m2.items():
        ts = dt.replace(tzinfo=timezone.utc)
        repo.upsert_metric("fred", "macro", "m2_sl", float(val), ts)
        n += 1
    logger.info("M2SL: %d 月度点", len(m2))

    return n


def collect_dxy(repo) -> int:
    """采集 DXY 日线 (yfinance)."""
    import yfinance as yf
    dxy = yf.download("DX-Y.NYB", start=START.strftime("%Y-%m-%d"),
                      end=(END + timedelta(days=1)).strftime("%Y-%m-%d"), progress=False)
    n = 0
    for dt, row in dxy.iterrows():
        try:
            close = float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"])
        except (TypeError, ValueError, IndexError):
            continue
        if not np.isfinite(close):
            continue
        ts = dt.to_pydatetime().replace(tzinfo=timezone.utc)
        repo.upsert_metric("yfinance", "DX-Y.NYB", "close", close, ts)
        n += 1
    logger.info("DXY: %d 日线点", n)
    return n


def collect_blockchain(repo) -> int:
    """采集 blockchain.info 链上数据 (日线)."""
    charts = {
        "n-unique-addresses": ("btc_onchain", "active_addresses"),
        "hash-rate": ("btc_onchain", "hash_rate"),
        "market-cap": ("btc_basics", "market_cap_usd"),
    }
    n = 0
    for chart, (sub, metric) in charts.items():
        url = f"https://api.blockchain.info/charts/{chart}?timespan=8years&format=json"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
            vals = data.get("values", [])
            for v in vals:
                ts = datetime.fromtimestamp(v["x"], tz=timezone.utc)
                if ts < START or ts > END:
                    continue
                repo.upsert_metric("blockchain_info", sub, metric, float(v["y"]), ts)
                n += 1
            logger.info("blockchain %s.%s: %d 点", sub, metric, len(vals))
        except Exception as e:
            logger.warning("blockchain %s 失败: %s", chart, e)
        time.sleep(1)  # 避免限流
    return n


def collect_funding_rate(repo) -> int:
    """采集 Binance funding rate (尽力而为, 历史有限)."""
    n = 0
    try:
        from binance.client import Client
        client = Client("", "")  # 公开接口无需 key
        # BTCUSDT perpetual funding rate history
        klines = client.futures_funding_rate(
            symbol="BTCUSDT", limit=1000)
        for k in klines:
            ts = datetime.fromtimestamp(k["fundingTime"] / 1000, tzinfo=timezone.utc)
            if ts < START or ts > END:
                continue
            repo.upsert_metric("binance", "funding_rate", "funding_rate",
                               float(k["fundingRate"]), ts)
            n += 1
        logger.info("Binance funding rate: %d 点", n)
    except Exception as e:
        logger.warning("Binance funding rate 失败: %s", e)
    return n


def main():
    repo = get_market_macro_repo(backend="sqlite_unified")
    logger.info("DAL db_path: %s", repo.db_path)

    total = 0
    logger.info("=== 采集 FRED 宏观数据 ===")
    total += collect_fred(repo)

    logger.info("=== 采集 DXY 日线 ===")
    total += collect_dxy(repo)

    logger.info("=== 采集 blockchain.info 链上数据 ===")
    total += collect_blockchain(repo)

    logger.info("=== 采集 Binance funding rate (尽力而为) ===")
    total += collect_funding_rate(repo)

    logger.info("=== 采集完成: 共写入 %d 条记录 ===", total)

    # 验证
    from dreambuddy_dal import get_market_macro_repo as _g
    r2 = _g(backend="sqlite_unified")
    for sub, metric in [("cpi", "actual"), ("fomc_decision", "rate_change"),
                        ("fedwatch", "hike_prob"), ("DX-Y.NYB", "close"),
                        ("btc_onchain", "active_addresses"), ("btc_basics", "market_cap_usd")]:
        rows = r2.query_metric_by_time(sub, metric, START, END)
        if rows:
            ts = [row[3] for row in rows]
            print(f"  {sub}.{metric}: {len(rows)} pts, {min(ts).date()} ~ {max(ts).date()}")
        else:
            print(f"  {sub}.{metric}: 0 pts")

    return 0


if __name__ == "__main__":
    sys.exit(main())
