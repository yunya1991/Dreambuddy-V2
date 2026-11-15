# -*- coding: utf-8 -*-
"""L1D-06 vol targeting 仓位 + L1D-07 风控五项 / KILL_SWITCH 单测。"""

import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import risk, sizing, store  # noqa: E402


def test_vol_scale_targets_and_caps():
    assert sizing.vol_scale(0.02) == 1.0
    assert sizing.vol_scale(0.01) == 2.0
    assert sizing.vol_scale(0.004) == 3.0
    assert sizing.vol_scale(0.0) == 3.0  # min_vol 兜底 + max_scale 截断


def test_target_position_allowed_and_deterministic():
    kwargs = {"price": 100.0, "equity_usdt": 400.0, "volatility": 0.02, "kill_switch": 0}
    first = sizing.target_position(1, 1.0, **kwargs)
    assert first == sizing.target_position(1, 1.0, **kwargs)
    assert first["allowed"] is True
    assert first["reject_reason"] is None
    assert first["notional_usdt"] == 400.0
    assert first["qty"] == 4.0
    assert first["leverage"] == 1.0
    assert first["vol_scale"] == 1.0
    assert first["sizing_version"] == sizing.SIZING_VERSION


def test_target_position_scales_with_strength_and_vol():
    half = sizing.target_position(1, 0.5, price=100.0, equity_usdt=400.0, volatility=0.02)
    assert half["notional_usdt"] == 200.0 and half["qty"] == 2.0
    low_vol = sizing.target_position(1, 0.5, price=100.0, equity_usdt=400.0, volatility=0.01)
    assert low_vol["notional_usdt"] == 400.0 and low_vol["vol_scale"] == 2.0


def test_target_position_flat_signal_places_nothing():
    out = sizing.target_position(0, 0.0, price=100.0, equity_usdt=400.0, volatility=0.02)
    assert out["allowed"] is False
    assert out["reject_reason"] == sizing.NO_DIRECTION
    assert out["qty"] == 0.0 and out["notional_usdt"] == 0.0


def test_target_position_rejects_bad_input():
    for kwargs in (
        {"direction": 2, "strength": 1.0, "price": 100.0, "equity_usdt": 400.0, "volatility": 0.02},
        {"direction": 1, "strength": 1.5, "price": 100.0, "equity_usdt": 400.0, "volatility": 0.02},
        {"direction": 1, "strength": 1.0, "price": 0.0, "equity_usdt": 400.0, "volatility": 0.02},
        {"direction": 1, "strength": 1.0, "price": 100.0, "equity_usdt": 0.0, "volatility": 0.02},
    ):
        with pytest.raises(ValueError):
            sizing.target_position(**kwargs)


def test_kill_switch_blocks_new_but_allows_reduce(monkeypatch):
    blocked = sizing.target_position(
        1, 1.0, price=100.0, equity_usdt=400.0, volatility=0.02, kill_switch=True
    )
    assert blocked["allowed"] is False and blocked["reject_reason"] == risk.KILL_SWITCH
    reduce = sizing.target_position(
        1,
        1.0,
        price=100.0,
        equity_usdt=400.0,
        volatility=0.02,
        kill_switch=True,
        is_new=False,
    )
    assert reduce["allowed"] is True and reduce["reject_reason"] is None

    monkeypatch.setenv(risk.KILL_SWITCH_ENV, "1")
    assert risk.kill_switch_active() is True
    monkeypatch.setenv(risk.KILL_SWITCH_ENV, "0")
    assert risk.kill_switch_active() is False
    assert risk.kill_switch_active("yes") is True


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"daily_pnl_usdt": -100.0}, risk.MAX_DAILY_LOSS),
        ({"open_positions": 3}, risk.MAX_POSITIONS),
        ({"equity_usdt": 100.0, "volatility": 0.006}, risk.MAX_LEVERAGE),  # 300/100 = 3x
        ({"gross_exposure_usdt": 1400.0}, risk.MAX_GROSS_EXPOSURE),  # 400 + 1400
        ({"volatility": 0.01}, risk.MAX_NOTIONAL),  # 400 × 2 = 800 > 500
    ],
)
def test_five_limits_reject_with_reason(kwargs, expected):
    base = {"price": 100.0, "equity_usdt": 400.0, "volatility": 0.02, "kill_switch": 0}
    base.update(kwargs)
    out = sizing.target_position(1, 1.0, **base)
    assert out["allowed"] is False
    assert out["reject_reason"] == expected
    assert out["qty"] == 0.0


def test_record_rejected_order_writes_reason(tmp_path):
    db = str(tmp_path / "trading.db")
    store.migrate(db)
    signal_id = store.append_signal(
        {
            "as_of": "2026-11-14",
            "symbol": "BTC-USDT",
            "rule_version": "dr-1.0.0",
            "params_hash": "h",
            "direction": 1,
            "strength": 0.8,
            "inputs_snapshot": {"slope_table": []},
        },
        db,
    )
    risk.record_rejected_order(
        order_id="o-1",
        signal_id=signal_id,
        symbol="BTC-USDT",
        side="buy",
        qty=0.0,
        notional=800.0,
        reject_reason=risk.MAX_NOTIONAL,
        db_path=db,
    )
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            'SELECT status, reject_reason, signal_id FROM "order" WHERE order_id = ?',
            ("o-1",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("rejected", risk.MAX_NOTIONAL, signal_id)

    with pytest.raises(ValueError):
        risk.record_rejected_order(
            order_id="o-2",
            signal_id=signal_id,
            symbol="BTC-USDT",
            side="buy",
            qty=0.0,
            reject_reason="whatever",
            db_path=db,
        )
