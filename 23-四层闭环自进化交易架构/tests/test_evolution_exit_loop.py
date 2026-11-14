"""23 离场循环（exit loop）下沉测试。"""

import time

import pytest
from dreambuddy_evolution.execution import EvolutionExitLoop
from dreambuddy_evolution.execution.outbox import ExecutionOutbox


class _Result:
    def __init__(self, executed=True, reason="", reason_code="", order_result=None):
        self.passed = executed
        self.executed = executed
        self.reason = reason
        self.reason_code = reason_code
        self.order_result = order_result or {"ord_id": "ord-close"}
        self.sltp_result = None


class _Gateway:
    def __init__(self, executed=True):
        self.executed = executed
        self.calls = []

    def submit(self, decision):
        self.calls.append(decision)
        return _Result(
            executed=self.executed,
            reason="" if self.executed else "gateway_reject",
            reason_code="" if self.executed else "REJECT",
        )


class _Okx:
    def __init__(self, positions=None):
        self.positions = positions or []
        self.sltp_calls = []
        self.cancel_calls = []

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": self.positions}

    def cancel_algo_orders(self, inst_id=None):
        self.cancel_calls.append(inst_id)
        return {"ok": True}

    def place_stop_loss_take_profit(self, **kwargs):
        self.sltp_calls.append(kwargs)
        return {"ok": True}


class _Decision:
    def __init__(self, action, reason="rule", params=None, sl_px=0.0, tp_px=0.0, confidence=0.8):
        self.action = action
        self.reason = reason
        self.params = params or {}
        self.sl_px = sl_px
        self.tp_px = tp_px
        self.confidence = confidence


class _Engine:
    def __init__(self, action="hold", **kw):
        self.action = action
        self.kw = kw
        self.contexts = []

    def decide(self, ctx):
        self.contexts.append(ctx)
        return _Decision(self.action, **self.kw)


def _pos(**kw):
    base = {
        "inst_id": "BTC-USDT-SWAP",
        "coin": "BTC",
        "pos_side": "long",
        "entry_price": 100.0,
        "current_price": 95.0,
        "position_usdt": 300.0,
        "position_qty": 3,
        "entry_time": time.time() - 3600,
        "source_tag": "evolution",
    }
    base.update(kw)
    return base


def _loop(tmp_path, engine, gateway=None, okx=None):
    return EvolutionExitLoop(
        gateway=gateway,
        okx_client=okx,
        exit_engine=engine,
        runtime_dir=tmp_path,
        enable_rl=False,
        enable_shadow_rl=False,
        log_fn=lambda *a, **k: None,
    )


def test_hold_records_metrics(tmp_path):
    engine = _Engine("hold")
    loop = _loop(tmp_path, engine)
    report = loop.run([_pos()])
    assert report["checked"] == 1 and report["hold"] == 1
    ctx = engine.contexts[0]
    assert ctx["upl"] == pytest.approx(-15.0)
    assert ctx["upl_ratio"] == pytest.approx(-0.05)
    assert ctx["position_age_sec"] >= 3500


def test_force_close_dispatches_exit_decision(tmp_path):
    gw = _Gateway()
    okx = _Okx([{"pos_side": "long", "pos": "3", "mark_px": "95"}])
    closed = []
    loop = _loop(tmp_path, _Engine("force_close"), gateway=gw, okx=okx)
    report = loop.run([_pos()], on_closed=lambda pos, dec, res, ctx: closed.append((pos, dec, res)))

    assert len(report["executed"]) == 1
    sig = gw.calls[0]
    assert sig["source"] == "23-evolution"
    assert sig["action"] == "close"
    assert sig["sz"] == 3
    assert sig["decision_id"].startswith("dec-23-")
    assert len(closed) == 1


