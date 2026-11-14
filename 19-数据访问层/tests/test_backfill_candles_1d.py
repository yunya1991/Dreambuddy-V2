# -*- coding: utf-8 -*-
"""日线 OHLC 回填脚本测试：聚合口径 + 无效日丢弃 + 幂等写入。"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_candles_1d.py"
_spec = importlib.util.spec_from_file_location("backfill_candles_1d", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

DAY = 86400
D1 = 1_790_553_600  # 2026-09-28T00:00:00Z（UTC 整日对齐）
CSV_HEADER = "ts_ms,open,high,low,close,volume\n"


def _write_csv(path: Path, rows):
    lines = [CSV_HEADER]
    for ts_ms, o, h, lo, c, v in rows:
        lines.append(f"{ts_ms},{o},{h},{lo},{c},{v}\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_aggregate_daily_ohlc():
    rows = [
        (D1 * 1000, 100.0, 105.0, 99.0, 102.0, 10.0),
        (D1 * 1000 + 3_600_000, 102.0, 110.0, 101.0, 108.0, 20.0),
        (D1 * 1000 + 7_200_000, 108.0, 109.0, 104.0, 106.0, 5.0),
        ((D1 + DAY) * 1000, 106.0, 107.0, 100.0, 101.0, 7.0),
    ]
    days = mod.aggregate_daily(rows)
    assert sorted(days) == [D1, D1 + DAY]
    bar = days[D1]
    assert bar["open"] == 100.0 and bar["close"] == 106.0
    assert bar["high"] == 110.0 and bar["low"] == 99.0
    assert bar["volume"] == 35.0


def test_invalid_day_dropped():
    rows = [
        (D1 * 1000, 100.0, 101.0, 99.0, 100.5, 1.0),
        ((D1 + DAY) * 1000, 100.0, 101.0, 99.0, 120.0, 1.0),  # close > high → 非法
    ]
    rows_out, dropped = mod.build_metric_rows(mod.aggregate_daily(rows), "BTC/USDT", "binance")
    assert dropped == 1
    assert len(rows_out) == 5  # 只写第 1 天 5 条
    assert {r[2] for r in rows_out} == {f"{m}_1d" for m in mod.METRICS}


def test_backfill_idempotent(tmp_path):
    csv_path = tmp_path / "bars.csv"
    _write_csv(
        csv_path,
        [
            (D1 * 1000, 100.0, 105.0, 99.0, 104.0, 10.0),
            ((D1 + DAY) * 1000, 104.0, 108.0, 103.0, 107.0, 12.0),
        ],
    )
    db = tmp_path / "core.db"
    sqlite3.connect(db).close()

    first = mod.backfill(csv_path, db, "BTC/USDT", "binance", dry_run=False)
    second = mod.backfill(csv_path, db, "BTC/USDT", "binance", dry_run=False)
    assert first["daily_bars"] == 2 and first["metric_rows"] == 10
    assert second["db_daily_close_rows"] == 2  # 幂等：重复执行不新增

    conn = sqlite3.connect(db)
    try:
        rows = dict(
            conn.execute(
                "SELECT metric_name, metric_value FROM mm_metrics "
                "WHERE sub_category = 'BTC/USDT' AND timestamp = ?",
                (D1,),
            ).fetchall()
        )
    finally:
        conn.close()
    assert rows["high_1d"] == 105.0 and rows["low_1d"] == 99.0
    assert rows["open_1d"] == 100.0 and rows["close_1d"] == 104.0
