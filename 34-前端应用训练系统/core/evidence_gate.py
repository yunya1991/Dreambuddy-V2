# -*- coding: utf-8 -*-
"""H5：InteractionCase 证据门禁（A/B/C 分级）。

冲突处理：
    - 现有 `adapters/*_session_collector.py` 产出 `TrainingCase`，字段与用途不同；
      本模块**不修改**既有采集器与 `l1_case_store.jsonl`，只提供独立的
      `interaction_case` 契约与纯函数分级器，由调用方决定是否落新存储。
    - 不重建第二套代码审计器：文件类证据可通过 `poe_audit` 注入 33 的
      `core.ai_audit.audit_ai_output`，门禁只负责 A/B/C 口径。

契约：56/contracts/interaction_case.schema.json（v1.0）。
分级（SPEC-56-H v0.3 §4.5）：
    - author_claim=observation + refs 含已校验的 span/checkpoint/file
      ⇒ derived.level=observation；否则 inference。
    - A：observation + 已校验 span/checkpoint + (可复现记录 | 人工确认)
    - B：有确认但够不到 A（含「只有 file 证据」）
    - C：inference 且无确认 —— 只可检索，不得进入训练/优化/settled
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, List, Optional

REF_TYPES = ("span", "checkpoint", "file", "ledger", "commit", "command")
OBSERVATION_REF_TYPES = ("span", "checkpoint", "file")
STRONG_REF_TYPES = ("span", "checkpoint")
ADMISSIBILITY = ("A", "B", "C")

_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

RefVerifier = Callable[[Dict[str, Any]], bool]
PoeAudit = Callable[[Dict[str, Any]], Dict[str, Any]]


class EvidenceGateError(ValueError):
    """案例不合法（fail-closed，不猜测）"""


def _default_verify_ref(ref: Dict[str, Any]) -> bool:
    """默认只做形状校验；真实存在性/hash 比对由调用方注入 verify_ref。"""
    if not isinstance(ref, dict):
        return False
    if ref.get("type") not in REF_TYPES:
        return False
    if not isinstance(ref.get("id"), str) or not ref.get("id", "").strip():
        return False
    if "hash" in ref and not _HASH_PATTERN.match(str(ref.get("hash"))):
        return False
    return True


def _validated_refs(
    case: Dict[str, Any], verify_ref: Optional[RefVerifier]
) -> List[Dict[str, Any]]:
    verifier = verify_ref or _default_verify_ref
    refs = case.get("refs") or []
    if not isinstance(refs, list) or not refs:
        raise EvidenceGateError("案例至少需要 1 条 refs")
    return [ref for ref in refs if bool(verifier(ref))]


def grade_case(
    case: Dict[str, Any],
    *,
    verify_ref: Optional[RefVerifier] = None,
    poe_audit: Optional[PoeAudit] = None,
) -> Dict[str, Any]:
    """计算 derived（level + admissibility）；作者自带 derived 一律拒绝。"""
    if not isinstance(case, dict):
        raise EvidenceGateError("case 必须是 dict")
    if "derived" in case:
        raise EvidenceGateError("案例不得自带 derived 字段；由证据门禁计算")
    if case.get("author_claim") not in ("observation", "inference"):
        raise EvidenceGateError("author_claim 必须是 observation|inference")

    verified = _validated_refs(case, verify_ref)
    if not verified:
        raise EvidenceGateError("没有通过校验的 refs")

    observation = case.get("author_claim") == "observation" and any(
        ref.get("type") in OBSERVATION_REF_TYPES for ref in verified
    )
    level = "observation" if observation else "inference"
    has_strong_ref = any(ref.get("type") in STRONG_REF_TYPES for ref in verified)
    confirmed = bool(case.get("human_confirmation")) or bool(case.get("reproduction"))

    if level == "observation" and has_strong_ref and confirmed:
        admissibility = "A"
        reason = "observation+span/checkpoint+confirmation"
    elif confirmed and (level == "inference" or not has_strong_ref):
        admissibility = "B"
        reason = "confirmed_but_not_A"
    else:
        admissibility = "C"
        reason = "inference_without_confirmation"

    out = copy.deepcopy(case)
    out["derived"] = {"level": level, "admissibility": admissibility}
    if poe_audit is not None:
        try:
            out["poe"] = dict(poe_audit(case) or {})
        except Exception as exc:  # 审计注入失败不改变 A/B/C
            out["poe"] = {"degraded": True, "reason": str(exc)}
    out["_gate_reason"] = reason
    return out


def is_trainable(case: Dict[str, Any]) -> bool:
    derived = (case or {}).get("derived") or {}
    return derived.get("admissibility") == "A"


def assert_admissible(case: Dict[str, Any], *, purpose: str = "train") -> None:
    """训练/优化只允许 A；C 级不得进入 settled。"""
    derived = (case or {}).get("derived") or {}
    level = derived.get("admissibility")
    if level not in ADMISSIBILITY:
        raise EvidenceGateError("案例缺少合法 derived.admissibility")
    if purpose in ("train", "optimize") and level != "A":
        raise EvidenceGateError(f"{purpose} 只允许 A 级案例，实际 {level}")
    if purpose == "settled" and level == "C":
        raise EvidenceGateError("C 级案例不得进入 settled")
    if purpose not in ("train", "optimize", "settled", "retrieve"):
        raise EvidenceGateError(f"未知用途: {purpose!r}")


__all__ = [
    "ADMISSIBILITY",
    "EvidenceGateError",
    "OBSERVATION_REF_TYPES",
    "REF_TYPES",
    "STRONG_REF_TYPES",
    "assert_admissible",
    "grade_case",
    "is_trainable",
]
