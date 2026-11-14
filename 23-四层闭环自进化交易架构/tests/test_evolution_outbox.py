"""23 执行发件箱（outbox）幂等测试。"""

from dreambuddy_evolution.execution import (
    EvolutionSignalDispatcher,
    ExecutionOutbox,
    build_entry_decision,
)
from dreambuddy_evolution.execution.outbox import (
    STATE_FAILED,
    STATE_FILLED,
    STATE_PENDING,
    STATE_SUBMITTED,
    STATE_SUBMITTING,
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
            reason="" if self.executed else "rejected_by_13",
            reason_code="" if self.executed else "FAKE_REJECT",
            order_result={"ord_id": "ord-1", "avg_px": 100.0} if self.executed else {},
        )


class _BoomOutbox:
    """enqueue 必抛异常，验证 FAIL-OPEN 回退直提。"""

    def enqueue(self, decision):
        raise RuntimeError("outbox_down")

    def get(self, decision_id):
        raise RuntimeError("outbox_down")

    def try_acquire(self, decision_id):
        raise RuntimeError("outbox_down")

    def mark_submitted(self, *a, **k):
        raise RuntimeError("outbox_down")

    def mark_failed(self, *a, **k):
        raise RuntimeError("outbox_down")


def _sig(price=100.0):
    return build_entry_decision("BTC-USDT-SWAP", "long", 0.8, 300.0, price=price)


def test_enqueue_first_then_duplicate(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    sig = _sig()
    assert box.enqueue(sig) == "enqueued"
    assert box.enqueue(sig) == "duplicate"
    row = box.get(sig["decision_id"])
    assert row["state"] == STATE_PENDING
    assert row["attempts"] == 0
    assert row["notional_usdt"] == 300.0


def test_dispatcher_dedupes_after_success(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    gw = _FakeGateway(executed=True)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = _sig()

    first = d.dispatch(sig)
    assert first["executed"] is True and not first.get("cached")

    second = d.dispatch(sig)
    assert len(gw.calls) == 1, "重复 decision_id 不得二次提交"
    assert second["reason_code"] == "DUPLICATE_DECISION"
    assert second["cached"] is True
    assert second["order_result"]["ord_id"] == "ord-1"

    row = box.get(sig["decision_id"])
    assert row["state"] == STATE_SUBMITTED
    assert row["attempts"] == 1


def test_dispatcher_in_flight(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    gw = _FakeGateway(executed=True)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = _sig()

    box.enqueue(sig)
    assert box.try_acquire(sig["decision_id"]) is True

    res = d.dispatch(sig)
    assert res["reason_code"] == "IN_FLIGHT"
    assert res["executed"] is False
    assert gw.calls == []
    assert box.get(sig["decision_id"])["state"] == STATE_SUBMITTING


def test_dispatcher_retry_exhausted(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db", max_attempts=1)
    gw = _FakeGateway(executed=False)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = _sig()

    first = d.dispatch(sig)
    assert first["reason_code"] == "FAKE_REJECT"
    assert box.get(sig["decision_id"])["state"] == STATE_FAILED

    second = d.dispatch(sig)
    assert second["reason_code"] == "RETRY_EXHAUSTED"
    assert len(gw.calls) == 1


def test_dispatcher_retry_succeeds_within_limit(tmp_path):
    class _FlakyGateway(_FakeGateway):
        def submit(self, decision):
            self.calls.append(decision)
            ok = len(self.calls) > 1
            return _FakeExecResult(
                executed=ok,
                reason="" if ok else "transient_reject",
                reason_code="" if ok else "TRANSIENT",
                order_result={"ord_id": "ord-2"} if ok else {},
            )

    box = ExecutionOutbox(db_path=tmp_path / "ob.db", max_attempts=3)
    gw = _FlakyGateway()
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = _sig()

    assert d.dispatch(sig)["executed"] is False
    second = d.dispatch(sig)
    assert second["executed"] is True
    assert second["decision_id"] == sig["decision_id"]
    assert len(gw.calls) == 2
    assert box.get(sig["decision_id"])["attempts"] == 2


def test_retry_pending_resets_failed(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    sig = _sig()
    box.enqueue(sig)
    assert box.try_acquire(sig["decision_id"]) is True
    box.mark_failed(sig["decision_id"], "transient")

    assert box.retry_pending() == 1
    row = box.get(sig["decision_id"])
    assert row["state"] == STATE_PENDING
    assert row["attempts"] == 1
    assert row["last_error"] == "transient"


def test_mark_filled_then_dispatch_returns_cache(tmp_path):
    box = ExecutionOutbox(db_path=tmp_path / "ob.db")
    gw = _FakeGateway(executed=True)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=box)
    sig = _sig()

    box.enqueue(sig)
    box.try_acquire(sig["decision_id"])
    box.mark_filled(
        sig["decision_id"], broker_ord_id="ord-9", result={"order_result": {"ord_id": "ord-9"}}
    )

    res = d.dispatch(sig)
    assert res["reason_code"] == "DUPLICATE_DECISION"
    assert res["order_result"]["ord_id"] == "ord-9"
    assert gw.calls == []
    assert box.get(sig["decision_id"])["state"] == STATE_FILLED


def test_outbox_failure_fail_open(tmp_path):
    gw = _FakeGateway(executed=True)
    d = EvolutionSignalDispatcher(gateway=gw, runtime_dir=tmp_path, outbox=_BoomOutbox())
    res = d.dispatch(_sig())
    assert res["executed"] is True
    assert len(gw.calls) == 1


def test_disabled_outbox_returns_none(tmp_path, monkeypatch):
    from dreambuddy_evolution.execution import default_outbox

    monkeypatch.setenv("EVOLUTION_OUTBOX_ENABLED", "off")
    monkeypatch.setenv("EVOLUTION_OUTBOX_DB", str(tmp_path / "disabled.db"))
    assert default_outbox() is None

    monkeypatch.setenv("EVOLUTION_OUTBOX_ENABLED", "on")
    box = default_outbox()
    assert box is not None and box.enabled is True
