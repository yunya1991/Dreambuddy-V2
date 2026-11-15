# -*- coding: utf-8 -*-
"""`trading.db` 迁移幂等与 signal 只追加单测（SPEC-54 §4.6 / L1D-02 验收）。"""

import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import store as S  # noqa: E402


def _signal(**overrides):
    record = {
        "as_of": "2026-11-14",
        "symbol": "BTC",
        "rule_version": "dr-1.0.0",
        "params_hash": "a" * 64,
        "direction": 1,
        "strength": 0.94,
        "slope_signs": {"20": 1, "60": 1},
        "adx_band": "gt25",
        "ema_order": "bull",
        "p_adj": 0.01,
        "flags": ["degraded_windows"],
        "seasonality": None,
        "inputs_snapshot": {"adx": {"adx14": 30.0}},
    }
    record.update(overrides)
    return record


def test_migrate_idempotent_and_schema(tmp_path):
    db = str(tmp_path / "trading.db")
    first = S.migrate(db)
    assert first["schema_version"] == 2
    assert first["tables"] == list(S.TABLES)
    assert sorted(first["created"]) == sorted(S.TABLES)

    second = S.migrate(db)
    assert second["created"] == []
    assert second["tables"] == list(S.TABLES)

    assert list(S.table_columns(db, "signal")) == list(S.SIGNAL_COLUMNS)
    for table in S.TABLES:
        assert S.table_columns(db, table), f"{table} 未建表"


def test_signal_is_append_only(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    signal_id = S.append_signal(_signal(), db)
    assert signal_id > 0

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE signal SET direction = -1 WHERE id = ?", (signal_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM signal WHERE id = ?", (signal_id,))
    finally:
        conn.close()


def test_duplicate_signal_rejected(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    S.append_signal(_signal(), db)
    with pytest.raises(sqlite3.IntegrityError):
        S.append_signal(_signal(), db)


def test_append_signal_validates_contract(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    with pytest.raises(S.TradingStoreError):
        S.append_signal(_signal(symbol=None), db)
    with pytest.raises(S.TradingStoreError):
        S.append_signal(_signal(direction=2), db)
    with pytest.raises(S.TradingStoreError):
        S.append_signal(_signal(strength=1.5), db)


def test_signal_roundtrip_keeps_json_fields(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    S.append_signal(_signal(), db)
    rows = S.list_signals(db, symbol="BTC")
    assert len(rows) == 1
    assert rows[0]["flags"] == ["degraded_windows"]
    assert rows[0]["slope_signs"] == {"20": 1, "60": 1}
    assert rows[0]["inputs_snapshot"] == {"adx": {"adx14": 30.0}}
    assert rows[0]["created_at"]


def test_signal_roundtrip_keeps_weights_fields(tmp_path):
    """SPEC §4.13：weights_version/hash/effective_date/axis_weights/weight_sources 落库。"""
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    S.append_signal(
        _signal(
            weights_version="weights-1.1.0",
            weights_hash="b" * 64,
            weights_effective_date="2026-11-16",
            axis_weights={"trend": 0.4, "adx": 0.25, "inertia": 0.2, "coherence": 0.15, "gap": 0},
            weight_sources={"prior": {"trend": 0.4}, "uncertainty": 0.0},
        ),
        db,
    )
    row = S.list_signals(db, symbol="BTC")[0]
    assert row["weights_version"] == "weights-1.1.0"
    assert row["weights_hash"] == "b" * 64
    assert row["weights_effective_date"] == "2026-11-16"
    assert row["axis_weights"]["gap"] == 0
    assert row["weight_sources"]["prior"]["trend"] == 0.4


def test_migrate_upgrades_v1_database_and_backfills_null(tmp_path):
    """历史 v1 库必须能幂等补列，且旧记录新列为 NULL（不伪造回填值）。"""
    db = str(tmp_path / "legacy.db")
    S.migrate(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA user_version = 1")
        for name, _kind in S._SIGNAL_V2_COLUMNS:
            conn.execute(f'ALTER TABLE signal DROP COLUMN "{name}"')
        conn.commit()
    finally:
        conn.close()
    info = S.migrate(db)
    assert info["schema_version"] == 2
    assert set(S.table_columns(db, "signal")) == set(S.SIGNAL_COLUMNS)
    S.append_signal(_signal(), db)
    row = S.list_signals(db, symbol="BTC")[0]
    assert row["weights_hash"] is None
    assert row["axis_weights"] is None


def test_order_fk_and_fill_append_only(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                'INSERT INTO "order" (order_id, signal_id, symbol, side, qty, status, created_at) '
                "VALUES ('o-1', 999, 'BTC', 'buy', 1, 'pending', '2026-11-14T00:00:00+00:00')"
            )
        conn.rollback()  # 释放失败的隐式事务写锁，再走 store 追加
        signal_id = S.append_signal(_signal(), db)
        conn.execute(
            'INSERT INTO "order" (order_id, signal_id, symbol, side, qty, status, created_at) '
            "VALUES ('o-1', ?, 'BTC', 'buy', 1, 'pending', '2026-11-14T00:00:00+00:00')",
            (signal_id,),
        )
        conn.execute("UPDATE \"order\" SET status = 'filled' WHERE order_id = 'o-1'")
        conn.execute(
            "INSERT INTO fill (fill_id, order_id, price, qty, fee, ts) "
            "VALUES ('f-1', 'o-1', 60000, 1, 0.5, '2026-11-14T00:00:00+00:00')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE fill SET price = 1 WHERE fill_id = 'f-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM fill WHERE fill_id = 'f-1'")
    finally:
        conn.close()


def test_position_and_comparison_upsert(tmp_path):
    db = str(tmp_path / "trading.db")
    S.migrate(db)
    conn = S.connect(db)
    try:
        conn.execute(
            "INSERT INTO position VALUES ('BTC', 0.1, 60000, 12.5, 6000, '2026-11-14T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO position VALUES "
            "('BTC', 0.2, 61000, 20.0, 12200, '2026-11-14T01:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO comparison VALUES ('2026-11-14', 'BTC', 1, 0.94, 'agree', 0.012, "
            "'2026-11-20T00:00:00+00:00')"
        )
        conn.commit()
        qty = conn.execute("SELECT qty FROM position WHERE symbol = 'BTC'").fetchone()[0]
        ret = conn.execute("SELECT realized_ret FROM comparison").fetchone()[0]
    finally:
        conn.close()
    assert qty == 0.2
    assert ret == 0.012
