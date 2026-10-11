"""33-REA解析器协议。

定义训练系统调用33-REA逆向解析的统一接口。
33-REA的S33节点通过适配器实现此协议。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class REAParseResult:
    """33-REA解析结果。"""

    def __init__(
        self,
        algorithm_patterns: Optional[List[str]] = None,
        call_chain: Optional[List[str]] = None,
        dependency_graph: Optional[Dict[str, Any]] = None,
        known_gaps: Optional[List[str]] = None,
        observations: Optional[List[str]] = None,
        evidence_level: str = "L3",
        confidence: float = 0.5,
        raw_evidence: Optional[Dict[str, Any]] = None,
    ):
        self.algorithm_patterns = algorithm_patterns or []
        self.call_chain = call_chain or []
        self.dependency_graph = dependency_graph or {}
        self.known_gaps = known_gaps or []
        self.observations = observations or []
        self.evidence_level = evidence_level
        self.confidence = confidence
        self.raw_evidence = raw_evidence or {}


class REAParser(ABC):
    """33-REA解析器协议。

    33-REA的S33_rea_analyze + S33_rea_trace通过适配器实现此协议。
    被动训练触发器通过此协议解析本次工程代码作为教学材料。
    """

    @abstractmethod
    def analyze(self, target_path: str, scope: str = "architecture") -> REAParseResult:
        """分析目标工程的架构和依赖。

        Args:
            target_path: 工程路径
            scope: 分析范围 (architecture/modules/dependencies/full)

        Returns:
            解析结果（含依赖图等）
        """
        ...

    @abstractmethod
    def trace(self, target_path: str, feature: str, entry: Optional[str] = None) -> REAParseResult:
        """追踪目标工程的功能调用链和算法模式。

        Args:
            target_path: 工程路径
            feature: 要追踪的功能描述
            entry: 可选入口函数/类名

        Returns:
            解析结果（含调用链、算法模式等）
        """
        ...
