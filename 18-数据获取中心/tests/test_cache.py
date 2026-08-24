"""去重缓存测试 — 对齐 TECHNICAL_DESIGN.md §3.3。

dedupe_key = sha256(source|category|sub_category|stable_id)；
同 key 去重，不同 sub_category/date 保留。
"""
from data_center.core.contract import DataRecord
from data_center.storage.cache import dedupe, dedupe_key


def _rec(sub, date):
    return DataRecord(
        source="fred", category="macro", sub_category=sub,
        timestamp="2026-08-24T08:00:00+08:00",
        metrics={"value": 1.0, "date": date}, events=[], timeseries=[], raw={},
    )


def test_same_key_dedupes():
    a = _rec("FEDFUNDS", "2026-08-01")
    b = _rec("FEDFUNDS", "2026-08-01")
    assert dedupe_key(a) == dedupe_key(b)
    assert len(dedupe([a, b])) == 1


def test_different_sub_category_kept():
    a = _rec("FEDFUNDS", "2026-08-01")
    b = _rec("RRPONTSYD", "2026-08-01")
    assert dedupe_key(a) != dedupe_key(b)
    assert len(dedupe([a, b])) == 2


def test_different_date_kept():
    a = _rec("FEDFUNDS", "2026-08-01")
    b = _rec("FEDFUNDS", "2026-07-01")
    assert dedupe_key(a) != dedupe_key(b)
    assert len(dedupe([a, b])) == 2
