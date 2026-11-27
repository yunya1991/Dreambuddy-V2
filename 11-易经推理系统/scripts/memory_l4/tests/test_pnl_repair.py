"""P0.5 零 pnl 记账修复测试。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.pnl_repair import repair_close_pnl  # noqa: E402


def test_long_zero_pnl_repaired_from_prices():
    pnl, pct, repaired = repair_close_pnl(
        entry_price=4069.4, exit_price=3892.6, direction="long", pnl=0.0, pnl_pct=0.0
    )
    assert repaired
    assert pct < 0
    assert abs(pct - (3892.6 - 4069.4) / 4069.4) < 1e-12
    assert pnl == 0.0  # 无仓位金额时只修比例


def test_short_zero_pnl_repaired():
    _, pct, repaired = repair_close_pnl(
        entry_price=100.0, exit_price=90.0, direction="short", pnl=0.0, pnl_pct=0.0
    )
    assert repaired and abs(pct - 0.10) < 1e-12


def test_absolute_pnl_derived_from_position_usdt():
    pnl, pct, repaired = repair_close_pnl(
        entry_price=100.0,
        exit_price=110.0,
        direction="long",
        pnl=0.0,
        pnl_pct=0.0,
        position_usdt=200.0,
    )
    assert repaired and abs(pct - 0.10) < 1e-12 and abs(pnl - 20.0) < 1e-9


def test_true_flat_trade_not_modified():
    pnl, pct, repaired = repair_close_pnl(
        entry_price=100.0, exit_price=100.0, direction="long", pnl=0.0, pnl_pct=0.0
    )
    assert not repaired and pnl == 0.0 and pct == 0.0


def test_existing_nonzero_pnl_not_overwritten():
    pnl, pct, repaired = repair_close_pnl(
        entry_price=100.0, exit_price=110.0, direction="long", pnl=5.0, pnl_pct=0.025
    )
    assert not repaired and pnl == 5.0 and pct == 0.025


def test_missing_prices_fail_open():
    assert repair_close_pnl(
        entry_price=0.0, exit_price=110.0, direction="long", pnl=0.0, pnl_pct=0.0
    ) == (0.0, 0.0, False)
    assert repair_close_pnl(
        entry_price=100.0, exit_price=0.0, direction="long", pnl=0.0, pnl_pct=0.0
    ) == (0.0, 0.0, False)


def test_minute_level_bdsm_close_repaired():
    # bdsm 同 bar 分钟级强平：价格小幅变动也应被记录，而非 0
    _, pct, repaired = repair_close_pnl(
        entry_price=61800.0, exit_price=61735.6, direction="long", pnl=0.0, pnl_pct=0.0
    )
    assert repaired and pct < 0
