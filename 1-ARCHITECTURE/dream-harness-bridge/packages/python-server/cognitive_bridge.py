# -*- coding: utf-8 -*-
"""P1-1: 认知能力 IPC 桥(DSH Worker 原生工具面)。

把 4-MEMORY 认知系统封装为 server.py 的进程内方法,供 cordis-plugin-dreamos-cognitive
通过共享 IPC(D3-b)调用——不启动第二个 MCP 进程。

复用事实源: 4-MEMORY/9-工具与接口/cognitive_loop_entry.py::CognitiveLoopEntry
写门禁与 cognitive_mcp_server.py §5.2 C6 对齐:
  1) COGNITIVE_MCP_MODE=local            → 只读拒绝
  2) COGNITIVE_MCP_WRITE_ENABLED != true → scope_denied
  3) principal ∉ {orchestrator,verifier,admin} → principal_denied
默认 principal 由宿主 env COGNITIVE_MCP_DEFAULT_PRINCIPAL 注入;仅当
COGNITIVE_MCP_ALLOW_CALLER_PRINCIPAL=true 时才信任调用方自声明。

DB 路径: COGNITIVE_MCP_DB_PATH / DREAMBUDDY_COGNITIVE_DB 可覆盖,
默认 4-MEMORY/data/cognitive_memory.db。

FAIL-OPEN: 任何异常 → {"ok": False, "degraded": True, "reason": ...},不抛错。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

# 仓库根 = python-server 上溯 4 级(packages/python-server → packages → dream-harness-bridge → 1-ARCHITECTURE → 仓库根)
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
)
_MEMORY_TOOLS_DIR = os.path.join(_REPO_ROOT, "4-MEMORY", "9-工具与接口")

_CLE: Any = None

# §5.2 C6 写主体矩阵(Worker 默认只读)
WRITE_ROLES = frozenset({"orchestrator", "verifier", "admin"})


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _write_principal(params: Dict[str, Any]) -> str:
    if _env_flag("COGNITIVE_MCP_ALLOW_CALLER_PRINCIPAL", default=False):
        caller = str(params.get("principal") or "").strip()
        if caller:
            return caller
    return os.environ.get("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "").strip()


def _write_gate(tool: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """返回 None 放行,否则返回拒绝响应。"""
    if os.environ.get("COGNITIVE_MCP_MODE", "ssh").strip().lower() == "local":
        return {
            "ok": False,
            "degraded": True,
            "reason": "write_denied: local readonly mode (COGNITIVE_MCP_MODE=local)",
            "error_code": "conflict",
        }
    if not _env_flag("COGNITIVE_MCP_WRITE_ENABLED", default=False):
        return {
            "ok": False,
            "degraded": True,
            "reason": "write_denied: COGNITIVE_MCP_WRITE_ENABLED != true",
            "error_code": "scope_denied",
        }
    principal = _write_principal(params)
    if principal not in WRITE_ROLES:
        return {
            "ok": False,
            "degraded": True,
            "reason": "write_denied: principal=%r not in %s" % (principal, sorted(WRITE_ROLES)),
            "error_code": "principal_denied",
        }
    return None


def _get_cle() -> Any:
    """惰性初始化 CognitiveLoopEntry(首次调用才打开 660MB 级 DB)。"""
    global _CLE
    if _CLE is None:
        if _MEMORY_TOOLS_DIR not in sys.path:
            sys.path.insert(0, _MEMORY_TOOLS_DIR)
        from cognitive_loop_entry import CognitiveLoopEntry  # noqa: PLC0415

        db_path = (
            os.environ.get("COGNITIVE_MCP_DB_PATH")
            or os.environ.get("DREAMBUDDY_COGNITIVE_DB")
            or ""
        ).strip()
        _CLE = CognitiveLoopEntry(storage_path=db_path or None)
    return _CLE


def _safe(value: Any) -> Any:
    """转成 JSON 安全结构(不可序列化字段降级为 str)。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return None


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [value]


