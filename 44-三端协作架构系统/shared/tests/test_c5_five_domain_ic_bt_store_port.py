"""C5 第五批：five_domain_ic_analysis + backtest_five_domain_v2 读路径 Store port 收编契约测试。

覆盖：
  - 两目标文件 sqlite3 直连已消除（connect 计数 = 0）；
  - 5 个新 helper（fetch_distinct_dates / fetch_rows_by_sources_until / fetch_latest_row /
    fetch_latest_rows_for_pairs / fetch_top10_inflow_until）开关关（legacy）与开关开
    （FD_IC_STORE_PORT / FD_BT5_STORE_PORT=1）输出逐字段相等；
  - date(timestamp) <= ? 与 timestamp <= ? 两种时间过滤形态分别等价；
  - top10 同批次 id 区间语义（id >= top-50 AND id <= top）；
  - ic_analysis 函数级等价（_get_daily_snapshots / _read_macro_for_date）；
    （backtest_five_domain_v2 模块级执行回测，不可 import，函数级等价走真实 DB 命令行验证）
  - FAIL-OPEN（DB 缺失 / port 故障均回落空结果；legacy 分支异常上抛保持原语义）；
  - 只读红线：port.write 未开放；port 文件无模块级 sys.path.insert。
"""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4"))
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统"))

import _five_domain_store_port as port_mod_flat  # noqa: E402  # ic_mod 内部实际引用（独立模块对象）
import five_domain_ic_analysis as ic_mod  # noqa: E402
from scripts.memory_l4 import _five_domain_store_port as port_mod  # noqa: E402

L4 = REPO_ROOT / "11-易经推理系统/scripts/memory_l4"
IC_PATH = L4 / "five_domain_ic_analysis.py"
BT_PATH = L4 / "backtest_five_domain_v2.py"
PORT_PATH = L4 / "_five_domain_store_port.py"

_MACRO_SOURCES = (
    "fred",
    "yfinance",
    "ccxt",
    "defillama",
    "etherscan",
    "tavily",
    "theblockbeats_dataview",
    "panewslab",
    "stablecoin_transparency",
    "odaily_newsflash",
    "fear_greed",
    "gold_supply_demand",
)
_BT_SOURCES = (
    "fred",
    "yfinance",
    "ccxt",
    "defillama",
    "etherscan",
    "tavily",
    "theblockbeats_dataview",
    "panewslab",
    "stablecoin_transparency",
)


