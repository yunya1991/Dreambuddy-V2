"""Dual-Model Proposal Pipeline — T-G7 提案与评估强制分离

SPEC-33-G：
  - §2.4：proposal.json / evaluation.json 契约；`proposer_model != evaluator_model`，缺失即 hold；
    `confidence` 只记录、不入任何门禁；proposal 必须自带 falsifier；verdict=reject 直接归档
  - §4 硬约束 4 / 11

工程约束：模型调用通过注入的 callable 完成（可离线测试）；本模块不写账本、不落盘。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

REQUIRED_FIELDS = (
    "proposal_id",
    "level",
    "trigger",
    "claim",
    "expected_effect",
    "blast_radius",
    "change_draft",
    "falsifier",
    "proposer_model",
    "created_at",
)
VALID_LEVELS = ("L1", "L2", "L3")
VALID_VERDICTS = ("improve", "reject", "hold")
_REASONING_KEYS = ("proposer_reasoning", "reasoning", "thoughts", "chain_of_thought")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_proposal(proposal: Any) -> Tuple[bool, str]:
    """校验 proposal 契约；缺 falsifier 即 hold（硬约束 11）。"""
    if not isinstance(proposal, dict):
        return False, "proposal must be an object"
    for field in REQUIRED_FIELDS:
        if field not in proposal:
            return False, f"missing field: {field}"
    for field in ("proposal_id", "claim", "proposer_model", "created_at"):
        if not str(proposal.get(field) or "").strip():
            return False, f"field {field} must be a non-empty string"
    if proposal.get("level") not in VALID_LEVELS:
        return False, "level must be L1|L2|L3"
    if not str(proposal.get("falsifier") or "").strip():
        return False, "missing falsifier"
    if not isinstance(proposal.get("change_draft"), dict):
        return False, "change_draft must be an object"
    return True, ""


class DualModelPipeline:
    """proposer → 契约校验 → 去推理 → evaluator；模型相同或契约不全一律 hold。"""

    def __init__(
        self,
        *,
        proposer: Callable[[Dict[str, Any]], Dict[str, Any]],
        evaluator: Callable[[Dict[str, Any]], Dict[str, Any]],
        proposer_model: str,
        evaluator_model: str,
        evaluator_version: str = "1",
        clock: Optional[Callable[[], str]] = None,
        id_factory: Optional[Callable[[], str]] = None,
    ):
        self.proposer = proposer
        self.evaluator = evaluator
        self.proposer_model = proposer_model
        self.evaluator_model = evaluator_model
        self.evaluator_version = evaluator_version
        self.clock = clock or _now
        self.id_factory = id_factory or (lambda: f"PR-{uuid.uuid4().hex}")

    def run(
        self, trigger: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        context = dict(context or {})
        reason = self._separation_error()
        if reason:
            return self._held(reason)

        raw = self.proposer({"trigger": trigger, "context": dict(context)}) or {}
        proposal = dict(raw)
        proposal.setdefault("proposal_id", self.id_factory())
        if not str(proposal.get("proposal_id") or "").strip():
            proposal["proposal_id"] = self.id_factory()
        proposal.setdefault("proposer_model", self.proposer_model)
        proposal.setdefault("created_at", self.clock())
        proposal.setdefault("trigger", trigger.get("trigger") if isinstance(trigger, dict) else "")

        ok, reason = validate_proposal(proposal)
        if not ok:
            return self._held(reason, proposal=proposal)

        evaluation = dict(
            self.evaluator(
                {
                    "proposal": self._sanitize(proposal),
                    "evidence": (
                        context.get("evidence")
                        if "evidence" in context
                        else (trigger.get("evidence") if isinstance(trigger, dict) else None)
                    ),
                }
            )
            or {}
        )
        evaluation.setdefault("proposal_id", proposal["proposal_id"])
        evaluation["evaluator_model"] = self.evaluator_model
        evaluation.setdefault("evaluator_version", self.evaluator_version)

        verdict = evaluation.get("verdict")
        if verdict not in VALID_VERDICTS:
            evaluation["verdict"] = "hold"
            return self._held(
                f"evaluation.verdict 非法: {verdict!r}", proposal=proposal, evaluation=evaluation
            )
        if self.evaluator_model == proposal["proposer_model"]:
            return self._held("建议模型与评估模型相同", proposal=proposal, evaluation=evaluation)

        status = "held" if verdict == "hold" else "evaluated"
        result = {"status": status, "proposal": proposal, "evaluation": evaluation, "reason": ""}
        if verdict == "hold":
            result["reason"] = str(evaluation.get("rationale") or "evaluator 判定 hold")
        return result

    # ---------- 内部 ----------

    def _separation_error(self) -> str:
        proposer = str(self.proposer_model or "").strip()
        evaluator = str(self.evaluator_model or "").strip()
        if not proposer or not evaluator:
            return "缺少 proposer_model / evaluator_model"
        if proposer == evaluator:
            return "建议模型与评估模型必须不同（提案/评估分离）"
        return ""

    @staticmethod
    def _sanitize(proposal: Dict[str, Any]) -> Dict[str, Any]:
        """评估输入不得包含提案模型推理过程（§2.4）。"""
        return {key: value for key, value in proposal.items() if key not in _REASONING_KEYS}

    @staticmethod
    def _held(
        reason: str,
        *,
        proposal: Optional[Dict[str, Any]] = None,
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "held",
            "reason": reason,
            "proposal": proposal,
            "evaluation": evaluation,
        }
