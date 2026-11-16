# -*- coding: utf-8 -*-
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from l1agg.capabilities.signal_exports import signal_query  # noqa: E402
from l1agg.capabilities.stats import run_capability  # noqa: E402

FORBIDDEN = {"order", "orders", "position", "positions", "size", "quantity", "side", "action"}


def _row(eval_id, *, target="BTC", horizon=5, rank_ic=0.35, excess=0.25, gate=1):
    return {
        "eval_id": eval_id,
        "method": "B14",
        "transform": "raw",
        "target": target,
        "horizon": horizon,
        "n": 300,
        "n_eff": 300,
        "rank_ic": rank_ic,
        "excess_hit": excess,
        "base_rate": 0.5,
        "hit_rate_lb": 0.6,
        "effect_bps": 18.0,
        "cost_bps": 10.0,
        "p_adj": 0.01,
        "status": "stable",
        "eval_at": "2026-11-15T00:00:00Z",
        "data_version": "v1",
        "gate_pass": gate,
    }


def _db(tmp_path, rows):
    path = tmp_path / "relationship_registry.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE relationship_eval (
              eval_id TEXT PRIMARY KEY, method TEXT, transform TEXT, target TEXT,
              horizon INTEGER, n INTEGER, n_eff INTEGER, rank_ic REAL,
              excess_hit REAL, base_rate REAL, hit_rate_lb REAL,
              effect_bps REAL, cost_bps REAL, p_adj REAL, status TEXT,
              eval_at TEXT, data_version TEXT, gate_pass INTEGER
            )
            """)
        keys = sorted(rows[0])
        conn.executemany(
            f"INSERT INTO relationship_eval ({','.join(keys)}) "
            f"VALUES ({','.join('?' for _ in keys)})",
            [[row[key] for key in keys] for row in rows],
        )
    return path


def _all_keys(value, acc=None):
    acc = acc if acc is not None else set()
    if isinstance(value, dict):
        for key, item in value.items():
            acc.add(str(key))
            _all_keys(item, acc)
    elif isinstance(value, list):
        for item in value:
            _all_keys(item, acc)
    return acc


def test_signal_query_returns_gated_signals_without_order_fields(tmp_path):
    path = _db(
        tmp_path,
        [_row("e1"), _row("e2", target="SP500")],
    )
    out = signal_query(
        db_path=str(path),
        as_of="2026-11-16",
        context={
            "BTC": {"ma_state": "up", "vol_pct": 0.3, "crowd_pct": 0.2},
            "SP500": {"ma_state": "down", "vol_pct": 0.3, "crowd_pct": 0.2},
        },
    )
    assert out["capability"] == "D-K03"
    data = out["data"]
    assert data["signal_count"] == 1
    assert data["blocked_count"] == 1
    assert data["signals"][0]["target"] == "BTC"
    assert data["signals"][0]["gating"]["decision"] == "allowed"
    assert data["blocked"][0]["gating"]["reasons"] == ["ma_against"]
    assert data["ablation"]["delta"] == 1
    assert not (_all_keys(out) & FORBIDDEN)
    assert "不含下单指令" in out["answer"]


def test_signal_query_gate_false_keeps_all_signals(tmp_path):
    path = _db(tmp_path, [_row("e1"), _row("e2", target="SP500")])
    out = signal_query(db_path=str(path), gate=False, as_of="2026-11-16", context={})
    data = out["data"]
    assert data["signal_count"] == 2
    assert data["blocked_count"] == 0
    assert data["ablation"]["delta"] == 0
    assert all("gating" not in signal for signal in data["signals"])


def test_signal_query_missing_context_blocks_all(tmp_path):
    path = _db(tmp_path, [_row("e1")])
    out = signal_query(db_path=str(path), as_of="2026-11-16")
    assert out["data"]["signal_count"] == 0
    assert out["data"]["blocked"][0]["gating"]["reasons"] == ["missing_context"]
    assert out["data"]["ablation"]["by_reason"]["missing_context"] == 1


def test_signal_query_missing_registry_degrades(tmp_path):
    out = signal_query(db_path=str(tmp_path / "absent.db"), as_of="2026-11-16")
    assert (out.get("quality") or {}).get("status") != "good"
    assert "signals" not in (out.get("data") or {})


def test_run_capability_routes_signal_query(tmp_path):
    path = _db(tmp_path, [_row("e1")])
    out = run_capability(
        "D-K03",
        db_path=str(path),
        as_of="2026-11-16",
        context={"BTC": {"ma_state": "up", "vol_pct": 0.2, "crowd_pct": 0.2}},
    )
    assert out["capability"] == "D-K03" and out["intent"] == "signal_query"
    assert out["data"]["signal_count"] == 1
