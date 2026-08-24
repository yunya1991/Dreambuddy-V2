"""T22 · ★ T-G4 拦截率硬门槛：96 脏数据注入

8源 × 3资产 × 4类脏 = 96 条参数化注入：
  EMPTY     — 空列表
  CONTRACT  — 契约非法（timestamp 格式错）
  DUPLICATE — 同批次重复 record
  STALE     — 过期数据（5年前）

断言：总拦截率 gate_passed=False 比例 ≥ 99.5%（96条中漏拦截 ≤ 0）
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "18-数据获取中心"))
sys.path.insert(0, str(_PROJECT_ROOT / "20-数据清洗中心"))

from data_center.core.contract import DataRecord  # noqa: E402

# ============================================================
# 8源 × 3资产 = 24 基础组合
# ============================================================
_SOURCES = [
    ("yfinance", "finance", "ohlcv"),
    ("fred", "macro", "m2"),
    ("etherscan", "chain", "whale"),
    ("ccxt", "chain", "ohlcv"),
    ("defillama", "chain", "tvl"),
    ("feedparser", "news", "rss"),
    ("gdelt", "news", "gdelt"),
    ("tavily", "news", "tavily"),
]
_ASSETS = ["BTC", "COIN", "XAU"]
_DIRTY_TYPES = ["EMPTY", "CONTRACT", "DUPLICATE", "STALE"]

# 96 组合
COMBOS = []
for src, cat, sub in _SOURCES:
    for asset in _ASSETS:
        for dirty in _DIRTY_TYPES:
            COMBOS.append((src, asset, cat, sub, dirty))


def _make_valid_record(source: str, asset: str, category: str, sub_category: str) -> DataRecord:
    """构造合法样例 DataRecord"""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if category in ("finance", "chain") and sub_category == "ohlcv":
        n = 48
        rng = np.random.default_rng(42)
        close = 50000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        ts_list = [
            {
                "timestamp": (datetime.utcnow() - timedelta(hours=n - i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": float(close[i] * 0.999),
                "high": float(close[i] * 1.005),
                "low": float(close[i] * 0.995),
                "close": float(close[i]),
                "volume": float(1e6),
            }
            for i in range(n)
        ]
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset},
            events=[], timeseries=ts_list, raw={},
        )
    elif category == "news":
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset},
            events=[{"timestamp": ts, "title": f"{asset} news", "importance": "medium"}],
            timeseries=[], raw={},
        )
    elif category == "macro":
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset, "value": 150.0, "unit": "USD"},
            events=[], timeseries=[], raw={},
        )
    else:
        return DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=ts, metrics={"asset": asset, "tvl": 1e9},
            events=[], timeseries=[], raw={},
        )


def _make_dirty_records(source: str, asset: str, category: str, sub_category: str, dirty_type: str):
    """构造脏 DataRecord 列表"""
    if dirty_type == "EMPTY":
        return []
    elif dirty_type == "CONTRACT":
        # timestamp 非法格式
        rec = _make_valid_record(source, asset, category, sub_category)
        return [DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp="INVALID_TIMESTAMP",
            metrics=rec.metrics, events=rec.events, timeseries=rec.timeseries, raw={},
        )]
    elif dirty_type == "DUPLICATE":
        # 两条完全相同的 record
        rec = _make_valid_record(source, asset, category, sub_category)
        return [rec, rec]
    elif dirty_type == "STALE":
        # 5年前的 timestamp
        stale_ts = "2020-01-01T00:00:00Z"
        rec = _make_valid_record(source, asset, category, sub_category)
        return [DataRecord(
            source=source, category=category, sub_category=sub_category,
            timestamp=stale_ts,
            metrics=rec.metrics, events=rec.events, timeseries=rec.timeseries, raw={},
        )]
    return []


@pytest.fixture(scope="module")
def gate_stats():
    """收集所有96条的 gate_passed 结果"""
    return {"total": 0, "blocked": 0, "leaked": []}


@pytest.mark.parametrize("source,asset,category,sub_category,dirty_type", COMBOS, ids=[
    f"{s}-{a}-{d}" for s, a, _, _, d in COMBOS
])
def test_t22_dirty_injection_blocked(source, asset, category, sub_category, dirty_type, gate_stats):
    """T22: 每条脏 DataRecord → CleaningPipeline → gate_passed 应为 False"""
    from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig

    dirty_records = _make_dirty_records(source, asset, category, sub_category, dirty_type)
    pipe = DataCleaningPipeline(PipelineConfig(
        enforce_hard_block=False,
        fail_open=True,
        freshness_threshold=timedelta(hours=48),
    ))
    silver = pipe.clean(dirty_records, source=source, category=category)

    gate_stats["total"] += 1
    if not silver.gate_passed:
        gate_stats["blocked"] += 1
    else:
        gate_stats["leaked"].append(f"{source}-{asset}-{dirty_type}")


def test_t22_g4_overall_block_rate(gate_stats):
    """★ T-G4: 总拦截率 ≥ 99.5%"""
    total = gate_stats["total"]
    blocked = gate_stats["blocked"]
    if total == 0:
        pytest.fail("未收集到任何脏数据测试结果")
    block_rate = blocked / total
    leaked = gate_stats["leaked"]
    assert block_rate >= 0.995, (
        f"T-G4 拦截率 {block_rate:.4f} < 0.995: "
        f"blocked={blocked}/{total}, leaked={leaked}"
    )
