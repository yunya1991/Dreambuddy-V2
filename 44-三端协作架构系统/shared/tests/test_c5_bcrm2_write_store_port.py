"""C5 第七批：bcrm2 写路径 Store port 收编契约测试。

覆盖：
  - learner 四处写 / macro 缓存读写 / backfill 三处读写已收编进 _store_port；
  - 开关关（默认 legacy）与开关开（BCRM_*_STORE_PORT=1）双 tmp DB 全表比对、返回值一致；
  - port 分支故障回退 legacy 直写（fail-safe：数据仍落盘，非 FAIL-OPEN 返回空）；
  - 读助手（regime/stats/eval/cache）两种模式输出相等；
  - 红线：storage.py/kg_store.py 直连数不变、learner 聚合读保留、
    macro/backfill 直连清零且删除 import sqlite3、_store_port 直连数固定；
  - backfill 模块经 sys.path 以顶层 bcrm2._store_port 导入（双模块对象事实登记）。
"""

import importlib
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统"))

from scripts.memory_l4.bcrm2 import _store_port as port_mod  # noqa: E402
from scripts.memory_l4.bcrm2 import (  # noqa: E402
    incremental_learner,
    macro_data_fetcher,
)

BASE = REPO_ROOT / "11-易经推理系统/scripts/memory_l4/bcrm2"
MACRO_PATH = BASE / "macro_data_fetcher.py"
LEARNER_PATH = BASE / "incremental_learner.py"
PORT_PATH = BASE / "_store_port.py"
BACKFILL_PATH = BASE / "scripts/backfill_fma_shadow.py"
STORAGE_PATH = BASE / "storage.py"
KG_STORE_PATH = BASE.parent / "kg_store.py"


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


def _conn(path) -> sqlite3.Connection:
    """测试种子/校验唯一连接入口（本文件仅此一处直连登记）。"""
    return sqlite3.connect(str(path))


