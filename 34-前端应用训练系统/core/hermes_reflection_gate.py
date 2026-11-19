# -*- coding: utf-8 -*-
"""D3D+：Hermes 反思门禁 → 广义认知注入。

定位：
  Hermes 的反思不是认知真相，只是**候选证据**。
  反思必须先过门禁（真实性 / 证据 / 无写动作 / 无密钥 / 无思维链 / 限长 / 去重 / 置信度），
  通过后写入 append-only 反思收件箱，由广义认知系统按其升级后的策略消费。

硬约束：
  - Hermes 不得直写认知记忆 / 图谱 / 向量库；
  - 门禁未过 → 不进入收件箱；
  - 注入模式固定 `candidate_only`，必须由认知系统复核后才能升级为记忆；
  - 原始思维链、密钥、写动作、无证据 claim 一律拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

MIN_CONFIDENCE = 0.5
MAX_SUMMARY_CHARS = 4000
MAX_ARTIFACT_BYTES = 16 * 1024
DEFAULT_TTL_S = 7 * 24 * 3600

READ_ONLY_ACTIONS = frozenset(
    {
        "recall",
        "unified_search",
        "query_entity",
        "semantic_lookup",
        "get_rea_snapshot",
        "stats",
        "health",
        "rea_audit",
        "get_rea_methodology",
    }
)
WRITE_ACTIONS = frozenset(
    {
        "memory_write",
        "write_memory",
        "update_memory",
        "record",
        "verify",
        "delete",
        "ingest_signal",
        "place_order",
        "cancel_order",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"(FEISHU_APP_SECRET|AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY)\s*[:=]", re.I),
    re.compile(r"(password|passwd|secret)\s*[:=]\s*\S+", re.I),
)
_COT_KEYS = frozenset({"reasoning", "chain_of_thought", "thoughts", "raw_cot"})


@dataclass(frozen=True)
class ReflectionInsight:
    claim: str
    evidence_refs: Tuple[str, ...] = ()
    confidence: float = 0.5
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReflectionProposal:
    reflection_id: str
    trace_id: str
    task_id: str
    summary: str
    insights: Tuple[ReflectionInsight, ...] = ()
    evidence_refs: Tuple[str, ...] = ()
    proposed_actions: Tuple[str, ...] = ()
    confidence: float = 0.5
    source: str = "hermes"
    produced_at: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectionGateResult:
    allowed: bool
    reflection_id: str
    reasons: Tuple[str, ...] = ()
    artifact: Optional[Dict[str, Any]] = None


def _as_tuple(value: Iterable[Any]) -> Tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in (value or ()) if str(item).strip())


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _SECRET_PATTERNS)


def _content_hash(artifact: Mapping[str, Any]) -> str:
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_reflection(
    proposal: ReflectionProposal,
    *,
    now: float,
    seen_keys: Optional[Iterable[str]] = None,
    min_confidence: float = MIN_CONFIDENCE,
    ttl_s: float = DEFAULT_TTL_S,
) -> ReflectionGateResult:
    """门禁评估；任何失败都不产生 artifact。"""
    if not isinstance(proposal, ReflectionProposal):
        return ReflectionGateResult(False, "", ("invalid_proposal",))

    reasons: List[str] = []
    if not str(proposal.reflection_id or "").strip():
        reasons.append("reflection_id_required")
    if not str(proposal.trace_id or "").strip():
        reasons.append("trace_id_required")
    if not str(proposal.task_id or "").strip():
        reasons.append("task_id_required")
    if not str(proposal.source or "").startswith("hermes"):
        reasons.append("source_must_be_hermes")
    if not str(proposal.summary or "").strip():
        reasons.append("summary_required")
    if float(proposal.confidence or 0.0) < min_confidence:
        reasons.append("confidence_below_min")

    evidence_refs = _as_tuple(proposal.evidence_refs)
    if not evidence_refs:
        reasons.append("evidence_refs_required")

    insights = list(proposal.insights or ())
    if not insights:
        reasons.append("insights_required")
    for index, insight in enumerate(insights):
        if not isinstance(insight, ReflectionInsight) or not str(insight.claim or "").strip():
            reasons.append("insight[%d].claim_required" % index)
            continue
        if not _as_tuple(insight.evidence_refs):
            reasons.append("insight[%d].evidence_required" % index)
        if float(insight.confidence or 0.0) < min_confidence:
            reasons.append("insight[%d].confidence_below_min" % index)

    actions = _as_tuple(proposal.proposed_actions)
    forbidden = sorted(set(actions) & WRITE_ACTIONS)
    if forbidden:
        reasons.append("write_action_forbidden:%s" % ",".join(forbidden))
    unknown = sorted(set(actions) - READ_ONLY_ACTIONS - WRITE_ACTIONS)
    if unknown:
        reasons.append("unknown_action:%s" % ",".join(unknown))

    metadata = dict(proposal.metadata or {})
    cot = sorted(key for key in metadata if str(key).lower() in _COT_KEYS)
    if cot:
        reasons.append("raw_cot_forbidden:%s" % ",".join(cot))

    blob = json.dumps(
        {
            "summary": proposal.summary,
            "insights": [
                {"claim": item.claim, "evidence_refs": list(_as_tuple(item.evidence_refs))}
                for item in insights
                if isinstance(item, ReflectionInsight)
            ],
            "evidence_refs": list(evidence_refs),
            "metadata": metadata,
        },
        ensure_ascii=False,
    )
    if _contains_secret(blob):
        reasons.append("secret_detected")

    if reasons:
        return ReflectionGateResult(False, str(proposal.reflection_id or ""), tuple(reasons))

    artifact: Dict[str, Any] = {
        "reflection_id": str(proposal.reflection_id),
        "trace_id": str(proposal.trace_id),
        "task_id": str(proposal.task_id),
        "source": str(proposal.source),
        "summary": str(proposal.summary)[:MAX_SUMMARY_CHARS],
        "insights": [
            {
                "claim": str(item.claim),
                "evidence_refs": list(_as_tuple(item.evidence_refs)),
                "confidence": round(float(item.confidence), 4),
                "tags": list(_as_tuple(item.tags)),
            }
            for item in insights
        ],
        "evidence_refs": list(evidence_refs),
        "confidence": round(float(proposal.confidence), 4),
        "provenance": {
            "gate": "hermes_reflection_gate",
            "gate_version": "v1",
            "producer": "hermes_reflection",
            "evidence": list(evidence_refs),
        },
        "injection": {
            "mode": "candidate_only",
            "status": "pending",
            "target": "generalized_cognition",
            "ttl_s": float(ttl_s),
            "requires_review": True,
        },
        "gated_at": float(now),
    }
    digest = _content_hash(artifact)
    artifact["content_hash"] = digest

    keys = set(seen_keys or ())
    if proposal.reflection_id in keys or digest in keys:
        return ReflectionGateResult(False, artifact["reflection_id"], ("duplicate_reflection",))

    encoded = json.dumps(artifact, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        return ReflectionGateResult(False, artifact["reflection_id"], ("artifact_too_large",))

    return ReflectionGateResult(True, artifact["reflection_id"], (), artifact)


class ReflectionInbox:
    """append-only 反思收件箱；只接收门禁通过的 candidate_only artifact。"""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()

    def _load_keys(self) -> set:
        keys = set()
        try:
            with open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if record.get("reflection_id"):
                        keys.add(str(record["reflection_id"]))
                    if record.get("content_hash"):
                        keys.add(str(record["content_hash"]))
        except FileNotFoundError:
            return keys
        except Exception:
            return keys
        return keys

    def enqueue(self, artifact: Mapping[str, Any]) -> bool:
        if not isinstance(artifact, Mapping):
            return False
        injection = artifact.get("injection") or {}
        if not isinstance(injection, Mapping) or injection.get("mode") != "candidate_only":
            return False
        if not artifact.get("reflection_id") or not artifact.get("content_hash"):
            return False
        with self._lock:
            keys = self._load_keys()
            if artifact["reflection_id"] in keys or artifact["content_hash"] in keys:
                return True
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(dict(artifact), ensure_ascii=False) + "\n")
                return True
            except Exception:
                return False

    def evaluate_and_enqueue(
        self,
        proposal: ReflectionProposal,
        *,
        now: float,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> ReflectionGateResult:
        result = evaluate_reflection(
            proposal,
            now=now,
            seen_keys=self._load_keys(),
            min_confidence=min_confidence,
        )
        if result.allowed and result.artifact is not None:
            if not self.enqueue(result.artifact):
                return ReflectionGateResult(False, result.reflection_id, ("inbox_write_failed",))
        return result
