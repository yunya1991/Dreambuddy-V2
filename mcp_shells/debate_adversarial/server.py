#!/usr/bin/env python3
"""mcp_shells/debate_adversarial/server.py — 32 对抗性辩论 Bot 的 MCP 壳。

工具（3 个）：
  - start_debate      启动一场结构化对抗评审（异步 job，立即返回 debate_id）
  - get_debate_result 轮询 job 状态/结果
  - health            配置/连通性自检（deep=true 时做一次 LLM ping）

设计：
  - stdio JSON-RPC 2.0，按需拉起；
  - 辩论耗时 30-90s，故 start_debate 用后台线程 + job 文件，不阻塞 MCP 调用；
  - 统一 L0 信封（envelope_wrap）；
  - 只读计算，无交易/无写外部状态；job 文件仅落本地 runtime。

环境：
  - LLM 走 core.llm_compat 自动探测（ANTHROPIC_* 优先，其次 DASHSCOPE_API_KEY）
  - DEBATE_PROVIDER / DEBATE_MODEL 可覆盖
  - DEBATE_MAX_ROUNDS（默认 3）、DEBATE_MAX_BACKGROUND_CHARS（默认 20000）
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BOT_ROOT = _REPO_ROOT / "32-对抗性辩论Bot"
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "agent.debate.mcp"
_JOB_DIR = Path(__file__).resolve().parent / "runtime" / "jobs"
_JOB_DIR.mkdir(parents=True, exist_ok=True)

_MAX_ROUNDS = int(os.environ.get("DEBATE_MAX_ROUNDS", "3"))
_MAX_BACKGROUND = int(os.environ.get("DEBATE_MAX_BACKGROUND_CHARS", "20000"))
_MAX_TOPIC = 2000

# ── M10 频控 / 并发 / Job 生命周期 ─────────────────────────────
_RATE_LIMIT_PER_MIN = int(os.environ.get("DEBATE_RATE_LIMIT_PER_MIN", "2"))
_RATE_LIMIT_WINDOW_SEC = 60.0
_MAX_CONCURRENT = int(os.environ.get("DEBATE_MAX_CONCURRENT", "2"))
_JOB_TTL_SEC = int(os.environ.get("DEBATE_JOB_TTL_SEC", str(24 * 3600)))  # 24h
_MAX_JOBS = int(os.environ.get("DEBATE_MAX_JOBS", "100"))
_MAX_RESULT_BYTES = int(os.environ.get("DEBATE_MAX_RESULT_BYTES", str(1024 * 1024)))  # 1MB

_rate_lock = threading.Lock()
_rate_timestamps: list[float] = []  # 滑动窗口内的 start_debate 时间戳

_concurrent_lock = threading.Lock()
_concurrent_count = 0  # 正在运行的 debate job 数


def _settings(provider: str | None = None, model: str | None = None):
    from core.llm_compat import LLMSettings

    return LLMSettings(
        provider=provider or os.environ.get("DEBATE_PROVIDER", "auto"),
        model=model or os.environ.get("DEBATE_MODEL"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        timeout_sec=float(os.environ.get("DEBATE_TIMEOUT_SEC", "90")),
        max_retries=int(os.environ.get("DEBATE_MAX_RETRIES", "2")),
    )


def _job_path(debate_id: str) -> Path:
    return _JOB_DIR / f"{debate_id}.json"


def _write_job(debate_id: str, payload: dict[str, Any]) -> None:
    target = _job_path(debate_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _read_job(debate_id: str) -> dict[str, Any] | None:
    """读 job；对 `_write_job` 的 tmp→replace 竞争做短暂重试。"""
    path = _job_path(debate_id)
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.05)
                continue
            return None


# ── M10 频控 / 并发 / TTL 辅助 ──────────────────────────────────


def _rate_limit_check() -> tuple[bool, str]:
    """滑动窗口频控：返回 (允许, 原因)。超限不排队，直接拒绝。"""
    now = time.monotonic()
    with _rate_lock:
        # 清理窗口外的时间戳
        cutoff = now - _RATE_LIMIT_WINDOW_SEC
        _rate_timestamps[:] = [t for t in _rate_timestamps if t > cutoff]
        if len(_rate_timestamps) >= _RATE_LIMIT_PER_MIN:
            oldest = _rate_timestamps[0] if _rate_timestamps else now
            retry_after = max(1, int(_RATE_LIMIT_WINDOW_SEC - (now - oldest)))
            return False, f"rate_limited: retry_after={retry_after}s"
        _rate_timestamps.append(now)
        return True, ""


def _concurrent_acquire() -> bool:
    """尝试占用一个并发槽；返回是否成功。"""
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
    """清理过期 job 文件，并保证总数 ≤ _MAX_JOBS（保留最新的）。"""
    try:
        jobs = sorted(_JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    now = time.time()
    # 先删过期
    for path in jobs:
        try:
            mtime = path.stat().st_mtime
            if now - mtime > _JOB_TTL_SEC:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    # 再按数量上限裁剪（删最旧的）
    remaining = sorted(_JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if len(remaining) > _MAX_JOBS:
        for path in remaining[: len(remaining) - _MAX_JOBS]:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


def _truncate_result(result: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """单 job 结果 ≤ _MAX_RESULT_BYTES；超限时截断 result 字段并标记 degraded。"""
    full = json.dumps(result, ensure_ascii=False)
    if len(full.encode("utf-8")) <= _MAX_RESULT_BYTES:
        return result, False
    # 去掉大字段，只保留元信息
    slim = {k: v for k, v in result.items() if k != "result"}
    slim["result"] = {
        "truncated": True,
        "schema_version": result.get("result", {}).get("schema_version"),
    }
    slim["degraded"] = True
    return slim, True


def _reset_governance() -> None:
    """重置频控与并发状态（仅供测试）。"""
    global _concurrent_count
    with _rate_lock:
        _rate_timestamps.clear()
    with _concurrent_lock:
        _concurrent_count = 0


def _is_job_expired(job: dict[str, Any]) -> bool:
    """根据 created_at 判断 job 是否超过 TTL。"""
    created = job.get("created_at")
    if not isinstance(created, str):
        return False
    try:
        created_ts = datetime.fromisoformat(created).timestamp()
    except (ValueError, TypeError):
        return False
    return (time.time() - created_ts) > _JOB_TTL_SEC


def _run_job(
    debate_id: str,
    mode: str,
    topic: str,
    background: str,
    rounds: int,
    judge: bool,
    provider: str | None,
    model: str | None,
    research: bool = False,
    research_sources: list[str] | None = None,
    research_max_items: int = 8,
    cross_examination: bool = False,
    adjudication: bool = True,
    profile: str = "auto",
) -> None:
    created_iso = datetime.now().isoformat()
    payload = {
        "debate_id": debate_id,
        "status": "running",
        "mode": mode,
        "profile": profile,
        "research": research,
        "cross_examination": cross_examination,
        "adjudication": adjudication,
        "topic": topic,
        "rounds": rounds,
        "created_at": created_iso,
        "started_at": created_iso,
        "expires_at": datetime.fromtimestamp(
            datetime.fromisoformat(created_iso).timestamp() + _JOB_TTL_SEC
        ).isoformat(),
    }
    _write_job(debate_id, payload)
    try:
        if mode == "review":
            from core.review_runner import run_review_sync

            result = run_review_sync(
                topic,
                background=background,
                rounds=rounds,
                judge=judge,
                settings=_settings(provider, model),
                research=research,
                research_sources=research_sources,
                research_max_items=research_max_items,
                debate_id=debate_id,
                cross_examination=cross_examination,
                adjudication=adjudication,
                profile=profile if profile != "auto" else "technical",
                timeout=float(os.environ.get("DEBATE_JOB_TIMEOUT_SEC", "180")),
            ).to_dict()
        else:
            from core.dsh_backend import run_dsh_debate_sync

            result = run_dsh_debate_sync(
                mode,
                topic,
                background,
                settings=_settings(provider, model),
                research=research,
                research_sources=research_sources,
                research_max_items=research_max_items,
                debate_id=debate_id,
                profile=profile,
            )
        payload.update(
            {
                "status": "completed",
                "completed_at": datetime.now().isoformat(),
                "result": result,
            }
        )
    except Exception as exc:  # noqa: BLE001 — job 失败落盘，不崩溃壳
        payload.update(
            {
                "status": "error",
                "completed_at": datetime.now().isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        _concurrent_release()
    # M10: 单 job 结果 ≤ _MAX_RESULT_BYTES
    payload, truncated = _truncate_result(payload)
    if truncated:
        payload["degraded"] = True
        payload["result_truncated"] = True
    _write_job(debate_id, payload)


def start_debate(arguments: dict[str, Any]) -> str:
    topic = str(arguments.get("topic") or "").strip()
    if not topic:
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "start_debate", "reason": "topic required"},
            ),
            ensure_ascii=False,
        )
    if len(topic) > _MAX_TOPIC:
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "start_debate", "reason": f"topic > {_MAX_TOPIC}"},
            ),
            ensure_ascii=False,
        )
    mode = str(arguments.get("mode") or "review").strip().lower()
    if mode not in ("review", "fast", "deep"):
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "start_debate", "reason": f"invalid mode: {mode}"},
            ),
            ensure_ascii=False,
        )
    rounds = max(1, min(int(arguments.get("rounds", 2)), _MAX_ROUNDS))
    background = str(arguments.get("background") or "")[:_MAX_BACKGROUND]
    judge = bool(arguments.get("judge", True))
    provider = arguments.get("provider")
    model = arguments.get("model")
    research = bool(arguments.get("research", False))
    raw_sources = arguments.get("research_sources") or []
    if isinstance(raw_sources, str):
        raw_sources = [s.strip() for s in raw_sources.split(",") if s.strip()]
    research_sources = list(raw_sources) if isinstance(raw_sources, list) else None
    research_max_items = max(1, min(int(arguments.get("research_max_items", 8)), 12))
    cross_examination = bool(arguments.get("cross_examination", False))
    adjudication = bool(arguments.get("adjudication", True))
    profile = str(arguments.get("profile") or "auto").strip().lower()
    if profile not in ("auto", "marketing", "technical", "signal", "generic"):
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "start_debate", "reason": f"invalid profile: {profile}"},
            ),
            ensure_ascii=False,
        )
    if profile in ("marketing", "technical") and mode != "review":
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "start_debate", "reason": f"profile {profile} 仅支持 mode=review"},
            ),
            ensure_ascii=False,
        )

    # M10: 清理过期 job + 控制总数
    _sweep_jobs()

    # M10: 频控（≤2/min/Worker），超限直接拒绝，不排队
    allowed, reason = _rate_limit_check()
    if not allowed:
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="timeout",
                meta={"tool": "start_debate", "reason": reason},
            ),
            ensure_ascii=False,
        )

    # M10: 并发上限（≤2），超限拒绝
    if not _concurrent_acquire():
        # 释放频控配额（未真正启动）
        with _rate_lock:
            if _rate_timestamps:
                _rate_timestamps.pop()
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="timeout",
                meta={
                    "tool": "start_debate",
                    "reason": f"concurrency_limit: max {_MAX_CONCURRENT} running",
                },
            ),
            ensure_ascii=False,
        )

    created_iso = datetime.now().isoformat()
    debate_id = uuid.uuid4().hex[:12]
    _write_job(
        debate_id,
        {
            "debate_id": debate_id,
            "status": "queued",
            "topic": topic,
            "rounds": rounds,
            "created_at": created_iso,
            "expires_at": datetime.fromtimestamp(
                datetime.fromisoformat(created_iso).timestamp() + _JOB_TTL_SEC
            ).isoformat(),
        },
    )
    thread = threading.Thread(
        target=_run_job,
        args=(
            debate_id,
            mode,
            topic,
            background,
            rounds,
            judge,
            provider,
            model,
            research,
            research_sources,
            research_max_items,
            cross_examination,
            adjudication,
            profile,
        ),
        daemon=True,
        name=f"debate-{debate_id}",
    )
    thread.start()
    return json.dumps(
        wrap(
            {"debate_id": debate_id, "status": "running", "rounds": rounds},
            SHELL_SOURCE,
            meta={"tool": "start_debate", "judge": judge},
        ),
        ensure_ascii=False,
    )


def get_debate_result(arguments: dict[str, Any]) -> str:
    debate_id = str(arguments.get("debate_id") or "").strip()
    if not debate_id:
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"tool": "get_debate_result", "reason": "debate_id required"},
            ),
            ensure_ascii=False,
        )
    job = _read_job(debate_id)
    if job is None:
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"tool": "get_debate_result", "debate_id": debate_id},
            ),
            ensure_ascii=False,
        )
    # M10: TTL 过期则清理文件并返回 not_found
    if _is_job_expired(job):
        _job_path(debate_id).unlink(missing_ok=True)
        return json.dumps(
            wrap(
                {},
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"tool": "get_debate_result", "debate_id": debate_id, "reason": "expired"},
            ),
            ensure_ascii=False,
        )
    return json.dumps(
        wrap(job, SHELL_SOURCE, meta={"tool": "get_debate_result"}),
        ensure_ascii=False,
    )


def health(arguments: dict[str, Any]) -> str:
    deep = bool(arguments.get("deep", False))
    info: dict[str, Any] = {
        "shell": SHELL_SOURCE,
        "job_dir": str(_JOB_DIR),
        "jobs": len(list(_JOB_DIR.glob("*.json"))),
        "llm_provider_env": os.environ.get("DEBATE_PROVIDER", "auto"),
        "anthropic_env": bool(
            os.environ.get("ANTHROPIC_AUTH_TOKEN") and os.environ.get("ANTHROPIC_BASE_URL")
        ),
        "dashscope_env": bool(os.environ.get("DASHSCOPE_API_KEY")),
        "m10_rate_limit_per_min": _RATE_LIMIT_PER_MIN,
        "m10_max_concurrent": _MAX_CONCURRENT,
        "m10_job_ttl_sec": _JOB_TTL_SEC,
        "m10_max_jobs": _MAX_JOBS,
        "m10_max_result_bytes": _MAX_RESULT_BYTES,
    }
    degraded = False
    if deep:
        try:
            import asyncio

            from core.llm_compat import health_check

            check = asyncio.run(health_check(_settings()))
            info["llm_check"] = check
            degraded = not check.get("ok", False)
        except Exception as exc:  # noqa: BLE001
            info["llm_check"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            degraded = True
    return json.dumps(
        wrap(
            info,
            SHELL_SOURCE,
            degraded=degraded,
            error_code="unavailable" if degraded else "",
            meta={"tool": "health"},
        ),
        ensure_ascii=False,
    )


# 工具名与函数名对齐，便于 MCP 调用方/测试直接引用
debate_health = health


_TOOLS = [
    {
        "name": "start_debate",
        "description": "启动一场结构化对抗评审（异步 job）。返回 debate_id，用 get_debate_result 轮询。M10 频控：≤2 次/分钟/Worker、并发 ≤2，超限返回 timeout；job TTL 24h。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "评审命题"},
                "mode": {
                    "type": "string",
                    "enum": ["review", "fast", "deep"],
                    "default": "review",
                    "description": "review=结构化评审；fast=DSH 1 轮并行；deep=DSH 2 轮+Judge+6 维评分",
                },
                "background": {"type": "string", "description": "背景材料（可选）"},
                "rounds": {"type": "integer", "default": 2, "minimum": 1, "maximum": _MAX_ROUNDS},
                "judge": {"type": "boolean", "default": True},
                "research": {
                    "type": "boolean",
                    "default": False,
                    "description": "启用 Research Prepass（只读 L0 MCP + 本地代码检索）",
                },
                "research_sources": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "unified_search",
                            "recall",
                            "code",
                            "code_search",
                            "l1_signal",
                            "l1_bus",
                            "l1_cycle",
                            "l1",
                            "l1_trading",
                        ],
                    },
                },
                "research_max_items": {
                    "type": "integer",
                    "default": 8,
                    "minimum": 1,
                    "maximum": 12,
                },
                "cross_examination": {
                    "type": "boolean",
                    "default": False,
                    "description": "review 模式第 1 轮后插入双向交叉质询",
                },
                "adjudication": {
                    "type": "boolean",
                    "default": True,
                    "description": "review 模式生成 6 维评分；deep 固定生成，fast 固定 null",
                },
                "profile": {
                    "type": "string",
                    "enum": ["auto", "marketing", "technical", "signal"],
                    "default": "auto",
                    "description": "角色 profile；auto=review→technical、fast/deep→generic；C-Drive 信号用 signal",
                },
                "provider": {
                    "type": "string",
                    "enum": ["auto", "anthropic", "openai_compat", "langchain"],
                },
                "model": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "get_debate_result",
        "description": "按 debate_id 读取 job 状态/结果（running/completed/error）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"debate_id": {"type": "string"}},
            "required": ["debate_id"],
        },
    },
    {
        "name": "debate_health",
        "description": "壳配置/LLM 连通性自检；deep=true 会做一次 LLM ping。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"deep": {"type": "boolean", "default": False}},
        },
    },
]

TOOL_DEFS = {
    t["name"]: {
        "description": t.get("description", ""),
        "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
    }
    for t in _TOOLS
}

_TOOL_HANDLERS = {
    "start_debate": start_debate,
    "get_debate_result": get_debate_result,
    "debate_health": health,
}


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, TOOL_DEFS, _TOOL_HANDLERS)
