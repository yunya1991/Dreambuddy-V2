"""Evidence 数据结构 — 借鉴 morluto/rea 的 Evidence-First 设计。

每条结论必须携带：来源(provenance)、置信度(confidence)、已知局限(known_gaps)。
区分 4 层事实：observations → derivations → inferences → unknowns。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceLevel(str, Enum):
    """事实分级：从直接观察到未知。"""

    OBSERVATION = "observation"  # 直接观察到的事实（代码/数据）
    DERIVATION = "derivation"    # 从观察推导的结论
    INFERENCE = "inference"      # 基于推导的推断
    UNKNOWN = "unknown"          # 已知的未知（无法确定）


@dataclass
class Evidence:
    """逆向分析的证据单元。

    Attributes:
        evidence_id: 唯一标识，格式 ev_<64 hex>
        result: 规范化结果
        level: 事实分级
        provenance: 来源描述（文件路径、行号、引擎、数据来源）
        confidence: 置信度 0.0-1.0
        known_gaps: 已知局限列表
        observations: 支撑该结论的原始观察
        created_at: 创建时间戳(ms)
    """

    result: Any
    level: EvidenceLevel = EvidenceLevel.OBSERVATION
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    known_gaps: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence_id: str = field(default_factory=lambda: f"ev_{uuid.uuid4().hex}")
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, Any]:
        level_val = self.level.value if isinstance(self.level, EvidenceLevel) else str(self.level)
        return {
            "evidence_id": self.evidence_id,
            "result": self.result,
            "level": level_val,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "known_gaps": self.known_gaps,
            "observations": self.observations,
            "created_at": self.created_at,
        }


def reverse_evidence(
    result: Any,
    level: EvidenceLevel = EvidenceLevel.OBSERVATION,
    provenance: dict[str, Any] | None = None,
    confidence: float = 1.0,
    known_gaps: list[str] | None = None,
    observations: list[dict[str, Any]] | None = None,
) -> Evidence:
    """构造 Evidence 的工厂函数。"""
    return Evidence(
        result=result,
        level=level,
        provenance=provenance or {},
        confidence=confidence,
        known_gaps=known_gaps or [],
        observations=observations or [],
    )
