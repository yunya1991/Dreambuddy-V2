"""C5 第四批：bcrm2 读路径 Store port 收编契约测试。

覆盖：
  - macro_data_fetcher / incremental_learner 的只读直连已消除（仅留写路径 connect）；
  - 开关关闭（默认 legacy）与开关打开（BCRM_*_STORE_PORT=1）输出逐字段相等；
  - as_tuple 下标语义（r[0..3] 与 id DESC 合并顺序）；
  - FAIL-OPEN（DB 缺失 / port 故障均回落空结果）；
  - 只读红线：port.write 未开放、写路径按 SPEC 暂缓（剩余 connect 数固定）；
  - 无模块级 sys.path.insert。
"""

import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统"))

from scripts.memory_l4 import five_domain_sqlite_reader as fdr  # noqa: E402
from scripts.memory_l4.bcrm2 import _store_port as port_mod  # noqa: E402
from scripts.memory_l4.bcrm2 import (  # noqa: E402
    incremental_learner,
    macro_data_fetcher,
)

BASE = REPO_ROOT / "11-易经推理系统/scripts/memory_l4/bcrm2"
MACRO_PATH = BASE / "macro_data_fetcher.py"
LEARNER_PATH = BASE / "incremental_learner.py"
PORT_PATH = BASE / "_store_port.py"


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


# ── 种子数据 ──────────────────────────────────────────────────────────────
def _seed_records(tmp_path: Path) -> str:
    db = tmp_path / "records.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, "
        "category TEXT, sub_category TEXT, metrics TEXT, raw TEXT, "
        "timeseries TEXT, timestamp INTEGER)"
    )
    rows = [
        # 同 (source, sub_category) 两条：最新（id 更大）必须胜出
        ("panewslab", "macro", "us_vix", '{"pn_us_vix": 15.3}', 100),
        ("panewslab", "macro", "us_vix", '{"pn_us_vix": 14.8}', 200),
        ("theblockbeats_dataview", "emotion", "signal", '{"overall": 61}', 300),
        ("theblockbeats_dataview", "onchain", "flow", '{"btc_netflow": -120.5}', 320),
        ("fear_greed", "emotion", "fng", '{"value": 55}', 400),
        ("etf_flow", "flow", "btc", '{"net_flow_usd": 123.4}', 410),
        # 白名单外 source：两种模式都必须忽略
        ("__noise__", "other", "x", '{"v": 1}', 500),
    ]
    for src, cat, sub, metrics, ts in rows:
        conn.execute(
            "INSERT INTO records (source, category, sub_category, metrics, timestamp) "
            "VALUES (?,?,?,?,?)",
            (src, cat, sub, metrics, ts),
        )
    conn.commit()
    conn.close()
    return str(db)


def _seed_trade_db(tmp_path: Path) -> incremental_learner.TradeDatabase:
    db = incremental_learner.TradeDatabase(str(tmp_path / "bcrm_trades.db"))
    conn = sqlite3.connect(db.db_path)
    for vid, sym, created, sharpe in (
        ("v1", "BTC", "2026-10-01T00:00:00", 1.2),
        ("v2", "BTC", "2026-10-05T00:00:00", 1.5),
        ("v3", "ETH", "2026-10-03T00:00:00", 0.9),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO model_versions "
            "(version_id, symbol, created_at, sharpe_ratio) VALUES (?,?,?,?)",
            (vid, sym, created, sharpe),
        )
    for sym, direction, entry, pnl in (
        ("BTC", 1, "2026-10-10T00:00:00", 2.1),
        ("BTC", -1, "2026-10-11T00:00:00", -1.4),
        ("ETH", 1, "2026-10-12T00:00:00", 0.5),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO trades "
            "(symbol, direction, entry_time, entry_price, pnl_pct) VALUES (?,?,?,?,?)",
            (sym, direction, entry, 100.0, pnl),
        )
    conn.commit()
    conn.close()
    return db


def _macro(monkeypatch, tmp_path: Path, db_path: str) -> macro_data_fetcher.MacroDataFetcher:
    monkeypatch.setattr(fdr, "DEFAULT_DB_PATH", db_path)
    return macro_data_fetcher.MacroDataFetcher(cache_dir=tmp_path)


# ── 只读直连已消除（写路径按 SPEC 暂缓） ──────────────────────────────────
def test_read_connects_collected():
    # 动态拼接避免本文件自身成为直连命中（C10 ratchet 计数口径）
    direct = "sqlite3." + "connect("
    macro_src = MACRO_PATH.read_text(encoding="utf-8")
    learner_src = LEARNER_PATH.read_text(encoding="utf-8")
    # macro 剩余 2 处均为写路径（_load_cache/_save_cache 用 pandas）
    assert macro_src.count(direct) == 2
    assert "mode=ro" not in macro_src
    # learner 剩余 5 处 = 4 写路径 + 1 聚合读（AVG/SUM 无法用 port 表达，按 SPEC 暂缓）
    assert learner_src.count(direct) == 5
    assert "mode=ro" not in learner_src


# ── 行为零变化：两种模式逐字段相等 ────────────────────────────────────────
def test_records_by_sources_tuple_equals_legacy(tmp_path):
    db = _seed_records(tmp_path)
    sources = ("panewslab", "theblockbeats_dataview")
    with _switch("BCRM_MACRO_STORE_PORT", False):
        legacy = [tuple(r) for r in port_mod.fetch_records_by_sources(db, sources)]
    with _switch("BCRM_MACRO_STORE_PORT", True):
        ported = port_mod.fetch_records_by_sources(db, sources)
    assert legacy == ported
    assert legacy, "种子数据必须产出非空结果，否则等价断言无意义"
    # 下标语义：r[0]=source, r[1]=sub_category, r[2]=metrics, r[3]=timestamp
    assert legacy[0][0] in sources and legacy[0][1] and legacy[0][3] == 320
    # id DESC 合并顺序
    assert [r[4] for r in ported] == sorted([r[4] for r in ported], reverse=True)


