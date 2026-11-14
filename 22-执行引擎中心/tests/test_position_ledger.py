"""P2 持仓账本测试（2026-11-14）

22 为持仓与已实现盈亏的唯一真相源：
- 部分减仓扣减数量并累计已实现盈亏
- 多空方向符号正确
- 未知持仓不臆造盈亏
- Gateway 成交后自动落账
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # 22-执行引擎中心
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from position_ledger import PositionLedger  # noqa: E402
from trade_execution_gateway import (  # noqa: E402
    ExecutionResult,
    FinalDecisionSignal,
    TradeExecutionGateway,
)


def _ledger(tmp_path) -> PositionLedger:
    return PositionLedger(tmp_path / "ledger.db")


def test_long_partial_close_realizes_pnl(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("ETH-USDT-SWAP", "long", 100, 100.0)

    out = led.apply_partial_close("ETH-USDT-SWAP", "long", 50, 110.0)

    assert out["realized_pnl"] == 500.0
    assert out["remaining_qty"] == 50.0
    assert out["ratio"] == 0.5
    assert led.get_position("ETH-USDT-SWAP", "long")["qty"] == 50.0


def test_short_partial_close_sign_is_inverted(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("BTC-USDT-SWAP", "short", 10, 100.0)

    out = led.apply_partial_close("BTC-USDT-SWAP", "short", 10, 95.0)

    assert out["realized_pnl"] == 50.0  # (100-95)*10
    assert led.get_position("BTC-USDT-SWAP", "short") is None


def test_full_close_removes_position_and_accumulates_pnl(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("SOL-USDT-SWAP", "long", 100, 10.0)

    led.apply_partial_close("SOL-USDT-SWAP", "long", 40, 11.0)
    out = led.apply_partial_close("SOL-USDT-SWAP", "long", 60, 12.0)

    assert out["remaining_qty"] == 0.0
    assert led.get_position("SOL-USDT-SWAP", "long") is None
    _row = [r for r in led.recent_fills(5) if r["action"] != "open"]
    assert sum(r["realized_pnl"] for r in _row) == 160.0  # 40*1 + 60*2


def test_unknown_position_does_not_fabricate_pnl(tmp_path):
    led = _ledger(tmp_path)

    out = led.apply_partial_close("DOGE-USDT-SWAP", "long", 10, 0.5)

    assert out["realized_pnl"] is None
    assert out["remaining_qty"] == 0.0


def test_weighted_average_on_add(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("ETH-USDT-SWAP", "long", 100, 100.0)

    out = led.record_open("ETH-USDT-SWAP", "long", 100, 120.0)

    assert out["qty"] == 200.0
    assert out["avg_entry"] == 110.0


class _OkxWithFills:
    def get_recent_fills(self, inst_id=None, limit=10):
        return {
            "ok": True,
            "fills": [
                {"pos_side": "long", "fill_px": 110.0, "fill_sz": 40.0, "fee": 0.5},
            ],
        }


def test_gateway_records_partial_close_automatically(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("ETH-USDT-SWAP", "long", 100, 100.0)
    gw = TradeExecutionGateway(
        okx_client=_OkxWithFills(),
        ledger=led,
        audit_path=tmp_path / "audit.jsonl",
    )
    sig = FinalDecisionSignal.from_dict(
        {
            "symbol": "ETH-USDT-SWAP",
            "pos_side": "long",
            "direction": "long",
            "action": "reduce",
            "sz": 40,
            "source": "23-evolution",
            "decision_id": "dec-test-1",
        }
    )

    gw._record_ledger(sig, ExecutionResult(passed=True, executed=True, reason="", reason_code=""))

    pos = led.get_position("ETH-USDT-SWAP", "long")
    assert pos["qty"] == 60.0
    last = led.recent_fills(1)[0]
    assert last["action"] == "reduce"
    assert last["realized_pnl"] == 399.5  # 40*(110-100) - 0.5 fee
    assert last["decision_id"] == "dec-test-1"


class _OkxWithPositions:
    def get_positions(self, inst_id=None):
        return {
            "ok": True,
            "positions": [
                {"inst_id": "BTC-USDT-SWAP", "pos_side": "short", "pos": 0.1, "avg_px": 66804.3},
                {"inst_id": "XAU-USDT-SWAP", "pos_side": "long", "pos": 18.0, "avg_px": 3879.4},
            ],
        }


def test_reconcile_backfills_missing_positions_idempotently(tmp_path):
    led = _ledger(tmp_path)
    led.record_open("ETH-USDT-SWAP", "long", 100, 100.0)  # 已有真实流水，必须保留

    first = led.reconcile(
        [
            {"inst_id": "ETH-USDT-SWAP", "pos_side": "long", "qty": 999, "avg_entry": 1.0},
            {"inst_id": "BTC-USDT-SWAP", "pos_side": "short", "qty": 0.1, "avg_entry": 66804.3},
        ]
    )
    second = led.reconcile(
        [{"inst_id": "BTC-USDT-SWAP", "pos_side": "short", "qty": 0.1, "avg_entry": 66804.3}]
    )

    assert first["inserted"] == 1 and first["skipped"] == 1
    assert second["inserted"] == 0 and second["skipped"] == 1
    eth = led.get_position("ETH-USDT-SWAP", "long")
    assert (eth["qty"], eth["avg_entry"], eth["source"]) == (100.0, 100.0, "")
    btc = led.get_position("BTC-USDT-SWAP", "short")
    assert (btc["qty"], btc["avg_entry"], btc["source"]) == (0.1, 66804.3, "22-reconciled")
    assert btc["entry_known"] == 1 and btc["realized_pnl"] == 0.0
    audits = [r for r in led.recent_fills(10) if r["action"] == "reconcile"]
    assert len(audits) == 1


def test_gateway_reconcile_ledger_reads_exchange_positions(tmp_path, monkeypatch):
    monkeypatch.setenv("POSITION_LEDGER_PATH", str(tmp_path / "gw_ledger.db"))
    gw = TradeExecutionGateway(
        okx_client=_OkxWithPositions(),
        audit_path=tmp_path / "audit.jsonl",
    )

    out = gw.reconcile_ledger()

    assert out["ok"] is True and out["inserted"] == 2
    rows = {p["inst_id"]: p for p in gw.list_positions()}
    assert rows["BTC-USDT-SWAP"]["source"] == "22-reconciled"
    assert rows["XAU-USDT-SWAP"]["avg_entry"] == 3879.4
