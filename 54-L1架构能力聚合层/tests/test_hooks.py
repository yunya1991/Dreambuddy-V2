# -*- coding: utf-8 -*-
"""四类追问钩子 + 三项可执行能力（hooks / relations）单元测试。"""

import datetime
import math
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import hooks as H  # noqa: E402
from l1agg import price_echo as P  # noqa: E402
from l1agg import relations as R  # noqa: E402

TODAY = datetime.date(2026, 11, 14)


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_metrics (
            source TEXT NOT NULL, sub_category TEXT NOT NULL, metric_name TEXT NOT NULL,
            metric_value REAL, timestamp INTEGER NOT NULL,
            PRIMARY KEY (source, sub_category, metric_name, timestamp)
        ) WITHOUT ROWID
        """)
    conn.executemany("INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _daily_rows(sub, metric, n, start=None, base=100.0, drift=0.004, wave=0.0):
    rows = []
    start = start or (TODAY - datetime.timedelta(days=n - 1))
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        ts = int(datetime.datetime(d.year, d.month, d.day, 16, tzinfo=datetime.UTC).timestamp())
        val = base * (1 + drift) ** i * (1 + wave * math.sin(i / 7.0))
        rows.append(("test", sub, metric, val, ts))
    return rows


# ---------- 1. 无年份日期解析 ----------


def test_parse_day_without_year_uses_current_year():
    assert P.parse_day("查询9月9日以太坊价格", today=TODAY) == "2026-09-09"


def test_parse_day_without_year_rolls_back_when_future():
    assert P.parse_day("12月1日", today=TODAY) == "2025-12-01"


def test_parse_day_hao_suffix():
    assert P.parse_day("9月9号", today=TODAY) == "2026-09-09"


def test_find_past_day_reference_matches_user_case():
    assert P.find_past_day_reference("查询9月9日以太坊价格", today=TODAY) == "2026-09-09"


# ---------- 2. 四类钩子 ----------


def test_hooks_four_items_in_order():
    hooks = H.build_hooks("ETH", at_day="2026-09-09")
    assert [h["id"] for h in hooks] == [
        "past_now_echo",
        "leader_compare",
        "top_correlation",
        "persistence_strength",
    ]


def test_hook_leader_for_eth_is_btc():
    hooks = H.build_hooks("ETH", at_day="2026-09-09")
    assert "比特币" in hooks[0]["text"]
    assert "2026-09-09" in hooks[0]["query"]
    assert "比特币" in hooks[0]["query"]


def test_hook_queries_are_executable_phrases():
    hooks = H.build_hooks("ETH")
    assert hooks[1]["query"] == "对比以太坊和比特币的涨跌幅"
    assert hooks[2]["query"] == "与以太坊相关性最高的指标"
    assert hooks[3]["query"] == "以太坊趋势延续性强度"


def test_hook_leader_for_btc_uses_peer():
    hooks = H.build_hooks("BTC")
    assert "以太坊" in hooks[0]["text"]
    assert "以太坊" in hooks[1]["query"]


def test_hook_group_mapping_us_equity():
    assert H.leader_of("NVDA") == "US500"
    assert H.leader_of("US500") == "US500"
    assert H.peer_of("US500") == "US100"


def test_format_hooks_text():
    text = H.format_hooks(H.build_hooks("ETH"))
    assert text.startswith("\n\n您还可以继续问：")
    assert len([line for line in text.splitlines() if line.strip()]) == 5


# ---------- 3. 龙头对照 ----------


def test_leader_gap_synthetic(tmp_path):
    db = str(tmp_path / "t.db")
    rows = _daily_rows("BTC", "close_usd", 200, base=100.0, drift=0.005)
    rows += _daily_rows("ETH", "close_usd", 200, base=50.0, drift=0.008)
    _make_db(db, rows)
    out = R.leader_gap(db, "ETH", days=365)
    assert out["symbol"] == "ETH"
    assert out["peer"] == "BTC"
    assert out["sample_n"] >= 150
    assert out["symbol_pct"] > out["peer_pct"]
    assert out["gap_pp"] > 0


def test_leader_gap_rejects_thin_overlap(tmp_path):
    db = str(tmp_path / "t.db")
    _make_db(db, _daily_rows("BTC", "close_usd", 5) + _daily_rows("ETH", "close_usd", 5))
    with pytest.raises(R.RelationError):
        R.leader_gap(db, "ETH")


# ---------- 4. 相关性 Top ----------


def test_top_correlated_excludes_same_price_and_ranks_indicators(tmp_path):
    """同质价格（ETH/BTC 价格、市值、盘口）不进指标排名，只作 price_baseline。"""
    db = str(tmp_path / "t.db")
    n = 400
    btc = _daily_rows("BTC", "close_usd", n, base=100.0, drift=0.004, wave=0.05)
    eth = []
    for _src, _sub, _metric, val, ts in btc:
        eth.append(("test", "ETH", "close_usd", val * 0.5, ts))
    # 真实维度指标：与 BTC 日变动同向
    flow = []
    for i, (_src, _sub, _metric, _val, ts) in enumerate(btc):
        flow.append(("test", "etf_flow", "total_flow", 10.0 * math.sin(i / 5.0), ts))
    # 价格衍生量：市值（应被排除）
    mcap = []
    for _src, _sub, _metric, val, ts in btc:
        mcap.append(("test", "btc_basics", "market_cap_usd", val * 1e6, ts))
    _make_db(db, btc + eth + flow + mcap)

    out = R.top_correlated(db, "BTC", top_k=3, days=1095, min_n=120)
    labels = [x["label"] for x in out["topk"]]
    assert all("ETH" not in name for name in labels)
    assert all(x["metric_name"] != "market_cap_usd" for x in out["topk"])
    assert out["price_baseline"][0]["sub_category"] == "ETH"
    assert "资产价格对照" in out["text"]
    assert out["method"] == "delta_pearson_by_observation_freq"


def test_top_correlated_low_sample_not_ranked(tmp_path):
    """样本不足的指标只进 low_sample，不参与主榜。"""
    db = str(tmp_path / "t.db")
    btc = _daily_rows("BTC", "close_usd", 400, wave=0.05)
    short = _daily_rows("stablecoins_top_10", "DAI_bln", 60, base=1.0, drift=0.001)
    _make_db(db, btc + short)
    out = R.top_correlated(db, "BTC", top_k=3, days=1095, min_n=120)
    assert all(x["sub_category"] != "stablecoins_top_10" for x in out["topk"])
    assert out["low_sample"]
    assert "样本不足" in out["text"]


def test_top_correlated_monthly_group(tmp_path):
    """月频指标（如 CPI）单独成组，不因日频样本不足被丢弃。"""
    db = str(tmp_path / "t.db")
    btc = _daily_rows("BTC", "close_usd", 1100, wave=0.05)
    cpi = []
    start = TODAY - datetime.timedelta(days=1080)
    for i in range(37):
        d = start + datetime.timedelta(days=30 * i)
        ts = int(datetime.datetime(d.year, d.month, d.day, 16, tzinfo=datetime.UTC).timestamp())
        cpi.append(("test", "CPIAUCSL", "value", 300.0 + i * 0.8 + 2.0 * math.sin(i), ts))
    _make_db(db, btc + cpi)
    out = R.top_correlated(db, "BTC", top_k=3, days=1095, min_n=120)
    assert out["monthly"]
    assert out["monthly"][0]["freq"] == "monthly"
    assert out["topk"][0]["freq"] == "monthly"
    assert "月频" in out["text"]


# ---------- 5. 延续性强度 ----------


def test_persistence_strength_synthetic(tmp_path):
    db = str(tmp_path / "t.db")
    _make_db(db, _daily_rows("BTC", "close_usd", 500, drift=0.003, wave=0.02))
    out = R.persistence_strength(db, "BTC", days=1200)
    assert out["capability"] == "persistence_strength"
    assert out["strength"] in {"strong", "medium", "weak", "unknown"}
    assert out["sample_n"] > 0
    assert "趋势延续性强度" in out["text"]


def test_persistence_strength_reports_missing(tmp_path):
    db = str(tmp_path / "t.db")
    _make_db(db, [])
    with pytest.raises(R.RelationError):
        R.persistence_strength(db, "BTC")
