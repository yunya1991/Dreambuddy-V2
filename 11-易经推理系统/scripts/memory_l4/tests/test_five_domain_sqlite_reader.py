#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_five_domain_sqlite_reader — 验证战略层从数据中心 SQLite 读五维数据。

覆盖：
1. 完整落库 → reader 读出所有字段 + 衍生计算（merrill/liquidity/atr_proxy）
2. 空 DB → fail-open 返回空 dict
3. DB 不存在 → fail-open 返回空 dict
4. 衍生计算函数直接验证
5. 旧记录被新记录覆盖（按 id 倒序取最新）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_DATA_CENTER = os.path.join(_REPO, "18-数据获取中心")
for _p in (_DATA_CENTER, _REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data_center.core.contract import DataRecord  # noqa: E402
from data_center.storage.sink_sqlite import SqliteSink  # noqa: E402
from scripts.memory_l4.five_domain_sqlite_reader import (  # noqa: E402
    _compute_liquidity_score,
    _compute_merrill,
    read_macro_from_sqlite,
)


def _ts(offset_min: float = 0.0) -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0) -
            timedelta(minutes=offset_min)).isoformat()


def _rec(source: str, category: str, sub: str, metrics: dict, raw: dict | None = None) -> DataRecord:
    return DataRecord(
        source=source, category=category, sub_category=sub, timestamp=_ts(),
        metrics=metrics, events={}, timeseries={}, raw=raw or {}, schema_version="v1",
    )


def test_read_macro_from_sqlite_full(tmp_path):
    db = str(tmp_path / "t.db")
    sink = SqliteSink(db)
    sink.write([
        _rec("fred", "macro", "FEDFUNDS", {"value": 5.25, "date": "2026-07-01"}),
        _rec("fred", "macro", "M2NS", {"value": 21000.0, "date": "2026-06-01"}),
        _rec("fred", "macro", "WALCL", {"value": 7000000.0, "date": "2026-08-19"}),
        _rec("fred", "macro", "CPIAUCSL", {"value": 310.0, "date": "2026-07-01"}),
        _rec("fred", "macro", "PPIACO", {"value": 280.0, "date": "2026-07-01"}),
        _rec("fred", "macro", "INDPRO", {"value": 105.0, "date": "2026-07-01"}),
        _rec("yfinance", "finance", "^VIX", {"price": 20.0, "symbol": "^VIX"}),
        _rec("defillama", "chain", "chains_summary",
             {"total_tvl_bln": 80.0},
             raw={"chains": {"Ethereum": {"tvl_bln": 30.0}, "TRON": {"tvl_bln": 10.0}}}),
    ])
    snap = read_macro_from_sqlite(db)
    # FRED 6 项
    assert snap["fedfunds_rate"] == 5.25
    assert snap["m2_index_bln"] == 21000.0
    assert snap["m2_yoy_pct"] is None  # 绝对值，同比暂留空
    assert snap["fed_balance_sheet_trillion"] == 0.0  # WALCL/1e12（pre-existing 换算，与 Fetcher 一致）
    assert snap["us_cpi_yoy_pct"] == 310.0
    assert snap["us_ppi_yoy_pct"] == 280.0
    assert snap["us_indpro_yoy_pct"] == 105.0
    # VIX
    assert snap["vix_close"] == 20.0
    # DeFi + 稳定币
    assert snap["defi_tvl_bln"] == 80.0
    assert snap["stablecoin_mcap_bln"] == 40.0  # ETH 30 + TRON 10
    # 衍生
    assert snap["merrill_phase"] == "OVERHEAT"  # cpi>=250 且 indpro>=100
    assert abs(snap["liquidity_score"] - 0.0625) < 1e-9  # 0.5*0.125 + 0.5*0.0
    assert abs(snap["atr_percentile_proxy"] - 0.25) < 1e-9  # (20-10)/40


def test_read_macro_latest_wins(tmp_path):
    """同一源多条记录，reader 取最新（id 倒序首条）。"""
    db = str(tmp_path / "t.db")
    sink = SqliteSink(db)
    sink.write([_rec("fred", "macro", "FEDFUNDS", {"value": 3.0, "date": "2026-06-01"})])
    sink.write([_rec("fred", "macro", "FEDFUNDS", {"value": 5.25, "date": "2026-07-01"})])
    snap = read_macro_from_sqlite(db)
    assert snap["fedfunds_rate"] == 5.25  # 新值覆盖旧值


def test_read_macro_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    SqliteSink(db)  # 仅建表，无数据
    snap = read_macro_from_sqlite(db)
    assert snap == {}  # 无记录 → 空 dict（fail-open）


def test_read_macro_missing_db(tmp_path):
    snap = read_macro_from_sqlite(str(tmp_path / "noexist.db"))
    assert snap == {}  # 文件不存在 → 空 dict


def test_read_macro_partial_data(tmp_path):
    """只落了部分源，reader 返回部分 dict，缺失键由调用方兜底。"""
    db = str(tmp_path / "partial.db")
    sink = SqliteSink(db)
    sink.write([_rec("fred", "macro", "FEDFUNDS", {"value": 4.5, "date": "2026-07-01"})])
    snap = read_macro_from_sqlite(db)
    assert snap.get("fedfunds_rate") == 4.5
    assert snap.get("vix_close") is None
    assert snap.get("defi_tvl_bln") is None


def test_compute_merrill():
    assert _compute_merrill(310.0, 105.0) == "OVERHEAT"
    assert _compute_merrill(200.0, 105.0) == "RECOVERY"
    assert _compute_merrill(310.0, 90.0) == "STAGFLATION"
    assert _compute_merrill(200.0, 90.0) == "REFLATION"
    assert _compute_merrill(None, 100.0) is None
    assert _compute_merrill(310.0, None) is None


def test_compute_liquidity_score():
    # fedfunds + m2 + bs 三项
    s = _compute_liquidity_score(3.0, 5.0, 6.0)
    # 0.5*((6-3)/6) + 0.25*((5+5)/15) + 0.25*((6-4)/5)
    # = 0.5*0.5 + 0.25*0.6667 + 0.25*0.4 = 0.25+0.1667+0.1 = 0.5167
    assert abs(s - 0.51667) < 1e-4
    # 单项
    assert abs(_compute_liquidity_score(3.0, None, None) - 0.5) < 1e-9
    # 全空
    assert _compute_liquidity_score(None, None, None) is None
