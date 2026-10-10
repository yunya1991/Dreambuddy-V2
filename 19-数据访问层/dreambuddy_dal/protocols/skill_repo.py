"""
dreambuddy_dal.protocols.skill_repo — SKILL 系统只读 Repository Protocol

对齐 DATA_AND_COGNITIVE_READONLY_ACCESS_SPEC §5.2
只读方法：list_skills / search_skills / get_skill
写入（register/update）走 skill-creator 工作流，不在此 Protocol 暴露。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class SkillRepository(ABC):
    """
    SKILL 只读仓储。
    读=前端/LLM 直接调用（list/search/get）；
    写=skill-creator SKILL → auto_sync_dispatcher.py。
    """

    @abstractmethod
    def list_skills(self, category: Optional[str] = None) -> List[dict]:
        """列出所有 SKILL，可按分类过滤。

        Returns:
            SKILL 列表，每项含 name/description/version/status/category/triggers
        """
        ...

    @abstractmethod
    def search_skills(self, query: str, top_k: int = 5) -> List[dict]:
        """按关键词搜索 SKILL。

        Args:
            query: 搜索文本
            top_k: 返回上限

        Returns:
            匹配的 SKILL 列表，含 score
        """
        ...

    @abstractmethod
    def get_skill(self, skill_id: str) -> dict:
        """获取单个 SKILL 详情。

        Args:
            skill_id: SKILL 名称或 ID

        Returns:
            SKILL 详情字典
        """
        ...
