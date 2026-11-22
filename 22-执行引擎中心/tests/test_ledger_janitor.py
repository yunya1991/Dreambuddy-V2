"""P1-6 janitor 状态机测试（SPEC-LEDGER-DOMAIN-ATTRIBUTION §8.2）。

janitor 代码在 15-监控告警系统/scripts，账本 API 复用 22；测试注入持仓快照，
覆盖 J1–J6/J8/J10（shadow 与 enforce 两种模式）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (REPO / "22-执行引擎中心", REPO / "15-监控告警系统" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ledger_janitor import run_fetch_failed, run_once  # noqa: E402
from position_ledger import PositionLedger  # noqa: E402

ETH = "ETH-USDT-SWAP"
T0 = datetime(2026, 11, 23, 8, 0, 0, tzinfo=timezone.utc)


def _ledger(tmp_path) -> PositionLedger:
    return PositionLedger(tmp_path / "janitor.db")


def test_j1_repeated_missing_marks_stale_break_in_shadow(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")

    run_once(led, [], now=T0)
    run_once(led, [], now=T0 + timedelta(seconds=700))
    out = run_once(led, [], now=T0 + timedelta(seconds=1400))

    assert out["breaks_created"] >= 1
    breaks = led.list_breaks(kind="stale_position")
    assert len(breaks) == 1 and breaks[0]["state"] == "OPEN"
    # shadow：只标记，不迁移状态、不写冷却
    assert led.get_position(ETH, "long")["status"] == "open"
    assert led.get_cooldown(ETH) is None


def test_j2_stale_position_not_counted_as_effective(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")
    led.set_setting("stale_after_seconds", "5")
    led.set_setting("min_confirmations", "1")

    run_once(led, [], now=T0)
    run_once(led, [], enforce=True, now=T0 + timedelta(seconds=10))

    assert led.get_position(ETH, "long")["status"] == "stale"
    assert [r["inst_id"] for r in led.list_effective_positions()] == []


def test_j3_enforce_close_after_writes_ghost_fill_without_cooldown(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="22-reconciled")
    led.set_setting("stale_after_seconds", "5")
    led.set_setting("close_after_seconds", "10")
    led.set_setting("min_confirmations", "1")

    run_once(led, [], now=T0)
    out = run_once(led, [], enforce=True, now=T0 + timedelta(seconds=11))

    assert out["closed"] == 1
    assert led.get_position(ETH, "long") is None
    fill = led.recent_fills(1)[0]
    assert fill["source"] == "22-janitor"
    # J10：账务修正不写冷却
    assert led.get_cooldown(ETH) is None


def test_j4_recovered_position_reopens_and_resolves_break(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")
    led.set_setting("stale_after_seconds", "5")
    led.set_setting("min_confirmations", "1")
    run_once(led, [], now=T0)
    run_once(led, [], enforce=True, now=T0 + timedelta(seconds=10))
    assert led.get_position(ETH, "long")["status"] == "stale"

    run_once(led, [{"inst_id": ETH, "pos_side": "long", "qty": 2.0, "avg_entry": 100.0}], now=T0)

    row = led.get_position(ETH, "long")
    assert row["status"] == "open" and int(row["miss_count"]) == 0
    assert led.list_breaks(kind="stale_position", state="OPEN") == []


def test_j5_exchange_only_position_is_backfilled_with_break(tmp_path):
    led = _ledger(tmp_path)

    out = run_once(
        led,
        [{"inst_id": ETH, "pos_side": "long", "qty": 1.0, "avg_entry": 1800.0}],
        now=T0,
    )

    assert out["breaks_created"] == 1
    pos = led.get_position(ETH, "long")
    assert pos["source"] == "22-reconciled" and pos["qty"] == 1.0
    assert led.list_breaks(kind="missing_in_ledger")[0]["state"] == "OPEN"


def test_j6_qty_and_price_drift_deduplicated(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2.0, 100.0, source="23-evolution")
    snap = [{"inst_id": ETH, "pos_side": "long", "qty": 3.0, "avg_entry": 101.0}]

    run_once(led, snap, now=T0)
    run_once(led, snap, now=T0 + timedelta(seconds=60))

    assert len(led.list_breaks(kind="qty_drift")) == 1
    assert len(led.list_breaks(kind="price_drift")) == 1


def test_j8_fetch_failure_does_not_increment_miss(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")

    out = run_fetch_failed(led, "timeout", now=T0)

    assert out["feed_state"] == "degraded"
    assert led.get_feed_state() == "degraded"
    assert int(led.get_position(ETH, "long")["miss_count"]) == 0
