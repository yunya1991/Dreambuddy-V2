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
from typing import Any


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
