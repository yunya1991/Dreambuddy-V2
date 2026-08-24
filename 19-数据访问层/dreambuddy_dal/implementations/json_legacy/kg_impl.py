"""JsonLegacyKnowledgeGraphRepository（P0 内存实体/别名/三元组+简单 BM25 近似排序）"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from dreambuddy_dal.protocols.kg_repo import KnowledgeGraphRepository


class JsonLegacyKnowledgeGraphRepository(KnowledgeGraphRepository):
    def __init__(self):
        self._entities: Dict[str, Dict] = {}  # id → {type,name,description,attrs,aliases:List[Tuple(alias,conf)]}
        self._triples: List[Tuple] = []  # (s,p,o,conf,source,valid_from)

    # ---------- 写 ----------
    def upsert_entity(self, entity_id, entity_type, canonical_name, *,
                      description=None, attributes_json=None) -> bool:
        existing = self._entities.get(entity_id) or {"aliases": []}
        existing.update({
            "entity_type": entity_type, "canonical_name": canonical_name,
            "description": description or existing.get("description"),
            "attributes_json": attributes_json or existing.get("attributes_json"),
            "aliases": existing.get("aliases") or [],
        })
        self._entities[entity_id] = existing
        return True

    def add_alias(self, entity_id, alias, *, confidence=1.0) -> bool:
        self._entities.setdefault(entity_id, {"aliases": []})
        self._entities[entity_id].setdefault("aliases", []).append((alias, confidence))
        return True

    def add_triple(self, subject_id, predicate, object_id, *, confidence=1.0,
                   source=None, valid_from=None) -> bool:
        self._triples.append((subject_id, predicate, object_id, confidence, source, valid_from))
        return True

    # ---------- 读 ----------
    def fts_search_entities(self, query: str, *, limit: int = 20):
        """简单字符串包含匹配 + 别名/名称/描述打分（近似 FTS5 BM25，排名足够用于 P0 行为验证）"""
        q = query.lower()
        scored: List[Tuple[float, str, str, str]] = []
        for eid, e in self._entities.items():
            haystacks = [e["canonical_name"].lower(), (e.get("description") or "").lower()]
            haystacks += [a.lower() for a, _ in e.get("aliases", [])]
            score = 0.0
            for h in haystacks:
                if q in h:
                    score += 1.0 + 0.5 * h.count(q)
            if score > 0:
                scored.append((score, eid, e["entity_type"], e["canonical_name"]))
        scored.sort(key=lambda x: -x[0])
        return [(eid, etype, cname, s) for s, eid, etype, cname in scored[:limit]]

    def query_subgraph_by_entity(self, entity_id, *, hops=2, direction="both",
                                  min_confidence=0.5):
        triples_out: List[Tuple[str, str, str, float]] = []
        entities_set: Set[str] = {entity_id}
        frontier: Set[str] = {entity_id}
        for _ in range(hops):
            next_frontier: Set[str] = set()
            for s, p, o, c, _src, _vf in self._triples:
                if c < min_confidence:
                    continue
                if direction in ("both", "out") and s in frontier:
                    triples_out.append((s, p, o, c))
                    next_frontier.add(o)
                    entities_set.add(o)
                if direction in ("both", "in") and o in frontier:
                    triples_out.append((s, p, o, c))
                    next_frontier.add(s)
                    entities_set.add(s)
            frontier = next_frontier - entities_set
        entities_list = [(eid, self._entities[eid]["entity_type"], self._entities[eid]["canonical_name"])
                         for eid in entities_set if eid in self._entities]
        return triples_out, entities_list


__all__ = ["JsonLegacyKnowledgeGraphRepository"]
