# -*- coding: utf-8 -*-
"""P0-D3C: A 层双层验收（规则硬门 + Hermes 语义软门）。

约束:
  - 规则 fail 一票否决；
  - 语义 pass 必须带证据引用，否则降级；
  - 规则 pass + 语义 fail → degraded（不直接推翻规则）；
  - 规则 degraded + 语义 pass(有引用) → pass（需抽样复核）；
  - 不修改输入对象，FAIL-OPEN。

依据: SPEC-P0-D3C §3。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

SEMANTIC_VERDICTS = frozenset({"pass", "degraded", "fail"})


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


@dataclass(frozen=True)
class SemanticReview:
    node_id: str
    verdict: str
    evidence_refs: Tuple[str, ...] = ()
    confidence: float = 0.0
    rationale: str = ""
    missing: Tuple[str, ...] = ()
    model_version: str = ""
    prompt_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        object.__setattr__(self, "missing", _as_tuple(self.missing))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "verdict": self.verdict,
            "evidence_refs": list(self.evidence_refs),
            "confidence": self.confidence,
            "rationale": self.rationale,
            "missing": list(self.missing),
            "model_version": self.model_version,
            "prompt_hash": self.prompt_hash,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["SemanticReview"]:
        if not isinstance(data, dict):
            return None
        verdict = str(data.get("verdict") or "")
        if verdict not in SEMANTIC_VERDICTS:
            return None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            node_id=str(data.get("node_id") or ""),
            verdict=verdict,
            evidence_refs=_as_tuple(data.get("evidence_refs")),
            confidence=confidence,
            rationale=str(data.get("rationale") or ""),
            missing=_as_tuple(data.get("missing")),
            model_version=str(data.get("model_version") or ""),
            prompt_hash=str(data.get("prompt_hash") or ""),
        )


def merge_verdict(rule_verdict: str, semantic: Optional[SemanticReview]) -> Tuple[str, str]:
    """返回 (最终 verdict, reason)。规则硬门优先。"""
    if rule_verdict == "fail":
        return "fail", "rule_veto"
    if semantic is None:
        return rule_verdict, "rule_only"
    if not isinstance(semantic, SemanticReview) or semantic.verdict not in SEMANTIC_VERDICTS:
        return rule_verdict, "semantic_invalid"

    if rule_verdict == "pass":
        if semantic.verdict == "pass":
            if semantic.evidence_refs:
                return "pass", "semantic_pass"
            return "degraded", "semantic_no_citation"
        return "degraded", "semantic_disagreement"

    if semantic.verdict == "pass":
        if semantic.evidence_refs:
            return "pass", "semantic_upgrade"
        return "degraded", "semantic_no_citation"

    return "degraded", "semantic_reject"


def _normalize_reviews(
    reviews: Any,
) -> Dict[str, SemanticReview]:
    out: Dict[str, SemanticReview] = {}
    if reviews is None:
        return out
    items: Iterable[Any]
    if isinstance(reviews, dict):
        items = reviews.values()
    elif isinstance(reviews, (list, tuple)):
        items = reviews
    else:
        return out
    for item in items:
        review = item if isinstance(item, SemanticReview) else SemanticReview.from_dict(item)
        if review is not None and review.node_id:
            out[review.node_id] = review
    return out


def apply_reviews(node_verdicts: Any, reviews: Any) -> List[Dict[str, Any]]:
    """把语义候选合并进规则裁决；返回新列表，不修改输入。"""
    try:
        nodes = [dict(n) for n in (node_verdicts or []) if isinstance(n, dict)]
        by_id = _normalize_reviews(reviews)
        for entry in nodes:
            review = by_id.get(str(entry.get("node_id")))
            if review is None:
                continue
            rule_verdict = str(entry.get("verdict") or "")
            merged, reason = merge_verdict(rule_verdict, review)
            entry["rule_verdict"] = rule_verdict
            entry["verdict"] = merged
            entry["reason"] = reason
            entry["semantic_verdict"] = review.verdict
            entry["semantic_confidence"] = review.confidence
            entry["semantic_evidence_refs"] = list(review.evidence_refs)
            entry["semantic_rationale"] = review.rationale
            entry["semantic_missing"] = list(review.missing)
            if rule_verdict != review.verdict:
                entry["disagreement"] = True
        return nodes
    except Exception:  # FAIL-OPEN
        return [dict(n) for n in (node_verdicts or []) if isinstance(n, dict)]