@contextmanager
def _switch(name: str, on: bool):
    old = os.environ.get(name)
    if on:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _seed(tmp_path: Path) -> str:
    db = tmp_path / "records.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, "
        "category TEXT, sub_category TEXT, metrics TEXT, raw TEXT, "
        "timeseries TEXT, timestamp TEXT)"
    )
    rows = [
        # id, source, sub_category, metrics, raw, timeseries, timestamp
        ("fred", "macro", "FEDFUNDS", '{"value": 3.6}', None, None, "2026-10-01T08:00:00"),
        ("fred", "macro", "FEDFUNDS", '{"value": 3.7}', None, None, "2026-10-03T08:00:00"),
        ("yfinance", "market", "^VIX", '{"value": 22.5}', None, None, "2026-10-02T15:00:00"),
        (
            "stablecoin_transparency",
            "current",
            "tether_current",
            '{"usdt_circulating_usd_bln": 168.4}',
            None,
            None,
            "2026-10-03T00:00:00",
        ),
        (
            "stablecoin_transparency",
            "hist",
            "stablecoin_hist_usdt",
            None,
            None,
            json.dumps(
                [
                    {"date": "2026-09-30", "circulating_usd_bln": 160.0},
                    {"date": "2026-10-02", "circulating_usd_bln": 168.0},
                ]
            ),
            "2026-10-01T00:00:00",
        ),
        (
            "stablecoin_transparency",
            "hist",
            "stablecoin_hist_usdt",
            None,
            None,
            json.dumps([{"date": "2026-10-01", "circulating_usd_bln": 165.0}]),
            "2026-10-03T00:00:00",
        ),
        (
            "stablecoin_transparency",
            "hist",
            "stablecoin_hist_usdc",
            None,
            None,
            json.dumps([{"date": "2026-10-01", "circulating_usd_bln": 66.0}]),
            "2026-10-03T00:00:00",
        ),
        (
            "panewslab",
            "overview",
            "overview_market",
            '{"global_market_cap_usd": 2700000000000.0}',
            '{"overview_trends": {"series": {"btc": [{"timestamp": "2026-10-01T00:00:00", "value": 1600000000000.0}]}}}',
            None,
            "2026-10-02T00:00:00",
        ),
        # top10_inflow_di 同批次 4 行（id 连续）
        (
            "theblockbeats_dataview",
            "emotion",
            "top10_inflow_di",
            '{"symbol": "BTC", "inflow_usd": 100.0, "rank": 1, "inflow_text": "+1亿"}',
            None,
            None,
            "2026-10-02T10:00:00",
        ),
        (
            "theblockbeats_dataview",
            "emotion",
            "top10_inflow_di",
            '{"symbol": "ETH", "inflow_usd": 50.0, "rank": 2, "inflow_text": "+5千万"}',
            None,
            None,
            "2026-10-02T10:00:01",
        ),
        (
            "theblockbeats_dataview",
            "emotion",
            "top10_inflow_di",
            '{"symbol": "SOL", "inflow_usd": 25.0, "rank": 3, "inflow_text": "+2.5千万"}',
            None,
            None,
            "2026-10-02T10:00:02",
        ),
        (
            "theblockbeats_dataview",
            "emotion",
            "top10_inflow_di",
            '{"symbol": "BTC", "inflow_usd": 100.0, "rank": 1, "inflow_text": "+1亿"}',
            None,
            None,
            "2026-10-02T10:00:03",
        ),  # symbol 重复，去重语义验证
        (
            "theblockbeats_dataview",
            "emotion",
            "bottom_pulse_index",
            '{"score": 61}',
            None,
            None,
            "2026-10-03T01:00:00",
        ),
        (
            "fear_greed",
            "emotion",
            "crypto_fear_greed",
            '{"value": 55}',
            None,
            None,
            "2026-10-03T02:00:00",
        ),
        ("__noise__", "x", "x", '{"v": 1}', None, None, "2026-10-03T03:00:00"),
        # 晚于 target_date 的 top10 行：时间过滤必须排除
        (
            "theblockbeats_dataview",
            "emotion",
            "top10_inflow_di",
            '{"symbol": "DOGE", "inflow_usd": 999.0, "rank": 1, "inflow_text": "+9亿"}',
            None,
            None,
            "2026-10-05T00:00:00",
        ),
    ]
    for src, cat, sub, metrics, raw, ts, stamp in rows:
        conn.execute(
            "INSERT INTO records (source, category, sub_category, metrics, raw, "
            "timeseries, timestamp) VALUES (?,?,?,?,?,?,?)",
            (src, cat, sub, metrics, raw, ts, stamp),
        )
    conn.commit()
    conn.close()
    return str(db)


# ── 只读直连已消除 ────────────────────────────────────────────────────────
def test_read_connects_collected():
    direct = "sqlite3." + "connect("  # 动态拼接避免本文件自身成为命中（C10 ratchet 口径）
    assert IC_PATH.read_text(encoding="utf-8").count(direct) == 0
    assert BT_PATH.read_text(encoding="utf-8").count(direct) == 0
    # port 集中点：新增 5 个 helper 后 connect 总数上界（只减不增由 ratchet 门禁看守）
    assert PORT_PATH.read_text(encoding="utf-8").count(direct) <= 9


# ── helper 级等价：两种开关逐字段相等 ────────────────────────────────────
def test_distinct_dates_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch("FD_IC_STORE_PORT", False):
        legacy = port_mod.fetch_distinct_dates(db, _MACRO_SOURCES)
    with _switch("FD_IC_STORE_PORT", True):
        ported = port_mod.fetch_distinct_dates(db, _MACRO_SOURCES)
    assert legacy == ported
    assert legacy == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05"]
    assert "__noise__" not in json.dumps(legacy)


def test_rows_until_date_func_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch("FD_IC_STORE_PORT", False):
        legacy = [
            tuple(r)
            for r in port_mod.fetch_rows_by_sources_until(
                db, _MACRO_SOURCES, "2026-10-03", use_date_func=True
            )
        ]
    with _switch("FD_IC_STORE_PORT", True):
        ported = [
            tuple(r.values())
            for r in port_mod.fetch_rows_by_sources_until(
                db, _MACRO_SOURCES, "2026-10-03", use_date_func=True
            )
        ]
    assert legacy == ported
    assert legacy, "种子数据必须产出非空结果，否则等价断言无意义"
    # 列序：source, sub_category, metrics, raw, timestamp, id；id DESC
    ids = [r[5] for r in legacy]
    assert ids == sorted(ids, reverse=True)
    # date(timestamp) <= 2026-10-03：排除 2026-10-05 的 top10 行与 __noise__
    assert all(r[4] <= "2026-10-03T23:59:59" for r in legacy)
    assert all(r[0] != "__noise__" for r in legacy)
    # 同 key 最新行保留（fred FEDFUNDS id=2 的 3.7 在列）
    fred_rows = [r for r in legacy if r[0] == "fred" and r[1] == "FEDFUNDS"]
    assert fred_rows[0][2] == '{"value": 3.7}'


