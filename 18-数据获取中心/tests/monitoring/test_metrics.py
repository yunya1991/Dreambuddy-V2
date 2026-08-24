"""M5-T1 Red — MetricsStore 调用统计测试（先写失败用例）。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# 1. InvocationMetric 数据模型断言
# ---------------------------------------------------------------------------
def test_invocation_metric_has_required_fields():
    """InvocationMetric 应包含：invocation_id, ts, source, category, status,
    duration_ms, records_count, error_type, error_msg。"""
    from data_center.monitoring.metrics import InvocationMetric

    m = InvocationMetric(
        invocation_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        source="fred",
        category="macro",
        status="ok",
        duration_ms=123.45,
        records_count=10,
        error_type=None,
        error_msg=None,
    )
    assert m.source == "fred"
    assert m.category == "macro"
    assert m.status == "ok"
    assert m.duration_ms > 0
    assert m.records_count == 10
    assert m.error_type is None
    assert m.error_msg is None


def test_invocation_metric_status_only_ok_or_error():
    """status 只允许 'ok' 或 'error'，其他值抛 ValueError。"""
    from data_center.monitoring.metrics import InvocationMetric

    with pytest.raises(ValueError):
        InvocationMetric(
            invocation_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            source="x",
            category="y",
            status="unknown",  # 非法
            duration_ms=1.0,
            records_count=0,
            error_type=None,
            error_msg=None,
        )


# ---------------------------------------------------------------------------
# 2. MetricsStore.record() 基础
# ---------------------------------------------------------------------------
def test_record_ok_metric_has_positive_duration():
    """成功调用：duration_ms > 0，records_count >= 0，status='ok'。"""
    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    metric = InvocationMetric(
        invocation_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        source="fred",
        category="macro",
        status="ok",
        duration_ms=80.5,
        records_count=3,
        error_type=None,
        error_msg=None,
    )
    store.record(metric)
    result = store.query(source="fred", category="macro")
    assert len(result) == 1
    assert result[0].status == "ok"
    assert result[0].duration_ms > 0
    assert result[0].records_count >= 0


def test_record_error_metric_has_error_fields():
    """异常调用：error_type 非空，status='error'。"""
    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    metric = InvocationMetric(
        invocation_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        source="tavily",
        category="news",
        status="error",
        duration_ms=45.0,
        records_count=0,
        error_type="SourceUnavailableError",
        error_msg="Missing TAVILY_API_KEY",
    )
    store.record(metric)
    result = store.query(source="tavily")
    assert len(result) == 1
    assert result[0].status == "error"
    assert result[0].error_type == "SourceUnavailableError"
    assert result[0].error_msg is not None


# ---------------------------------------------------------------------------
# 3. MetricsStore.query() 过滤
# ---------------------------------------------------------------------------
def test_query_filters_by_source_and_category():
    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    items = [
        ("fred", "macro", "ok"),
        ("fred", "macro", "error"),
        ("ccxt", "chain", "ok"),
        ("tavily", "news", "ok"),
    ]
    for src, cat, st in items:
        store.record(InvocationMetric(
            invocation_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            source=src,
            category=cat,
            status=st,
            duration_ms=10.0,
            records_count=0,
            error_type=None if st == "ok" else "E",
            error_msg=None,
        ))
    # source + category 过滤
    fred_macro = store.query(source="fred", category="macro")
    assert len(fred_macro) == 2
    # 仅 source 过滤
    fred_all = store.query(source="fred")
    assert len(fred_all) == 2
    # 仅 category 过滤
    chain = store.query(category="chain")
    assert len(chain) == 1
    assert chain[0].source == "ccxt"
    # 不过滤 → 4 条
    assert len(store.query()) == 4


def test_query_filters_by_time_window():
    """window_sec 只返回最近 N 秒内的记录。"""
    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    now = datetime.now(timezone.utc)
    # 老记录（60 秒前）
    store.record(InvocationMetric(
        invocation_id="old",
        ts=now - timedelta(seconds=60),
        source="x",
        category="y",
        status="ok",
        duration_ms=1.0,
        records_count=0,
        error_type=None,
        error_msg=None,
    ))
    # 新记录
    store.record(InvocationMetric(
        invocation_id="new",
        ts=now,
        source="x",
        category="y",
        status="ok",
        duration_ms=1.0,
        records_count=0,
        error_type=None,
        error_msg=None,
    ))
    recent = store.query(window_sec=5)
    assert len(recent) == 1
    assert recent[0].invocation_id == "new"


# ---------------------------------------------------------------------------
# 4. MetricsStore.summary() 聚合
# ---------------------------------------------------------------------------
def test_summary_groups_by_source_category():
    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    # fred/macro: 2 ok + 1 error，duration [10, 20, 30]
    for i, st in enumerate(["ok", "ok", "error"]):
        store.record(InvocationMetric(
            invocation_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            source="fred",
            category="macro",
            status=st,
            duration_ms=float((i + 1) * 10),
            records_count=i,
            error_type=None if st == "ok" else "E",
            error_msg=None,
        ))
    s = store.summary()
    fred_key = ("fred", "macro")
    assert fred_key in s
    bucket = s[fred_key]
    assert bucket["total"] == 3
    assert bucket["ok_count"] == 2
    assert bucket["error_count"] == 1
    # avg = (10 + 20 + 30) / 3 = 20.0
    assert bucket["avg_duration_ms"] == pytest.approx(20.0, abs=0.1)


def test_summary_empty_store_returns_empty_dict():
    from data_center.monitoring.metrics import MetricsStore

    assert MetricsStore().summary() == {}


# ---------------------------------------------------------------------------
# 5. 线程安全：并发 record 不丢失
# ---------------------------------------------------------------------------
def test_metrics_store_thread_safe():
    import threading

    from data_center.monitoring.metrics import InvocationMetric, MetricsStore

    store = MetricsStore()
    N = 200
    per_thread = 20

    def worker(tid: int):
        for i in range(per_thread):
            store.record(InvocationMetric(
                invocation_id=f"t{tid}-{i}",
                ts=datetime.now(timezone.utc),
                source="s",
                category="c",
                status="ok",
                duration_ms=1.0,
                records_count=0,
                error_type=None,
                error_msg=None,
            ))

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(N // per_thread)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.query()) == N
    assert store.summary()[("s", "c")]["total"] == N
