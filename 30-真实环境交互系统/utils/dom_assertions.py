"""DOM 断言工具 — 便捷的 DOM 状态断言方法"""
from __future__ import annotations

from typing import Any, Optional

from playwright.sync_api import Page, Locator


class DOMAssertions:
    """DOM 断言工具集 — 提供常用的 DOM 状态断言方法"""

    @staticmethod
    def element_exists(page: Page, selector: str) -> bool:
        """检查元素是否存在。"""
        return page.locator(selector).count() > 0

    @staticmethod
    def element_visible(page: Page, selector: str) -> bool:
        """检查元素是否可见。"""
        locator = page.locator(selector)
        return locator.count() > 0 and locator.first.is_visible()

    @staticmethod
    def text_contains(page: Page, selector: str, text: str) -> bool:
        """检查元素文本是否包含指定内容。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return text in locator.first.inner_text()

    @staticmethod
    def text_equals(page: Page, selector: str, text: str) -> bool:
        """检查元素文本是否完全匹配。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.inner_text().strip() == text.strip()

    @staticmethod
    def attribute_equals(page: Page, selector: str,
                         attr: str, value: str) -> bool:
        """检查元素属性是否等于指定值。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.get_attribute(attr) == value

    @staticmethod
    def count_equals(page: Page, selector: str, count: int) -> bool:
        """检查匹配元素数量是否等于指定值。"""
        return page.locator(selector).count() == count

    @staticmethod
    def count_greater_than(page: Page, selector: str, count: int) -> bool:
        """检查匹配元素数量是否大于指定值。"""
        return page.locator(selector).count() > count

    @staticmethod
    def has_class(page: Page, selector: str, class_name: str) -> bool:
        """检查元素是否包含指定 CSS 类。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        classes = locator.first.get_attribute("class") or ""
        return class_name in classes.split()

    @staticmethod
    def is_enabled(page: Page, selector: str) -> bool:
        """检查元素是否启用。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.is_enabled()

    @staticmethod
    def is_checked(page: Page, selector: str) -> bool:
        """检查复选框/单选框是否选中。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.is_checked()

    @staticmethod
    def value_equals(page: Page, selector: str, value: str) -> bool:
        """检查输入框值是否等于指定值。"""
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        return locator.first.input_value() == value

    @staticmethod
    def url_contains(page: Page, text: str) -> bool:
        """检查当前 URL 是否包含指定文本。"""
        return text in page.url

    @staticmethod
    def title_contains(page: Page, text: str) -> bool:
        """检查页面标题是否包含指定文本。"""
        return text in page.title()
