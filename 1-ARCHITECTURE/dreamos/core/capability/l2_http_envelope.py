"""DreamOS HTTP 出口 → L2Envelope 增量附加（SPEC-56 §4.3 IF-3 / GAP-01 / P0-1）。

**只做增量，不改既有键**：在原有响应体上追加 `ok` / `meta` / `trace` / `quality`
（失败再加 `error_code`），因此 3.1 前端与既有调用方读取的旧字段全部保留。

契约判定的唯一事实源在 `56-L2架构能力聚合层/runtime/l2_envelope.py`，
此处按路径加载该模块，不复制任何字段/校验逻辑（避免两套口径漂移）。

同源口径：`tokens_used` 与 `budget_remaining` 都取自 `TradingAgent.run()`
返回的**同一个结果快照**（`tokens_used` + `budget_status`），不由各端点自行记账；
`budget_remaining` 取 `per_day.remaining`（跨周期累计，`per_cycle` 在 end_cycle 后归零，
无法代表本次运行后的剩余）。

FAIL-OPEN：56 运行时不可用或构造被拒时，原样返回业务体，API 不因信封失败而 5xx。
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from dreamos.shared.llm_client import (
    FallbackChainLLMClient,
    NoOpLLMClient,
    get_default_client,
)
from dreamos.shared.utils import gen_cycle_id

logger = logging.getLogger(__name__)

CAPABILITY_ID = "l2.dreamos"
BUDGET_SOURCE = "dreamos.global_budget"

_REPO_ROOT = Path(__file__).resolve().parents[4]
_L2_ENVELOPE_PATH = _REPO_ROOT / "56-L2架构能力聚合层" / "runtime" / "l2_envelope.py"

_ERROR_CODES = {400: "invalid", 404: "not_found", 500: "unavailable"}

_MODULE: Any = None


def _l2() -> Any:
    """加载 56 发票契约实现（惰性 + 缓存）；不可用返回 None。"""
    global _MODULE
    if _MODULE is None and _L2_ENVELOPE_PATH.is_file():
        try:
            spec = importlib.util.spec_from_file_location("l2_envelope_56", _L2_ENVELOPE_PATH)
            module = importlib.util.module_from_spec(spec)
            # dataclass 解析注解时依赖 sys.modules 中存在模块本身
            sys.modules["l2_envelope_56"] = module
            spec.loader.exec_module(module)
            _MODULE = module
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN，信封不阻断 API
            logger.warning("L2Envelope 运行时加载失败: %s", exc)
    return _MODULE


def resolve_model_name() -> str:
    """当前进程实际生效的 LLM 模型；未配置 LLM 时返回 'none'（零 token 语义）。"""
    client: Any = get_default_client()
    if isinstance(client, NoOpLLMClient):
        return "none"
    if isinstance(client, FallbackChainLLMClient):
        client = client.clients[0] if client.clients else None
    model = getattr(client, "model", "") if client is not None else ""
    return str(model) if model else "none"


def _budget_remaining_from(payload: Mapping[str, Any]) -> int:
    status = payload.get("budget_status") or {}
    per_day = status.get("per_day") or {}
    try:
        return max(0, int(per_day.get("remaining", 0)))
    except (TypeError, ValueError):
        return 0


def _sagc_from_run(result: Mapping[str, Any]) -> Dict[str, str]:
    plan = result.get("plan") or {}
    execution = result.get("execution") or {}
    return {
        "S": "done" if result.get("intent") else "skipped",
        "A": "done" if plan.get("nodes") else "skipped",
        "C": "done" if execution.get("nodes_executed") else "skipped",
        "G": "done" if result.get("cycle_id") else "skipped",
    }


def _enrich(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    model: str,
    tokens_used: int,
    budget_remaining: int,
    route: str,
    sagc: Optional[Mapping[str, Any]],
    latency_ms: int,
    evidence: str,
    degraded: bool,
    ok: bool = True,
    error_code: str = "",
) -> Dict[str, Any]:
    module = _l2()
    body = dict(payload)
    if module is None:
        return body
    try:
        parts = module.build_envelope_parts(
            capability_id=CAPABILITY_ID,
            run_id=run_id,
            model=model,
            budget=module.BudgetSnapshot(
                source=BUDGET_SOURCE,
                tokens_used=max(0, int(tokens_used)),
                budget_remaining=max(0, int(budget_remaining)),
            ),
            route=route,
            sagc=dict(sagc) if sagc is not None else None,
            latency_ms=max(0, int(latency_ms)),
            degraded=degraded,
            quality={"evidence": evidence},
        )
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN，保留业务体
        logger.warning("L2Envelope 附加失败（已降级为原响应）: %s", exc)
        return body
    body["ok"] = ok
    body.update(parts)
    if not ok:
        body["error_code"] = error_code
    return body


def enrich_agent_result(
    result: Mapping[str, Any],
    *,
    tokens_key: str = "tokens_used",
    budget_remaining: Optional[int] = None,
    sagc: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """`/run` `/analyze` `/chat` `/intent` 等推理结果出口。"""
    model = resolve_model_name()
    raw_tokens = result.get(tokens_key)
    if raw_tokens is None:
        raw_tokens = result.get("total_tokens", 0)
    tokens = 0 if model == "none" else int(raw_tokens or 0)
    remaining = _budget_remaining_from(result) if budget_remaining is None else budget_remaining
    return _enrich(
        result,
        run_id=str(result.get("cycle_id") or gen_cycle_id("http")),
        model=model,
        tokens_used=tokens,
        budget_remaining=remaining,
        route="L2_HANDOFF",
        sagc=dict(sagc) if sagc is not None else _sagc_from_run(result),
        latency_ms=int(result.get("latency_ms") or result.get("total_latency_ms") or 0),
        evidence="partial",
        degraded=bool(result.get("degraded", False)),
    )


def enrich_static(
    payload: Mapping[str, Any],
    *,
    budget_remaining: int = 0,
    route: str = "L1_DIRECT",
    evidence: str = "full",
) -> Dict[str, Any]:
    """非推理出口（health/status/nodes/history/budget/异步提交与轮询）。"""
    return _enrich(
        payload,
        run_id=str(payload.get("cycle_id") or gen_cycle_id("http")),
        model="none",
        tokens_used=0,
        budget_remaining=budget_remaining,
        route=route,
        sagc=None,
        latency_ms=0,
        evidence=evidence,
        degraded=False,
    )


def enrich_error(
    payload: Mapping[str, Any], *, status_code: int, budget_remaining: int = 0
) -> Dict[str, Any]:
    """失败出口：ok=false + error_code（SPEC-56 §4.3 硬约束 3）。"""
    return _enrich(
        payload,
        run_id=gen_cycle_id("http"),
        model="none",
        tokens_used=0,
        budget_remaining=budget_remaining,
        route="L1_DIRECT",
        sagc=None,
        latency_ms=0,
        evidence="none",
        degraded=True,
        ok=False,
        error_code=_ERROR_CODES.get(status_code, "unavailable"),
    )
