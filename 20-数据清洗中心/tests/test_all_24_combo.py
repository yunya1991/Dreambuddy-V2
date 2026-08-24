"""T21 · Silver 覆盖 8 collector 全源（24 组合参数化）

8 collector × 3 资产 = 24 组合：
  yfinance × {BTC, COIN, XAU}      — finance, OHLCV 时序
  fred      × {M2NS, M2SL, CPI}     — macro, metrics 扁平
  etherscan × {ETH, BTC, USDT}     — chain, metrics
  ccxt      × {BTC, ETH, SOL}      — chain, OHLCV 时序
  defillama × {ETH, BSC, SOL}      — chain, TVL metrics
  feedparser× {BTC, COIN, XAU}     — news, events
  gdelt     × {BTC, COIN, XAU}     — news, events
  tavily    × {BTC, COIN, XAU}     — news, events

断言：CleaningTrace 非空 + Gate 不崩（PASS/FAIL 都允许，只要不抛）
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "18-数据获取中心"))
sys.path.insert(0, str(_PROJECT_ROOT / "20-数据清洗中心"))

from data_center.core.contract import DataRecord  # noqa: E402


# ============================================================
# 24 组合参数表（8 collector × 3 资产）
# ============================================================
COMBOS = [
    # yfinance × 3 finance 资产
    ("yfinance", "BTC", "finance", "ohlcv"),
    ("yfinance", "COIN", "finance", "ohlcv"),
    ("yfinance", "XAU", "finance", "ohlcv"),
    # fred × 3 macro 指标
    ("fred", "M2NS", "macro", "m2"),
    ("fred", "M2SL", "macro", "m2"),
    ("fred", "CPI", "macro", "cpi"),
    # etherscan × 3 chain 资产
    ("etherscan", "ETH", "chain", "whale"),
    ("etherscan", "BTC", "chain", "whale"),
    ("etherscan", "USDT", "chain", "whale"),
    # ccxt × 3 chain OHLCV
    ("ccxt", "BTC", "chain", "ohlcv"),
    ("ccxt", "ETH", "chain", "ohlcv"),
    ("ccxt", "SOL", "chain", "ohlcv"),
    # defillama × 3 chain TVL
    ("defillama", "ETH", "chain", "tvl"),
    ("defillama", "BSC", "chain", "tvl"),
    ("defillama", "SOL", "chain", "tvl"),
    # feedparser × 3 news
    ("feedparser", "BTC", "news", "rss"),
    ("feedparser", "COIN", "news", "rss"),
    ("feedparser", "XAU", "news", "rss"),
    # gdelt × 3 news
    ("gdelt", "BTC", "news", "gdelt"),
    ("gdelt", "COIN", "news", "gdelt"),
    ("gdelt", "XAU", "news", "gdelt"),
    # tavily × 3 news
    ("tavily", "BTC", "news", "tavily"),
    ("tavily", "COIN", "news", "tavily"),
    ("tavily", "XAU", "news", "tavily"),
]


def _make_sample_record(source: str, asset: str, category: str, sub_category: str) -> DataRecord:
    """为每个 collector 构造样例 DataRecord"""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rng = np.random.default_rng(42)

    if category == "finance" and sub_category == "ohlcv":
        # OHLCV 时序（yfinance/ccxt）
        n = 168  # 7 天小时级
        base = 50000 if asset == "BTC" else (200 if asset == "COIN" else 2000)
        close = base * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        timeseries = [
            {
                "timestamp": (datetime.utcnow() - timedelta(hours=n - i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": float(close[i] * 0.999),
                "high": float(close[i] * 1.005),
                "low": float(close[i] * 0.995),
                "close": float(close[i]),
                "volume": float(1e6 * (1 + rng.uniform(-0.5, 0.5))),
            }
            for i in range(n)
        ]
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset},
            events=[], timeseries=timeseries, raw={},
        )

    elif category == "macro":
        # macro 扁平 metrics（fred）
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts,
            metrics={"asset": asset, "value": float(rng.uniform(100, 200)), "unit": "USD"},
            events=[], timeseries=[], raw={},
        )

    elif category == "chain" and sub_category == "tvl":
        # TVL metrics（defillama）
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts,
            metrics={"asset": asset, "tvl": float(rng.uniform(1e9, 5e10)), "chain": asset},
            events=[], timeseries=[], raw={},
        )

    elif category == "chain" and sub_category == "whale":
        # whale 事件（etherscan）
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset},
            events=[
                {"timestamp": ts, "from": "0xabc", "to": "0xdef", "value": float(rng.uniform(10, 1000))},
                {"timestamp": ts, "from": "0x123", "to": "0x456", "value": float(rng.uniform(10, 1000))},
            ],
            timeseries=[], raw={},
        )

    elif category == "news":
        # news events
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset},
            events=[
                {"timestamp": ts, "title": f"{asset} market update", "importance": "medium"},
                {"timestamp": ts, "title": f"{asset} analysis report", "importance": "low"},
            ],
            timeseries=[], raw={},
        )

    # fallback
    return DataRecord(
        source=source, category=category, sub_category=sub_category,
        timestamp=ts, metrics={"asset": asset}, events=[], timeseries=[], raw={},
    )


@pytest.mark.parametrize("source,asset,category,sub_category", COMBOS, ids=[
    f"{s}-{a}" for s, a, _, _ in COMBOS
])
def test_t21_silver_covers_all_8_collectors(source, asset, category, sub_category):
    """T21: 每个 collector×asset 组合构造样例 DataRecord → 跑 CleaningPipeline → trace 非空 + 不崩"""
    from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig

    rec = _make_sample_record(source, asset, category, sub_category)
    pipe = DataCleaningPipeline(PipelineConfig(
        enforce_hard_block=False,  # 允许 FAIL
        fail_open=True,
        freshness_threshold=timedelta(days=30),
    ))
    silver = pipe.clean([rec], source=source, category=category)

    # trace 非空
    assert len(silver.trace.actions) > 0, f"trace 为空: {source}-{asset}"
    # Gate 不崩（PASS/FAIL 都允许）
    assert isinstance(silver.gate_passed, bool)
    # df 非空（除非是 macro 单行）
    assert silver.df is not None
