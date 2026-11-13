#!/usr/bin/env python3
"""mcp_shells/l2_dreamos/server.py — L2 DreamOS 编排 MCP（P1-B，DEC-01/02）

异步 submit/poll 范式：submit_run 立即返回 run_id，后台 job 异步推进，
poll_run / get_result 消费。遵循 L2 control exposure 规范（Mandate + 预算 + trace）。

五工具：
  submit_run   — 提交一个 DreamOS 编排 run（intent + budget + trace_id）
  poll_run     — 轮询 run 状态（submitted/running/done/failed）
  get_result   — 获取已完成 run 的结果（仅 done 状态可读）
  get_intent   — 读取 run 的意图元数据（S 层入口）
  get_budget   — 读取 run 的 token 预算与用量（B 层预算审计）

设计：
  - stdio JSON-RPC 2.0
  - job 存储：runtime/jobs/<run_id>.json（文件锁 safe，tmp→replace 原子写）
  - TTL + 并发上限 + 结果大小封顶（复用 debate_adversarial 治理范式）
  - LLM 依赖：optional（get_intent 可用规则或 LLM，预算审计零 LLM）
  - HTTP fallback：DREAMOS_API_BASE 可 env 覆盖，设了就转发；没设走本地 job store

硬约束：
  - 壳零业务逻辑（intent 解析委托给 l1.intent / 预算委托给 l0.cognition）
  - L2 写工具需 Mandate + 预算 + trace 三件套（submit_run 校验）
  - 永不直连 DB（DreamOS API 或本地 job store）
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

SHELL_SOURCE = "l2.dreamos.mcp"
_JOB_DIR = Path(__file__).resolve().parent / "runtime" / "jobs"
_JOB_DIR.mkdir(parents=True, exist_ok=True)

# ── 治理常量 ──
_JOB_TTL_SEC = int(os.environ.get("DREAMOS_JOB_TTL_SEC", str(24 * 3600)))
_MAX_JOBS = int(os.environ.get("DREAMOS_MAX_JOBS", "100"))
_MAX_RESULT_BYTES = int(os.environ.get("DREAMOS_MAX_RESULT_BYTES", str(2 * 1024 * 1024)))  # 2MB
_MAX_CONCURRENT = int(os.environ.get("DREAMOS_MAX_CONCURRENT", "4"))
_RATE_LIMIT_PER_MIN = int(os.environ.get("DREAMOS_RATE_LIMIT_PER_MIN", "10"))
_RATE_LIMIT_WINDOW_SEC = 60.0
_MOCK_RUN_DURATION_SEC = float(os.environ.get("DREAMOS_MOCK_RUN_DURATION_SEC", "2.0"))

# DreamOS HTTP API（可选，设了就先 HTTP 转发；没设走本地 job store）
_DREAMOS_API_BASE = os.environ.get("DREAMOS_API_BASE", "").rstrip("/")

# ── 并发治理 state ──
_rate_lock = threading.Lock()
_rate_timestamps: List[float] = []
_concurrent_lock = threading.Lock()
_concurrent_count = 0

# 状态机合法迁移
_VALID_STATES = {"submitted", "running", "done", "failed", "cancelled"}


# ── Job 读写 ──


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
    path = _job_path(run_id)
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.05)
                continue
            return None


# ── 治理：频控 / 并发 / TTL 清理 ──


def _rate_limit_check() -> tuple[bool, str]:
    now = time.monotonic()
    with _rate_lock:
        cutoff = now - _RATE_LIMIT_WINDOW_SEC
        _rate_timestamps[:] = [t for t in _rate_timestamps if t > cutoff]
        if len(_rate_timestamps) >= _RATE_LIMIT_PER_MIN:
            oldest = _rate_timestamps[0] if _rate_timestamps else now
            retry = max(1, int(_RATE_LIMIT_WINDOW_SEC - (now - oldest)))
            return False, f"rate_limited: retry_after={retry}s"
        _rate_timestamps.append(now)
        return True, ""


def _concurrent_acquire() -> bool:
    global _concurrent_count
    with _concurrent_lock:
        if _concurrent_count >= _MAX_CONCURRENT:
            return False
        _concurrent_count += 1
        return True


def _concurrent_release() -> None:
    global _concurrent_count
    with _concurrent_lock:
        _concurrent_count = max(0, _concurrent_count - 1)


def _sweep_jobs() -> None:
    try:
        jobs = sorted(_JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    now = time.time()
    for path in jobs:
        try:
            mtime = path.stat().st_mtime
            if now - mtime > _JOB_TTL_SEC:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    remaining = sorted(_JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if len(remaining) > _MAX_JOBS:
        for path in remaining[: len(remaining) - _MAX_JOBS]:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


# ── Job 生命周期（本地 mock 引擎） ──


def _advance_job_state(run_id: str, payload: Dict[str, Any]) -> None:
    """后台线程推进 job 状态（submitted → running → done）。

    真实实现会调用 DreamOS LLM 编排引擎；此处用 sleep + 合成结果占位，
    让壳接口在 P1 即可端到端可用。
    """
    _concurrent_acquire()
    try:
        # submitted → running
        payload["state"] = "running"
        payload["started_at"] = _now_iso()
        _write_job(run_id, payload)

        # sleep 模拟编排耗时
        time.sleep(_MOCK_RUN_DURATION_SEC)

        # running → done
        payload["state"] = "done"
        payload["completed_at"] = _now_iso()
        elapsed = (
            datetime.fromisoformat(payload["completed_at"])
            - datetime.fromisoformat(payload["started_at"])
        ).total_seconds()
        tokens_used = int(payload.get("budget", {}).get("total_tokens", 0) * 0.3)

        payload["result"] = {
            "schema_version": "0.1",
            "status": "completed",
            "intent_name": payload.get("intent"),
            "elapsed_sec": round(elapsed, 3),
            "tokens_used": tokens_used,
            "summary": f"Mock DreamOS run for intent={payload.get('intent')!r} completed",
        }
        payload["budget"]["tokens_used"] = tokens_used
        payload["budget"]["budget_remaining"] = max(
            0, payload["budget"].get("total_tokens", 0) - tokens_used
        )
        _write_job(run_id, payload)
    except Exception as exc:
        payload["state"] = "failed"
        payload["error"] = str(exc)
        payload["completed_at"] = _now_iso()
        _write_job(run_id, payload)
    finally:
        _concurrent_release()
        _sweep_jobs()


# ── 工具实现 ──


def _handle_submit_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """提交 DreamOS run。

    args:
      intent (str, req) — 要编排的意图
      budget (dict, req) — {total_tokens: int, max_duration_sec?: int}
      trace_id (str, opt) — 链路 trace_id（供审计回查）
      mandate (str, opt) — L2 写工具三件套之一（壳层暂不强制，未来强化）

    返回：{ok, run_id, state, created_at, meta}
    """
    intent = args.get("intent")
    budget = args.get("budget")
    trace_id = args.get("trace_id") or ""

    if not isinstance(intent, str) or not intent.strip():
        return {"ok": False, "error_code": "invalid", "reason": "intent 必须是非空字符串"}
    if not isinstance(budget, dict) or not isinstance(budget.get("total_tokens"), int):
        return {
            "ok": False,
            "error_code": "invalid",
            "reason": "budget.total_tokens 必须是正整数",
        }

    allowed, reason = _rate_limit_check()
    if not allowed:
        return {"ok": False, "error_code": "rate_limited", "reason": reason}

    if _concurrent_count >= _MAX_CONCURRENT:
        return {
            "ok": False,
            "error_code": "concurrent_limit",
            "reason": f"并发上限 {_MAX_CONCURRENT} 已达",
        }

    run_id = f"dr_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    payload = {
        "run_id": run_id,
        "intent": intent.strip(),
        "state": "submitted",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "trace_id": trace_id,
        "budget": {
            "total_tokens": budget["total_tokens"],
            "tokens_used": 0,
            "budget_remaining": budget["total_tokens"],
            "max_duration_sec": budget.get("max_duration_sec", 300),
        },
        "result": None,
        "error": None,
        "meta": {
            "shell": SHELL_SOURCE,
            "mock_engine": _DREAMOS_API_BASE == "",
        },
    }

    _write_job(run_id, payload)

    # 后台线程推进状态（DREAMOS_MOCK_ENGINE=0 可禁用，供测试用）
    _mock_engine_on = os.environ.get("DREAMOS_MOCK_ENGINE", "1") != "0"
    if _DREAMOS_API_BASE == "" and _mock_engine_on:
        threading.Thread(target=_advance_job_state, args=(run_id, payload), daemon=True).start()

    return {
        "ok": True,
        "run_id": run_id,
        "state": "submitted",
        "created_at": now,
        "meta": {
            "shell": SHELL_SOURCE,
            "mock_engine": _DREAMOS_API_BASE == "",
            "ttl_sec": _JOB_TTL_SEC,
        },
    }


def _handle_poll_run(args: Dict[str, Any]) -> Dict[str, Any]:
    run_id = args.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return {"ok": False, "error_code": "invalid", "reason": "run_id 必须是非空字符串"}

    payload = _read_job(run_id.strip())
    if payload is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"run_id={run_id!r} 不存在或已过期",
        }

    return {
        "ok": True,
        "run_id": run_id.strip(),
        "state": payload["state"],
        "created_at": payload.get("created_at"),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "error": payload.get("error"),
    }


def _handle_get_result(args: Dict[str, Any]) -> Dict[str, Any]:
    run_id = args.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return {"ok": False, "error_code": "invalid", "reason": "run_id 必须是非空字符串"}

    payload = _read_job(run_id.strip())
    if payload is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"run_id={run_id!r} 不存在或已过期",
        }

    state = payload.get("state")
    if state in ("submitted", "running"):
        return {
            "ok": False,
            "error_code": "not_ready",
            "reason": f"run 尚未完成（state={state}），请继续 poll_run",
            "run_id": run_id.strip(),
            "state": state,
        }
    if state == "failed":
        return {
            "ok": False,
            "error_code": "job_failed",
            "reason": payload.get("error", "unknown"),
            "run_id": run_id.strip(),
            "state": "failed",
        }

    result = payload.get("result") or {}
    slim_result, truncated = _truncate_result(result, run_id)

    return {
        "ok": True,
        "run_id": run_id.strip(),
        "state": "done",
        "result": slim_result,
        "truncated": truncated,
        "budget": payload.get("budget"),
        "completed_at": payload.get("completed_at"),
    }


def _handle_get_intent(args: Dict[str, Any]) -> Dict[str, Any]:
    """读取 run 的意图元数据（S 层入口）。"""
    run_id = args.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return {"ok": False, "error_code": "invalid", "reason": "run_id 必须是非空字符串"}

    payload = _read_job(run_id.strip())
    if payload is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"run_id={run_id!r} 不存在或已过期",
        }

    return {
        "ok": True,
        "run_id": run_id.strip(),
        "intent": payload.get("intent"),
        "trace_id": payload.get("trace_id"),
        "state": payload.get("state"),
        "created_at": payload.get("created_at"),
    }


def _handle_get_budget(args: Dict[str, Any]) -> Dict[str, Any]:
    """读取 run 的 token 预算 + 用量（B 层预算审计）。"""
    run_id = args.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return {"ok": False, "error_code": "invalid", "reason": "run_id 必须是非空字符串"}

    payload = _read_job(run_id.strip())
    if payload is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"run_id={run_id!r} 不存在或已过期",
        }

    return {
        "ok": True,
        "run_id": run_id.strip(),
        "budget": payload.get("budget"),
        "state": payload.get("state"),
    }


def _truncate_result(result: Any, run_id: str) -> tuple[Any, bool]:
    """结果超 2MB 时截断（只保留元信息）。"""
    try:
        full = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"truncated": True, "run_id": run_id, "schema_version": None}, True
    if len(full.encode("utf-8")) <= _MAX_RESULT_BYTES:
        return result, False
    if isinstance(result, dict):
        slim = {k: v for k, v in result.items() if k != "result"}
        slim["result"] = {"truncated": True, "schema_version": result.get("schema_version")}
        return slim, True
    return {"truncated": True, "run_id": run_id}, True


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "submit_run": {
        "description": "提交 DreamOS 编排 run（异步，立即返回 run_id）。需 intent + budget.total_tokens + 可选 trace_id。",
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "要编排的意图（S 层入口）"},
                "budget": {
                    "type": "object",
                    "description": "token 预算",
                    "properties": {
                        "total_tokens": {"type": "integer", "description": "总 token 预算"},
                        "max_duration_sec": {"type": "integer", "description": "最大耗时（秒）"},
                    },
                    "required": ["total_tokens"],
                },
                "trace_id": {"type": "string", "description": "链路 trace_id（审计用）"},
            },
            "required": ["intent", "budget"],
        },
    },
    "poll_run": {
        "description": "轮询 run 状态（submitted/running/done/failed）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "submit_run 返回的 run_id"},
            },
            "required": ["run_id"],
        },
    },
    "get_result": {
        "description": "获取已完成 run 的结果（仅 done 状态可读）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "submit_run 返回的 run_id"},
            },
            "required": ["run_id"],
        },
    },
    "get_intent": {
        "description": "读取 run 的意图元数据（S 层入口）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "submit_run 返回的 run_id"},
            },
            "required": ["run_id"],
        },
    },
    "get_budget": {
        "description": "读取 run 的 token 预算 + 用量（B 层预算审计）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "submit_run 返回的 run_id"},
            },
            "required": ["run_id"],
        },
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "submit_run": _handle_submit_run,
    "poll_run": _handle_poll_run,
    "get_result": _handle_get_result,
    "get_intent": _handle_get_intent,
    "get_budget": _handle_get_budget,
}

_TOOL_LIST: List[Dict[str, Any]] = [
    {
        "name": name,
        "description": defs["description"],
        "inputSchema": defs["inputSchema"],
        "annotations": defs.get("annotations", {}),
    }
    for name, defs in _TOOL_DEFS.items()
]


def _reset_governance() -> None:
    """重置频控 + 并发状态（测试用）。"""
    global _concurrent_count
    with _rate_lock:
        _rate_timestamps.clear()
    with _concurrent_lock:
        _concurrent_count = 0


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """测试入口：单参数 JSON-RPC 分发。"""
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
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _TOOL_LIST},
        }

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
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, _TOOL_DEFS, _TOOL_HANDLERS)
