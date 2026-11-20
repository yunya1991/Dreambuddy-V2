"""D2 资金流 · Web3 链上增强测试。

用户口径（2026-11-20 确认）：
  - web3_buy_sell_vol_ratio      → 场内微观，直接增强「主动买卖比」
  - web3_smart_money_net_inflow_usd / web3_new_wallet_pct_med → 链上资金流动，
    合成后直接并入 D2 资金流（不新增维度、不新增因子槽位）

约定：raw>0 → 空头力量；raw<0 → 多头力量。
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from dreambuddy_evolution.core.dimension_force_evaluator import (
    DimensionForceEvaluator,
)

NOW = int(time.time())


def _make_db(tmp_path):
    db_path = tmp_path / "d2_web3.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE mm_metrics ("
        "sub_category TEXT, metric_name TEXT, metric_value REAL, timestamp INTEGER)"
    )
    conn.commit()
    return db_path, conn


def _put(conn, sub, metric, value, ts=NOW):
    conn.execute("INSERT INTO mm_metrics VALUES (?,?,?,?)", (sub, metric, value, ts))
    conn.commit()


def _insert_web3(conn, *, bs=1.02, inflow=400_000.0, new_wallet=6.0, ts=NOW):
    _put(conn, "web3_market", "web3_buy_sell_vol_ratio", bs, ts)
    _put(conn, "web3_market", "web3_smart_money_net_inflow_usd", inflow, ts)
    _put(conn, "web3_market", "web3_new_wallet_pct_med", new_wallet, ts)


def _neutral_switch(monkeypatch, enabled: bool):
    """强制 enable_d2_web3_flow 开关（其余开关走默认值）。"""
    import dreambuddy_evolution.agi_config as cfg

    monkeypatch.setattr(
        cfg,
        "get_switch",
        lambda name, default=False: enabled if name == "enable_d2_web3_flow" else default,
    )


def test_web3_only_drives_flow_dimension(tmp_path):
    db_path, conn = _make_db(tmp_path)
    _insert_web3(conn, bs=1.02, inflow=400_000.0, new_wallet=6.0)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    # 买入占优 + 聪明钱净流入 + 新钱涌入 → 多头力量（raw<0）
    assert out["direction"] == "long"
    assert out["raw_z"] == pytest.approx(-0.7, abs=1e-6)
    assert out["components"]["web3_buy_sell_vol_ratio"]["part"] == pytest.approx(-0.4)
    # OKX 缺失时由链上买卖比顶替
    assert out["components"]["taker_source"] == "web3_buy_sell_vol_ratio"


def test_web3_blends_into_okx_taker(tmp_path):
    db_path, conn = _make_db(tmp_path)
    _put(conn, "okx_derivatives", "taker_buy_sell_ratio", 1.04)
    _insert_web3(conn, bs=1.02, inflow=400_000.0, new_wallet=6.0)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    assert out["components"]["taker_source"] == "okx+web3_blend"
    # okx part = -(1.04-1)/1.0 = -0.04；web3 part = -0.4 → 0.7/-0.3 混合后 -0.148
    assert out["components"]["taker_buy_sell_ratio"]["part"] == pytest.approx(-0.148, abs=1e-3)
    # raw = mean(-0.148, -1.0) = -0.574
    assert out["raw_z"] == pytest.approx(-0.574, abs=1e-3)


def test_outflow_flips_to_short(tmp_path):
    db_path, conn = _make_db(tmp_path)
    _insert_web3(conn, bs=0.98, inflow=-400_000.0, new_wallet=0.0)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    assert out["direction"] == "short"
    assert out["raw_z"] > 0


def test_without_web3_keeps_legacy_behaviour(tmp_path):
    db_path, conn = _make_db(tmp_path)
    for i in range(30):
        _put(
            conn, "long_short_ratio", "long_short_ratio", 1.2 if i % 2 else 0.9, NOW - (30 - i) * 60
        )
    _put(conn, "long_short_ratio", "long_short_ratio", 1.3)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    assert "web3_buy_sell_vol_ratio" not in out["components"]
    assert "web3_smart_money_net_inflow_usd" not in out["components"]
    assert "taker_source" not in out["components"]
    assert out["direction"] == "short"


def test_switch_off_ignores_web3(tmp_path, monkeypatch):
    db_path, conn = _make_db(tmp_path)
    _put(conn, "long_short_ratio", "long_short_ratio", 1.3)
    _insert_web3(conn)
    _neutral_switch(monkeypatch, False)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    assert "web3_buy_sell_vol_ratio" not in out["components"]
    assert "web3_smart_money_net_inflow_usd" not in out["components"]


def test_stale_web3_ignored(tmp_path):
    db_path, conn = _make_db(tmp_path)
    stale = NOW - 8 * 24 * 3600
    _insert_web3(conn, ts=stale)

    out = DimensionForceEvaluator(str(db_path)).evaluate_d2("BTC")

    assert "web3_buy_sell_vol_ratio" not in out["components"]
    assert "web3_smart_money_net_inflow_usd" not in out["components"]
