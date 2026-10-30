"""三后端 adapter（SPEC-C C7）：每后端独立 FAIL-OPEN，异常只标记 degraded。"""
import os
import sys
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _norm_hit(text: str, source: str, score: float, ref: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
    """归一化命中结构：ref 为去重键（规范化路径/记忆 ID）。"""
    return {"text": text, "source": source, "score": float(score), "ref": ref, "meta": meta or {}}


class Backend41:
    """41-SearchAPI 后端（外部部署 /home/ubuntu/fis-p0 独立 venv，必须探活）。"""

    name = "search41"

    def __init__(self, root: Optional[str] = None):
        self._root = root or os.path.join(_REPO_ROOT, "41-文件索引系统")
        self._api = None

    def _probe(self) -> bool:
        """探活：索引库文件存在才尝试加载（外部部署可能未就绪）。"""
        try:
            db_path = os.path.join(self._root, "data", "index.db")
            if not os.path.exists(db_path):
                return False
            return True
        except Exception:
            return False

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not self._probe():
            raise RuntimeError("41 index db not found (external deploy not ready)")
        if self._api is None:
            sys.path.insert(0, os.path.join(self._root, "api"))
            from search_api import SearchAPI  # noqa: E402
            self._api = SearchAPI(self._root)
        result = self._api.search(query, limit=top_k)
        hits = []
        for h in result.get("hits", []):
            path = str(h.get("path", ""))
            hits.append(_norm_hit(str(h.get("title", path)), self.name,
                                  float(h.get("score", 0.0)), path, {"path": path}))
        return hits


class BackendChroma:
    """ChromaDB RAG 后端（2-KNOWLEDGE/9-RAG-INFRA）。"""

    name = "chroma"

    def __init__(self):
        self._svc = None

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._svc is None:
            sys.path.insert(0, os.path.join(_REPO_ROOT, "2-KNOWLEDGE", "9-RAG-INFRA"))
            from index_query_service import IndexQueryService  # noqa: E402
            self._svc = IndexQueryService()
        result = self._svc.query(query, top_k=top_k)
        hits = []
        items = result.get("results", result.get("hits", [])) if isinstance(result, dict) else result
        for h in items or []:
            if isinstance(h, dict):
                ref = str(h.get("id", h.get("source", "")))
                hits.append(_norm_hit(str(h.get("text", h.get("content", ""))), self.name,
                                      float(h.get("score", h.get("distance", 0.0))), ref))
        return hits


class BackendRecall:
    """认知 recall 后端（4-MEMORY cognitive_loop_entry）。"""

    name = "recall"

    def search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        cog_path = os.path.join(_REPO_ROOT, "4-MEMORY", "9-工具与接口")
        if cog_path not in sys.path:
            sys.path.insert(0, cog_path)
        from cognitive_loop_entry import get_cle  # noqa: E402
        cle = get_cle()
        memories = cle.recall(query, top_k=top_k)
        hits = []
        for m in memories or []:
            if isinstance(m, dict):
                mid = str(m.get("id", ""))
                hits.append(_norm_hit(str(m.get("content", "")), self.name,
                                      float(m.get("score", m.get("confidence", 0.0))), mid,
                                      {"memory_id": mid}))
        return hits
