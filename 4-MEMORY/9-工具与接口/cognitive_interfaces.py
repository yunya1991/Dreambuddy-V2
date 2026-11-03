"""认知系统三层边界 ABC 接口契约

SPEC: SPEC-CognitiveSystem-Evolution.md §3.5 M6

定义认知系统层间正式契约，为渐进式对齐提供接口边界：
  - CognitiveRouter  (L3 路由层 — Intent-Engine → 三库加权召回)
  - EvidenceSink     (L2 Evidence Ledger — 集中化决策审计 trail)
  - MetacogMonitor   (L4 元认知层 — 自我监控+错误检测，研究探索项)

设计原则：
  - 只定义接口契约，不修改已有实现类
  - 不强制已有类继承 ABC（渐进式，先定义后对齐）
  - EvidenceLedger 可作为 EvidenceSink 的实现，暂不强制继承
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

# ============================================================
# 结果类型 dataclass
# ============================================================


@dataclass
class RecallResult:
    """路由层召回结果 — 三库加权召回的统一输出。

    Attributes:
        memories: 记忆库召回结果（list of dict，每条含 id/score/content 等）
        skills: SKILL 库召回结果
        knowledge: 知识库召回结果
        confidence: 综合置信度 0.0-1.0
    """

    memories: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    knowledge: list[dict] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)  # B3（41 SPEC §13.2）：41 文档通道召回结果
    confidence: float = 0.0


@dataclass
class MonitorResult:
    """元认知监控结果 — 自我监控+错误检测输出。

    Attributes:
        action: 监控行动 ("proceed" | "verify")
        targets: 需要验证的目标 ID 列表
        calibration: 校准系数 0.0-1.0（默认 1.0 = 无校准）
    """

    action: str = "proceed"
    targets: list[str] = field(default_factory=list)
    calibration: float = 1.0


# ============================================================
# TB2 Beta 分布 verify（SPEC-L0-AGENT-TRAIN-BASE v0.1 §2）
# ============================================================


@dataclass
class BetaState:
    """Beta(α, β) 置信度分布 — 支持部分成功/部分失败。

    alpha: 成功伪计数；beta: 失败伪计数。
    """

    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        total = self.alpha + self.beta
        if total <= 0.0:
            return 0.5
        return self.alpha / total

    def update(self, success_rate: float, weight: float = 1.0) -> "BetaState":
        """按成功率更新分布（success_rate ∈ [0,1]）。"""
        rate = min(1.0, max(0.0, float(success_rate)))
        return BetaState(
            alpha=self.alpha + rate * weight,
            beta=self.beta + (1.0 - rate) * weight,
        )


@dataclass
class VerifyResult:
    """verify 结果（信封 schema 零变化，业务体放 data）。"""

    ok: bool = True
    data: dict = field(default_factory=dict)


def verify_beta(
    memory_id: str,
    success_rate: float,
    evidence_confidence: float = 0.5,
    drift_detected: bool = False,
    beta_state: Optional["BetaState"] = None,
) -> VerifyResult:
    """Beta 分布更新（TB2 核心）。

    Args:
        success_rate: [0,1] 部分成功率
        evidence_confidence: PoE 证据链置信度，修正 success_rate
        drift_detected: TB1 漂移检测结果 → True 时重置先验（Bayesian reset）
        beta_state: 已有后验（None 表示无信息先验 Beta(1,1)）
    """
    if drift_detected or beta_state is None:
        state = BetaState(1.0, 1.0)
    else:
        state = beta_state

    adjusted_rate = min(1.0, max(0.0, float(success_rate))) * min(
        1.0, max(0.0, float(evidence_confidence))
    )
    new_state = state.update(adjusted_rate)

    return VerifyResult(
        ok=True,
        data={
            "memory_id": memory_id,
            "confidence": new_state.mean,
            "beta_alpha": new_state.alpha,
            "beta_beta": new_state.beta,
            "drift_detected": drift_detected,
            "data_schema_version": "0.2-beta",
        },
    )


# ============================================================
# L3 路由层接口
# ============================================================


class CognitiveRouter(ABC):
    """L3 路由层接口 — Intent-Engine → 三库加权召回。

    职责：接收 intent_vector，路由到记忆/SKILL/知识三库，
    按权重聚合召回结果，输出统一 RecallResult。

    实现方：加权聚合层 (weighted_aggregation.py) 可对齐此契约。
    """

    @abstractmethod
    def route(self, intent_vector: Any, databases: dict) -> RecallResult:
        """路由 intent_vector 到三库，返回加权召回结果。

        Args:
            intent_vector: 意图向量（由 Intent-Engine 产出）
            databases: 三库句柄 dict（memories/skills/knowledge）

        Returns:
            RecallResult 含三库召回结果 + 综合置信度
        """
        ...


# ============================================================
# L2 Evidence Ledger 接口
# ============================================================


class EvidenceSink(ABC):
    """L2 Evidence Ledger 接口 — 集中化决策审计 trail。

    职责：接收 EvidenceEntry，计算 receipt_hash 并持久化，
    提供不可篡改的决策审计 trail。

    实现方：EvidenceLedger (evidence_ledger.py) 已具备 append() 语义，
    可作为本接口的实现，暂不强制继承（渐进式对齐）。
    """

    @abstractmethod
    def append(self, entry: Any) -> str:
        """追加条目到 Ledger，返回 receipt_hash。

        Args:
            entry: EvidenceEntry 或等价审计条目

        Returns:
            receipt_hash（条目哈希），失败返回空字符串（FAIL-OPEN）
        """
        ...


# ============================================================
# L4 元认知层接口（研究探索项）
# ============================================================


class MetacogMonitor(ABC):
    """L4 元认知层接口（研究探索项）— 自我监控+错误检测。

    职责：监控工作区状态，检测错误模式，
    决定是否触发 verify 校准或直接 proceed。

    状态：研究探索项，M1 降级为非阻塞，具体实现待 L4 落地。
    """

    @abstractmethod
    def monitor(self, workspace_state: dict) -> MonitorResult:
        """监控工作区状态，返回监控行动建议。

        Args:
            workspace_state: 工作区状态 dict（含活跃记忆/技能/上下文等）

        Returns:
            MonitorResult 含 action ("proceed"|"verify") + targets + calibration
        """
        ...
