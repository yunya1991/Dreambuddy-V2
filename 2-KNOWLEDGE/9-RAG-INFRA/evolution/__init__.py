# -*- coding: utf-8 -*-
"""持续进化层（阶段3）：文档采集、自动标注、反馈机制。

形成"采集 → 标注 → 索引 → 检索 → 反馈 → 优化"的持续进化闭环。
"""

from .ingest import ingest_document
from .annotate import annotate_chunk
from .feedback import record_feedback

__all__ = [
    "ingest_document",
    "annotate_chunk",
    "record_feedback",
]
