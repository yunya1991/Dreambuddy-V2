"""FeatureHub 异常体系"""
from __future__ import annotations


class FeatureError(Exception):
    """FeatureHub 基础异常"""


class FeatureSetNotFound(FeatureError):
    """启用集合不存在"""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"FeatureSet '{name}' not found in ENABLED_SETS")
