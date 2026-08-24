"""M5-T2 Red — QualityChecker 数据质量测试。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_center.core.contract import DataRecord


def _new_record(
    *,
    source="fred",
    category="macro",
    sub_category="FEDFUNDS",
    metrics=None,
    ts=None,
) -> DataRecord:
    # macro 默认 stable_id = sub_category:date，控制 date 即可控制重复
    if metrics is None:
        metrics = {"value": 5.25, "date": "2026-08-24"}
    return DataRecord(
        source=source,
        category=category,
        sub_category=sub_category,
        timestamp=ts or datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        events=[],
        timeseries=[],
        raw={},
    )


# ---------------------------------------------------------------------------
# 1. EMPTY_RESULT
# ---------------------------------------------------------------------------
def test_empty_records_triggers_empty_result():
    """空列表且非 degraded → EMPTY_RESULT。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    issues = QualityChecker().check_all([], source="fred", category="macro", is_degraded=False)
    codes = [i.code for i in issues]
    assert QualityIssueCode.EMPTY_RESULT in codes


def test_empty_records_degraded_not_trigger():
    """空列表 + is_degraded=True → 不触发 EMPTY_RESULT。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    issues = QualityChecker().check_all([], source="fred", category="macro", is_degraded=True)
    codes = [i.code for i in issues]
    assert QualityIssueCode.EMPTY_RESULT not in codes


def test_empty_records_with_allowlist_not_trigger():
    """空列表 + source 在 allowlist → 不触发 EMPTY_RESULT。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    qc = QualityChecker(allow_empty_degraded_sources=["glassnode"])
    issues = qc.check_all([], source="glassnode", category="chain", is_degraded=False)
    codes = [i.code for i in issues]
    assert QualityIssueCode.EMPTY_RESULT not in codes


# ---------------------------------------------------------------------------
# 2. CONTRACT_INVALID
# ---------------------------------------------------------------------------
def test_invalid_metrics_type_triggers_contract_invalid():
    """metrics 含嵌套 dict/list → CONTRACT_INVALID。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    bad = _new_record(source="tavily", category="news",
                      sub_category="rss", metrics={"a": "ok"})
    bad.metrics = {"nested": {"a": 1}}

    issues = QualityChecker().check_all([bad], source="tavily", category="news")
    codes = [i.code for i in issues]
    assert QualityIssueCode.CONTRACT_INVALID in codes


def test_valid_records_no_contract_issue():
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    issues = QualityChecker().check_all(
        [_new_record()], source="fred", category="macro"
    )
    codes = [i.code for i in issues]
    assert QualityIssueCode.CONTRACT_INVALID not in codes


# ---------------------------------------------------------------------------
# 3. DUPLICATE_DETECTED
# ---------------------------------------------------------------------------
def test_same_dedupe_key_triggers_duplicate():
    """相同 dedupe_key（同 source/category/sub_category + metrics.date 一致）→ 重复。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    common_metrics = {"value": 5.25, "date": "2026-08-24"}
    r1 = _new_record(
        source="fred", category="macro", sub_category="FEDFUNDS", metrics=common_metrics
    )
    r2 = _new_record(
        source="fred", category="macro", sub_category="FEDFUNDS", metrics=common_metrics
    )
    issues = QualityChecker().check_all([r1, r2], source="fred", category="macro")
    codes = [i.code for i in issues]
    assert QualityIssueCode.DUPLICATE_DETECTED in codes


def test_different_keys_no_duplicate():
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    r1 = _new_record(
        source="fred", category="macro", sub_category="FEDFUNDS",
        metrics={"value": 5.25, "date": "2026-08-23"},
    )
    r2 = _new_record(
        source="fred", category="macro", sub_category="FEDFUNDS",
        metrics={"value": 5.25, "date": "2026-08-24"},
    )
    issues = QualityChecker().check_all([r1, r2], source="fred", category="macro")
    codes = [i.code for i in issues]
    assert QualityIssueCode.DUPLICATE_DETECTED not in codes


# ---------------------------------------------------------------------------
# 4. TIMESTAMP_FRESHNESS
# ---------------------------------------------------------------------------
def test_old_timestamp_triggers_freshness():
    """最老记录超过 freshness_threshold → FRESHNESS issue。"""
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    old_ts = datetime.now(timezone.utc) - timedelta(days=5)
    r = _new_record(source="fred", category="macro", ts=old_ts.isoformat())
    qc = QualityChecker(freshness_threshold=timedelta(hours=48))
    issues = qc.check_all([r], source="fred", category="macro")
    codes = [i.code for i in issues]
    assert QualityIssueCode.TIMESTAMP_FRESHNESS in codes


def test_fresh_timestamp_no_freshness_issue():
    from data_center.monitoring.quality import QualityChecker, QualityIssueCode

    now = datetime.now(timezone.utc).isoformat()
    r = _new_record(source="fred", category="macro", ts=now)
    qc = QualityChecker(freshness_threshold=timedelta(hours=48))
    issues = qc.check_all([r], source="fred", category="macro")
    codes = [i.code for i in issues]
    assert QualityIssueCode.TIMESTAMP_FRESHNESS not in codes


# ---------------------------------------------------------------------------
# 5. check_all 聚合：空列表产生多条 issue 场景
# ---------------------------------------------------------------------------
def test_check_all_returns_list_of_quality_issues():
    from data_center.monitoring.quality import QualityChecker, QualityIssue

    issues = QualityChecker().check_all([], source="s", category="c")
    assert isinstance(issues, list)
    if issues:
        for i in issues:
            assert isinstance(i, QualityIssue)