def _dump(db_path) -> dict:
    """全表导出（rowid 序），created_at 归一化为 None（DB 默认时间戳跨跑不可比）。"""
    conn = _conn(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        out = {}
        for t in tables:
            rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
            cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
            norm = []
            for row in rows:
                d = dict(zip(cols, row, strict=True))
                if "created_at" in d:
                    d["created_at"] = None
                norm.append(d)
            out[t] = norm
        return out
    finally:
        conn.close()


def _seed_shadow_db(path, old_rows=2) -> str:
    conn = _conn(path)
    conn.execute(
        "CREATE TABLE shadow_param_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, timestamp TEXT NOT NULL,"
        "actual_direction TEXT, actual_confidence REAL, actual_threshold REAL,"
        "actual_pnl_pct REAL, actual_win INTEGER, fma_on_allowed INTEGER, actual_entry_time TEXT)"
    )
    for i in range(old_rows):
        conn.execute(
            "INSERT INTO shadow_param_log (symbol, timestamp, actual_direction) VALUES (?,?,?)",
            ("OLD", f"2026-10-0{i + 1}T00:00:00", "UP"),
        )
    conn.commit()
    conn.close()
    return str(path)


def _seed_regime_db(path) -> str:
    conn = _conn(path)
    conn.execute(
        "CREATE TABLE regime_state_daily ("
        "timestamp TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT 'BTCUSDT',"
        "price_close REAL NOT NULL, level_smooth REAL NOT NULL, trend_smooth REAL NOT NULL,"
        "consensus REAL NOT NULL, hmm_state INTEGER NOT NULL,"
        "regime_probs TEXT NOT NULL, top3 TEXT NOT NULL,"
        "PRIMARY KEY (timestamp, symbol))"
    )
    rows = [
        ("2026-10-03", "BTCUSDT", 63000.0, 0.3, 1.8, 0.7, 2, "{}", "[]"),
        ("2026-10-01", "BTCUSDT", 61000.0, 0.1, -0.5, 0.4, 0, "{}", "[]"),
        ("2026-10-02", "BTCUSDT", 62000.0, 0.2, 0.6, 0.5, 1, "{}", "[]"),
        ("2026-10-02", "ETHUSDT", 3100.0, 0.2, 0.9, 0.6, 2, "{}", "[]"),
    ]
    conn.executemany("INSERT INTO regime_state_daily VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return str(path)


_SHADOW_RECORDS = [
    {
        "symbol": "BTC",
        "timestamp": "2026-10-30T00:00:00",
        "actual_direction": "UP",
        "actual_confidence": 0.85,
        "actual_threshold": 0.7955,
        "actual_pnl_pct": 0.06,
        "actual_win": 1,
        "fma_on_allowed": 1,
        "actual_entry_time": "2026-10-30T00:00:00",
    },
    {
        "symbol": "ETH",
        "timestamp": "2026-10-30T01:00:00",
        "actual_direction": "DOWN",
        "actual_confidence": 0.82,
        "actual_threshold": 0.7955,
        "actual_pnl_pct": -0.08,
        "actual_win": 0,
        "fma_on_allowed": 0,
        "actual_entry_time": "2026-10-30T01:00:00",
    },
    {
        "symbol": "SOL",
        "timestamp": "2026-10-30T02:00:00",
        "actual_direction": "HOLD",  # stats/eval 的 WHERE 必须过滤掉
        "actual_confidence": 0.5,
        "actual_threshold": 0.7955,
        "actual_pnl_pct": None,
        "actual_win": None,
        "fma_on_allowed": 0,
        "actual_entry_time": "2026-10-30T02:00:00",
    },
]

_TRADE = {
    "symbol": "BTC",
    "direction": 1,
    "entry_time": "2026-10-10T00:00:00",
    "entry_price": 60000.0,
    "pnl_pct": 2.5,
}


# ── 直连收编红线（写路径） ─────────────────────────────────────────────────
def test_write_connects_collected():
    # 动态拼接避免本文件自身成为直连命中（C10 ratchet 计数口径）
    direct = "sqlite3." + "connect("
    port_src = PORT_PATH.read_text(encoding="utf-8")
    learner_src = LEARNER_PATH.read_text(encoding="utf-8")
    macro_src = MACRO_PATH.read_text(encoding="utf-8")
    backfill_src = BACKFILL_PATH.read_text(encoding="utf-8")
    # 收编容器：15 处固定（2 工厂 + 10 助手 legacy 内联 + 3 第四批既有）
    assert port_src.count(direct) == 15
    # learner 仅剩 1 处 = get_recent_performance 聚合读（AVG/SUM port 不可表达，SPEC 暂缓）
    assert learner_src.count(direct) == 1
    assert "AVG(pnl_pct)" in learner_src
    # macro / backfill 直连清零，且模块级 import sqlite3 已删除
    assert macro_src.count(direct) == 0
    assert "import sqlite3" not in macro_src
    assert backfill_src.count(direct) == 0
    assert "import sqlite3" not in backfill_src
    # 连接持有型组件保持原状（按 SPEC 单独立项，本批不动）
    assert STORAGE_PATH.read_text(encoding="utf-8").count(direct) == 1
    assert KG_STORE_PATH.read_text(encoding="utf-8").count(direct) == 1


# ── learner 写：双 tmp DB 全表比对 + 返回值一致 ────────────────────────────
def _exercise_learner(db_path: str):
    db = incremental_learner.TradeDatabase(db_path)
    r1 = db.add_trade(_TRADE)
    r2 = db.add_trades_batch(
        [
            dict(_TRADE, entry_time="2026-10-11T00:00:00", direction=-1, pnl_pct=-1.2),
            dict(_TRADE, entry_time="2026-10-12T00:00:00", symbol="ETH", pnl_pct=0.8),
        ]
    )
    r3 = db.save_model_version("v001", "BTC", {"sharpe_ratio": 1.5, "win_rate": 0.6}, notes="t")
    # 重复插入同键交易：INSERT OR IGNORE 幂等语义两种模式一致
    r4 = db.add_trade(_TRADE)
    return r1, r2, r3, r4, db


def test_learner_writes_port_equal_legacy(tmp_path):
    db_a = str(tmp_path / "a" / "trades.db")
    db_b = str(tmp_path / "b" / "trades.db")
    with _switch("BCRM_LEARNER_STORE_PORT", False):
        ra = _exercise_learner(db_a)
    with _switch("BCRM_LEARNER_STORE_PORT", True):
        rb = _exercise_learner(db_b)
    assert ra[:4] == rb[:4], "返回值（lastrowid/批次长度/bool/IGNORE 语义）必须一致"
    assert ra[0] > 0 and ra[1] == 2 and ra[2] is True
    assert _dump(db_a) == _dump(db_b)
    # 两种模式下读回也一致（第四批读助手回归）
    assert ra[4].get_model_versions("BTC")[0]["version_id"] == "v001"
    assert len(rb[4].get_trades_for_retraining("BTC", min_trades=2)) == 2


def test_learner_write_fallback_when_port_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        port_mod, "_connect_rw", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    db_path = str(tmp_path / "f" / "trades.db")
    with _switch("BCRM_LEARNER_STORE_PORT", True):
        # port 分支故障 → 回退 legacy 直写：数据仍落盘（fail-safe）
        r1, r2, r3, _r4, db = _exercise_learner(db_path)
    assert r1 > 0 and r2 == 2 and r3 is True
    dumped = _dump(db_path)
    assert len(dumped["trades"]) == 3
    assert dumped["model_versions"][0]["version_id"] == "v001"
    assert db.get_recent_performance("BTC")["n_trades"] == 2  # 聚合读不受影响


def test_learner_default_legacy_when_switch_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        port_mod, "_connect_rw", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with _switch("BCRM_LEARNER_STORE_PORT", False):
        r1, r2, r3, _r4, _db = _exercise_learner(str(tmp_path / "d" / "trades.db"))
    assert r1 > 0 and r2 == 2 and r3 is True


# ── macro 缓存：写读双模式等价 + 失败语义保留 ──────────────────────────────
def _macro_df() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        pd.to_datetime([1700000000, 1700086400], unit="s", utc=True), name="timestamp"
    )
    return pd.DataFrame({"funding_rate": [0.0001, -0.0002]}, index=idx)


def test_macro_cache_roundtrip_equal(tmp_path):
    df = _macro_df()
    with _switch("BCRM_MACRO_STORE_PORT", False):
        fa = macro_data_fetcher.MacroDataFetcher(cache_dir=tmp_path / "a")
        fa._save_cache("BTC", "funding_rate_BTC", df)
        la = fa._load_cache("BTC", "funding_rate_BTC")
    with _switch("BCRM_MACRO_STORE_PORT", True):
        fb = macro_data_fetcher.MacroDataFetcher(cache_dir=tmp_path / "b")
        fb._save_cache("BTC", "funding_rate_BTC", df)
        lb = fb._load_cache("BTC", "funding_rate_BTC")
    assert la is not None and lb is not None
    assert la.equals(lb)
    assert list(la.columns) == ["funding_rate"]
    assert _dump(tmp_path / "a" / "macro_BTC.db") == _dump(tmp_path / "b" / "macro_BTC.db")


def test_macro_cache_fallback_when_port_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        port_mod, "_connect_rw", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        port_mod, "_connect_ro", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with _switch("BCRM_MACRO_STORE_PORT", True):
        f = macro_data_fetcher.MacroDataFetcher(cache_dir=tmp_path / "c")
        f._save_cache("BTC", "funding_rate_BTC", _macro_df())  # 回退 legacy 写入仍落盘
        loaded = f._load_cache("BTC", "funding_rate_BTC")  # 回退 legacy 读仍命中
    assert loaded is not None and len(loaded) == 2


def test_macro_cache_missing_source_returns_none(tmp_path):
    for flag in (False, True):
        with _switch("BCRM_MACRO_STORE_PORT", flag):
            f = macro_data_fetcher.MacroDataFetcher(cache_dir=tmp_path / "m")
            assert f._load_cache("BTC", "funding_rate_BTC") is None


# ── backfill 助手：清写 / 统计 / 评估读 / regime 读 双模式等价 ─────────────
def test_purge_insert_stats_eval_equal(tmp_path):
    db_a = _seed_shadow_db(tmp_path / "sa.db")
    db_b = _seed_shadow_db(tmp_path / "sb.db")
    with _switch("BCRM_BACKFILL_STORE_PORT", False):
        na = port_mod.purge_and_insert_shadow_rows(db_a, _SHADOW_RECORDS)
        sa = port_mod.fetch_shadow_stats(db_a)
        ea = port_mod.fetch_shadow_eval_records(db_a)
    with _switch("BCRM_BACKFILL_STORE_PORT", True):
        nb = port_mod.purge_and_insert_shadow_rows(db_b, _SHADOW_RECORDS)
        sb = port_mod.fetch_shadow_stats(db_b)
        eb = port_mod.fetch_shadow_eval_records(db_b)
    assert na == nb == 2  # 旧记录数
    assert _dump(db_a) == _dump(db_b)
    assert sa == sb
    assert sa["stats"]["total"] == 2  # HOLD 已过滤
    assert sa["stats"]["fma_on"] == 1 and sa["stats"]["wins"] == 1
    assert [r["symbol"] for r in sa["per_symbol"]] == ["BTC", "ETH"]
    assert ea == eb and len(ea) == 2
    assert ea[0]["fma_on_allowed"] == 1  # 原始 int，bool 转换在调用方


def test_purge_insert_fallback_when_port_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        port_mod, "_connect_rw", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    db = _seed_shadow_db(tmp_path / "sf.db", old_rows=3)
    with _switch("BCRM_BACKFILL_STORE_PORT", True):
        old = port_mod.purge_and_insert_shadow_rows(db, _SHADOW_RECORDS)
    assert old == 3  # 回退 legacy 仍完成清写
    assert _dump(db)["shadow_param_log"].__len__() == 3  # 旧 3 行已清除，新 3 行落盘


def test_fetch_regime_rows_equal(tmp_path):
    db = _seed_regime_db(tmp_path / "r.db")
    with _switch("BCRM_BACKFILL_STORE_PORT", False):
        legacy = port_mod.fetch_regime_rows(db)
    with _switch("BCRM_BACKFILL_STORE_PORT", True):
        ported = port_mod.fetch_regime_rows(db)
    assert legacy == ported and len(legacy) == 3  # ETHUSDT 被 symbol 过滤
    assert [r["timestamp"] for r in ported] == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_fetch_regime_rows_fallback_when_port_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        port_mod,
        "SqliteReadOnlyPort",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    db = _seed_regime_db(tmp_path / "rf.db")
    with _switch("BCRM_BACKFILL_STORE_PORT", True):
        rows = port_mod.fetch_regime_rows(db)
    assert len(rows) == 3  # 回退 legacy 直连仍读到


# ── backfill 脚本集成：模块可导入，符号来自顶层 bcrm2._store_port ──────────
def test_backfill_module_uses_top_level_port():
    mod = importlib.import_module("scripts.memory_l4.bcrm2.scripts.backfill_fma_shadow")
    # 双模块对象事实登记：脚本 sys.path 直跑需要顶层 bcrm2 包，
    # 与本测试的 scripts.memory_l4.bcrm2._store_port 是两个模块对象。
    assert mod.fetch_regime_rows.__module__ == "bcrm2._store_port"
    assert mod.purge_and_insert_shadow_rows.__module__ == "bcrm2._store_port"
    assert callable(mod.fetch_btc_regime_data)


def test_backfill_fetch_btc_regime_data_equal(tmp_path):
    mod = importlib.import_module("scripts.memory_l4.bcrm2.scripts.backfill_fma_shadow")
    db = _seed_regime_db(tmp_path / "bf.db")
    with _switch("BCRM_BACKFILL_STORE_PORT", False):
        legacy = mod.fetch_btc_regime_data(Path(db), days=2)
    with _switch("BCRM_BACKFILL_STORE_PORT", True):
        ported = mod.fetch_btc_regime_data(Path(db), days=2)
    assert legacy == ported and len(legacy) == 2  # days 截断取最后 N 条
    assert legacy[-1]["timestamp"] == "2026-10-03"


# ── 无模块级 sys.path.insert（backfill 为脚本，豁免） ─────────────────────
def test_no_module_level_sys_path_insert():
    for p in (MACRO_PATH, LEARNER_PATH, PORT_PATH):
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not line.lstrip().startswith("sys.path.insert"), f"{p.name}: {line}"