def test_panewslab_snapshot_port_equals_legacy(tmp_path, monkeypatch):
    db = _seed_records(tmp_path)
    with _switch("BCRM_MACRO_STORE_PORT", False):
        legacy = _macro(monkeypatch, tmp_path, db)._fetch_panewslab_blockbeats_snapshot_latest()
    with _switch("BCRM_MACRO_STORE_PORT", True):
        ported = _macro(monkeypatch, tmp_path, db)._fetch_panewslab_blockbeats_snapshot_latest()
    assert not legacy.empty, "种子数据必须产出非空结果"
    assert list(legacy.columns) == list(ported.columns)
    assert float(legacy["pn_us_vix"].iloc[0]) == 14.8  # 同 key 取 id 最大的最新值
    assert legacy.equals(ported)


def test_new_sources_snapshot_port_equals_legacy(tmp_path, monkeypatch):
    db = _seed_records(tmp_path)
    with _switch("BCRM_MACRO_STORE_PORT", False):
        legacy = _macro(monkeypatch, tmp_path, db)._fetch_new_sources_snapshot()
    with _switch("BCRM_MACRO_STORE_PORT", True):
        ported = _macro(monkeypatch, tmp_path, db)._fetch_new_sources_snapshot()
    assert not legacy.empty, "种子数据必须产出非空结果"
    assert legacy.equals(ported)


def test_trade_db_reads_port_equal_legacy(tmp_path):
    db = _seed_trade_db(tmp_path)
    with _switch("BCRM_LEARNER_STORE_PORT", False):
        legacy_versions = db.get_model_versions()
        legacy_btc = db.get_model_versions("BTC")
        legacy_trades = db.get_trades_for_retraining("BTC", min_trades=2)
    with _switch("BCRM_LEARNER_STORE_PORT", True):
        ported_versions = db.get_model_versions()
        ported_btc = db.get_model_versions("BTC")
        ported_trades = db.get_trades_for_retraining("BTC", min_trades=2)

    assert legacy_versions and legacy_trades
    assert legacy_versions == ported_versions
    assert legacy_btc == ported_btc
    assert legacy_trades == ported_trades
    assert [r["created_at"] for r in ported_btc] == sorted(
        [r["created_at"] for r in ported_btc], reverse=True
    )
    assert len(ported_trades) == 2 and ported_trades[0]["entry_time"] == "2026-10-11T00:00:00"


# ── 默认 legacy：开关未设时 port 故障不影响结果 ──────────────────────────
def test_legacy_is_default_when_switch_unset(tmp_path, monkeypatch):
    db = _seed_records(tmp_path)
    monkeypatch.setattr(
        port_mod,
        "SqliteReadOnlyPort",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with _switch("BCRM_MACRO_STORE_PORT", False):
        assert (
            not _macro(monkeypatch, tmp_path, db)
            ._fetch_panewslab_blockbeats_snapshot_latest()
            .empty
        )
    # 开关打开且 port 故障 → FAIL-OPEN 空结果（不抛异常）
    with _switch("BCRM_MACRO_STORE_PORT", True):
        assert _macro(monkeypatch, tmp_path, db)._fetch_panewslab_blockbeats_snapshot_latest().empty


# ── FAIL-OPEN ────────────────────────────────────────────────────────────
def test_missing_db_returns_empty(tmp_path, monkeypatch):
    missing = str(tmp_path / "nope.db")
    for flag in (False, True):
        with _switch("BCRM_MACRO_STORE_PORT", flag):
            assert (
                _macro(monkeypatch, tmp_path, missing)
                ._fetch_panewslab_blockbeats_snapshot_latest()
                .empty
            )
            assert _macro(monkeypatch, tmp_path, missing)._fetch_new_sources_snapshot().empty
    with _switch("BCRM_MACRO_STORE_PORT", True):
        assert port_mod.fetch_records_by_sources(missing, ("panewslab",)) == []


def test_unknown_source_returns_empty(tmp_path):
    db = _seed_records(tmp_path)
    for flag in (False, True):
        with _switch("BCRM_MACRO_STORE_PORT", flag):
            assert port_mod.fetch_records_by_sources(db, ("__absent__",)) == []


def test_port_health_and_unknown_table(tmp_path):
    ok = port_mod.SqliteReadOnlyPort(_seed_records(tmp_path))
    assert ok.health()["ok"] is True
    assert ok.query("other", limit=1)["error_code"] == "unknown_table"
    assert ok.query("records", filters={"source": "__none__"})["count"] == 0
    assert port_mod.SqliteReadOnlyPort(str(tmp_path / "nope.db")).health()["ok"] is False


# ── 只读红线（写路径暂缓） ───────────────────────────────────────────────
def test_write_not_open(tmp_path):
    try:
        port_mod.SqliteReadOnlyPort(str(tmp_path / "x.db")).write("records", data={"id": 1})
    except NotImplementedError:
        return
    raise AssertionError("C5 第四批只读收编不得开放 write")


def test_no_module_level_sys_path_insert():
    for p in (MACRO_PATH, LEARNER_PATH, PORT_PATH):
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not line.lstrip().startswith("sys.path.insert"), f"{p.name}: {line}"
