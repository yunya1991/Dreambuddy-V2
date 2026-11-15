# -*- coding: utf-8 -*-
"""P1-2 批量回放 + 按类复盘表（SPEC-54-L1交易层 §6.1 / §6.2）。

覆盖：
  - `batch_metrics` 7 键口径与 `replay_key` 逐标的留存；
  - 失败隔离（单标的样本不足只 `skipped`，不中断整批、不伪造指标）；
  - 不合并组合信号（无 `signal/direction/position` 顶层字段）；
  - 同输入同 `replay_key`（确定性）；
  - 复盘表 6 列固定、按 40 层 `class` 聚合、未打分行不入分母；
  - `avg_hold_bars` 缺 `hold_bars` 时留空并计数；`comparison` 只读。
"""

import datetime as _dt
import json
import math
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import comparison, store  # noqa: E402
from l1agg.trading.batch import (  # noqa: E402
    BATCH_METRIC_KEYS,
    REVIEW_COLUMNS,
    batch_replay,
    review_table,
)

WARMUP = 30


def _series(n=140, base=100.0, step=0.6, amp=3.0, start=_dt.date(2025, 1, 1)):
    prices = [round(base + step * i + amp * math.sin(i / 3.0), 4) for i in range(n)]
    dates = [(start + _dt.timedelta(days=i)).isoformat() for i in range(n)]
    highs = [round(price * 1.01, 4) for price in prices]
    lows = [round(price * 0.99, 4) for price in prices]
    return {"prices": prices, "dates": dates, "highs": highs, "lows": lows}


# ------------------------------------------------------------ 批量回放


def test_batch_metrics_shape_and_keys():
    out = batch_replay(
        {"BTC": _series(), "ETH": _series(base=2000.0, step=6.0, amp=20.0)},
        warmup=WARMUP,
        weights_mode="off",
    )
    assert out["capability"] == "D-BATCH"
    assert out["n_symbols"] == 2
    assert out["n_ok"] == 2
    assert out["n_skipped"] == 0
    assert [row["symbol"] for row in out["batch_metrics"]] == ["BTC", "ETH"]
    for row in out["batch_metrics"]:
        assert set(BATCH_METRIC_KEYS).issubset(set(row))
        assert row["status"] == "ok"
        assert row["bars"] == 140 - WARMUP
        assert row["class"] == "crypto"
        assert len(row["replay_key"]) == 64


def test_failed_symbol_is_isolated():
    out = batch_replay(
        {"BTC": _series(), "ZZZ": {"prices": [100.0, 101.0, 102.0]}},
        warmup=WARMUP,
        weights_mode="off",
    )
    by_symbol = {row["symbol"]: row for row in out["batch_metrics"]}
    assert by_symbol["BTC"]["status"] == "ok"
    assert by_symbol["ZZZ"]["status"] == "skipped"
    assert "样本不足" in by_symbol["ZZZ"]["reason"]
    assert by_symbol["ZZZ"]["cum_ret"] is None
    assert by_symbol["ZZZ"]["class"] == "unbound"
    assert out["n_ok"] == 1
    assert out["n_skipped"] == 1
    assert "batch_skipped:1" in out["flags"]


def test_no_portfolio_signal_merge():
    out = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off")
    for key in ("signal", "signals", "direction", "position", "combined_direction"):
        assert key not in out
    assert "no_portfolio_signal" in out["flags"]


def test_replay_key_is_deterministic():
    first = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off")
    second = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["replay_keys"] == second["replay_keys"]


def test_risk_passthrough_is_verbatim():
    risk = {"cluster": {"crypto": 0.4}, "max_gross": 0.8}
    out = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off", risk=risk)
    assert out["risk"] == risk
    empty = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off")
    assert empty["risk"] == {}


# ------------------------------------------------------------ 复盘表


def _review_rows():
    return [
        {"symbol": "BTC", "realized_ret": 0.10, "scored_at": "2026-11-01", "hold_bars": 6},
        {"symbol": "ETH", "realized_ret": -0.05, "scored_at": "2026-11-02", "hold_bars": 4},
        {"symbol": "SOL", "realized_ret": 0.02, "scored_at": "2026-11-03"},
        {"symbol": "US100", "realized_ret": 0.03, "scored_at": "2026-11-04", "hold_bars": 10},
        {"symbol": "AAPL", "realized_ret": None},
        {"symbol": "NVDA", "realized_ret": 0.01, "scored_at": "2026-11-06", "hold_bars": 8},
        {"symbol": "ZZZ", "realized_ret": 0.50, "scored_at": "2026-11-05"},
    ]


