"""C7 统一检索（SPEC-C P0 前置切片）：经 Search port 分发，不直连三后端。

三后端 adapter：41-SearchAPI（外部部署，探活）/ ChromaDB RAG / 认知 recall。
分数 min-max 归一化 + 按 source 分层；去重键=规范化路径/记忆 ID；
断全部后端返回 error_code=all_sources_unavailable（非空结果）。
"""
from .unified import UnifiedSearch, get_unified_search

__all__ = ["UnifiedSearch", "get_unified_search"]