def test_partial_close_uses_reduce_and_ratio(tmp_path):
    gw = _Gateway()
    okx = _Okx([{"pos_side": "long", "pos": "4", "mark_px": "95"}])
    loop = _loop(
        tmp_path, _Engine("partial_close", params={"partial_pct": 0.5}), gateway=gw, okx=okx
    )
    report = loop.run([_pos()])

    sig = gw.calls[0]
    assert sig["action"] == "reduce"
    assert sig["sz"] == 2
    assert sig["payload"]["reduce_ratio"] == 0.5
    assert len(report["executed"]) == 1


def test_close_size_unknown_does_not_dispatch(tmp_path):
    gw = _Gateway()
    okx = _Okx([])  # 无持仓可查
    loop = _loop(tmp_path, _Engine("force_close"), gateway=gw, okx=okx)
    report = loop.run([_pos(position_qty=0)])
    assert gw.calls == []
    assert len(report["failed"]) == 1
    assert report["failed"][0]["reason"] == "size_unknown"


def test_gateway_reject_reports_failed(tmp_path):
    gw = _Gateway(executed=False)
    okx = _Okx([{"pos_side": "long", "pos": "3", "mark_px": "95"}])
    loop = _loop(tmp_path, _Engine("force_close"), gateway=gw, okx=okx)
    report = loop.run([_pos()])
    assert len(report["failed"]) == 1
    assert report["failed"][0]["reason_code"] == "REJECT"


def test_ghost_position_calls_hook(tmp_path):
    ghosts = []
    okx = _Okx([])
    loop = _loop(tmp_path, _Engine("hold"), okx=okx)
    report = loop.run(
        [_pos(current_price=0, position_usdt=0)], on_ghost=lambda pos, px: ghosts.append(px)
    )
    assert report["skipped"] == 1
    assert ghosts == [100.0]


def test_adjust_sl_tp_routes_to_okx(tmp_path):
    okx = _Okx([{"pos_side": "long", "pos": "3", "mark_px": "95"}])
    loop = _loop(tmp_path, _Engine("trailing", sl_px=96.5, tp_px=110.0), okx=okx)
    report = loop.run([_pos(current_price=99.0)])
    assert report["executed"][0]["action"] == "trailing"
    assert okx.cancel_calls == ["BTC-USDT-SWAP"]
    assert okx.sltp_calls[0]["stop_loss_px"] == 96.5
    assert okx.sltp_calls[0]["take_profit_px"] == 110.0


def test_enricher_can_skip_and_override(tmp_path):
    engine = _Engine("hold")
    loop = _loop(tmp_path, engine)

    class _Skip:
        pass

    report = loop.run([_pos()], enricher=lambda pos, ctx: None)
    assert report["skipped"] == 1 and engine.contexts == []

    report = loop.run([_pos()], enricher=lambda pos, ctx: {"ess": 0.9, "has_stronger_signal": True})
    assert engine.contexts[0]["ess"] == 0.9
    assert engine.contexts[0]["has_stronger_signal"] is True
    assert report["hold"] == 1


def test_exception_in_one_position_does_not_block_others(tmp_path):
    class _Boom:
        def decide(self, ctx):
            if ctx["symbol"] == "BTC":
                raise RuntimeError("decide_boom")
            return _Decision("hold")

    loop = _loop(tmp_path, _Boom())
    report = loop.run([_pos(), _pos(inst_id="ETH-USDT-SWAP", coin="ETH")])
    assert report["checked"] == 2
    assert len(report["failed"]) == 1
    assert report["hold"] == 1


def test_outbox_dedupes_repeated_close(tmp_path):
    gw = _Gateway()
    # 同一 decision 重复 dispatch 时由 outbox 去重（此处直接验证 dispatcher 层）
    from dreambuddy_evolution.execution import build_exit_decision

    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    from dreambuddy_evolution.execution import EvolutionSignalDispatcher

    disp = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = build_exit_decision("BTC-USDT-SWAP", "long", sz=3, reduce_ratio=1.0)
    assert disp.dispatch(sig)["executed"] is True
    assert disp.dispatch(sig)["reason_code"] == "DUPLICATE_DECISION"
    assert len(gw.calls) == 1
