"""P1：多域账本归因测试（SPEC-LEDGER-DOMAIN-ATTRIBUTION §8）。

覆盖 U1–U9（单测）、M1–M3（迁移）、I1/I6/I7（集成），
以及不变量 Σdomain_positions.qty == positions.qty。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from executors.drop_copy_adapter import DropCopyAdapter  # noqa: E402
from position_ledger import PositionLedger, domain_of  # noqa: E402
from trade_execution_gateway import (  # noqa: E402
    ExecutionResult,
    FinalDecisionSignal,
    TradeExecutionGateway,
)

ETH = "ETH-USDT-SWAP"
BTC = "BTC-USDT-SWAP"


def _ledger(tmp_path, name: str = "ledger.db") -> PositionLedger:
    return PositionLedger(tmp_path / name)


def _assert_balanced(led: PositionLedger) -> None:
    assert abs(led.position_qty_sum() - led.domain_qty_sum()) <= 1e-9


def test_domain_mapping():
    assert domain_of("23-evolution") == "23"
    assert domain_of("evolution") == "23"
    assert domain_of("11-yijing") == "11"
    assert domain_of("50-nn") == "50"
    assert domain_of("6-trading") == "6"
    assert domain_of("22-reconciled") == "22"
    assert domain_of("22-sltp_reconcile") == "22"
    assert domain_of("") == "legacy"


def test_gateway_open_falls_back_to_ticker_when_fill_missing(tmp_path):
    """成交索引 lag 且下单响应无均价时，开仓必须按最新价落账（不得整笔漏账）。"""

    class _NoFillsOkx:
        def get_ticker(self, inst_id):
            return {"ok": True, "last": 76.5}

        def get_positions(self, inst_id=None):
            return {"ok": True, "positions": []}

    led = _ledger(tmp_path)
    gw = TradeExecutionGateway(okx_client=_NoFillsOkx(), ledger=led)
    sig = FinalDecisionSignal(
        signal_id="s1",
        source="23-evolution",
        symbol=ETH,
        direction="long",
        decision_id="d1",
        action="open",
        sz=1.3,
        pos_side="long",
    )
    res = ExecutionResult(
        passed=True,
        executed=True,
        reason="PASS",
        reason_code="PASS",
        order_result={"ok": True, "ord_id": "1"},
    )

    gw._record_ledger(sig, res)

    fill = led.recent_fills(1)[0]
    assert fill["action"] == "open" and fill["domain"] == "23"
    assert abs(fill["px"] - 76.5) < 1e-9
    _assert_balanced(led)


def test_u1_open_allocates_domain_and_lot(tmp_path):
    led = _ledger(tmp_path)

    out = led.record_fill(ETH, "long", "open", 2.0, 1800.0, source="23-evolution")

    assert out["ok"] and out["domain"] == "23"
    dom = led.list_domain_positions(domain="23")
    assert len(dom) == 1 and dom[0]["qty"] == 2.0
    lots = led.list_lots(inst_id=ETH, domain="23")
    assert len(lots) == 1 and lots[0]["remaining_qty"] == 2.0
    fill = led.recent_fills(1)[0]
    assert fill["domain"] == "23" and fill["action"] == "open"
    _assert_balanced(led)


def test_u2_same_domain_add_weighted_avg_and_multiple_lots(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 100, 100.0, source="23-evolution")
    out = led.record_fill(ETH, "long", "open", 100, 120.0, source="23-evolution")

    assert out["qty"] == 200.0 and out["avg_entry"] == 110.0
    assert len(led.list_lots(inst_id=ETH, domain="23")) == 2
    _assert_balanced(led)


def test_u3_fifo_partial_close_consumes_oldest_lot(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 10, 100.0, source="23-evolution")
    led.record_fill(ETH, "long", "open", 10, 120.0, source="23-evolution")

    out = led.record_fill(ETH, "long", "reduce", 15, 130.0, source="23-evolution", fee=1.0)

    # 10@100 + 5@120 → (30*10)+(10*5) - 1 = 349
    assert abs(out["realized_pnl"] - 349.0) < 1e-9
    lots = led.list_lots(inst_id=ETH, domain="23")
    assert len(lots) == 1 and lots[0]["remaining_qty"] == 5.0 and lots[0]["px"] == 120.0
    _assert_balanced(led)


def test_u4_full_close_closes_domain_and_sets_cooldown(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")

    out = led.record_fill(ETH, "long", "reduce", 2, 110.0, source="23-evolution")

    assert out["cooldown_set"] is True
    assert led.get_position(ETH, "long") is None
    dom = led.list_domain_positions(domain="23", include_closed=True)
    assert dom[0]["status"] == "closed" and dom[0]["qty"] == 0.0
    assert led.get_cooldown(ETH) is not None
    _assert_balanced(led)


def test_u5_cross_domain_close_is_rejected(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 2, 100.0, source="23-evolution")

    out = led.close_position("11", ETH, "long", 1.0, px=110.0)

    assert out["ok"] is False and out["reason"] == "domain_mismatch"
    assert led.get_position(ETH, "long")["qty"] == 2.0
    _assert_balanced(led)


def test_u6_over_close_truncates_and_writes_break(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 10, 100.0, source="23-evolution")

    out = led.close_position("23", ETH, "long", 15.0, px=110.0, source="23-evolution")

    assert out["ok"] is True
    assert out["executed_qty"] == 10.0 and out["shortfall"] == 5.0
    breaks = led.list_breaks(kind="over_close")
    assert len(breaks) == 1 and breaks[0]["state"] == "OPEN"
    assert led.get_position(ETH, "long") is None


def test_u7_insufficient_domain_does_not_borrow_other_domain(tmp_path):
    led = _ledger(tmp_path)
    led.record_fill(ETH, "long", "open", 3, 100.0, source="23-evolution")

    # 请求域 11 无份额：拒绝，不跨域借仓
    out = led.close_position("11", ETH, "long", 3.0, px=110.0)
    assert out["ok"] is False
    assert led.get_position(ETH, "long")["qty"] == 3.0
    assert led.list_breaks(kind="over_close") == []
    _assert_balanced(led)


def test_u8_reserve_release_and_expire(tmp_path):
    led = _ledger(tmp_path)

    r = led.reserve("23", ETH, "long", 500.0, decision_id="d1")
    assert r["ok"] is True and led.held_notional("23") == 500.0

    led.release(r["reservation_id"])
    assert led.held_notional("23") == 0.0

    r2 = led.reserve("23", BTC, "short", 300.0, ttl=-1)  # 立即可过期
    assert r2["ok"] is True
    assert led.expire_reservations() == 1
    assert led.held_notional("23") == 0.0


def test_u9_concurrent_reserve_respects_limit(tmp_path):
    led = _ledger(tmp_path)
    results = []

    def _worker():
        results.append(led.reserve("23", ETH, "long", 60.0, limit_notional=100.0))

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for r in results if r.get("ok")) == 1
    assert led.held_notional("23") == 60.0


def test_m1_ddl_is_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    led1 = PositionLedger(db)
    led1.record_fill(ETH, "long", "open", 1, 100.0, source="23-evolution")
    led2 = PositionLedger(db)  # 二次初始化不应报错或重复建表

    assert led2.get_position(ETH, "long")["qty"] == 1.0
    assert len(led2.list_domain_positions()) == 1
    _assert_balanced(led2)


def test_m2_backfill_is_idempotent(tmp_path):
    db = tmp_path / "backfill.db"
    led = PositionLedger(db)
    led.record_open(ETH, "long", 2.0, 100.0, source="22-reconciled")
    first_lots = len(led.list_lots(inst_id=ETH, only_open=True))

    PositionLedger(db)  # 再次迁移

    assert len(led.list_lots(inst_id=ETH, only_open=True)) == first_lots
    assert led.get_position(ETH, "long")["qty"] == 2.0
    _assert_balanced(led)


def test_i7_historical_closed_rows_are_closed(tmp_path):
    db = tmp_path / "hist.db"
    led = PositionLedger(db)
    led.record_open(ETH, "long", 1.0, 100.0, source="22-reconciled")
    led.apply_partial_close(ETH, "long", 1.0, 101.0, source="22-reconciled")

    assert led.get_position(ETH, "long") is None
    dom = led.list_domain_positions(domain="22", include_closed=True)
    assert dom and dom[0]["status"] == "closed"
    _assert_balanced(led)


class _OkxOpenFill:
    def get_recent_fills(self, inst_id=None, limit=10):
        return {
            "ok": True,
            "fills": [
                {
                    "trade_id": "trade-open-1",
                    "side": "buy",
                    "pos_side": "long",
                    "fill_px": 1800.0,
                    "fill_sz": 2.0,
                    "fee": 0.2,
                    "ts": 0,
                }
            ],
        }


def test_i1_gateway_single_write_entry_keeps_l1_l2_balanced(tmp_path):
    led = _ledger(tmp_path, "gw.db")
    gw = TradeExecutionGateway(
        okx_client=_OkxOpenFill(), ledger=led, audit_path=tmp_path / "audit.jsonl"
    )
    sig = FinalDecisionSignal.from_dict(
        {
            "symbol": ETH,
            "pos_side": "long",
            "direction": "long",
            "action": "open",
            "sz": 2.0,
            "source": "23-evolution",
            "decision_id": "dec-p1-open",
        }
    )

    gw._record_ledger(sig, ExecutionResult(passed=True, executed=True, reason="", reason_code=""))

    fill = led.recent_fills(1)[0]
    assert fill["domain"] == "23" and fill["exchange_fill_id"] == "trade-open-1"
    assert led.get_position(ETH, "long")["qty"] == 2.0
    _assert_balanced(led)


def test_i6_drop_copy_replay_is_idempotent(tmp_path):
    led = _ledger(tmp_path, "dropcopy.db")
    adapter = DropCopyAdapter(led)
    rec = {
        "inst_id": BTC,
        "pos_side": "long",
        "side": "buy",
        "exchange_fill_id": "fill-xyz",
        "qty": 1.5,
        "px": 60000.0,
    }

    first = adapter.import_fills([rec], domain="50", source="50-dropcopy")
    second = adapter.import_fills([rec], domain="50", source="50-dropcopy")

    assert first["imported"] == 1 and first["duplicate"] == 0
    assert second["imported"] == 0 and second["duplicate"] == 1
    assert led.get_position(BTC, "long")["qty"] == 1.5
    _assert_balanced(led)
