# -*- coding: utf-8 -*-
"""跨资产龙头注册表（与 40 层分类统一）单元测试。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import align as A  # noqa: E402
from l1agg import leader_registry as R  # noqa: E402

_DAY = 86400
NOW = int(datetime.datetime(2026, 11, 14, 12, 0, tzinfo=datetime.UTC).timestamp())


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


def test_classification_is_loaded_from_40():
    """分类口径必须来自 40 层，不得在 54 内另立。"""
    assert R.CLASS_IDS, "未读到 40 层 ASSET_CLASSES"
    for cls in (
        "crypto",
        "precious_metal",
        "energy",
        "us_index",
        "us_etf",
        "us_stock",
        "fx",
        "rates_credit",
        "macro",
    ):
        assert cls in R.CLASS_IDS, cls


def test_every_binding_class_exists_in_40():
    for sym, b in R.BINDINGS.items():
        assert b.asset_class in R.CLASS_IDS, (sym, b.asset_class)


def test_no_silent_gap_for_g1_anchors():
    """G1 六个锚：要么已绑定，要么在 UNBOUND 里登记原因。"""
    for sym in R.G1_ANCHORS:
        assert sym in R.BINDINGS or sym in R.UNBOUND, f"G1 锚 {sym} 既未绑定也未登记缺失"


def test_proxy_flag_explicit():
    assert R.resolve("CL").proxy is True
    assert R.resolve("DXY").proxy is True
    assert R.resolve("US500").proxy is True
    assert R.resolve("BTC").proxy is False


def test_unbound_has_reason():
    assert R.resolve("JP225") is None
    assert "历史不足" in (R.unbound_reason("JP225") or "")
    assert R.class_of("JP225") == "apac_index"
    assert R.class_of("DJIA") == "us_index"  # 40 未登记成员，经绑定归属


def test_cross_asset_backfill_bindings():
    """回填落库后：美股/ETF/金属/能源全部可解析，且代理标注显式。"""
    for sym in (
        "DJIA",
        "NVDA",
        "AAPL",
        "MSFT",
        "TSLA",
        "AMZN",
        "GOOGL",
        "META",
        "SPY",
        "QQQ",
        "XAG",
        "XCU",
        "BZ",
        "NG",
    ):
        assert R.is_bound(sym), sym
        assert R.unbound_reason(sym) is None
    assert R.resolve("DJIA").proxy is True
    assert R.resolve("BZ").proxy is True
    assert R.resolve("NG").proxy is True
    assert R.resolve("NVDA").proxy is False
    assert R.resolve("BZ").series_id == "DCOILBRENTEU::value"
    assert R.resolve("NG").series_id == "DHHNGSP::value"
    assert R.class_of("XAG") == "precious_metal"
    assert R.class_of("XCU") == "industrial_metal"
    assert R.class_of("SPY") == "us_etf"


def test_load_leader_raises_for_uncollected(tmp_path):
    db = tmp_path / "core.db"
    _make_db(str(db), [])
    with pytest.raises(A.AlignError) as exc:
        A.load_leader(str(db), "JP225")
    assert "not_collected" in str(exc.value)
    with pytest.raises(A.AlignError):
        A.load_leader(str(db), "NOT_A_SYMBOL")


def test_load_leader_reads_bound_series(tmp_path):
    db = tmp_path / "core.db"
    rows = [("fred", "DCOILWTICO", "value", 70.0 + i, NOW - (4 - i) * _DAY) for i in range(5)]
    _make_db(str(db), rows)
    series = A.load_leader(str(db), "CL", days=30)
    assert len(series) == 5
    assert list(series.values())[-1] == 74.0
    # 绑定存在但库内无点 → 同样报 not_collected，不得静默返回 {}
    with pytest.raises(A.AlignError):
        A.load_leader(str(db), "BTC")


def test_coverage_marks_status(tmp_path):
    db = tmp_path / "core.db"
    rows = [("okx", "BTC", "close_usd", 100.0 + i, NOW - (299 - i) * _DAY) for i in range(300)]
    _make_db(str(db), rows)
    rows_out = {r["symbol"]: r for r in R.coverage(str(db), min_days=250)}
    assert rows_out["BTC"]["status"] == "available"
    assert rows_out["BTC"]["sample_n"] == 300
    assert rows_out["ETH"]["status"] == "missing"  # 已绑定但无点
    assert rows_out["NVDA"]["status"] == "missing"  # 已绑定但库里没有点
    assert rows_out["JP225"]["status"] == "not_collected"
    summary = R.coverage_summary(str(db), min_days=250)
    assert summary["available"] == 1
    assert summary["class_count"] == len(R.CLASS_IDS)


def test_leaders_by_class_covers_all_classes():
    grouped = R.leaders_by_class()
    for cls in R.CLASS_IDS:
        assert grouped.get(cls), f"{cls} 无任何龙头"


def test_default_pool_scope():
    """「数据与图表」默认池：BTC/黄金/原油/三大指数/VIX/美股代币龙头。"""
    pool = R.default_pool()
    assert pool[0] == "BTC"
    assert len(pool) == len(set(pool))
    assert all(R.is_bound(sym) for sym in pool), [sym for sym in pool if not R.is_bound(sym)]
    classes = [R.class_of(sym) for sym in pool]
    assert classes.count("us_index") == 3
    for cls in ("crypto", "precious_metal", "energy", "macro", "us_stock"):
        assert cls in classes, cls
    assert "VIX" in pool
    # 返回副本，调用方修改不污染注册表（ETH 已在首屏内，改用池外标的做探针）
    pool.append("DOGE")
    assert "DOGE" not in R.default_pool()


def test_unbound_tokenized_stocks_visible():
    assert R.is_bound("COIN") is False
    assert "未采集" in (R.unbound_reason("COIN") or "")
    assert "未采集" in (R.unbound_reason("MSTR") or "")


def test_frontend_script_uses_registry_pool():
    """前端脚本不得自带资产白名单：默认池必须来自 leader_registry。"""
    import importlib.util

    repo = os.path.dirname(os.path.abspath(_MODULE_ROOT))
    script = os.path.join(repo, "3.1-FRONTEND", "scripts", "visual_overview.py")
    assert os.path.isfile(script), script
    spec = importlib.util.spec_from_file_location("_visual_overview", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    symbols, base, _ = mod._parse_args([])
    assert symbols == R.default_pool()[:12]
    assert base == "BTC"
    assert not hasattr(mod, "DEFAULT_ASSETS")
