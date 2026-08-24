"""BaseCollector 抽象 — 对齐 TECHNICAL_DESIGN.md §5.2。

SDK 轨所有 collector 继承此类，设置 source/category 并实现 fetch() -> list[DataRecord]。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data_center.core.contract import DataRecord


class BaseCollector(ABC):
    """采集器抽象基类。"""

    source: str = ""
    category: str = ""

    def __init__(self, config: dict | None = None):
        self.config: dict[str, Any] = config or {}

    @abstractmethod
    def fetch(self, params: dict) -> list[DataRecord]:
        """按 params 采集，返回 DataRecord 列表。"""

    def is_available(self) -> bool:
        """源是否就绪（API Key/依赖检查）。默认 True，子类按需覆写。"""
        return True
