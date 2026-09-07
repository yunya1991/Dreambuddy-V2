# -*- coding: utf-8 -*-
"""开发流程集成：对话调研检测 → 归档 → ingest 增量索引。

对外暴露检测器、归档器与工作流编排的主要函数。
"""

from .detector import detect_research
from .archiver import archive_research
from .workflow import check_and_prompt, archive_from_conversation, batch_detect

__all__ = [
    "detect_research",
    "archive_research",
    "check_and_prompt",
    "archive_from_conversation",
    "batch_detect",
]
