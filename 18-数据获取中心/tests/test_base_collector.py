"""BaseCollector 抽象测试 — 对齐 TECHNICAL_DESIGN.md §5.2。

SDK 轨所有 collector 继承 BaseCollector，实现 fetch() -> list[DataRecord]。
"""
import pytest

from data_center.collectors._base import BaseCollector


def test_subclass_without_fetch_cannot_instantiate():
    class Bad(BaseCollector):
        source = "x"
        category = "macro"

    with pytest.raises(TypeError):
        Bad()  # 抽象方法未实现


def test_subclass_with_fetch_works():
    class Good(BaseCollector):
        source = "fred"
        category = "macro"

        def fetch(self, params):
            return []

    c = Good()
    assert c.source == "fred"
    assert c.category == "macro"
    assert c.is_available() is True
    assert c.fetch({}) == []


def test_is_available_default_true():
    class C(BaseCollector):
        def fetch(self, params):
            return []

    assert C().is_available() is True
