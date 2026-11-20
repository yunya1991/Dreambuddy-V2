"""L2Envelope 统一信封（SPEC-56 §4.3 IF-3 / ADR-03 / GAP-01）。

出口契约（本文首次在代码层冻结）：

    {ok, result, meta{layer, capability_id, run_id, model, tokens_used,
                      budget_remaining, latency_ms, degraded, needs_review},
     trace{route, reasons, sagc{S,A,C,G}, nodes},
     quality{evidence, caveat}}  失败时 + error_code

硬约束（与 SPEC-56 §4.3 一一对应）：
  1. `tokens_used` 与 `budget_remaining` **必须同源**：两者只能由同一个
     `BudgetSnapshot`（DreamOS `GlobalBudgetManager` 的当次快照）派生，
     不接受调用方分别传两个数字，从结构上禁止各自记账。
  2. `model == "none"` ⇒ `tokens_used == 0`（纯编排路径不产生 token）。
  3. 失败用 `ok=false + error_code`，不用成功结构掩盖；`ok=true` 不得携带 error_code。
  4. 文本纪律（「将会/预计/必然」等）由 57 宪法门禁 C-05 `E_PROPHECY` 单点判定，
     信封不重复实现，避免两套词表漂移。

版本：`ENVELOPE_VERSION = "0.1"`（D1：扩展 L0 既有 0.1，不新开 0.2-l2；
新增字段须按 ADR-03 升次版本，禁止各壳私加）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

ENVELOPE_VERSION = "0.1"
LAYER = "L2"
MODEL_NONE = "none"

TRACE_ROUTES = ("L1_DIRECT", "L2_HANDOFF")
SAGC_STAGES = ("S", "A", "C", "G")
SAGC_STATES = ("pending", "done", "skipped", "failed")
EVIDENCE_LEVELS = ("none", "partial", "full")

DEFAULT_CAVEAT = "历史统计/模型推断，不代表未来"

#: 57 提示词溯源增量（IF-P-3 / contracts/l2_meta.schema.json），允许出现在 meta 中
META_INCREMENT_KEYS = (
    "prompt_id",
    "prompt_version",
    "prompt_fingerprint",
    "constitution_version",
    "constitution_tokens",
    "tool_set_fingerprint",
    "reasoning_effort",
)

META_KEYS = (
    "layer",
    "capability_id",
    "run_id",
    "model",
    "tokens_used",
    "budget_remaining",
    "latency_ms",
    "degraded",
    "needs_review",
) + META_INCREMENT_KEYS

TOP_KEYS = ("ok", "result", "meta", "trace", "quality")


class EnvelopeError(ValueError):
    """信封不满足冻结契约（构造或校验期拒绝，fail-closed）"""


@dataclass(frozen=True)
class BudgetSnapshot:
    """一次运行的预算快照——token 计量的唯一来源（同源约束的载体）。

    `source` 必须声明记账主体（如 `dreamos.global_budget`），空值直接拒绝：
    没有来源的计量无法审计，也就不能出现在信封里。
    """

    source: str
    tokens_used: int
    budget_remaining: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise EnvelopeError("budget.source 不得为空（计量必须可审计）")
        for field in ("tokens_used", "budget_remaining"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise EnvelopeError(f"budget.{field} 必须是整数: {value!r}")
            if value < 0:
                raise EnvelopeError(f"budget.{field} 不得为负: {value}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_sagc(sagc: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    if sagc is None:
        return dict.fromkeys(SAGC_STAGES, "pending")
    if not isinstance(sagc, Mapping):
        raise EnvelopeError("trace.sagc 必须是 {S,A,C,G} 对象")
    missing = [stage for stage in SAGC_STAGES if stage not in sagc]
    extra = sorted(set(sagc) - set(SAGC_STAGES))
    if missing:
        raise EnvelopeError(f"trace.sagc 缺少阶段: {missing}（四阶段不可缺）")
    if extra:
        raise EnvelopeError(f"trace.sagc 含未知阶段: {extra}")
    out = {}
    for stage in SAGC_STAGES:
        state = sagc[stage]
        if state not in SAGC_STATES:
            raise EnvelopeError(f"trace.sagc.{stage} 非法: {state!r}（允许 {SAGC_STATES}）")
        out[stage] = state
    return out


def build_envelope_parts(
    *,
    capability_id: str,
    run_id: str,
    model: str,
    budget: BudgetSnapshot,
    route: str,
    reasons: Sequence[str] = (),
    sagc: Optional[Mapping[str, Any]] = None,
    latency_ms: int = 0,
    degraded: bool = False,
    needs_review: bool = False,
    quality: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """构造 `{meta, trace, quality}` 三段。

    供 HTTP 出口做**增量附加**（保留既有响应键），也供 `build_envelope` 复用，
    保证两条出口只有一套判定逻辑与一套字段冻结。
    """
    if not _non_empty_str(capability_id):
        raise EnvelopeError("capability_id 不得为空")
    if not _non_empty_str(run_id):
        raise EnvelopeError("run_id 不得为空")
    if not _non_empty_str(model):
        raise EnvelopeError("model 不得为空（纯编排请显式传 'none'）")
    if not isinstance(budget, BudgetSnapshot):
        raise EnvelopeError("budget 必须是 BudgetSnapshot（禁止 tokens/余额分开传）")
    if route not in TRACE_ROUTES:
        raise EnvelopeError(f"trace.route 非法: {route!r}（允许 {TRACE_ROUTES}）")
    if not _is_int(latency_ms) or latency_ms < 0:
        raise EnvelopeError(f"latency_ms 必须是非负整数: {latency_ms!r}")
    if model == MODEL_NONE and budget.tokens_used != 0:
        raise EnvelopeError("model=none 时 tokens_used 必须为 0")

    quality_doc = dict(quality or {})
    evidence = quality_doc.get("evidence", "none")
    if evidence not in EVIDENCE_LEVELS:
        raise EnvelopeError(f"quality.evidence 非法: {evidence!r}（允许 {EVIDENCE_LEVELS}）")
    caveat = quality_doc.get("caveat") or DEFAULT_CAVEAT
    if not _non_empty_str(caveat):
        raise EnvelopeError("quality.caveat 不得为空")

    parts: Dict[str, Dict[str, Any]] = {
        "meta": {
            "layer": LAYER,
            "capability_id": capability_id,
            "run_id": run_id,
            "model": model,
            "tokens_used": budget.tokens_used,
            "budget_remaining": budget.budget_remaining,
            "latency_ms": latency_ms,
            "degraded": bool(degraded),
            "needs_review": bool(needs_review),
        },
        "trace": {
            "route": route,
            "reasons": [str(item) for item in (reasons or ())],
            "sagc": _normalize_sagc(sagc),
            "nodes": [],
        },
        "quality": {"evidence": evidence, "caveat": caveat},
    }
    errors = validate_envelope_parts(parts)
    if errors:
        raise EnvelopeError("；".join(errors))
    return parts


def build_envelope(
    result: Any,
    *,
    capability_id: str,
    run_id: str,
    model: str,
    budget: BudgetSnapshot,
    route: str,
    reasons: Sequence[str] = (),
    sagc: Optional[Mapping[str, Any]] = None,
    nodes: Sequence[Any] = (),
    latency_ms: int = 0,
    degraded: bool = False,
    needs_review: bool = False,
    quality: Optional[Mapping[str, Any]] = None,
    error_code: str = "",
) -> Dict[str, Any]:
    """构造完整 L2Envelope；任何违反冻结契约的输入直接抛 `EnvelopeError`。"""
    parts = build_envelope_parts(
        capability_id=capability_id,
        run_id=run_id,
        model=model,
        budget=budget,
        route=route,
        reasons=reasons,
        sagc=sagc,
        latency_ms=latency_ms,
        degraded=degraded,
        needs_review=needs_review,
        quality=quality,
    )
    parts["trace"]["nodes"] = list(nodes or ())

    envelope: Dict[str, Any] = {
        "ok": not _non_empty_str(error_code),
        "result": result,
        **parts,
    }
    if envelope["ok"] is False:
        envelope["error_code"] = error_code

    errors = validate_envelope(envelope)
    if errors:
        raise EnvelopeError("；".join(errors))
    return envelope


def validate_envelope_parts(parts: Any) -> List[str]:
    """校验 `{meta, trace, quality}` 三段（增量附加模式用；不含 ok/result）。"""
    if not isinstance(parts, Mapping):
        return ["信封段必须是对象"]
    synthetic: Dict[str, Any] = {"ok": True, "result": None}
    for key in ("meta", "trace", "quality"):
        synthetic[key] = parts.get(key)
    return validate_envelope(synthetic)


def validate_envelope(envelope: Any) -> List[str]:
    """按冻结契约校验信封，返回错误列表（空列表即通过）。"""
    if not isinstance(envelope, Mapping):
        return ["信封必须是对象"]

    errors: List[str] = []
    for key in TOP_KEYS:
        if key not in envelope:
            errors.append(f"缺少信封字段: {key}")
    allowed = set(TOP_KEYS) | {"error_code"}
    extra = sorted(set(envelope) - allowed)
    if extra:
        errors.append(f"信封含未冻结字段: {extra}")

    ok = envelope.get("ok")
    if not isinstance(ok, bool):
        errors.append("ok 必须是布尔值")
    error_code = envelope.get("error_code", "")
    if ok is False:
        if not _non_empty_str(error_code):
            errors.append("ok=false 时必须给 error_code（不得用成功结构掩盖失败）")
    elif ok is True and _non_empty_str(error_code):
        errors.append("ok=true 时不得携带 error_code")

    meta = envelope.get("meta")
    if not isinstance(meta, Mapping):
        errors.append("meta 必须是对象")
    else:
        for key in META_KEYS[:9]:
            if key not in meta:
                errors.append(f"meta 缺少字段: {key}")
        extra_meta = sorted(set(meta) - set(META_KEYS))
        if extra_meta:
            errors.append(f"meta 含未冻结字段: {extra_meta}")
        if meta.get("layer") != LAYER:
            errors.append(f"meta.layer 必须是 {LAYER}")
        if not _non_empty_str(meta.get("capability_id")):
            errors.append("meta.capability_id 不得为空")
        if not _non_empty_str(meta.get("run_id")):
            errors.append("meta.run_id 不得为空")
        if not _non_empty_str(meta.get("model")):
            errors.append("meta.model 不得为空")
        tokens = meta.get("tokens_used")
        remaining = meta.get("budget_remaining")
        if not _is_int(tokens) or tokens < 0:
            errors.append(f"meta.tokens_used 必须是非负整数: {tokens!r}")
        if not _is_int(remaining) or remaining < 0:
            errors.append(f"meta.budget_remaining 必须是非负整数: {remaining!r}")
        if meta.get("model") == MODEL_NONE and tokens != 0:
            errors.append("model=none 时 tokens_used 必须为 0")
        if not _is_int(meta.get("latency_ms")) or meta["latency_ms"] < 0:
            errors.append(f"meta.latency_ms 必须是非负整数: {meta.get('latency_ms')!r}")
        for key in ("degraded", "needs_review"):
            if not isinstance(meta.get(key), bool):
                errors.append(f"meta.{key} 必须是布尔值")

    trace = envelope.get("trace")
    if not isinstance(trace, Mapping):
        errors.append("trace 必须是对象")
    else:
        extra_trace = sorted(set(trace) - {"route", "reasons", "sagc", "nodes"})
        if extra_trace:
            errors.append(f"trace 含未冻结字段: {extra_trace}")
        if trace.get("route") not in TRACE_ROUTES:
            errors.append(f"trace.route 非法: {trace.get('route')!r}")
        reasons = trace.get("reasons")
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            errors.append("trace.reasons 必须是字符串数组")
        sagc = trace.get("sagc")
        if not isinstance(sagc, Mapping):
            errors.append("trace.sagc 必须是 {S,A,C,G} 对象")
        else:
            for stage in SAGC_STAGES:
                if sagc.get(stage) not in SAGC_STATES:
                    errors.append(f"trace.sagc.{stage} 非法: {sagc.get(stage)!r}")
        if not isinstance(trace.get("nodes"), list):
            errors.append("trace.nodes 必须是数组")

    quality = envelope.get("quality")
    if not isinstance(quality, Mapping):
        errors.append("quality 必须是对象")
    else:
        extra_quality = sorted(set(quality) - {"evidence", "caveat"})
        if extra_quality:
            errors.append(f"quality 含未冻结字段: {extra_quality}")
        if quality.get("evidence") not in EVIDENCE_LEVELS:
            errors.append(f"quality.evidence 非法: {quality.get('evidence')!r}")
        if not _non_empty_str(quality.get("caveat")):
            errors.append("quality.caveat 不得为空")

    return errors
