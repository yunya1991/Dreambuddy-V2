"""规则解释器：把评分卡里的 check.type 解释为 Finding。

只做纯文本/正则判断，保证离线、确定性、可单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import evidence
from .loaders import Surface

SEVERITY_RANK = {"blocker": 3, "warn": 2, "info": 1}
SUPPORTED_CHECKS = {
    "entity_hit",
    "intent_term",
    "bilingual",
    "boundary_declared",
    "cross_field_dup",
    "length_range",
    "field_present",
    "evidence_present",
    "family_distinct",
}


@dataclass
class Finding:
    rule_id: str
    title: str
    dimension: str
    severity: str
    weight: float
    passed: bool
    ratio: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    advice: str = ""

    @property
    def earned(self) -> float:
        return round(self.weight * self.ratio, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "dimension": self.dimension,
            "severity": self.severity,
            "weight": self.weight,
            "passed": self.passed,
            "ratio": round(self.ratio, 4),
            "earned": self.earned,
            "evidence": self.evidence,
            "message": self.message,
            "advice": self.advice,
        }


def _result(
    ratio: float, evidence_map: Dict[str, Any], message: str
) -> Tuple[float, Dict[str, Any], str]:
    ratio = max(0.0, min(1.0, ratio))
    return ratio, evidence_map, message


def _check_entity_hit(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    text = evidence.as_text(surface.get(str(check.get("field") or "description")))
    lexicon = (context.get("card") or {}).get("entity_lexicon") or {}
    matched = evidence.match_entities(text, lexicon)
    minimum = int(check.get("min") or 1)
    ratio = min(1.0, len(matched) / minimum) if minimum else 1.0
    return _result(ratio, {"matched_entities": matched, "required": minimum}, "")


def _check_intent_term(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    text = evidence.as_text(surface.get(str(check.get("field") or "description")))
    terms = [str(item) for item in (check.get("terms") or [])]
    matched = [term for term in terms if term in text]
    return _result(1.0 if matched else 0.0, {"matched_terms": matched}, "")


def _check_bilingual(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    counts = evidence.bilingual_counts(surface.get(str(check.get("field") or "tags")))
    need_ascii = int(check.get("min_ascii") or 1)
    need_cjk = int(check.get("min_cjk") or 1)
    ratio = min(
        1.0,
        counts["ascii_words"] / need_ascii if need_ascii else 1.0,
        counts["cjk_chars"] / need_cjk if need_cjk else 1.0,
    )
    return _result(ratio, counts, "")


def _check_boundary(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    markers = [str(item) for item in (check.get("markers") or [])]
    hits: List[Dict[str, str]] = []
    for name in check.get("fields") or ["not_for", "description"]:
        text = evidence.as_text(surface.get(str(name)))
        for marker in markers:
            if marker in text:
                hits.append({"field": str(name), "marker": marker})
                break
    return _result(1.0 if hits else 0.0, {"hits": hits}, "")


def _check_field_present(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    condition = check.get("when") or {}
    if condition:
        actual = str(surface.get(str(condition.get("field") or "")) or "")
        allowed = [str(item) for item in (condition.get("in") or [])]
        blocked = [str(item) for item in (condition.get("not_in") or [])]
        if allowed and actual not in allowed:
            return _result(1.0, {"skipped": "when_not_in"}, "")
        if blocked and actual in blocked:
            return _result(1.0, {"skipped": "when_in_blocked"}, "")
    fields = [str(item) for item in (check.get("fields") or [])]
    present = [name for name in fields if evidence.as_text(surface.get(name)).strip()]
    ratio = len(present) / len(fields) if fields else 1.0
    return _result(ratio, {"present": present, "missing": sorted(set(fields) - set(present))}, "")


def _check_evidence_present(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    field_name = str(check.get("field") or "")
    value = surface.get(field_name)
    minimum = int(check.get("min") or 1)
    if isinstance(value, (list, tuple, set)):
        count = len(value)
        ratio = min(1.0, count / minimum) if minimum else 1.0
        return _result(ratio, {"field": field_name, "count": count, "required": minimum}, "")
    if isinstance(value, bool):
        return _result(1.0 if value else 0.0, {"field": field_name, "value": value}, "")
    text = evidence.as_text(value).strip()
    return _result(1.0 if text else 0.0, {"field": field_name, "chars": len(text)}, "")


def _check_length_range(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    text = evidence.as_text(surface.get(str(check.get("field") or ""))).strip()
    pattern = check.get("pattern")
    length = len(text)
    evidence_map: Dict[str, Any] = {"length": length}
    if pattern:
        compiled = re.compile(str(pattern))
        ok = bool(compiled.match(text))
        evidence_map["pattern"] = str(pattern)
        return _result(1.0 if ok else 0.0, evidence_map, "")
    minimum = check.get("min")
    maximum = check.get("max")
    ok = True
    if minimum is not None and length < int(minimum):
        ok = False
    if maximum is not None and length > int(maximum):
        ok = False
    evidence_map.update({"min": minimum, "max": maximum})
    return _result(1.0 if ok else 0.0, evidence_map, "")


def _check_cross_field_dup(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    check = rule.get("check") or {}
    fields = [str(item) for item in (check.get("fields") or [])]
    card = context.get("card") or {}
    duplicated = evidence.shared_terms(
        {name: surface.get(name) for name in fields},
        card.get("dup_whitelist") or [],
        card.get("entity_lexicon") or {},
    )
    return _result(0.0 if duplicated else 1.0, {"duplicates": duplicated[:10]}, "")


def _check_family_distinct(surface: Surface, rule: dict, context: dict) -> Tuple[float, dict, str]:
    name = str(surface.get("name") or "")
    siblings = [str(item) for item in (context.get("siblings") or []) if item != name]
    own = evidence.name_tokens(name)
    if not siblings:
        return _result(1.0, {"distinct_tokens": own, "siblings": 0}, "")
    sibling_tokens = {token for sibling in siblings for token in evidence.name_tokens(sibling)}
    distinct = [token for token in own if token not in sibling_tokens]
    return _result(
        1.0 if distinct else 0.0,
        {"distinct_tokens": distinct, "siblings": len(siblings)},
        "",
    )


CHECKERS: Dict[str, Callable[[Surface, dict, dict], Tuple[float, dict, str]]] = {
    "entity_hit": _check_entity_hit,
    "intent_term": _check_intent_term,
    "bilingual": _check_bilingual,
    "boundary_declared": _check_boundary,
    "field_present": _check_field_present,
    "evidence_present": _check_evidence_present,
    "length_range": _check_length_range,
    "cross_field_dup": _check_cross_field_dup,
    "family_distinct": _check_family_distinct,
}


def evaluate(surface: Surface, card: dict, siblings: Optional[List[str]] = None) -> List[Finding]:
    findings: List[Finding] = []
    context = {"card": card, "siblings": siblings or []}
    for rule in card.get("rules") or []:
        if surface.kind not in (rule.get("applies_to") or []):
            continue
        check = rule.get("check") or {}
        checker = CHECKERS.get(str(check.get("type") or ""))
        if checker is None:
            continue
        ratio, evidence_map, message = checker(surface, rule, context)
        messages = rule.get("messages") or {}
        passed = ratio >= 1.0
        findings.append(
            Finding(
                rule_id=str(rule.get("id") or ""),
                title=str(rule.get("title") or ""),
                dimension=str(rule.get("dimension") or "retrievability"),
                severity=str(rule.get("severity") or "warn"),
                weight=float(rule.get("weight") or 0),
                passed=passed,
                ratio=ratio,
                evidence=evidence_map,
                message="" if passed else str(messages.get("fail") or ""),
                advice="" if passed else str(messages.get("advice") or ""),
            )
        )
    return findings
