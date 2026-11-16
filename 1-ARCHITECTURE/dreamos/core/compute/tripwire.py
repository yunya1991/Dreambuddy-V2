"""
DreamOS C层 — 45 tripwire 运行时（G-L2-10 / G-L2-11）

设计对齐 45 门禁适配器的双模语义（先 shadow 记录，误拦率达标后转 hard）:
    shadow: 评估并记录裁决，一律放行（用于误拦率统计）
    hard:   BLOCK 立即熔断，循环以 stop_reason=error 收尾（fail-closed）

内置门禁（SPEC-56 §4.7 / G-L2-10 / G-L2-11）:
    G-L2-10 循环出口门禁：出口契约自洽（7 值枚举 / resumable 推导 / parked 子因 / trace_id）
    G-L2-11 工具集门禁：policy.order 顺序、write/trade 必须 Mandate、trade 必须 human

本模块不持网络与存储：需要 45 HTTP 裁决时由调用侧注入 evaluator。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .types import PARKED_REASONS, RESUMABLE_STOP_REASONS, STOP_REASONS

TRIPWIRE_MODES = ("shadow", "hard")

# 权限顺序契约（tool_set.schema.json: policy.order const）
POLICY_ORDER = ["deny", "mode", "allow", "human"]

VERDICT_PASS = "PASS"
VERDICT_BLOCK = "BLOCK"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_SKIP = "SKIP"

_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")
_TOOL_NAME_PATTERN = re.compile(r"^l[0-2]\.[a-z0-9_]+\.[a-z0-9_]+$")
_TRIPWIRE_ID_PATTERN = re.compile(r"^G-L2-[0-9]+$")

# evaluator(context) -> {"verdict": str, "detail": dict}
TripwireFn = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class TripwireResult:
    tripwire_id: str
    verdict: str
    detail: Dict[str, Any] = field(default_factory=dict)
    checkpoint: str = ""
    node_id: Optional[str] = None
    at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tripwire_id": self.tripwire_id,
            "verdict": self.verdict,
            "detail": self.detail,
            "checkpoint": self.checkpoint,
            "node_id": self.node_id,
            "at": self.at,
        }


class TripwireRegistry:
    """tripwire 注册表：ID → evaluator；未注册的门禁返回 SKIP（不误拦）"""

    def __init__(self) -> None:
        self._evaluators: Dict[str, TripwireFn] = {}

    def register(self, tripwire_id: str, fn: TripwireFn) -> None:
        if not _TRIPWIRE_ID_PATTERN.match(tripwire_id):
            raise ValueError(f"tripwire_id 非法: {tripwire_id!r}（应形如 G-L2-10）")
        if not callable(fn):
            raise TypeError("tripwire evaluator 必须可调用")
        self._evaluators[tripwire_id] = fn

    def ids(self) -> List[str]:
        return sorted(self._evaluators)

    def evaluate(
        self,
        tripwire_id: str,
        context: Dict[str, Any],
        checkpoint: str = "",
        node_id: Optional[str] = None,
    ) -> TripwireResult:
        fn = self._evaluators.get(tripwire_id)
        if fn is None:
            return TripwireResult(
                tripwire_id,
                VERDICT_SKIP,
                {"reason": "未注册 evaluator"},
                checkpoint,
                node_id,
            )
        try:
            ctx = dict(context or {})
            ctx["checkpoint"] = checkpoint
            ctx["node_id"] = node_id
            raw = fn(ctx) or {}
            verdict = str(raw.get("verdict") or VERDICT_INCONCLUSIVE).upper()
            if verdict not in (VERDICT_PASS, VERDICT_BLOCK, VERDICT_INCONCLUSIVE, VERDICT_SKIP):
                verdict = VERDICT_INCONCLUSIVE
            detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
            return TripwireResult(tripwire_id, verdict, detail, checkpoint, node_id)
        except Exception as exc:  # FAIL-OPEN：evaluator 自身异常不阻塞循环
            return TripwireResult(
                tripwire_id,
                VERDICT_INCONCLUSIVE,
                {"error": f"{type(exc).__name__}: {exc}"},
                checkpoint,
                node_id,
            )

    def evaluate_all(
        self,
        tripwire_ids: List[str],
        context: Dict[str, Any],
        checkpoint: str = "",
        node_id: Optional[str] = None,
    ) -> List[TripwireResult]:
        return [self.evaluate(tid, context, checkpoint, node_id) for tid in tripwire_ids]


# ============================================================
# 内置门禁
# ============================================================


def _g_l2_10_stop_contract(context: Dict[str, Any]) -> Dict[str, Any]:
    """循环出口门禁：只在 end 检查点评估"""
    if context.get("checkpoint") != "end":
        return {"verdict": VERDICT_SKIP, "detail": {"reason": "仅循环出口评估"}}

    report = context.get("report")
    if report is None or not hasattr(report, "stop_contract"):
        return {"verdict": VERDICT_BLOCK, "detail": {"reason": "缺少 execution report"}}

    try:
        contract = report.stop_contract()
    except Exception as exc:
        return {"verdict": VERDICT_BLOCK, "detail": {"error": str(exc)}}

    reasons: List[str] = []
    stop_reason = contract.get("stop_reason")
    if stop_reason not in STOP_REASONS:
        reasons.append(f"stop_reason 非法: {stop_reason!r}")

    expected_resumable = stop_reason in RESUMABLE_STOP_REASONS
    if contract.get("resumable") is not expected_resumable:
        reasons.append(f"resumable 与 stop_reason 不一致: {contract.get('resumable')}")

    if stop_reason == "parked":
        if contract.get("parked_reason") not in PARKED_REASONS:
            reasons.append(f"parked 缺少合法子因: {contract.get('parked_reason')!r}")
    elif "parked_reason" in contract:
        reasons.append("非 parked 携带 parked_reason")

    if not _ID_PATTERN.match(str(contract.get("trace_id") or "")):
        reasons.append(f"trace_id 非法: {contract.get('trace_id')!r}")

    if reasons:
        return {"verdict": VERDICT_BLOCK, "detail": {"reasons": reasons}}
    return {"verdict": VERDICT_PASS, "detail": {"stop_reason": stop_reason}}


def _g_l2_11_tool_set(context: Dict[str, Any]) -> Dict[str, Any]:
    """工具集门禁：检查 state.extra.tool_set（未附快照则 SKIP）"""
    state = context.get("state")
    extra = getattr(state, "extra", None) if state is not None else None
    tool_set = (extra or {}).get("tool_set") if isinstance(extra, dict) else None
    if not isinstance(tool_set, dict):
        return {"verdict": VERDICT_SKIP, "detail": {"reason": "未附 tool_set 快照"}}

    reasons: List[str] = []
    policy = tool_set.get("policy") or {}
    if policy.get("order") != POLICY_ORDER:
        reasons.append(f"policy.order 非冻结顺序: {policy.get('order')!r}")
    if policy.get("mode") not in ("default", "plan", "accept_edits", "bypass"):
        reasons.append(f"policy.mode 非法: {policy.get('mode')!r}")

    for tool in tool_set.get("tools") or []:
        name = str(tool.get("name") or "")
        if not _TOOL_NAME_PATTERN.match(name):
            reasons.append(f"工具名非法: {name!r}")
        effect = tool.get("effect")
        if effect in ("write", "trade") and tool.get("requires_mandate") is not True:
            reasons.append(f"{name}: {effect} 缺少 Mandate")
        if effect == "trade" and tool.get("approval") not in ("human", "deny"):
            reasons.append(f"{name}: trade 审批必须 human/deny，实际 {tool.get('approval')!r}")

    if reasons:
        return {"verdict": VERDICT_BLOCK, "detail": {"reasons": reasons[:8]}}
    return {"verdict": VERDICT_PASS, "detail": {"tools": len(tool_set.get("tools") or [])}}


def default_registry() -> TripwireRegistry:
    registry = TripwireRegistry()
    registry.register("G-L2-10", _g_l2_10_stop_contract)
    registry.register("G-L2-11", _g_l2_11_tool_set)
    return registry