def test_review_columns_are_fixed():
    out = review_table([])
    assert [col["key"] for col in out["columns"]] == [
        "class",
        "n",
        "win_rate",
        "avg_ret",
        "avg_hold_bars",
        "scored_at",
    ]
    assert [col["key"] for col in REVIEW_COLUMNS] == [col["key"] for col in out["columns"]]
    assert out["rows"] == []
    assert out["n_rows"] == 0


def test_review_aggregates_by_class():
    out = review_table(_review_rows())
    by_class = {row["class"]: row for row in out["rows"]}
    crypto = by_class["crypto"]
    assert crypto["n"] == 3
    assert crypto["win_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert crypto["avg_ret"] == pytest.approx((0.10 - 0.05 + 0.02) / 3, abs=1e-8)
    assert crypto["avg_hold_bars"] == pytest.approx(5.0)
    assert crypto["scored_at"] == "2026-11-03"
    assert by_class["us_index"]["n"] == 1
    assert by_class["us_stock"]["n"] == 1
    assert by_class["unbound"]["n"] == 1
    assert by_class["unbound"]["avg_hold_bars"] is None


def test_review_excludes_unscored_from_denominator():
    out = review_table(_review_rows())
    assert out["n_pending"] == 1
    assert out["n_scored"] == 6
    assert "unscored_rows:1" in out["flags"]
    assert sum(row["n"] for row in out["rows"]) == out["n_scored"]


def test_review_hold_bars_missing_is_counted():
    out = review_table(_review_rows())
    assert out["hold_bars_missing"] == 2
    assert "hold_bars_missing:2" in out["flags"]


def test_review_order_is_deterministic():
    out = review_table(_review_rows())
    counts = [row["n"] for row in out["rows"]]
    assert counts == sorted(counts, reverse=True)
    assert [row["class"] for row in out["rows"]] == [
        "crypto",
        "unbound",
        "us_index",
        "us_stock",
    ]


def test_review_reads_comparison_table(tmp_path):
    db_path = str(tmp_path / "trading.db")
    store.migrate(db_path)
    comparison.record_comparison(
        "2026-11-10", "BTC", l1_direction=1, l1_strength=0.7, db_path=db_path
    )
    comparison.record_comparison(
        "2026-11-10", "ETH", l1_direction=-1, l1_strength=0.5, db_path=db_path
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE comparison SET realized_ret = ?, scored_at = ? WHERE symbol = ?",
            (0.04, "2026-11-12", "BTC"),
        )
        conn.execute(
            "UPDATE comparison SET realized_ret = ?, scored_at = ? WHERE symbol = ?",
            (-0.02, "2026-11-12", "ETH"),
        )
        conn.commit()
    finally:
        conn.close()

    out = review_table(db_path=db_path)
    assert out["n_scored"] == 2
    assert out["n_pending"] == 0
    assert out["rows"][0]["class"] == "crypto"
    assert out["rows"][0]["win_rate"] == pytest.approx(0.5)
    assert out["rows"][0]["avg_ret"] == pytest.approx(0.01, abs=1e-8)


def test_cum_ret_never_enters_board_columns():
    """LT-AC5：`cum_ret` 只走回放/复盘链路，不得进入 D-E17 看板列。"""
    from l1agg.capabilities.visual import CLASS_BOARD_COLUMNS

    board_keys = {col["key"] for col in CLASS_BOARD_COLUMNS}
    assert "cum_ret" not in board_keys
    review_keys = {col["key"] for col in REVIEW_COLUMNS}
    assert "cum_ret" not in review_keys
    out = batch_replay({"BTC": _series()}, warmup=WARMUP, weights_mode="off")
    assert "cum_ret" in out["batch_metrics"][0]


def test_review_custom_resolver_overrides_class():
    out = review_table(_review_rows(), class_resolver=lambda symbol: "custom")
    assert [row["class"] for row in out["rows"]] == ["custom"]
    assert out["rows"][0]["n"] == 6
