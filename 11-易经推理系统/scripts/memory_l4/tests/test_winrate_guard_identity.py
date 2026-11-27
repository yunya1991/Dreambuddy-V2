"""P0-A 成交身份契约 + 双口径胜率守卫测试。

覆盖：旧库幂等迁移、身份写入、双 WR（含/不含零盈亏）、Wilson CI、
11 专属过滤、历史 UNKNOWN 隔离、空样本。
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4 import winrate_guard as wg  # noqa: E402
from scripts.memory_l4.bcrm2 import _store_port as sp  # noqa: E402
from scripts.memory_l4.trade_identity import build_identity, classify_source  # noqa: E402

LEGACY_TRADES_DDL = """
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    pnl_pct REAL,
    hold_bars INTEGER,
    exit_reason TEXT,
    confidence REAL,
    hexagram TEXT,
    upper_gua TEXT,
    lower_gua TEXT,
    position_factor REAL,
    model_version TEXT,
    fold_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, entry_time, direction)
)
"""


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _trade(pnl: float, source: str = "", mode: str = "live", hours_ago: int = 1) -> dict:
    exit_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    entry_dt = exit_dt - timedelta(hours=2)
    return {
        "symbol": "BTC",
        "direction": "long",
        "entry_time": _iso(entry_dt),
        "exit_time": _iso(exit_dt),
        "entry_price": 100.0,
        "exit_price": 100.0 * (1 + pnl),
        "pnl_pct": pnl,
        "hold_bars": 2,
        "exit_reason": "tp",
        "confidence": 0.8,
        "source_system": source,
        "mode": mode,
    }


def test_migrate_legacy_db_adds_identity_columns(tmp_path):
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute(LEGACY_TRADES_DDL)
    con.execute(
        "INSERT INTO trades (symbol,direction,entry_time,exit_time,entry_price,pnl_pct)"
        " VALUES ('BTC',1,'2026-11-01T00:00:00+00:00','2026-11-01T02:00:00+00:00',100,0.01)"
    )
    con.commit()
    con.close()

    sp.init_learner_tables(str(db))  # 幂等迁移

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    for c in ("source_system", "mode", "git_sha", "config_hash", "signal_id", "trade_id"):
        assert c in cols, f"缺少身份列 {c}"
    row = con.execute("SELECT source_system, pnl_pct FROM trades").fetchone()
    assert row[0] == "", "历史行必须保持 UNKNOWN，禁止猜测回填"
    assert row[1] == 0.01
    con.close()

    # 幂等：重复迁移不再新增、不报错
    assert sp.migrate_trade_identity(str(db)) == []


def test_insert_trade_persists_identity(tmp_path):
    db = tmp_path / "new.db"
    sp.init_learner_tables(str(db))
    sp.insert_trade(str(db), _trade(0.01, source="11-bcrm"))
    sp.insert_trade(str(db), _trade(-0.02, source="23-evolution", hours_ago=3))

    rows = sp.fetch_table_rows(
        str(db), "trades", "BCRM_LEARNER_STORE_PORT", columns="source_system,mode,pnl_pct"
    )
    assert len(rows) == 2
    sources = {r["source_system"] for r in rows}
    assert sources == {"11-bcrm", "23-evolution"}


def test_summarize_dual_winrate_zero_and_ci():
    trades = [{"pnl": p, "exit_time": "2026-11-20T00:00:00+00:00"} for p in (0.01, -0.02, 0.0)]
    m = wg.summarize(trades)
    assert m["n"] == 3 and m["wins"] == 1 and m["losses"] == 1 and m["zero_n"] == 1
    assert m["win_rate"] == round(1 / 3, 4)
    assert m["win_rate_nonzero"] == 0.5
    lo, hi = m["win_rate_ci95"]
    assert 0.0 <= lo <= hi <= 1.0
    assert m["profit_factor"] == 0.5
    assert m["mean_pnl_raw"] == round((0.01 - 0.02) / 3, 6)


def test_summarize_empty():
    m = wg.summarize([])
    assert m["n"] == 0 and m["win_rate"] == 0.0 and m["profit_factor"] is None
    assert m["win_rate_ci95"] == [0.0, 0.0]


def test_collect_and_yijing_attribution(tmp_path):
    db = tmp_path / "mix.db"
    sp.init_learner_tables(str(db))
    sp.insert_trade(str(db), _trade(0.01, source="11-bcrm"))
    sp.insert_trade(str(db), _trade(-0.01, source="11-bcrm", hours_ago=2))
    sp.insert_trade(str(db), _trade(0.03, source="23-evolution", hours_ago=3))
    sp.insert_trade(str(db), _trade(0.0, source="", hours_ago=4))  # 历史 UNKNOWN

    trades = wg.collect_db_trades(db, days=30)
    assert len(trades) == 4
    yj = [t for t in trades if t["source_system"] == "11-bcrm"]
    assert len(yj) == 2
    m = wg.summarize(yj)
    assert m["n"] == 2 and m["win_rate"] == 0.5

    unknown = [t for t in trades if not t["source_system"]]
    assert len(unknown) == 1
    shared = wg.summarize(trades)
    assert shared["n"] == 4 and shared["zero_n"] == 1

    # 老库无身份列时 collect 自动降级为空串
    legacy = tmp_path / "legacy2.db"
    con = sqlite3.connect(legacy)
    con.execute(LEGACY_TRADES_DDL)
    con.execute(
        "INSERT INTO trades (symbol,direction,entry_time,exit_time,entry_price,pnl_pct)"
        " VALUES (?,?,?,?,?,?)",
        (
            "BTC",
            1,
            _iso(datetime.now(timezone.utc) - timedelta(hours=3)),
            _iso(datetime.now(timezone.utc) - timedelta(hours=1)),
            100.0,
            0.005,
        ),
    )
    con.commit()
    con.close()
    rows = wg.collect_db_trades(legacy, days=30)
    assert len(rows) == 1 and rows[0]["source_system"] == ""


def test_classify_source_mapping():
    assert classify_source(domain_tag="23域") == "23-evolution"
    assert classify_source(source_tag="bdsm") == "11-bdsm"
    assert classify_source(source_tag="bcrm") == "11-bcrm"
    assert classify_source(strategy_source="martingale") == "external-martingale"
    assert classify_source() == "11-unknown"


def test_build_identity_fields():
    class Rec:
        trade_id = "T-1"
        source_tag = "bcrm"
        domain_tag = ""
        strategy_source = ""

    ident = build_identity(Rec(), shadow_mode=True)
    assert ident["source_system"] == "11-bcrm"
    assert ident["mode"] == "shadow"
    assert ident["trade_id"] == "T-1"
    assert ident["signal_id"] == "" and ident["config_hash"] == ""
