"""采集器注册表 — (category, source) -> BaseCollector 工厂。

注册式架构：新增数据源 = 注册一个 collector，不动 dispatcher。
"""
from __future__ import annotations

from data_center.collectors._base import BaseCollector
from data_center.core.errors import SourceUnavailableError


class Registry:
    """(category, source) -> collector 类 的注册表。"""

    def __init__(self):
        self._map: dict[tuple[str, str], type[BaseCollector]] = {}

    def register(self, category: str, source: str, cls: type[BaseCollector]) -> None:
        self._map[(category, source)] = cls

    def get(self, category: str, source: str) -> type[BaseCollector]:
        cls = self._map.get((category, source))
        if cls is None:
            raise SourceUnavailableError(f"未注册的源: {category}/{source}")
        return cls

    def list(self) -> list[tuple[str, str]]:
        return list(self._map.keys())


# 全局默认注册表，DataCenter 不传 registry 时使用
default_registry = Registry()
