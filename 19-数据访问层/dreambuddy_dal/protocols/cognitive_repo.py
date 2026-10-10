"""
dreambuddy_dal.protocols.cognitive_repo — 认知系统只读 Repository Protocol

对齐 DATA_AND_COGNITIVE_READONLY_ACCESS_SPEC §5.2
只读方法：recall / stats / health
写入（record/verify）走后端工作流，不在此 Protocol 暴露。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class CognitiveRepository(ABC):
    """
    认知记忆只读仓储。
    读=前端/LLM 直接调用（recall/stats/health）；
    写=后端工作流（cognitive_mcp_server.py record/verify）。
    """

    @abstractmethod
    def recall(
        self,
        context: str,
        top_k: int = 5,
        min_quality: str = "C",
    ) -> List[dict]:
        """检索相关历史经验记忆。

        Args:
            context: 任务描述或关键词
            top_k: 返回上限
            min_quality: 最低质量等级 S/A/B/C/D

        Returns:
            记忆列表，每项含 id/content/score/quality_level/tags
        """
        ...

    @abstractmethod
    def stats(self) -> dict:
        """返回认知系统统计信息（记忆总数/质量分布等）。"""
        ...

    @abstractmethod
    def health(self) -> dict:
        """返回认知系统健康状态。"""
        ...
