"""23 域 FinalDecisionSignal 生产与 22 网关提交测试（M1）。"""

from datetime import datetime, timedelta, timezone

from dreambuddy_evolution.execution import (
    SOURCE,
    EvolutionSignalDispatcher,
    build_entry_decision,
    build_exit_decision,
    compute_sl_tp_pct,
)


class _FakeExecResult:
    def __init__(self, executed=True, reason="", reason_code="", order_result=None):
        self.passed = executed
        self.executed = executed
        self.reason = reason
        self.reason_code = reason_code
        self.order_result = order_result or {}
        self.sltp_result = {"ok": True}


class _FakeGateway:
    def __init__(self, executed=True):
        self.executed = executed
        self.calls = []

    def submit(self, decision):
        self.calls.append(decision)
        return _FakeExecResult(
            executed=self.executed,
            reason="" if self.executed else "rejected",
            reason_code="" if self.executed else "FAKE_REJECT",
            order_result={"ord_id": "ord-1", "avg_px": 100.0} if self.executed else {},
        )


def test_entry_signal_contract():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    sig = build_entry_decision(
        symbol="BTC-USDT-SWAP",
        direction="long",
        confidence=0.83,
        notional_usdt=500.0,
        tier="standard",
        price=100.0,
        atr_pct=0.01,
        now=now,
    )
    assert sig["source"] == SOURCE
    assert sig["decision_id"].startswith("dec-23-BTC-USDT-SWAP-open-")
    assert sig["signal_id"].endswith(sig["decision_id"])
    assert sig["direction"] == "long"
    assert sig["action"] == "open"
    assert sig["sl_px"] < 100.0 < sig["tp_px"]
    assert sig["payload"]["notional_usdt"] == 500.0
    assert sig["payload"]["tag"] == "evo23"
    assert sig["expires_at"].endswith("Z")
    _exp = datetime.fromisoformat(sig["expires_at"].replace("Z", "+00:00"))
    assert _exp > now


def test_short_signal_sl_tp_inverted():
    sig = build_entry_decision(
        symbol="ETH-USDT-SWAP",
        direction="short",
        confidence=0.7,
        notional_usdt=200.0,
        price=100.0,
        atr_pct=0.02,
    )
    assert sig["sl_px"] > 100.0 > sig["tp_px"]
    assert sig["direction"] == "short"


def test_exit_signal_full_and_partial():
    _full = build_exit_decision("BTC-USDT-SWAP", "long", sz=10, reduce_ratio=1.0)
    _part = build_exit_decision("BTC-USDT-SWAP", "long", sz=3, reduce_ratio=0.3)
    assert _full["action"] == "close"
    assert _part["action"] == "reduce"
    assert _part["payload"]["reduce_ratio"] == 0.3
    assert _full["source"] == SOURCE


def test_sl_tp_floor():
    _sl, _tp = compute_sl_tp_pct("probe", atr_pct=0.0)
    assert _sl == 0.04
    assert _tp == 0.12
    _sl2, _tp2 = compute_sl_tp_pct("trend", atr_pct=0.02)
    assert _sl2 == 0.10  # 5.0 × 2%
    assert _tp2 == 0.15


def test_dispatcher_without_gateway(tmp_path):
    d = EvolutionSignalDispatcher(gateway=None, runtime_dir=tmp_path)
    res = d.dispatch(build_exit_decision("BTC-USDT-SWAP", "long", sz=1))
    assert res["ok"] is False
    assert res["reason_code"] == "NO_GATEWAY"
    assert (tmp_path / "execution_decisions.jsonl").exists()


def test_dispatcher_forwards_to_gateway(tmp_path):
    gw = _FakeGateway(executed=True)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path)
    sig = build_entry_decision("BTC-USDT-SWAP", "long", 0.8, 300.0, price=100.0)
    res = d.dispatch(sig)
    assert res["ok"] is True
    assert res["executed"] is True
    assert res["order_result"]["ord_id"] == "ord-1"
    assert gw.calls and gw.calls[0]["decision_id"] == sig["decision_id"]


def test_dispatcher_gateway_reject(tmp_path):
    d = EvolutionSignalDispatcher(gateway=_FakeGateway(executed=False), runtime_dir=tmp_path)
    res = d.dispatch(build_entry_decision("BTC-USDT-SWAP", "long", 0.8, 300.0))
    assert res["ok"] is False
    assert res["reason_code"] == "FAKE_REJECT"


def test_expires_at_is_future():
    sig = build_entry_decision("BTC-USDT-SWAP", "long", 0.8, 300.0)
    exp = datetime.fromisoformat(sig["expires_at"].replace("Z", "+00:00"))
    assert exp - datetime.now(timezone.utc) > timedelta(minutes=1)
