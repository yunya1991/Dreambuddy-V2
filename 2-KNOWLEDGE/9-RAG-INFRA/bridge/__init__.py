# -*- coding: utf-8 -*-
"""RAG ↔ 4-MEMORY 桥接层。

将 RAG 检索结果 record 为 C 级记忆，verify 验证后反哺知识库权重，
形成「检索 → 记忆 → 验证 → 权重进化」闭环。

公共接口：
- record_retrieval_as_memory：RAG 检索结果 → C 级记忆 + 映射表
- verify_and_feedback：verify 记忆 → 更新知识单元 boost 因子
- apply_boost_to_results：将 boost 因子叠加到检索结果 final_score
- get_boost / update_boost：boost 因子直接读写
"""

from .memory_bridge import (
    record_retrieval_as_memory,
    verify_and_feedback,
    purge_temporary_entries,
    resolve_default_paths,
    resolve_default_map_path,
)
from .weight_feedback import (
    apply_boost_to_results,
    get_boost,
    update_boost,
    reset,
    resolve_default_weight_path,
    BOOST_MIN,
    BOOST_MAX,
    BOOST_SUCCESS_FACTOR,
    BOOST_FAILURE_FACTOR,
    DEFAULT_BOOST,
)

__all__ = [
    "record_retrieval_as_memory",
    "verify_and_feedback",
    "purge_temporary_entries",
    "resolve_default_paths",
    "resolve_default_map_path",
    "resolve_default_weight_path",
    "apply_boost_to_results",
    "get_boost",
    "update_boost",
    "reset",
    "BOOST_MIN",
    "BOOST_MAX",
    "BOOST_SUCCESS_FACTOR",
    "BOOST_FAILURE_FACTOR",
    "DEFAULT_BOOST",
]
