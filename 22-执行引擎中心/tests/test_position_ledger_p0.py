"""P0：账本并发底座、effective 读口径与 feed 保护测试（2026-11-23）。

覆盖 SPEC-LEDGER-DOMAIN-ATTRIBUTION §7 P0-1/P0-2/P0-5：
- SQLite WAL + busy_timeout
- verified_at / status 与 v_effective_positions
- 心跳缺失/过期时回退 raw 持仓，避免放开限额
- 历史已平行迁移为 closed
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from position_ledger import PositionLedger  # noqa: E402

OLD_TS = "2020-01-01T00:00:00Z"


def _ledger(tmp_path) -> PositionLedger:
    return PositionLedger(tmp_path / "ledger.db")


def _pos_ids(rows) -> set:
    return {str(r["inst_id"]) for r in rows}


def test_sqlite_wal_and_busy_timeout(tmp_path):
    led = _ledger(tmp_path)
    with led._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(mode).lower() == "wal"
    assert int(timeout) == 5000


def test_effective_view_excludes_unverified_stale_and_expired(tmp_path):
    led = _ledger(tmp_path)
    for inst in ("FRESH", "UNVERIFIED", "STALE", "EXPIRED"):
        led.record_open(inst, "long", 1, 100.0)
    led.mark_verified([{"inst_id": "FRESH", "pos_side": "long"}])
    led.heartbeat()

    with led._connect() as conn:
        conn.execute(
            "UPDATE positions SET verified_at=?, status='stale' WHERE inst_id='STALE'",
            (OLD_TS,),
        )
        conn.execute(
            "UPDATE positions SET verified_at=? WHERE inst_id='EXPIRED'",
            (OLD_TS,),
        )

    assert _pos_ids(led.list_effective_positions()) == {"FRESH"}


def test_effective_view_falls_back_to_raw_without_heartbeat(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("A", "long", 1, 100.0)
    led.record_open("B", "long", 1, 100.0)
    # 从未对账：没有心跳，effective 视图不可信 → 回退 raw，保持保守占用
    assert _pos_ids(led.list_effective_positions()) == {"A", "B"}


def test_effective_view_falls_back_when_heartbeat_stale(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("A", "long", 1, 100.0)
    led.heartbeat(ts=OLD_TS)
    assert _pos_ids(led.list_effective_positions(max_heartbeat_age_seconds=300)) == {"A"}


def test_mark_verified_reopens_stale_and_resets_miss(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("ETH-USDT-SWAP", "long", 2, 100.0)
    with led._connect() as conn:
        conn.execute(
            "UPDATE positions SET status='stale', miss_count=5, stale_since=?"
            " WHERE inst_id='ETH-USDT-SWAP'",
            (OLD_TS,),
        )

    assert led.mark_verified([{"inst_id": "ETH-USDT-SWAP", "pos_side": "long"}]) == 1

    row = led.get_position("ETH-USDT-SWAP", "long")
    assert row["status"] == "open"
    assert int(row["miss_count"]) == 0
    assert row["stale_since"] is None
    assert row["verified_at"]


def test_migration_marks_historical_closed_rows(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE positions (
            inst_id TEXT NOT NULL,
            pos_side TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 0,
            avg_entry REAL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            entry_known INTEGER NOT NULL DEFAULT 1,
            opened_at TEXT,
            updated_at TEXT,
            closed_at TEXT,
            PRIMARY KEY (inst_id, pos_side)
        );
        INSERT INTO positions
            (inst_id, pos_side, qty, avg_entry, realized_pnl, entry_known,
             opened_at, updated_at, closed_at)
        VALUES
            ('OLD', 'long', 0, 100, 5, 0, '2026-01-01', '2026-01-02', '2026-01-02'),
            ('OPEN', 'long', 2, 100, 0, 1, '2026-01-03', '2026-01-03', NULL);
        """)
    conn.commit()
    conn.close()

    led = PositionLedger(db)

    with led._connect() as c:
        old = c.execute("SELECT status FROM positions WHERE inst_id='OLD'").fetchone()[0]
    assert old == "closed"
    assert led.get_position("OPEN", "long")["status"] == "open"
    assert led.get_position("OPEN", "long")["verified_at"]
