"""mcp_shells/_shared/l2_meta.py — L2 壳 meta 计量补齐（SPEC-56 §4.3 ADR-03 / P0-1）

问题：4 个 L2 壳（l2.dreamos / l2.debate / l2.train / l2.emergence）的 tools/call
结果直接返回 handler dict，`meta` 只有壳私有键，缺 `model / tokens_used /
budget_remaining`，层级成本审计与证据边界断链。

做法：在 shell_runtime 的统一出口（tools/call 归一化之后）补齐 L2 冻结字段，
**只增不改**：既有 meta 键与信封其他字段全部保留。

取值纪律（不造数）：
  - model：工具显式 `model` 参数 > 壳声明的环境变量 > 壳默认
    （纯指标壳固定 `none`；有 LLM 但模型未知记 `unspecified`）
  - tokens_used / budget_remaining：取结果自带的 budget 快照（同源）；
    `budget_remaining` 缺失时按同快照 `total_tokens - tokens_used` 推导
  - `model == "none"` ⇒ `tokens_used = 0`（SPEC-56 §4.3 硬约束 2）
  - 完全取不到预算时记 0（契约不允许 null），不编造额度

FAIL-OPEN：任何异常返回原信封，不阻断 tools/call。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Tuple

L2_PREFIX = "l2."

#: 壳级模型声明：llm=False 表示该壳不调用生成式模型（meta 固定 model=none）
SHELL_PROFILE: Dict[str, Dict[str, Any]] = {
    "l2.dreamos.mcp": {"llm": True, "model_env": ("DREAMOS_MODEL",)},
    "l2.debate.mcp": {"llm": True, "model_env": ("DEBATE_MODEL", "ANTHROPIC_MODEL")},
    "l2.train.mcp": {"llm": True, "model_env": ("TRAIN_MODEL",)},
    "l2.emergence.mcp": {"llm": False, "model_env": ()},
    "l2.dsh.mcp": {"llm": True, "model_env": ("DREAMOS_MODEL",)},
}

DEFAULT_PROFILE = {"llm": True, "model_env": ()}


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _budget_of(doc: Any) -> Optional[Tuple[int, int]]:
    """从 budget dict 读取 (tokens_used, budget_remaining)。"""
    if not isinstance(doc, Mapping):
        return None
    if not any(k in doc for k in ("tokens_used", "budget_remaining", "total_tokens")):
        return None
    used = _as_int(doc.get("tokens_used"))
    total = _as_int(doc.get("total_tokens"))
    raw_remaining = doc.get("budget_remaining")
    if raw_remaining is None:
        remaining = max(0, total - used) if total else 0
    else:
        remaining = _as_int(raw_remaining)
    return used, remaining


def _pick_budget(envelope: Mapping[str, Any], arguments: Mapping[str, Any]) -> Tuple[int, int]:
    result = envelope.get("result")
    data = envelope.get("data")
    candidates = [envelope.get("budget")]
    for container in (result, data):
        if isinstance(container, Mapping):
            candidates.append(container.get("budget"))
            status = container.get("budget_status")
            if isinstance(status, Mapping):
                per_day = status.get("per_day")
                if isinstance(per_day, Mapping) and "remaining" in per_day:
                    candidates.append({"budget_remaining": per_day.get("remaining")})
    # submit 类：只有申请额度（total_tokens），本次尚未消耗
    arg_budget = arguments.get("budget")
    if isinstance(arg_budget, Mapping) and "total_tokens" in arg_budget:
        candidates.append({"total_tokens": arg_budget.get("total_tokens"), "tokens_used": 0})

    for candidate in candidates:
        parsed = _budget_of(candidate)
        if parsed is not None:
            return parsed
    return 0, 0


def _resolve_model(shell_id: str, arguments: Mapping[str, Any]) -> str:
    explicit = arguments.get("model")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    profile = SHELL_PROFILE.get(shell_id, DEFAULT_PROFILE)
    for env_key in profile.get("model_env", ()):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return "unspecified" if profile.get("llm") else "none"


def _run_id_of(envelope: Mapping[str, Any], shell_id: str, tool_name: str) -> str:
    containers = [envelope]
    for key in ("result", "data"):
        nested = envelope.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    for container in containers:
        for key in ("run_id", "debate_id", "job_id", "train_id", "cycle_id", "trace_id"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return f"{shell_id}:{tool_name}"


def attach_l2_meta(
    envelope: Dict[str, Any],
    *,
    shell_id: str,
    tool_name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    latency_ms: float = 0,
) -> Dict[str, Any]:
    """在 L2 壳信封的 meta 上补齐 L2 冻结字段；非 L2 壳原样返回。"""
    if not isinstance(envelope, dict) or not shell_id.startswith(L2_PREFIX):
        return envelope
    try:
        args = arguments if isinstance(arguments, Mapping) else {}
        model = _resolve_model(shell_id, args)
        tokens, remaining = _pick_budget(envelope, args)
        if model == "none":
            tokens = 0
        meta = dict(envelope.get("meta") or {})
        meta.update(
            {
                "layer": "L2",
                "capability_id": shell_id,
                "run_id": _run_id_of(envelope, shell_id, tool_name),
                "model": model,
                "tokens_used": tokens,
                "budget_remaining": remaining,
                "latency_ms": _as_int(latency_ms),
                "degraded": bool(envelope.get("degraded", not envelope.get("ok", True))),
                "needs_review": bool(envelope.get("needs_review", False)),
            }
        )
        envelope["meta"] = meta
    except Exception:  # noqa: BLE001 — FAIL-OPEN，计量失败不影响业务结果
        return envelope
    return envelope


__all__ = ["attach_l2_meta", "SHELL_PROFILE"]
