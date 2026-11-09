"""M4-1 测试：task_dispatcher（SPEC-M3 §1.1）。

覆盖：task schema/持久化、去重、优先级、P2 饥饿防护、salience 配额。
"""

from __future__ import annotations

import pytest
from task_dispatcher import (
    SALIENCE_QUOTA,
    Task,
    TaskDispatcher,
)


@pytest.fixture
def dispatcher(tmp_path):
    path = str(tmp_path / "dispatch_tasks.jsonl")
    return TaskDispatcher(dispatch_path=path)


def _task(symbol="BTC/USDT", priority="P0", trigger="macro_led", **kw):
    return dict(symbol=symbol, trigger=trigger, priority=priority, requester="40-cycle", **kw)


class TestTaskSubmit:
    def test_submit_returns_task_with_schema(self, dispatcher):
        t = dispatcher.submit(**_task())
        assert isinstance(t, Task)
        assert t.priority == "P0"
        assert t.symbol == "BTC/USDT"
        assert t.state == "queued"
        assert t.task_id.startswith("task_")
        assert t.deadline_at and t.created_at

    def test_invalid_priority_returns_none(self, dispatcher):
        assert dispatcher.submit(**_task(priority="P9")) is None

    def test_invalid_trigger_defaults_to_routine(self, dispatcher):
        t = dispatcher.submit(**_task(trigger="garbage"))
        assert t.trigger == "routine"


class TestDeduplication:
    def test_same_symbol_no_duplicate(self, dispatcher):
        t1 = dispatcher.submit(**_task())
        t2 = dispatcher.submit(**_task())  # 同标的再提交
        assert t1.task_id == t2.task_id

    def test_different_symbols_both_submitted(self, dispatcher):
        t1 = dispatcher.submit(**_task(symbol="BTC/USDT"))
        t2 = dispatcher.submit(**_task(symbol="ETH/USDT"))
        assert t1.task_id != t2.task_id


class TestPriorityAndQueued:
    def test_list_queued_sorted_by_priority(self, dispatcher):
        dispatcher.submit(**_task(symbol="A", priority="P2", trigger="routine"))
        dispatcher.submit(**_task(symbol="B", priority="P0"))
        dispatcher.submit(**_task(symbol="C", priority="P1", trigger="micro_led"))
        queued = dispatcher.list_queued()
        assert [q.priority for q in queued] == ["P0", "P1", "P2"]

    def test_list_queued_filter_by_priority(self, dispatcher):
        dispatcher.submit(**_task(symbol="A", priority="P2", trigger="routine"))
        dispatcher.submit(**_task(symbol="B", priority="P0"))
        p0 = dispatcher.list_queued(priority="P0")
        assert len(p0) == 1 and p0[0].priority == "P0"


class TestSalienceQuota:
    def test_p1_quota_limits_per_source(self, dispatcher):
        # 同一源提交 SALIENCE_QUOTA 次 P1 应成功
        for i in range(SALIENCE_QUOTA):
            t = dispatcher.submit(
                **_task(symbol=f"S{i}", priority="P1", trigger="micro_led"),
                salience_source="11-bcrm",
            )
            assert t is not None, f"P1 #{i} should succeed"
        # 第 SALIENCE_QUOTA+1 次应被配额拦截
        blocked = dispatcher.submit(
            **_task(symbol="SX", priority="P1", trigger="micro_led"),
            salience_source="11-bcrm",
        )
        assert blocked is None

    def test_p0_not_subject_to_salience_quota(self, dispatcher):
        # P0 不受 salience 配额限制
        for i in range(SALIENCE_QUOTA + 5):
            t = dispatcher.submit(
                **_task(symbol=f"P0-{i}", priority="P0"),
                salience_source="11-bcrm",
            )
            assert t is not None


class TestP2Timeshare:
    def test_empty_dispatcher_p2_yield_allowed(self, dispatcher):
        assert dispatcher.p2_yield_allowed() is True

    def test_p1_blocked_when_p2_below_floor(self, dispatcher):
        # 提交大量非 P2 任务，使 P2 时间片低于下限
        for i in range(10):
            dispatcher.submit(**_task(symbol=f"P0-{i}", priority="P0"))
        # P2 占比 0/10 = 0 < P2_MIN_TIMESHARE
        assert dispatcher.p2_yield_allowed() is False
        # 新 P1 应被拒绝
        blocked = dispatcher.submit(
            **_task(symbol="P1-blocked", priority="P1", trigger="micro_led"),
            salience_source="11-bdsm",
        )
        assert blocked is None

    def test_p0_not_blocked_by_p2_floor(self, dispatcher):
        for i in range(10):
            dispatcher.submit(**_task(symbol=f"P0-{i}", priority="P0"))
        # P0 不受 P2 下限限制
        t = dispatcher.submit(**_task(symbol="P0-new", priority="P0"))
        assert t is not None


class TestStateUpdate:
    def test_update_state(self, dispatcher):
        t = dispatcher.submit(**_task())
        ok = dispatcher.update_state(t.task_id, "running")
        assert ok is True
        # queued 列表应不再包含它
        assert not dispatcher.list_queued()

    def test_update_invalid_state_returns_false(self, dispatcher):
        t = dispatcher.submit(**_task())
        assert dispatcher.update_state(t.task_id, "bogus") is False


class TestPersistence:
    def test_tasks_persist_across_instances(self, tmp_path):
        path = str(tmp_path / "dp.jsonl")
        d1 = TaskDispatcher(dispatch_path=path)
        d1.submit(**_task(symbol="BTC/USDT", priority="P0"))
        d2 = TaskDispatcher(dispatch_path=path)
        queued = d2.list_queued()
        assert len(queued) == 1
        assert queued[0].symbol == "BTC/USDT"
