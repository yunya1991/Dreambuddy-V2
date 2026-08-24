"""Crawler adapters 测试 — 提取字段 dict → DataRecord(category=web)。

adapter 把 Spider/Playwright 提取的字段 dict 转成统一 DataRecord 契约。
"""
from data_center.crawler.adapters import adapt_item, adapt_items
from data_center.core.contract import DataRecord


def test_adapt_single_item():
    """单条提取结果 → DataRecord。"""
    fields = {"title": "央行降息", "link": "http://pbc.gov.cn/1", "date": "2024-08-24"}
    site = {"source": "pbc", "sub_category": "announcement"}
    rec = adapt_item(fields, site)
    assert isinstance(rec, DataRecord)
    assert rec.source == "pbc"
    assert rec.category == "web"
    assert rec.sub_category == "announcement"
    assert rec.metrics["title"] == "央行降息"
    assert rec.metrics["link"] == "http://pbc.gov.cn/1"
    assert rec.raw["date"] == "2024-08-24"


def test_adapt_metrics_flat_only():
    """metrics 仅含 string/number，嵌套对象放 raw。"""
    fields = {"title": "news", "count": 5, "nested": {"a": 1}}
    site = {"source": "reuters", "sub_category": "article"}
    rec = adapt_item(fields, site)
    assert rec.metrics["title"] == "news"
    assert rec.metrics["count"] == 5
    # nested dict 不进 metrics
    assert "nested" not in rec.metrics
    # 但保留在 raw
    assert rec.raw["nested"] == {"a": 1}


def test_adapt_items_multiple():
    """多条提取结果 → list[DataRecord]。"""
    items = [
        {"title": "t1", "link": "l1"},
        {"title": "t2", "link": "l2"},
    ]
    site = {"source": "coindesk", "sub_category": "news"}
    recs = adapt_items(items, site)
    assert len(recs) == 2
    assert recs[0].metrics["title"] == "t1"
    assert recs[1].metrics["title"] == "t2"


def test_adapt_empty_list():
    assert adapt_items([], {"source": "x", "sub_category": "y"}) == []


def test_adapt_missing_site_fields_defaults():
    """site 缺少 source/sub_category 时有合理默认。"""
    rec = adapt_item({"title": "t"}, {})
    assert rec.source == "crawler"
    assert rec.sub_category == "page"


def test_adapt_summary_goes_to_events():
    """summary/content 字段放入 events 而非 metrics。"""
    fields = {"title": "t", "summary": "long text here"}
    rec = adapt_item(fields, {"source": "s", "sub_category": "sc"})
    assert rec.events[0]["summary"] == "long text here"
    assert "summary" not in rec.metrics


def test_adapt_validates_record():
    """产出 DataRecord 经过契约校验，不合法则抛异常。"""
    import pytest
    from data_center.core.errors import ContractError
    with pytest.raises(ContractError):
        # source 为空会触发 ContractError
        adapt_item({"title": "t"}, {"source": "", "sub_category": "x"})
