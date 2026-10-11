"""案例评估器协议。

定义训练系统评估案例学习价值的统一接口。
CaseIngestGate通过适配器实现此协议。
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from enum import Enum


class IngestDecision(str, Enum):
    """案例入库决策。"""
    INGEST = "ingest"        # 入库（主动训练或被动辅导）
    DEFERRED = "deferred"    # 暂缓（加入待训练队列）
    SKIP = "skip"            # 跳过（学习价值不足）


class CaseEvaluation:
    """案例评估结果。"""

    def __init__(
        self,
        decision: IngestDecision,
        novelty: float = 0.0,
        significance: float = 0.0,
        anomaly: float = 0.0,
        reproducibility: float = 0.0,
        reason: str = "",
    ):
        self.decision = decision
        self.novelty = novelty
        self.significance = significance
        self.anomaly = anomaly
        self.reproducibility = reproducibility
        self.reason = reason


class CaseEvaluator(ABC):
    """案例评估器协议。

    CaseIngestGate通过适配器实现此协议。
    被动训练触发器通过此协议评估收尾案例的学习价值。
    """

    @abstractmethod
    def evaluate(self, case: Dict[str, Any]) -> CaseEvaluation:
        """评估案例的学习价值。

        Args:
            case: 案例数据（含intent/actions/outcome/learned/验收证据等）

        Returns:
            评估结果（决策+四维评分+原因）
        """
        ...