def test_rows_until_raw_ts_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch("FD_BT5_STORE_PORT", False):
        legacy = [
            tuple(r)
            for r in port_mod.fetch_rows_by_sources_until(
                db,
                _BT_SOURCES,
                "2026-10-02T23:59:59",
                switch="FD_BT5_STORE_PORT",
                use_date_func=False,
            )
        ]
    with _switch("FD_BT5_STORE_PORT", True):
        ported = [
            tuple(r.values())
            for r in port_mod.fetch_rows_by_sources_until(
                db,
                _BT_SOURCES,
                "2026-10-02T23:59:59",
                switch="FD_BT5_STORE_PORT",
                use_date_func=False,
            )
        ]
    assert legacy == ported
    assert legacy, "种子数据必须产出非空结果"
    # timestamp <= 2026-10-02T23:59:59：排除 10-03 与 10-05 行
    assert all(r[4] <= "2026-10-02T23:59:59" for r in legacy)
    assert not any(r[1] == "FEDFUNDS" and r[2] == '{"value": 3.7}' for r in legacy)


def test_latest_row_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    for flag, sw in ((False, "FD_IC_STORE_PORT"), (True, "FD_IC_STORE_PORT")):
        with _switch(sw, flag):
            row = port_mod.fetch_latest_row(
                db,
                "stablecoin_transparency",
                "stablecoin_hist_usdt",
                columns="timeseries",
                switch=sw,
            )
        if not flag:
            legacy = row
        else:
            ported = row
    assert legacy is not None and ported is not None
    l_ts = legacy["timeseries"] if isinstance(legacy, dict) else legacy["timeseries"]
    p_ts = ported["timeseries"]
    assert l_ts == p_ts
    # id=6（最新）的 timeseries，而非 id=5
    assert "165.0" in p_ts and "160.0" not in p_ts


def test_latest_rows_for_pairs_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    pairs = [
        ("fred", "FEDFUNDS"),
        ("yfinance", "^VIX"),
        ("stablecoin_transparency", "tether_current"),
        ("absent", "nope"),
    ]
    with _switch("FD_BT5_STORE_PORT", False):
        legacy = {
            k: dict(v)
            for k, v in port_mod.fetch_latest_rows_for_pairs(
                db, pairs, switch="FD_BT5_STORE_PORT"
            ).items()
        }
    with _switch("FD_BT5_STORE_PORT", True):
        ported = port_mod.fetch_latest_rows_for_pairs(db, pairs, switch="FD_BT5_STORE_PORT")
    assert set(legacy) == set(ported)
    assert ("absent", "nope") not in ported
    for k in legacy:
        assert dict(legacy[k]) == dict(ported[k])
    assert json.loads(ported[("fred", "FEDFUNDS")]["metrics"])["value"] == 3.7


def test_top10_until_port_equals_legacy_and_window(tmp_path):
    db = _seed(tmp_path)
    for use_date_func, sw in ((True, "FD_IC_STORE_PORT"), (False, "FD_BT5_STORE_PORT")):
        max_ts = "2026-10-03" if use_date_func else "2026-10-02T23:59:59"
        with _switch(sw, False):
            legacy_top, legacy_rows = port_mod.fetch_top10_inflow_until(
                db, max_ts, switch=sw, use_date_func=use_date_func
            )
            legacy_rows = [tuple(r) for r in legacy_rows]
        with _switch(sw, True):
            ported_top, ported_rows = port_mod.fetch_top10_inflow_until(
                db, max_ts, switch=sw, use_date_func=use_date_func
            )
            ported_rows = [tuple(r.values()) for r in ported_rows]
        assert legacy_top is not None and ported_top is not None
        assert int(legacy_top["id"]) == int(ported_top["id"])
        assert legacy_rows == ported_rows
        # top 必须是 10-02 批次末行（id=12），不是 10-05 的新行（id=16）
        assert int(ported_top["id"]) == 12
        # 区间 [12-50, 12] → 同批次 4 行（id 9-12），含重复 symbol 行（去重在调用方）
        assert len(ported_rows) == 4


