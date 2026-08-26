"""sqlite 落库测试 — 对齐 TECHNICAL_DESIGN.md §6/§3.3。

写入后可读回、字段一致；同 dedupe_key 二次写入被忽略。
扩展：metrics/quality/alerts 三表 + 按源/时间窗口查询 + source_health。
"""
from datetime import datetime, timezone, timedelta

from data_center.core.contract import DataRecord
from data_center.monitoring.alerting import Alert, AlertLevel
from data_center.monitoring.metrics import InvocationMetric
from data_center.monitoring.quality import QualityChecker, QualityIssue, QualityIssueCode
from data_center.storage.sink_sqlite import SqliteSink


def _rec(sub, date, val):
    return DataRecord(
        source="fred", category="macro", sub_category=sub,
        timestamp="2026-08-24T08:00:00+08:00",
        metrics={"value": val, "date": date},
        events=[], timeseries=[{"date": date, "value": val}],
        raw={"series_id": sub},
    )


def test_write_and_read_back(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    assert sink.write([_rec("FEDFUNDS", "2026-08-01", 5.25)]) == 1
    rows = sink.read_all()
    assert len(rows) == 1
    r = rows[0]
    assert r.source == "fred"
    assert r.sub_category == "FEDFUNDS"
    assert r.metrics["value"] == 5.25
    assert r.metrics["date"] == "2026-08-01"
    assert r.timeseries[0]["value"] == 5.25


def test_dedupe_at_sink(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    rec = _rec("FEDFUNDS", "2026-08-01", 5.25)
    assert sink.write([rec]) == 1
    assert sink.write([rec]) == 0  # 同 dedupe_key，INSERT OR IGNORE 跳过
    assert len(sink.read_all()) == 1


# ── 扩展：metrics / quality / alerts 三表 ─────────────────────────────────────


def _mk_metric(source="fred", category="macro", status="ok", duration_ms=120.0, records_count=1):
    if status == "ok":
        return InvocationMetric.new_ok(
            source=source, category=category,
            duration_ms=duration_ms, records_count=records_count,
        )
    return InvocationMetric.new_error(
        source=source, category=category,
        duration_ms=duration_ms, exc=RuntimeError("boom"),
    )


def test_write_metric_and_summary(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    sink.write_metric(_mk_metric("fred", "macro", "ok", 100.0, 3))
    sink.write_metric(_mk_metric("fred", "macro", "ok", 200.0, 5))
    sink.write_metric(_mk_metric("ccxt", "chain", "error", 50.0))
    summary = sink.summary()
    assert ("fred", "macro") in summary
    fm = summary[("fred", "macro")]
    assert fm["total"] == 2
    assert fm["ok_count"] == 2
    assert fm["error_count"] == 0
    assert fm["total_records"] == 8
    assert 100.0 <= fm["avg_duration_ms"] <= 200.0
    cm = summary[("ccxt", "chain")]
    assert cm["error_count"] == 1


def test_write_quality_and_recent_issues(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    sink.write_quality(_mk_metric("fred", "macro"), [
        QualityIssue(code=QualityIssueCode.EMPTY_RESULT, message="空列表", source="fred", category="macro"),
    ])
    sink.write_quality(_mk_metric("ccxt", "chain"), [
        QualityIssue(code=QualityIssueCode.DUPLICATE_DETECTED, message="dup key=x", source="ccxt", category="chain"),
    ])
    issues = sink.recent_issues(limit=10)
    assert len(issues) == 2
    assert issues[0]["code"] in ("EMPTY_RESULT", "DUPLICATE_DETECTED")


def test_write_alert_and_recent_alerts(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    sink.write_alert(Alert(level=AlertLevel.ERROR, title="FRED 不可达", message="timeout", tags=["fred"]))
    sink.write_alert(Alert(level=AlertLevel.WARNING, title="CCXT 限频", message="429", tags=["ccxt"]))
    alerts = sink.recent_alerts(limit=10)
    assert len(alerts) == 2
    assert alerts[0]["level"] in ("ERROR", "WARNING")


# ── 扩展：records 按源/时间窗口查询 ────────────────────────────────────────────


def test_query_records_by_source(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    sink.write([_rec("FEDFUNDS", "2026-08-01", 5.25)])
    sink.write([_rec("CPI", "2026-07-01", 3.0)])
    rows = sink.query_records(source="fred", limit=10)
    assert len(rows) == 2
    subs = {r.sub_category for r in rows}
    assert subs == {"FEDFUNDS", "CPI"}


def test_query_records_window_sec(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    # 一条新数据（now）+ 一条旧数据（2 小时前）
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sink.write([DataRecord(
        source="fred", category="macro", sub_category="LIVE",
        timestamp=now_iso, metrics={"value": 1}, events=[], timeseries=[], raw={},
    )])
    sink.write([DataRecord(
        source="fred", category="macro", sub_category="OLD",
        timestamp=old_iso, metrics={"value": 2}, events=[], timeseries=[], raw={},
    )])
    # 1 小时窗口只能看到 LIVE
    recent = sink.query_records(source="fred", window_sec=3600)
    assert len(recent) == 1
    assert recent[0].sub_category == "LIVE"


def test_latest_records_by_source(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    for i in range(5):
        sink.write([_rec(f"SERIES_{i}", f"2026-08-0{i+1}", float(i))])
    latest = sink.latest_records(source="fred", limit=3)
    assert len(latest) == 3


def test_source_health(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    # fred 最近成功
    sink.write_metric(_mk_metric("fred", "macro", "ok", 100.0, 3))
    # ccxt 最近失败
    sink.write_metric(_mk_metric("ccxt", "chain", "error", 50.0))
    health = sink.source_health()
    assert "fred" in health
    assert health["fred"]["last_status"] == "ok"
    assert health["fred"]["last_records"] == 3
    assert "ccxt" in health
    assert health["ccxt"]["last_status"] == "error"


def test_quality_check_integration(tmp_path):
    """集成测试：完整链路 采集→落库→质量检查→issue 落库。"""
    sink = SqliteSink(str(tmp_path / "t.db"))
    checker = QualityChecker(freshness_threshold=timedelta(hours=1))
    # 一条过时记录（2 小时前）→ 触发 FRESHNESS issue
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    records = [DataRecord(
        source="fred", category="macro", sub_category="OLD",
        timestamp=old_iso, metrics={"value": 1}, events=[], timeseries=[], raw={},
    )]
    metric = _mk_metric("fred", "macro", "ok", 100.0, 1)
    sink.write(records)
    sink.write_metric(metric)
    issues = checker.check_all(records, source="fred", category="macro")
    sink.write_quality(metric, issues)
    saved = sink.recent_issues(limit=10)
    assert len(saved) >= 1
    assert any(i["code"] == "TIMESTAMP_FRESHNESS" for i in saved)
