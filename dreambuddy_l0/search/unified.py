"""UnifiedSearch：实现 Search port，分发三后端并合并结果（FAIL-OPEN）。"""
from typing import Any, Dict, List, Optional
from ..envelope import envelope
from .backends import Backend41, BackendChroma, BackendRecall


class UnifiedSearch:
    """统一检索：单后端失败剔除并标注 degraded；全失败返回 all_sources_unavailable。"""

    def __init__(self, backends: Optional[List[Any]] = None):
        self._backends = backends or [Backend41(), BackendChroma(), BackendRecall()]

    def _minmax_norm(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not hits:
            return hits
        scores = [h["score"] for h in hits]
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        for h in hits:
            h["score"] = round((h["score"] - lo) / span, 4)
        return hits

    def search(self, query: str, *, sources: Optional[List[str]] = None,
               top_k: int = 5, cursor: Optional[str] = None) -> Dict[str, Any]:
        per_source: Dict[str, List[Dict[str, Any]]] = {}
        degraded_sources: List[str] = []
        for be in self._backends:
            if sources and be.name not in sources:
                continue
            try:
                per_source[be.name] = self._minmax_norm(be.search(query, top_k))
            except Exception as e:
                degraded_sources.append(be.name)
        # 全后端不可用：显式错误码（SPEC-C C7 验收），不得返回空结果伪装成功
        if not per_source:
            return envelope({"query": query, "hits": [], "per_source": {},
                              "degraded_sources": degraded_sources},
                             "unified_search", degraded=True,
                             meta={"reason": "all_sources_unavailable",
                                   "error_code": "all_sources_unavailable",
                                   "error": f"all backends failed: {degraded_sources}"})
        # 去重：ref（规范化路径/记忆 ID）为键，保留高分
        seen: Dict[str, Dict[str, Any]] = {}
        for src, hits in per_source.items():
            for h in hits:
                key = h["ref"]
                if key not in seen or h["score"] > seen[key]["score"]:
                    h2 = dict(h)
                    h2["sources"] = [src]
                    seen[key] = h2
                else:
                    if src not in seen[key]["sources"]:
                        seen[key]["sources"].append(src)
        merged = sorted(seen.values(), key=lambda h: -h["score"])[:top_k]
        return envelope({"query": query, "hits": merged,
                         "per_source": {s: len(v) for s, v in per_source.items()},
                         "degraded_sources": degraded_sources}, "unified_search")

    def index(self, items: List[Dict[str, Any]], *, source: str = "") -> int:
        raise RuntimeError("unified_search is read-only; index via backend directly")


_default: Optional[UnifiedSearch] = None


def get_unified_search() -> UnifiedSearch:
    global _default
    if _default is None:
        _default = UnifiedSearch()
    return _default