# ── ic_analysis 函数级等价 ───────────────────────────────────────────────
def test_ic_read_macro_for_date_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch("FD_IC_STORE_PORT", False):
        legacy = ic_mod._read_macro_for_date(Path(db), "2026-10-03")
    with _switch("FD_IC_STORE_PORT", True):
        ported = ic_mod._read_macro_for_date(Path(db), "2026-10-03")
    assert legacy == ported
    assert legacy["fedfunds_rate"] == 3.7
    assert legacy["vix_close"] == 22.5
    assert legacy["fear_greed_norm"] == 0.55
    assert legacy["stablecoin_mcap_bln"] == 168.4
    # top10：10-02 批次 4 行 symbol 去重（BTC 重复）→ 100+50+25=175
    assert legacy["blockbeats_inflow_top10_total_usd"] == 175.0
    assert legacy["pn_overview_market_global_market_cap_usd"] == 2700000000000.0


def test_ic_get_daily_snapshots_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch("FD_IC_STORE_PORT", False):
        legacy = ic_mod._get_daily_snapshots(Path(db))
    with _switch("FD_IC_STORE_PORT", True):
        ported = ic_mod._get_daily_snapshots(Path(db))
    assert [d for d, _ in legacy] == [d for d, _ in ported]
    assert legacy == ported
    assert legacy, "快照必须非空"


# ── 默认 legacy：开关未设时 port 故障不影响结果 ──────────────────────────
def test_legacy_is_default_when_switch_unset(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    _broken = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))  # noqa: E731
    # ic_mod 通过 memory_l4 目录 sys.path 引用的是独立模块对象，两侧都要打桩
    monkeypatch.setattr(port_mod, "RecordsStorePort", _broken)
    monkeypatch.setattr(port_mod_flat, "RecordsStorePort", _broken)
    with _switch("FD_IC_STORE_PORT", False):
        assert port_mod.fetch_distinct_dates(db, _MACRO_SOURCES)
        assert ic_mod._read_macro_for_date(Path(db), "2026-10-03")["fedfunds_rate"] == 3.7
    # 开关打开且 port 故障 → FAIL-OPEN 空结果（不抛异常）
    with _switch("FD_IC_STORE_PORT", True):
        assert port_mod.fetch_distinct_dates(db, _MACRO_SOURCES) == []
        assert ic_mod._read_macro_for_date(Path(db), "2026-10-03") == {}


# ── FAIL-OPEN：DB 缺失 ───────────────────────────────────────────────────
def test_missing_db_fail_open(tmp_path):
    missing = str(tmp_path / "nope.db")
    with _switch("FD_IC_STORE_PORT", True):
        assert port_mod.fetch_distinct_dates(missing, _MACRO_SOURCES) == []
        assert port_mod.fetch_rows_by_sources_until(missing, _MACRO_SOURCES, "2026-10-03") == []
        assert port_mod.fetch_latest_row(missing, "a", "b") is None
        assert (
            port_mod.fetch_latest_rows_for_pairs(missing, [("a", "b")], switch="FD_IC_STORE_PORT")
            == {}
        )
        assert port_mod.fetch_top10_inflow_until(missing, "2026-10-03") == (None, [])
        # 函数级：两种开关都返回空
    for flag in (False, True):
        with _switch("FD_IC_STORE_PORT", flag):
            assert ic_mod._read_macro_for_date(Path(missing), "2026-10-03") == {}
            assert ic_mod._get_daily_snapshots(Path(missing)) == []


def test_legacy_branch_raises_on_missing_db(tmp_path):
    """legacy 分支异常上抛（保持原语义：无 try 的调用方行为零变化）。"""
    missing = str(tmp_path / "nope.db")
    with _switch("FD_IC_STORE_PORT", False):
        try:
            port_mod.fetch_rows_by_sources_until(missing, _MACRO_SOURCES, "2026-10-03")
        except Exception:
            return
    raise AssertionError("legacy 分支不得吞掉连接异常（FAIL-OPEN 仅属 port 分支）")


# ── 只读红线 ─────────────────────────────────────────────────────────────
def test_write_not_open(tmp_path):
    try:
        port_mod.RecordsStorePort(str(tmp_path / "x.db")).write("records", data={"id": 1})
    except NotImplementedError:
        return
    raise AssertionError("C5 第五批只读收编不得开放 write")


def test_no_module_level_sys_path_insert_in_port():
    for line in PORT_PATH.read_text(encoding="utf-8").splitlines():
        assert not line.lstrip().startswith("sys.path.insert"), f"port 文件: {line}"
