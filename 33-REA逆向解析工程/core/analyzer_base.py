"""分析器基类 — 所有语言/格式分析器的统一接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .evidence import Evidence


@dataclass
class AnalyzeResult:
    """分析结果容器。

    Attributes:
        target: 分析目标路径或标识
        summary: 人类可读的摘要
        evidence: 证据列表（每条结论带 provenance + confidence + known_gaps）
        raw: 原始结构化数据（依赖图、调用链等）
    """

    target: str
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
            "raw": self.raw,
        }


class AnalyzerBase(ABC):
    """分析器抽象基类。"""

    @abstractmethod
    def analyze(self, target: str, **kwargs: Any) -> AnalyzeResult:
        """分析目标，返回带 Evidence 的结果。"""

    @abstractmethod
    def supported_targets(self) -> list[str]:
        """返回支持的目标类型（如 ['python', 'typescript']）。"""
