"""33-REA逆向解析工程 - 核心分析模块。

提供 Evidence 数据结构、分析器基类、Python/TS 分析器、依赖图、调用链追踪、git 历史溯源。
"""

from .analyzer_base import AnalyzerBase, AnalyzeResult
from .evidence import Evidence, EvidenceLevel, reverse_evidence

__all__ = [
    "Evidence",
    "EvidenceLevel",
    "reverse_evidence",
    "AnalyzerBase",
    "AnalyzeResult",
]
