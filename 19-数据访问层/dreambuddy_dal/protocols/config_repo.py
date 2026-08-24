"""
dreambuddy_dal.protocols.config_repo — ConfigRepository Protocol（配置域）
对齐 SCHEMA_DESIGN.md §7 cv_config_versions（全局单版本激活 + 时间线版本管理）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional


class ConfigRepository(ABC):
    """
    全系统统一配置版本管理。
    设计原则：所有策略 / 风控 / 阈值配置的变更，必须先创建"新版本"再 activate；
    activate 操作由 DB 触发器保证：全局同一时刻只有 1 条 is_active=1。
    """

    @abstractmethod
    def get_active_version(self, config_name: str = "global") -> Optional[Dict]:
        """
        取当前激活版本配置值字典（JSON 解析后）。
        - 若无激活版本返回 None（调用方用默认值启动）
        """
        ...

    @abstractmethod
    def activate_version(
        self,
        config_name: str,
        version: int,
        *,
        activated_by: str = "system",
        activated_at: Optional[datetime] = None,
    ) -> bool:
        """
        将某版本切为激活（自动取消旧激活）。
        - version 必须存在（否则返回 False）
        - activated_at=None → 用当前 UTC 时间
        """
        ...

    @abstractmethod
    def get_specific_version(
        self, config_name: str, version: int
    ) -> Optional[Dict]:
        """查指定历史版本（用于复盘 / 回滚前比对）"""
        ...

    @abstractmethod
    def create_version(
        self,
        config_name: str,
        config_data: Dict,
        *,
        created_by: str = "system",
        description: Optional[str] = None,
    ) -> int:
        """
        创建新配置版本（不自动激活）。
        :return: 新版本号（单调递增整数）
        """
        ...