def _recall(params: Dict[str, Any]) -> Dict[str, Any]:
    cle = _get_cle()
    memories = cle.recall(
        context=str(params.get("context") or ""),
        top_k=int(params.get("top_k") or 5),
        min_quality=str(params.get("min_quality") or "C"),
    )
    memories = _safe(memories) or []
    return {"ok": True, "result": {"memories": memories, "count": len(memories)}}


def _search(params: Dict[str, Any]) -> Dict[str, Any]:
    cle = _get_cle()
    results = cle.search(
        query=str(params.get("query") or ""),
        top_k=int(params.get("top_k") or 5),
        tags=_as_list(params.get("tags")) or None,
    )
    results = _safe(results) or []
    return {"ok": True, "result": {"results": results, "count": len(results)}}


def _record(params: Dict[str, Any]) -> Dict[str, Any]:
    denied = _write_gate("record", params)
    if denied is not None:
        return denied
    cle = _get_cle()
    memory_id = cle.record(
        content=str(params.get("content") or ""),
        quality_level=str(params.get("quality_level") or "C"),
        tags=_as_list(params.get("tags")),
        source=str(params.get("source") or "dsh-cognitive-plugin"),
        level=str(params.get("level") or "observation"),
        known_gaps=(_as_list(params.get("known_gaps")) or None),
        observations=(_as_list(params.get("observations")) or None),
        external_id=params.get("external_id") or params.get("idempotency_key"),
    )
    return {"ok": True, "result": {"memory_id": memory_id}}


def _verify(params: Dict[str, Any]) -> Dict[str, Any]:
    denied = _write_gate("verify", params)
    if denied is not None:
        return denied
    memory_id = str(params.get("memory_id") or "")
    if not memory_id:
        return {"ok": False, "degraded": True, "reason": "memory_id_required"}

    # SPEC-33-G T-G1 后果回传: 与 cognitive_mcp_server 同契约(默认 enforce)
    outcome_mode = os.environ.get("COGNITIVE_VERIFY_OUTCOME_MODE", "enforce").strip().lower()
    outcome_entry: Optional[Dict[str, Any]] = None
    outcome = params.get("outcome")
    try:
        from outcome_ledger import OutcomeLedger, validate_outcome  # noqa: PLC0415

        outcome_ok, outcome_reason = validate_outcome(outcome)
        if not outcome_ok and outcome_mode != "shadow":
            return {
                "ok": False,
                "degraded": True,
                "reason": "outcome_required: %s" % outcome_reason,
                "error_code": "outcome_required",
            }
        if outcome_ok:
            outcome_entry = OutcomeLedger().record(outcome, memory_id=memory_id)
    except Exception as e:  # noqa: BLE001  (FAIL-OPEN: ledger 不可用不阻塞 verify)
        outcome_entry = None
        if outcome_mode == "enforce":
            return {
                "ok": False,
                "degraded": True,
                "reason": "outcome_ledger_unavailable: %s" % type(e).__name__,
            }

    result = (
        _safe(
            _get_cle().verify(
                memory_id=memory_id,
                success=bool(params.get("success", True)),
                known_gaps_update=(_as_list(params.get("known_gaps_update")) or None),
            )
        )
        or {}
    )
    if outcome_entry is not None:
        result["outcome_id"] = outcome_entry.get("event_id")
    elif outcome_mode == "shadow":
        result["outcome_warning"] = "outcome_required"
    return {"ok": True, "result": result}


_METHODS = {
    "cognitive_recall": _recall,
    "cognitive_search": _search,
    "cognitive_record": _record,
    "cognitive_verify": _verify,
}

METHOD_NAMES = frozenset(_METHODS)


def handle(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """方法分派(FAIL-OPEN)。"""
    try:
        fn = _METHODS.get(method)
        if fn is None:
            return {"ok": False, "degraded": True, "reason": "unknown_method:%s" % method}
        return fn(params or {})
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "degraded": True,
            "reason": "cognitive_bridge_error: %s: %s" % (type(e).__name__, e),
        }
