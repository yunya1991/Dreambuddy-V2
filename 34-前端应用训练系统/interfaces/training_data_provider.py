"""训练数据提供者协议。

定义训练系统从各数据源获取训练数据的统一接口。
各数据源（Trae记忆、认知系统、SKILL、文档、33-REA）实现此协议。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class TrainingCase:
    """训练案例数据结构（对齐SPL TDR SolutionCase）。"""

    def __init__(
        self,
        intent: str,
        actions: List[str],
        outcome_text: str,
        learned: List[str],
        layer_tags: Optional[List[str]] = None,
        quality: str = "B",
        confidence: float = 0.4,
        source: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.intent = intent
        self.actions = actions
        self.outcome_text = outcome_text
        self.learned = learned
        self.layer_tags = layer_tags or []
        self.quality = quality
        self.confidence = confidence
        self.source = source
        self.metadata = metadata or {}


class TrainingDataProvider(ABC):
    """训练数据提供者协议。

    所有数据源（Trae记忆、认知系统、SKILL索引、文档知识库、33-REA）
    必须实现此协议，主动训练采集器通过此协议批量获取数据。
    """

    @abstractmethod
    def get_source_name(self) -> str:
        """返回数据源名称（如 'trae_memory', 'cognitive', 'skill', 'doc', 'rea'）。"""
        ...

    @abstractmethod
    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        """批量获取训练案例。

        Args:
            limit: 最大返回案例数
            since: 增量采集时间戳（可选），只返回此时间之后的新数据

        Returns:
            训练案例列表
        """
        ...

    @abstractmethod
    def get_quality_threshold(self) -> str:
        """返回该数据源的质量门槛（如 'B' 表示只接受B级以上）。"""
        ...
