"""scheduler 测试 — 持续采集调度器。

覆盖：单次采集成功/失败、质量 issue 落库、告警落库、频率配置、启停。
用 fake_fetcher 注入避免真实网络调用。
"""
from dataclasses import dataclass
from typing import Any

import pytest

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import AlertLevel
from data_center.monitoring.quality import QualityChecker
from data_center.storage.sink_sqlite import SqliteSink
from data_center.scheduler import CollectionScheduler, CollectionTask


def _rec(source="fred", category="macro", sub="FEDFUNDS", val=5.25):
    from datetime import datetime, timezone
    return DataRecord(
        source=source, category=category, sub_category=sub,
        timestamp=datetime.now(timezone.utc).isoformat(),
        metrics={"value": val}, events=[], timeseries=[], raw={},
    )


def _make_dc(records_or_exc):
    """构造 fake DataCenter：fetch 返回 records 或抛异常。"""
    class _FakeDC:
        def __init__(self):
            self._records_or_exc = records_or_exc
            self.call_count = 0
        def fetch(self, category: str, **params):
            self.call_count += 1
            if isinstance(self._records_or_exc, Exception):
                raise self._records_or_exc
            return list(self._records_or_exc)
    return _FakeDC()


def test_collect_once_success(tmp_path):
    """单次采集成功：records + metric + quality 全部落库。"""
    dc = _make_dc([_rec("fred", "macro", "FEDFUNDS", 5.25)])
    sink = SqliteSink(str(tmp_path / "t.db"))
    sched = CollectionScheduler(
        dc=dc, sink=sink, quality=QualityChecker(),
        tasks=[CollectionTask(
            name="fred_rates", category="macro", source="fred",
            params={"series": "FEDFUNDS"}, interval_sec=3600,
        )],
    )
    metric = sched.collect_once(sched.tasks[0])
    assert metric.status == "ok"
    assert metric.records_count == 1
    # records 落库
    assert len(sink.read_all()) == 1
    # metric 落库
    health = sink.source_health()
    assert "fred" in health
    assert health["fred"]["last_status"] == "ok"
    assert health["fred"]["total"] == 1


def test_collect_once_error(tmp_path):
    """采集异常：metric(error) + alert 落库。"""
    dc = _make_dc(RuntimeError("FRED 不可达"))
    sink = SqliteSink(str(tmp_path / "t.db"))
    sched = CollectionScheduler(
        dc=dc, sink=sink, quality=QualityChecker(),
        tasks=[CollectionTask(
            name="fred_rates", category="macro", source="fred",
            params={"series": "FEDFUNDS"}, interval_sec=3600,
        )],
    )
    metric = sched.collect_once(sched.tasks[0])
    assert metric.status == "error"
    assert metric.error_type == "RuntimeError"
    # alert 落库
    alerts = sink.recent_alerts(limit=10)
    assert len(alerts) == 1
    assert alerts[0]["level"] in ("ERROR", "CRITICAL")
    assert "FRED" in alerts[0]["title"] or "fred" in alerts[0]["title"].lower()


def test_collect_with_quality_issue(tmp_path):
    """采集返回过时记录 → quality issue 落库。"""
    from datetime import datetime, timezone, timedelta
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    old_rec = DataRecord(
        source="fred", category="macro", sub_category="OLD",
        timestamp=old_iso, metrics={"value": 1}, events=[], timeseries=[], raw={},
    )
    dc = _make_dc([old_rec])
    sink = SqliteSink(str(tmp_path / "t.db"))
    checker = QualityChecker(freshness_threshold=timedelta(hours=1))
    sched = CollectionScheduler(
        dc=dc, sink=sink, quality=checker,
        tasks=[CollectionTask(
            name="fred_test", category="macro", source="fred",
            params={"series": "OLD"}, interval_sec=3600,
        )],
    )
    sched.collect_once(sched.tasks[0])
    issues = sink.recent_issues(limit=10)
    assert len(issues) >= 1
    assert any(i["code"] == "TIMESTAMP_FRESHNESS" for i in issues)


def test_default_tasks_config(tmp_path):
    """默认任务清单：9 个 collector 频率分级正确。"""
    dc = _make_dc([])
    sink = SqliteSink(str(tmp_path / "t.db"))
    sched = CollectionScheduler(
        dc=dc, sink=sink, quality=QualityChecker(),
        tasks=CollectionScheduler.default_tasks(),
    )
    # 默认应有任务覆盖 macro/finance/chain/news 四类
    cats = {t.category for t in sched.tasks}
    assert cats == {"macro", "finance", "chain", "news"}
    # 链上频率最高（≤ 5min），宏观最低（≥ 1h）
    chain_task = next(t for t in sched.tasks if t.category == "chain")
    macro_task = next(t for t in sched.tasks if t.category == "macro")
    assert chain_task.interval_sec <= 300
    assert macro_task.interval_sec >= 3600


def test_scheduler_start_stop(tmp_path):
    """启停：启动后能执行至少一次采集，stop 后线程退出。"""
    import time
    dc = _make_dc([_rec("ccxt", "chain", "ticker", 100.0)])
    sink = SqliteSink(str(tmp_path / "t.db"))
    sched = CollectionScheduler(
        dc=dc, sink=sink, quality=QualityChecker(),
        tasks=[CollectionTask(
            name="ccxt_ticker", category="chain", source="ccxt",
            params={"symbol": "BTC/USDT"}, interval_sec=1,  # 1s 便于测试
        )],
    )
    sched.start()
    time.sleep(2.5)  # 等 2-3 次采集
    sched.stop()
    assert dc.call_count >= 1
    health = sink.source_health()
    assert "ccxt" in health
    assert health["ccxt"]["total"] >= 1
