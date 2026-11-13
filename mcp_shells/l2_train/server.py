#!/usr/bin/env python3
"""mcp_shells/l2_train/server.py — L2 训练编排 MCP（P2，DEC-02）

control 层：trigger_training 是写工具（requires_mandate=true），
get_training_status / list_runs 只读观察。

真实训练后端（34 / 45 门禁）未接入前用本地 job store 模拟，
submit 后立即返回 run_id + 状态推进。

硬约束：
  - L2 写工具三件套：Mandate + 预算 + trace（trigger_training 校验）
  - 壳零业务逻辑：真实训练委托给 L2 control 层实现
  - 永不直连 DB（走本地 job store / Ray 集群 RPC）
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l2.train.mcp"
_JOB_DIR = Path(__file__).resolve().parent / "runtime" / "jobs"
_JOB_DIR.mkdir(parents=True, exist_ok=True)

_JOB_TTL_SEC = int(os.environ.get("TRAIN_JOB_TTL_SEC", str(12 * 3600)))
_MAX_JOBS = int(os.environ.get("TRAIN_MAX_JOBS", "50"))
_MOCK_DURATION_SEC = float(os.environ.get("TRAIN_MOCK_DURATION_SEC", "3.0"))
_RATE_LIMIT = int(os.environ.get("TRAIN_RATE_LIMIT", "5"))

_rate_lock = threading.Lock()
_rate_timestamps: List[float] = []
_concurrent_lock = threading.Lock()
_concurrent_count = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(run_id: str) -> Path:
    return _JOB_DIR / f"{run_id}.json"


def _write_job(run_id: str, payload: Dict[str, Any]) -> None:
    target = _job_path(run_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _read_job(run_id: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_job_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _rate_check() -> tuple[bool, str]:
    now = time.monotonic()
    with _rate_lock:
        cutoff = now - 60.0
        _rate_timestamps[:] = [t for t in _rate_timestamps if t > cutoff]
        if len(_rate_timestamps) >= _RATE_LIMIT:
            return False, "rate_limited"
        _rate_timestamps.append(now)
        return True, ""


def _reset_governance() -> None:
    global _concurrent_count
    with _rate_lock:
        _rate_timestamps.clear()
    with _concurrent_lock:
        _concurrent_count = 0


def _advance_state(run_id: str, payload: Dict[str, Any]) -> None:
    global _concurrent_count
    with _concurrent_lock:
        _concurrent_count += 1
    try:
        payload["state"] = "running"
        payload["started_at"] = _now_iso()
        _write_job(run_id, payload)
        time.sleep(_MOCK_DURATION_SEC)
        # 85% 概率成功
        if time.time() % 100 > 15:
            payload["state"] = "done"
            payload["completed_at"] = _now_iso()
            payload["result"] = {
                "schema_version": "0.1",
                "status": "completed",
                "trainer": payload.get("trainer"),
                "eval_accuracy": 0.72 + (time.time() % 0.25),
                "loss": 0.12 + (time.time() % 0.05),
            }
        else:
            payload["state"] = "failed"
            payload["completed_at"] = _now_iso()
            payload["error"] = "mock training failure"
        _write_job(run_id, payload)
    finally:
        with _concurrent_lock:
            _concurrent_count -= 1


# ── 工具实现 ──


def _handle_trigger_training(args: Dict[str, Any]) -> Dict[str, Any]:
    """触发训练 run（写工具，需三件套）。

    args:
      trainer (str, req) — 训练器名（如 "ray-optimizer", "d2a-holdout"）
      mandate (str, req) — 写工具三件套 ①
      budget (dict, req) — {total_tokens: int} 三件套 ②
      trace_id (str, req) — 链路 trace_id 三件套 ③
      params (dict, opt) — 训练超参数
    """
    trainer = args.get("trainer")
    mandate = args.get("mandate")
    budget = args.get("budget")
    trace_id = args.get("trace_id")

    missing = [
        k
        for k, v in [
            ("trainer", trainer),
            ("mandate", mandate),
            ("budget", budget),
            ("trace_id", trace_id),
        ]
        if not v
    ]
    if missing:
        return {
            "ok": False,
            "error_code": "invalid",
            "reason": f"缺少必填字段: {missing}",
            "hard_constraint": "trigger_training 需 Mandate + 预算 + trace 三件套",
        }
    if not isinstance(budget, dict) or not isinstance(budget.get("total_tokens"), int):
        return {"ok": False, "error_code": "invalid", "reason": "budget.total_tokens 必须是整数"}

    ok, reason = _rate_check()
    if not ok:
        return {"ok": False, "error_code": reason, "reason": f"频控：每分钟 {_RATE_LIMIT} 次"}

    run_id = f"tr_{uuid.uuid4().hex[:12]}"
    payload = {
        "run_id": run_id,
        "trainer": trainer,
        "state": "submitted",
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "trace_id": trace_id,
        "mandate": mandate,
        "budget": {"total_tokens": budget["total_tokens"], "tokens_used": 0},
        "params": args.get("params") or {},
        "result": None,
        "error": None,
        "meta": {"shell": SHELL_SOURCE, "mock_engine": True},
    }
    _write_job(run_id, payload)

    if os.environ.get("TRAIN_MOCK_ENGINE", "1") != "0":
        threading.Thread(target=_advance_state, args=(run_id, payload), daemon=True).start()

    return {
        "ok": True,
        "run_id": run_id,
        "state": "submitted",
        "created_at": _now_iso(),
        "meta": {"shell": SHELL_SOURCE, "ttl_sec": _JOB_TTL_SEC},
    }


def _handle_get_training_status(args: Dict[str, Any]) -> Dict[str, Any]:
    run_id = args.get("run_id")
    if not run_id:
        return {"ok": False, "error_code": "invalid", "reason": "run_id 必填"}
    payload = _read_job(run_id)
    if payload is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"run_id={run_id!r} 不存在或已过期",
        }
    return {
        "ok": True,
        "run_id": run_id,
        "state": payload["state"],
        "trainer": payload.get("trainer"),
        "created_at": payload.get("created_at"),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "error": payload.get("error"),
    }


def _handle_list_runs(args: Dict[str, Any]) -> Dict[str, Any]:
    """列出最近 training runs。optional state_filter（submitted/running/done/failed）。"""
    state_filter = args.get("state_filter")
    try:
        limit = int(args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))

    runs: List[Dict[str, Any]] = []
    for p in sorted(_JOB_DIR.glob("tr_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        data = _read_job(p.stem)
        if data is None:
            continue
        if state_filter and data.get("state") != state_filter:
            continue
        runs.append(
            {
                "run_id": data["run_id"],
                "state": data["state"],
                "trainer": data.get("trainer"),
                "created_at": data.get("created_at"),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
        if len(runs) >= limit:
            break
    return {
        "ok": True,
        "total": len(runs),
        "runs": runs,
        "meta": {"source": SHELL_SOURCE},
    }


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "trigger_training": {
        "description": "触发训练 run（写工具，需 Mandate + budget + trace 三件套）。",
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "trainer": {
                    "type": "string",
                    "description": "训练器名（ray-optimizer / d2a-holdout ...）",
                },
                "mandate": {"type": "string", "description": "写工具 Mandate（硬约束 H5）"},
                "budget": {
                    "type": "object",
                    "properties": {"total_tokens": {"type": "integer"}},
                    "required": ["total_tokens"],
                },
                "trace_id": {"type": "string", "description": "链路 trace_id"},
                "params": {"type": "object", "description": "训练超参数（可选）"},
            },
            "required": ["trainer", "mandate", "budget", "trace_id"],
        },
    },
    "get_training_status": {
        "description": "轮询 training run 状态（submitted/running/done/failed）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    "list_runs": {
        "description": "列出最近 training runs（可按 state 过滤）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_filter": {
                    "type": "string",
                    "description": "optional: submitted/running/done/failed",
                },
                "limit": {"type": "integer", "description": "default 20, max 200"},
            },
        },
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "trigger_training": _handle_trigger_training,
    "get_training_status": _handle_get_training_status,
    "list_runs": _handle_list_runs,
}

_TOOL_LIST: List[Dict[str, Any]] = [
    {
        "name": n,
        "description": d["description"],
        "inputSchema": d["inputSchema"],
        "annotations": d.get("annotations", {}),
    }
    for n, d in _TOOL_DEFS.items()
]


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SHELL_SOURCE, "version": "0.1"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOL_LIST}}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        result = handler(params.get("arguments") or {})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, _TOOL_DEFS, _TOOL_HANDLERS)
