"""M5-T4 Red/Green — DataCenter 埋点集成测试。

三种核心场景：
1. 成功调用 → metric ok + 无质量告警
2. 采集抛异常 → metric error + ERROR 告警
3. 返回 CONTRACT 异常记录 → CONTRACT_INVALID quality issue + WARNING 告警
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import (
    Alert,
    AlertChannel,
    AlertLevel,
    FileAlertChannel,
)
from data_center.monitoring.metrics import InvocationMetric, MetricsStore
from data_center.monitoring.quality import QualityIssue, QualityIssueCode
from data_center.collectors._base import BaseCollector


class _SpyAlertChannel(AlertChannel):
    def __init__(self):
        self.received: list[Alert] = []

    def emit(self, alert: Alert) -> None:
        self.received.append(alert)


# ---------------------------------------------------------------------------
# 场景 1: FredCollector 成功 → metric ok + 无质量告警
# ---------------------------------------------------------------------------
def test_successful_fetch_records_ok_metric_and_no_quality_alerts():
    from data_center import DataCenter
    from data_center.core.registry import Registry
    from data_center.monitoring import MonitoringBundle, AlertRouter, QualityChecker, MetricsStore

    spy = _SpyAlertChannel()
    bundle = MonitoringBundle(
        metrics=MetricsStore(),
        quality=QualityChecker(),
        alerts=AlertRouter([spy]),
    )

    # 注册假的成功 collector
    class _OKCollector(BaseCollector):
        source = "ok_src"
        category = "macro"

        def fetch(self, params):
            time.sleep(0.002)
            return [DataRecord(
                source="ok_src", category="macro", sub_category="X",
                timestamp="2026-08-24T00:00:00+00:00",
                metrics={"value": 1.0, "date": "2026-08-24"},
                events=[], timeseries=[], raw={},
            )]

    reg = Registry()
    reg.register("macro", "ok_src", _OKCollector)

    dc = DataCenter(registry=reg, monitoring=bundle)
    result = dc.fetch("macro", source="ok_src")
    assert len(result) == 1

    # metric 断言
    summary = bundle.metrics.summary()
    assert ("ok_src", "macro") in summary
    bucket = summary[("ok_src", "macro")]
    assert bucket["total"] == 1
    assert bucket["ok_count"] == 1
    assert bucket["error_count"] == 0
    assert bucket["avg_duration_ms"] >= 1.0  # 至少 sleep 2ms

    # 无 ERROR/CRITICAL 告警
    error_alerts = [a for a in spy.received if a.level in (AlertLevel.ERROR, AlertLevel.CRITICAL)]
    assert error_alerts == []


# ---------------------------------------------------------------------------
# 场景 2: collector 抛异常 → metric error + ERROR 告警
# ---------------------------------------------------------------------------
def test_fetch_exception_records_error_metric_and_emits_error_alert():
    from data_center import DataCenter
    from data_center.core.registry import Registry
    from data_center.monitoring import MonitoringBundle, AlertRouter, QualityChecker, MetricsStore

    spy = _SpyAlertChannel()
    bundle = MonitoringBundle(
        metrics=MetricsStore(),
        quality=QualityChecker(),
        alerts=AlertRouter([spy], min_level=AlertLevel.WARNING),
    )

    class _BadCollector(BaseCollector):
        source = "bad_src"
        category = "news"

        def fetch(self, params):
            raise RuntimeError("上游 API 502")

    reg = Registry()
    reg.register("news", "bad_src", _BadCollector)

    dc = DataCenter(registry=reg, monitoring=bundle)

    with pytest.raises(RuntimeError):  # 异常仍向上抛（保持行为不变）
        dc.fetch("news", source="bad_src")

    summary = bundle.metrics.summary()
    bucket = summary[("bad_src", "news")]
    assert bucket["error_count"] == 1

    # 断言有 ERROR 级告警且包含 RuntimeError
    errs = [a for a in spy.received if a.level == AlertLevel.ERROR]
    assert len(errs) >= 1
    texts = [e.title + " " + e.message for e in errs]
    assert any("RuntimeError" in t for t in texts)


# ---------------------------------------------------------------------------
# 场景 3: 返回 CONTRACT 错误的 record → CONTRACT_INVALID issue + 告警
# ---------------------------------------------------------------------------
def test_contract_bad_record_emits_warning_alert():
    from data_center import DataCenter
    from data_center.core.registry import Registry
    from data_center.monitoring import MonitoringBundle, AlertRouter, QualityChecker, MetricsStore

    spy = _SpyAlertChannel()
    bundle = MonitoringBundle(
        metrics=MetricsStore(),
        quality=QualityChecker(),
        alerts=AlertRouter([spy], min_level=AlertLevel.INFO),
    )

    class _BadRecordCollector(BaseCollector):
        source = "badrec"
        category = "news"

        def fetch(self, params):
            # 返回一条 metrics 嵌套非法的 record
            rec = DataRecord(
                source="badrec", category="news", sub_category="rss",
                timestamp="2026-08-24T00:00:00+00:00",
                metrics={"ok": 1},
                events=[], timeseries=[], raw={},
            )
            rec.metrics = {"nested": {"deep": True}}  # 注入嵌套
            return [rec]

    reg = Registry()
    reg.register("news", "badrec", _BadRecordCollector)

    dc = DataCenter(registry=reg, monitoring=bundle)
    result = dc.fetch("news", source="badrec")
    assert len(result) == 1  # 数据质量不阻断返回

    # 有 CONTRACT_INVALID issue
    # 直接通过 quality 检查也能看到（实际上 DataCenter 已经检查过了，我们用 assert 告警）
    warns = [a for a in spy.received if "CONTRACT_INVALID" in a.title or
             any("CONTRACT_INVALID" in tag for tag in a.tags)]
    assert len(warns) >= 1, (
        f"期望有 CONTRACT_INVALID 告警，实际: {[(a.level, a.title, a.tags) for a in spy.received]}"
    )


# ---------------------------------------------------------------------------
# 场景 4: monitoring=None → 使用 default_monitoring_bundle（自动监控）
# ---------------------------------------------------------------------------
def test_monitoring_none_uses_default_bundle_records_metrics():
    from data_center import DataCenter
    from data_center.core.registry import Registry

    class _TinyCollector(BaseCollector):
        source = "tiny"
        category = "macro"

        def fetch(self, params):
            return [DataRecord(
                source="tiny", category="macro", sub_category="foo",
                timestamp="2026-08-24T00:00:00+00:00",
                metrics={"value": 1, "date": "2026-08-24"},
                events=[], timeseries=[], raw={},
            )]

    reg = Registry()
    reg.register("macro", "tiny", _TinyCollector)

    dc = DataCenter(registry=reg)  # 不传 monitoring → 默认 bundle
    result = dc.fetch("macro", source="tiny")
    assert len(result) == 1

    # DataCenter 实例应保存 monitoring，外部可读取
    assert dc.monitoring is not None
    summary = dc.monitoring.metrics.summary()
    assert ("tiny", "macro") in summary
    assert summary[("tiny", "macro")]["ok_count"] == 1


# ---------------------------------------------------------------------------
# 场景 5: 空列表（非 degraded） → EMPTY_RESULT issue + WARNING 告警
# ---------------------------------------------------------------------------
def test_empty_records_non_degraded_emits_warning():
    from data_center import DataCenter
    from data_center.core.registry import Registry
    from data_center.monitoring import MonitoringBundle, AlertRouter, QualityChecker, MetricsStore

    spy = _SpyAlertChannel()
    bundle = MonitoringBundle(
        metrics=MetricsStore(),
        quality=QualityChecker(),
        alerts=AlertRouter([spy], min_level=AlertLevel.INFO),
    )

    class _EmptyCollector(BaseCollector):
        source = "empty_src"
        category = "chain"

        def fetch(self, params):
            return []  # 非 degraded，空列表

    reg = Registry()
    reg.register("chain", "empty_src", _EmptyCollector)

    dc = DataCenter(registry=reg, monitoring=bundle)
    dc.fetch("chain", source="empty_src")

    titles = [a.title for a in spy.received]
    tags_sum = []
    for a in spy.received:
        tags_sum.extend(a.tags)
    assert "EMPTY_RESULT" in tags_sum or any("EMPTY_RESULT" in t for t in titles)
