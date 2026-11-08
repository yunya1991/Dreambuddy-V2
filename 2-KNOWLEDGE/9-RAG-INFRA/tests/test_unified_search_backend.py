"""统一检索后端归一化测试：IndexQueryService 与 hybrid_search 两种结果形状。"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def test_backend_chroma_normalizes_index_query_shape():
    from dreambuddy_l0.search.backends import BackendChroma

    class FakeSvc:
        def query(self, query, top_k):
            return [{
                "title": "Kalman",
                "path": "finance/kalman.md",
                "category": "doc",
                "description": "desc",
                "score": 1.0,
            }]

    backend = BackendChroma()
    backend._svc = FakeSvc()
    hits = backend.search("Kalman", 3)

    assert len(hits) == 1
    assert hits[0]["text"] == "Kalman"
    assert hits[0]["ref"] == "finance/kalman.md"
    assert hits[0]["score"] == 1.0
    assert hits[0]["meta"]["title"] == "Kalman"


def test_backend_chroma_keeps_hybrid_shape():
    from dreambuddy_l0.search.backends import BackendChroma

    class FakeSvc:
        def query(self, query, top_k):
            return [{"text": "content", "score": 0.5, "id": "hit-1"}]

    backend = BackendChroma()
    backend._svc = FakeSvc()
    hits = backend.search("q", 3)

    assert hits[0]["text"] == "content"
    assert hits[0]["ref"] == "hit-1"


def test_minmax_norm_constant_scores_preserved():
    from dreambuddy_l0.search.unified import UnifiedSearch

    search = UnifiedSearch(backends=[])
    hits = [{"score": 1.0}, {"score": 1.0}]
    out = search._minmax_norm(hits)
    assert all(h["score"] == 1.0 for h in out)


def test_minmax_norm_varies_scores():
    from dreambuddy_l0.search.unified import UnifiedSearch

    search = UnifiedSearch(backends=[])
    hits = [{"score": 0.2}, {"score": 1.0}]
    out = search._minmax_norm(hits)
    assert [h["score"] for h in out] == [0.0, 1.0]