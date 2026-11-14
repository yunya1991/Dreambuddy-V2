"""P2：23 部分减仓后同步剩余仓位（读取 22 账本）。"""

from __future__ import annotations

from types import SimpleNamespace

from dreambuddy_evolution.execution.exit_loop import EvolutionExitLoop


class _Okx:
    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": [{"pos_side": "long", "pos": 100}]}


class _LedgerGateway:
    def get_position(self, inst_id, pos_side):
        return {"qty": 60.0, "avg_entry": 100.0}


class _Dispatcher:
    def __init__(self):
        self._gateway = _LedgerGateway()

    def dispatch(self, sig):
        return {"ok": True, "executed": True, "reason": "", "reason_code": ""}


def test_partial_close_refreshes_remaining_qty_from_ledger():
    loop = EvolutionExitLoop(okx_client=_Okx(), enable_rl=False)
    loop._dispatcher = _Dispatcher()
    pos = {
        "inst_id": "ETH-USDT-SWAP",
        "coin": "ETH",
        "pos_side": "long",
        "entry_price": 100.0,
        "current_price": 110.0,
        "position_qty": 100,
        "position_usdt": 11000.0,
    }
    ctx = {"position_qty": 100, "position_usdt": 11000.0, "pos_side": "long"}

    res = loop._execute_close(
        pos,
        "ETH-USDT-SWAP",
        "ETH",
        "long",
        0.5,
        SimpleNamespace(reason="rule4 batch1"),
        ctx,
        None,
    )

    assert res["status"] == "executed"
    assert pos["position_qty"] == 60.0
    assert ctx["position_qty"] == 60.0
    assert ctx["position_usdt"] == 5500.0


def test_partial_close_falls_back_to_ratio_when_no_ledger():
    loop = EvolutionExitLoop(okx_client=_Okx(), enable_rl=False)
    loop._dispatcher = _Dispatcher()
    loop._dispatcher._gateway = object()  # 无 get_position
    pos = {
        "inst_id": "ETH-USDT-SWAP",
        "coin": "ETH",
        "pos_side": "long",
        "entry_price": 100.0,
        "current_price": 110.0,
        "position_qty": 100,
        "position_usdt": 11000.0,
    }
    ctx = {"position_qty": 100, "position_usdt": 11000.0, "pos_side": "long"}

    loop._execute_close(
        pos,
        "ETH-USDT-SWAP",
        "ETH",
        "long",
        0.5,
        SimpleNamespace(reason="rule4 batch1"),
        ctx,
        None,
    )

    assert pos["position_qty"] == 50.0
