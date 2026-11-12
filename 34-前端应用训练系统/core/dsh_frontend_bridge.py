# -*- coding: utf-8 -*-
"""DSH 前端统一桥 — 所有前端 adapter 的唯一 Python 入口（B 方案）。

设计:
  - 前端 → 本桥 → call_worker_tool 完整链路 (mandate_gate → tool→shell_map
    → ShellHandleManager → ShellHandle.call)
  - ShellHandleManager 生命周期: 本模块单例, 进程内共享
  - launcher_factory 根据 47 registry spec.transport 选 launcher:
      stdio      → stdio_shell_launcher.stdio_launcher
      ssh-stdio  → ssh_shell_launcher.ssh_launcher
      in-process → InProcessShell 包装直接 import 的 handler 函数
  - InProcessShell: 给不跑 MCP stdio 协议的本地 handler 用(8 SubAgent,
    orchestrator, C-Drive, synthesizer 等); 不走 JSON-RPC, 直接函数调用,
    实现 .call/.is_alive/.close 壳接口契约, 让 ShellHandleManager 统一管理

CLI 用法 (前端 scripts/ 调):
  python3 dsh_frontend_bridge.py call <role> <tool> '<args_json>'
  python3 dsh_frontend_bridge.py handler <handler_name> '<args_json>'

硬约束:
  HC-1 FAIL-OPEN: 任一层异常 → {ok:false, error_code:"unavailable", meta.degraded:true}
  HC-2 进程内单例: ShellHandleManager 本模块缓存, 避免重复拉起壳
  HC-3 向后兼容: handler 子命令保留现有 dsh_adapter.py 调用格式
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

# ── 进程内 handler 注册表 (非 MCP shell, 直接函数调用) ───────────────
# transport="in-process" 的壳不走 47 registry (47 registry 是 MCP 壳),
# 这里维护本地 handler 映射: {shell_id: (module_path, callable_name)}
# 这些 handler 直接 import 调用, 包装为 InProcessShell 后统一进 ShellHandleManager.

IN_PROCESS_HANDLERS: Dict[str, Dict[str, Any]] = {
    # 8 SubAgent — python-server handle_* 函数
    "subagent.technical": {
        "module": "technical_agent",
        "handler": "handle_technical_agent",
        "tools": ["technical_agent"],
    },
    "subagent.sentiment": {
        "module": "sentiment_agent",
        "handler": "handle_sentiment_agent",
        "tools": ["sentiment_agent"],
    },
    "subagent.macro": {
        "module": "macro_agent",
        "handler": "handle_macro_agent",
        "tools": ["macro_agent"],
    },
    "subagent.flow": {
        "module": "flow_agent",
        "handler": "handle_flow_agent",
        "tools": ["flow_agent"],
    },
    "subagent.valuation": {
        "module": "valuation_agent",
        "handler": "handle_valuation_agent",
        "tools": ["valuation_agent"],
    },
    "subagent.onchain": {
        "module": "onchain_agent",
        "handler": "handle_onchain_agent",
        "tools": ["onchain_agent"],
    },
    "subagent.risk": {
        "module": "risk_agent",
        "handler": "handle_risk_agent",
        "tools": ["risk_agent"],
    },
    "subagent.portfolio": {
        "module": "portfolio_agent",
        "handler": "handle_portfolio_agent",
        "tools": ["portfolio_agent"],
    },
    # C-Drive + 辩论
    "c-drive": {"module": "c_drive_agent", "handler": "handle_c_drive_agent", "tools": ["c_drive"]},
    "c-drive.debate": {"module": "c_drive_agent", "handler": "handle_debate", "tools": ["debate"]},
    # Synthesizer
    "synthesizer": {
        "module": "synthesizer_agent",
        "handler": "handle_synthesizer_agent",
        "tools": ["synthesizer"],
    },
    # OrchestratorV2 (内联 import, 不走 python-server)
    "orchestrator": {
        "module": None,
        "handler": "_handle_orchestrator_v2",
        "tools": ["orchestrator"],
    },
    # OrchestratorV2 异步作业查询 (配合 orchestrator 的 async=True 提交)
    "orchestrator.status": {
        "module": None,
        "handler": "_handle_orchestrator_status",
        "tools": ["status"],
    },
    # Knowledge search (RAG: fts/vector/hybrid)
    "knowledge.search": {
        "module": None,
        "handler": "_handle_knowledge_search",
        "tools": ["search"],
    },
    # Skill index (scan_skills/build_registry/drift/conflicts)
    "skill.index": {
        "module": None,
        "handler": "_handle_skill_index",
        "tools": ["list", "query", "drift", "conflicts", "stats"],
    },
    # User memory (SQLite user_memory.db, 与认知系统物理隔离)
    "user.memory": {
        "module": None,
        "handler": "_handle_user_memory",
        "tools": ["get", "put", "delete", "list", "search"],
    },
    # Data DAL query (SQLite mm_metrics: chain/market/macro 指标查询)
    "data.dal_query": {
        "module": None,
        "handler": "_handle_dal_query",
        "tools": ["chain", "market", "macro", "metric"],
    },
    # Shell runtime stats (壳健康度/调用量, 前端监控用)
    "shell.stats": {
        "module": None,
        "handler": "_handle_shell_stats",
        "tools": ["stats", "health"],
    },
}


# ── InProcessShell: 包装直接 import 的 handler ──────────────────────────


class InProcessShell:
    """把一个 module::callable 包装成壳对象, 满足 ShellHandle 契约。

    壳接口: .call(tool, args), .is_alive(), .close()
    实际调用: handler(args) —— handler 自带 tool 信息 (或 tool=handler_name)
    """

    def __init__(self, handler_fn: Callable[..., Any], shell_id: str):
        self._handler = handler_fn
        self._shell_id = shell_id
        self._alive = True
        self._closed = False

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用包装的 handler; 异常 → 统一信封。"""
        if self._closed:
            return {
                "ok": False,
                "error_code": "shell_degraded",
                "meta": {"reason": "in_process_shell_closed", "shell_id": self._shell_id},
            }
        try:
            payload = dict(args) if isinstance(args, dict) else {}
            # 内联 handler (如 orchestrator) 自带 node_output 包装
            result = self._handler(payload)
            # handler 可能返回统一信封 {ok, data, ...} 或裸值
            if isinstance(result, dict) and ("ok" in result or "error_code" in result):
                return result
            return {
                "ok": True,
                "data": result,
                "error_code": None,
                "meta": {"shell_id": self._shell_id},
            }
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "shell_degraded",
                "meta": {"reason": f"{type(exc).__name__}: {exc}", "shell_id": self._shell_id},
            }

    def is_alive(self) -> bool:
        return self._alive and not self._closed

    def close(self) -> None:
        self._alive = False
        self._closed = True


# ── launcher 工厂 ──────────────────────────────────────────────────────


def _resolve_34_core_dir() -> str:
    """解析 34-前端应用训练系统/core 绝对路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return here


def _resolve_repo_root() -> str:
    """解析 dreambuddy-v2 仓库根 (47 registry 的 ../../ 位置)。"""
    core_dir = _resolve_34_core_dir()
    return os.path.normpath(os.path.join(core_dir, "..", ".."))


def _import_python_server(script_dir: str) -> Optional[str]:
    """尝试把 1-ARCHITECTURE/dream-harness-bridge/packages/python-server 加入 sys.path。"""
    repo_root = _resolve_repo_root()
    candidate = os.path.normpath(
        os.path.join(
            repo_root, "1-ARCHITECTURE", "dream-harness-bridge", "packages", "python-server"
        )
    )
    if os.path.isdir(candidate):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        return candidate
    # fallback: dsh_adapter.py 原有路径解析
    candidate2 = os.path.normpath(
        os.path.join(
            script_dir,
            "..",
            "..",
            "1-ARCHITECTURE",
            "dream-harness-bridge",
            "packages",
            "python-server",
        )
    )
    if os.path.isdir(candidate2):
        if candidate2 not in sys.path:
            sys.path.insert(0, candidate2)
        return candidate2
    return None


def _resolve_dreamos_root() -> Optional[str]:
    """解析 dreamos 模块根 (orchestrator_v2 需要)。"""
    repo_root = _resolve_repo_root()
    dreamos_parent = os.path.join(repo_root, "1-ARCHITECTURE")
    if os.path.isdir(os.path.join(dreamos_parent, "dreamos")):
        if dreamos_parent not in sys.path:
            sys.path.insert(0, dreamos_parent)
        return dreamos_parent
    return None


def _load_inprocess_handler(shell_id: str) -> Optional[Callable[..., Any]]:
    """加载 in-process handler 函数 (import 模块 + getattr callable)。"""
    spec = IN_PROCESS_HANDLERS.get(shell_id)
    if spec is None:
        return None
    module_name = spec.get("module")
    handler_name = spec["handler"]

    if module_name is None:
        # 内联 handler (如 _handle_orchestrator_v2) — 在本模块 globals 里
        fn = globals().get(handler_name)
        if callable(fn):
            return fn
        return None

    # 需要 import python-server
    ps_dir = _import_python_server(_resolve_34_core_dir())
    if ps_dir is None:
        return None
    try:
        mod = __import__(module_name)
        return getattr(mod, handler_name)
    except Exception:
        return None


# ── OrchestratorV2 异步作业表 (进程内单例, 与 ShellHandleManager 同生命周期) ──

_ORCH_JOBS: Dict[str, Dict[str, Any]] = {}
_ORCH_JOBS_LOCK = threading.Lock()
_ORCH_JOB_TTL_S = 3600.0  # 完成后的作业保留 1 小时，供前端轮询补取


def _run_orchestrator_cycle(node_output: Dict[str, Any]) -> Dict[str, Any]:
    """同步执行一次 OrchestratorV2.run_cycle()（原有实现，未改语义）。"""
    if not isinstance(node_output, dict):
        node_output = {}
    symbol = node_output.get("symbol", "BTC")
    market_data = node_output.get("market_data") or {"symbol": symbol}

    if _resolve_dreamos_root() is None:
        # dreamos/ 已归档：这是结构性归档，不是运行时故障，用独立原因码区分
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": "dreamos_archived"},
        }

    try:
        from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"orchestrator_import_failed: {type(e).__name__}: {e}"},
        }

    try:
        orch = OrchestratorV2(use_hermes=False)
        cycle_result = orch.run_cycle(market_data)
        signal = cycle_result.get("signal", {})
        status = cycle_result.get("status", "FAILED")
        confidence = 0.7 if status == "COMPLETED" else 0.4
        return {
            "ok": True,
            "data": {
                "cycle_id": cycle_result.get("cycle_id", ""),
                "status": status,
                "selection": cycle_result.get("selection", {}),
                "signal": signal,
                "execution": cycle_result.get("execution", {}),
                "review": cycle_result.get("review", {}),
                "bayesian_triggered": cycle_result.get("bayesian_triggered", False),
                "errors": cycle_result.get("errors", []),
                "direction": signal.get("direction", "HOLD"),
                "confidence": signal.get("confidence", confidence),
                "source": "orchestrator-v2",
            },
            "error_code": None,
            "meta": {"shell_id": "orchestrator"},
        }
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"orchestrator_error: {type(e).__name__}: {e}"},
        }


def _prune_orchestrator_jobs(now: float) -> None:
    """清理超过 TTL 的已完成作业（调用方需持锁）。"""
    expired = [
        jid
        for jid, job in _ORCH_JOBS.items()
        if job.get("status") == "done"
        and now - float(job.get("finished_at") or now) > _ORCH_JOB_TTL_S
    ]
    for jid in expired:
        _ORCH_JOBS.pop(jid, None)


def _to_ipc_envelope(handler_result: Any) -> Dict[str, Any]:
    """把 handler 级返回 {ok, data|error_code, meta} 归一成 call_handler 的 {ok, output}。"""
    if not isinstance(handler_result, dict):
        return {"ok": True, "output": handler_result}
    if handler_result.get("ok") is False:
        return {
            "ok": False,
            "error": handler_result.get("error_code") or "orchestrator_failed",
            "meta": handler_result.get("meta", {}),
        }
    data = handler_result.get("data")
    if isinstance(data, dict) and "output" in data:
        return {"ok": True, "output": data.get("output")}
    return {"ok": True, "output": data, "meta": handler_result.get("meta", {})}


def _orchestrator_job_worker(job_id: str, node_output: Dict[str, Any]) -> None:
    """后台线程：执行 run_cycle 并把结果写回作业表（异常也落库，避免前端永远 pending）。"""
    try:
        result = _to_ipc_envelope(_run_orchestrator_cycle(node_output))
    except Exception as e:  # noqa: BLE001 FAIL-OPEN
        result = {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"orchestrator_worker_error: {type(e).__name__}: {e}"},
        }
    with _ORCH_JOBS_LOCK:
        job = _ORCH_JOBS.get(job_id)
        if job is not None:
            job["status"] = "done"
            job["result"] = result
            job["finished_at"] = time.time()


def _handle_orchestrator_v2(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: OrchestratorV2.run_cycle()。

    async=True（或 mode="async"）→ 提交作业立即返回 job_id；
    默认仍为同步执行（本地 IPC 兼容路径）。
    """
    node_output = args.get("node_output", args) if isinstance(args, dict) else {}
    if not isinstance(node_output, dict):
        node_output = {}

    if isinstance(args, dict) and (args.get("async") is True or args.get("mode") == "async"):
        job_id = uuid.uuid4().hex
        now = time.time()
        with _ORCH_JOBS_LOCK:
            _prune_orchestrator_jobs(now)
            _ORCH_JOBS[job_id] = {
                "status": "pending",
                "created_at": now,
                "finished_at": None,
                "result": None,
            }
        threading.Thread(
            target=_orchestrator_job_worker,
            args=(job_id, node_output),
            daemon=True,
        ).start()
        return {
            "ok": True,
            "data": {"status": "accepted", "job_id": job_id},
            "error_code": None,
            "meta": {"shell_id": "orchestrator", "mode": "async"},
        }

    return _run_orchestrator_cycle(node_output)


def _handle_orchestrator_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """查询异步 orchestrator 作业：pending → {status:"pending"}；done → 原样回传结果。

    done 分支把结果放进 data.output，使 call_handler 走「透传 output」分支，
    返回结构与同步调用完全一致（{ok, output}），前端无需区分同步/异步。
    """
    job_id = args.get("job_id") if isinstance(args, dict) else None
    if not isinstance(job_id, str) or not job_id:
        return {
            "ok": False,
            "error_code": "bad_request",
            "meta": {"reason": "job_id must be a non-empty string"},
        }

    with _ORCH_JOBS_LOCK:
        job = _ORCH_JOBS.get(job_id)
        status = None if job is None else job.get("status")
        result = None if job is None else job.get("result")

    if status is None:
        return {
            "ok": False,
            "error_code": "job_not_found",
            "meta": {"job_id": job_id},
        }
    if status != "done":
        return {
            "ok": True,
            "data": {"job_id": job_id, "status": "pending"},
            "error_code": None,
            "meta": {"shell_id": "orchestrator.status"},
        }
    return {
        "ok": True,
        "data": {"job_id": job_id, "status": "done", "output": result},
        "error_code": None,
        "meta": {"shell_id": "orchestrator.status"},
    }


# ── Knowledge search handler ──────────────────────────────────────────


def _resolve_rag_infra_dir() -> Optional[str]:
    repo_root = _resolve_repo_root()
    candidate = os.path.normpath(os.path.join(repo_root, "2-KNOWLEDGE", "9-RAG-INFRA"))
    if os.path.isdir(candidate):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        return candidate
    return None


def _handle_knowledge_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: RAG 检索 (fts/vector/hybrid), 包装 knowledge_search_adapter.py 原逻辑。"""
    rag_dir = _resolve_rag_infra_dir()
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    method = args.get("method", "hybrid")

    if not query:
        return {
            "ok": True,
            "data": {"results": [], "method": method, "degraded": False},
            "error_code": None,
            "meta": {"shell_id": "knowledge.search"},
        }
    if rag_dir is None:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": "rag_infra_not_found"},
        }

    _keyword_search = _hybrid_search = _vector_search = None
    try:
        from rag_engine.keyword_search import keyword_search as _keyword_search  # noqa: F811
    except Exception:
        pass
    try:
        from rag_engine.hybrid_retriever import hybrid_search as _hybrid_search  # noqa: F811
    except Exception:
        pass
    try:
        from vector_store.search import search as _vector_search  # noqa: F811
    except Exception:
        pass

    results, degraded = [], False
    try:
        if method == "fts":
            if _keyword_search:
                raw = _keyword_search(query, top_k=top_k)
                results = _format_knowledge_results(raw, "fts")
            else:
                degraded = True
        elif method == "vector":
            if _vector_search:
                raw = _vector_search(query, top_k=top_k)
                results = _format_knowledge_results(raw, "vector")
            else:
                degraded = True
        else:
            if _hybrid_search:
                raw = _hybrid_search(query, top_k=top_k)
                results = _format_knowledge_results(raw, "hybrid")
            elif _keyword_search:
                raw = _keyword_search(query, top_k=top_k)
                results = _format_knowledge_results(raw, "fts")
                degraded = True
            else:
                degraded = True
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"search_error: {type(e).__name__}: {e}"},
        }

    return {
        "ok": True,
        "data": {"results": results[:top_k], "method": method, "degraded": degraded},
        "error_code": None,
        "meta": {"shell_id": "knowledge.search"},
    }


def _format_knowledge_results(raw, method: str) -> list:
    formatted = []
    for r in raw or []:
        formatted.append(
            {
                "content": r.get("content", ""),
                "score": round(float(r.get("score", r.get("final_score", 0))), 4),
                "source": r.get("source_file", r.get("source", "")),
                "heading": r.get("heading", ""),
                "domain": r.get("domain", ""),
            }
        )
    return formatted


# ── Skill index handler ────────────────────────────────────────────────


def _resolve_skill_indexer_dir() -> Optional[str]:
    repo_root = _resolve_repo_root()
    candidate = os.path.normpath(
        os.path.join(repo_root, "1-ARCHITECTURE", "skills", "dream-skill-index-governance")
    )
    if os.path.isdir(candidate):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        return candidate
    return None


def _handle_skill_index(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: Skill 索引 (list/query/drift/conflicts/stats), 包装 skill_index_adapter.py 原逻辑。"""
    skill_dir = _resolve_skill_indexer_dir()
    command = args.get("command", "list")
    if skill_dir is None:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": "skill_indexer_not_found"},
        }

    try:
        from skill_indexer import (
            ALL_SKILL_ROOTS,
            build_registry,
            detect_conflicts,
            detect_drift,
            scan_skills,
        )
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"skill_indexer_import_failed: {type(e).__name__}: {e}"},
        }

    try:
        roots = ALL_SKILL_ROOTS
        entries = scan_skills(roots)

        if command == "list":
            registry = build_registry(entries)
            return {
                "ok": True,
                "data": registry,
                "error_code": None,
                "meta": {"shell_id": "skill.index"},
            }

        if command == "query":
            trigger = args.get("trigger")
            category = args.get("category")
            status = args.get("status")
            matched = []
            for e in entries:
                if trigger is not None and trigger not in e.triggers:
                    continue
                if category is not None and e.category != category:
                    continue
                if status is not None and e.status != status:
                    continue
                matched.append(
                    {
                        "name": e.name,
                        "description": e.description,
                        "version": e.version,
                        "status": e.status,
                        "category": e.category,
                        "triggers": e.triggers,
                        "cognitive_links": e.cognitive_links,
                        "confidence": e.confidence,
                        "apply_count": e.apply_count,
                        "last_verified": e.last_verified,
                        "path": str(e.path),
                    }
                )
            return {
                "ok": True,
                "data": {"schema_version": "1.0", "count": len(matched), "skills": matched},
                "error_code": None,
                "meta": {"shell_id": "skill.index"},
            }

        if command == "drift":
            return {
                "ok": True,
                "data": detect_drift(entries),
                "error_code": None,
                "meta": {"shell_id": "skill.index"},
            }

        if command == "conflicts":
            return {
                "ok": True,
                "data": detect_conflicts(entries),
                "error_code": None,
                "meta": {"shell_id": "skill.index"},
            }

        if command == "stats":
            by_status, by_category = {}, {}
            for e in entries:
                by_status[e.status] = by_status.get(e.status, 0) + 1
                by_category[e.category] = by_category.get(e.category, 0) + 1
            return {
                "ok": True,
                "data": {
                    "total_count": len(entries),
                    "by_status": by_status,
                    "by_category": by_category,
                    "roots_scanned": len(roots),
                },
                "error_code": None,
                "meta": {"shell_id": "skill.index"},
            }

        return {
            "ok": False,
            "error_code": "not_found",
            "meta": {
                "reason": f"unknown command: {command}",
                "available": ["list", "query", "drift", "conflicts", "stats"],
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"skill_index_error: {type(e).__name__}: {e}"},
        }


# ── User memory handler ────────────────────────────────────────────────


def _resolve_user_memory_db() -> str:
    repo_root = _resolve_repo_root()
    # 和 user_memory_adapter.py 原有路径一致
    candidates = [
        os.path.normpath(os.path.join(repo_root, "scheduler_data", "user_memory.db")),
        os.path.normpath(os.path.join(repo_root, "3.1-FRONTEND", "scripts", "user_memory.db")),
    ]
    for c in candidates:
        d = os.path.dirname(c)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        return c
    return candidates[0]


def _ensure_user_memory_schema(conn) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'frontend',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_um_key ON user_memories(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_um_category ON user_memories(category)")
    conn.commit()


def _handle_user_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: 用户层记忆 SQLite 操作, 与 cognitive memory 物理隔离。"""
    import sqlite3

    command = args.get("command", "list")
    db_path = _resolve_user_memory_db()

    try:
        conn = sqlite3.connect(db_path)
        _ensure_user_memory_schema(conn)
        cur = conn.cursor()

        if command == "get":
            key = args.get("key", "")
            cur.execute(
                "SELECT id,key,value,category,source,created_at,updated_at FROM user_memories WHERE key=?",
                (key,),
            )
            row = cur.fetchone()
            cols = ["id", "key", "value", "category", "source", "created_at", "updated_at"]
            conn.close()
            if row:
                return {
                    "ok": True,
                    "data": dict(zip(cols, row, strict=True)),
                    "error_code": None,
                    "meta": {"shell_id": "user.memory"},
                }
            return {
                "ok": True,
                "data": None,
                "error_code": None,
                "meta": {"shell_id": "user.memory", "reason": "not_found"},
            }

        if command == "put":
            key = args.get("key", "")
            value = args.get("value", "")
            category = args.get("category", "general")
            source = args.get("source", "frontend")
            cur.execute(
                "INSERT OR REPLACE INTO user_memories(key,value,category,source,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
                (key, value, category, source),
            )
            conn.commit()
            conn.close()
            return {
                "ok": True,
                "data": {"key": key, "rows": cur.rowcount},
                "error_code": None,
                "meta": {"shell_id": "user.memory"},
            }

        if command == "delete":
            key = args.get("key", "")
            cur.execute("DELETE FROM user_memories WHERE key=?", (key,))
            conn.commit()
            conn.close()
            return {
                "ok": True,
                "data": {"key": key, "rows": cur.rowcount},
                "error_code": None,
                "meta": {"shell_id": "user.memory"},
            }

        if command == "list":
            category = args.get("category")
            if category:
                cur.execute(
                    "SELECT id,key,value,category,source,created_at,updated_at FROM user_memories WHERE category=? ORDER BY updated_at DESC",
                    (category,),
                )
            else:
                cur.execute(
                    "SELECT id,key,value,category,source,created_at,updated_at FROM user_memories ORDER BY updated_at DESC LIMIT 200"
                )
            rows = cur.fetchall()
            cols = ["id", "key", "value", "category", "source", "created_at", "updated_at"]
            conn.close()
            return {
                "ok": True,
                "data": [dict(zip(cols, r, strict=True)) for r in rows],
                "error_code": None,
                "meta": {"shell_id": "user.memory", "count": len(rows)},
            }

        if command == "search":
            q = args.get("query", "")
            cur.execute(
                "SELECT id,key,value,category,source,created_at,updated_at FROM user_memories WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT 50",
                (f"%{q}%", f"%{q}%"),
            )
            rows = cur.fetchall()
            cols = ["id", "key", "value", "category", "source", "created_at", "updated_at"]
            conn.close()
            return {
                "ok": True,
                "data": [dict(zip(cols, r, strict=True)) for r in rows],
                "error_code": None,
                "meta": {"shell_id": "user.memory", "count": len(rows)},
            }

        conn.close()
        return {
            "ok": False,
            "error_code": "not_found",
            "meta": {
                "reason": f"unknown command: {command}",
                "available": ["get", "put", "delete", "list", "search"],
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"user_memory_error: {type(e).__name__}: {e}"},
        }


# ── Data DAL query handler ────────────────────────────────────────────


def _resolve_core_db() -> str:
    """解析 dreambuddy_core.db 路径 (和 chain_data_query.py 原有逻辑一致)。"""
    env_path = os.environ.get("DREAMBUDDY_CORE_DB")
    if env_path and os.path.isfile(env_path):
        return env_path
    repo_root = _resolve_repo_root()
    candidates = [
        os.path.normpath(os.path.join(repo_root, "19-数据访问层", "data", "dreambuddy_core.db")),
        os.path.normpath(
            os.path.join(repo_root, "34-前端应用训练系统", "data", "dreambuddy_core.db")
        ),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # 不存在时返回第一个候选, 让后面 sqlite3.connect 报错
    return candidates[0]


# chain 指标定义 (sub_category + metric_name → output_key)
_CHAIN_METRICS = [
    # btc_onchain: 真实 metric_name (DB 只有这些)
    ("btc_onchain", "difficulty_change_pct", "difficulty_change_pct"),
    ("btc_onchain", "difficulty_progress_pct", "difficulty_progress_pct"),
    ("btc_onchain", "mempool_count", "mempool_count"),
    ("btc_onchain", "mempool_fee_btc", "mempool_fee_btc"),
    ("btc_onchain", "mempool_size_kb", "mempool_size_kb"),
    ("btc_onchain", "remaining_blocks", "remaining_blocks"),
    ("btc_onchain", "tip_height", "tip_height"),
    # exchanges_whales: DB 里是 us_DXXXXX 格式, 取几个有意义的
    ("exchanges_whales", "us_SP500_value", "sp500_equity_value"),
    ("exchanges_whales", "us_VIXCLS_value", "vix_value"),
    ("exchanges_whales", "us_DTWEXBGS_value", "dollar_index_value"),
    (
        "exchanges_whales",
        "ex_bal_BTC_chg30d_pct",
        "ex_bal_btc_chg30d_pct",
    ),  # 交易所BTC余额30日变化%
    # btc_basics: 链上基础指标 (收口 P2: OnchainPanel 需要)
    ("btc_basics", "market_cap_usd", "market_cap_usd"),
    ("btc_basics", "total_btc", "total_btc"),
    ("btc_basics", "active_addresses", "active_addresses"),
    ("btc_basics", "hashrate", "hash_rate"),
    ("btc_basics", "tx_count_24h", "tx_count_24h"),
    # btc_metrics: bgeometrics 链上估值指标 (收口 P2: ValuationPanel 真实 MVRV)
    ("btc_metrics", "mvrv", "mvrv"),
    ("btc_metrics", "sopr", "sopr"),
    ("btc_metrics", "nupl", "nupl"),
    ("btc_metrics", "puell_multiple", "puell_multiple"),
    ("btc_metrics", "realized_price", "realized_price"),
    ("btc_metrics", "nvt_ratio", "nvt_ratio"),
    # chains_summary: DeFi TVL (收口 P2: BreadthPanel 需要)
    ("chains_summary", "total_tvl_bln", "defi_tvl_bln"),  # DeFi 总 TVL(十亿), tvl_bln 键为 0.0 坏值
    # utxo_age_distribution: 持有者分布 (收口 P2: OnchainPanel 需要)
    ("utxo_age_distribution", "long_term_holder_supply_pct", "lth_supply_pct"),
    ("utxo_age_distribution", "mid_term_holder_supply_pct", "mth_supply_pct"),
    ("utxo_age_distribution", "short_term_holder_supply_pct", "sth_supply_pct"),
    ("utxo_age_distribution", "profit_supply_pct", "profit_supply_pct"),
    ("utxo_age_distribution", "hodl_waves_1y_plus_pct", "hodl_waves_1y_plus_pct"),
    ("utxo_age_distribution", "utxo_count", "utxo_count"),
]

_MACRO_METRICS = [
    # macro: metric_name 全是 "value" (DB 实际结构)
    ("DX-Y.NYB", "value", "DXY"),
    ("^TNX", "value", "US10Y"),
    ("^VIX", "value", "VIX"),
    ("GC=F", "value", "Gold"),
    ("SP500", "value", "SP500"),
    ("WALCL", "value", "Fed_liquidity"),  # Fed 资产负债表
    ("FEDFUNDS", "value", "Fed_rate"),  # 联邦基金利率
    ("CPIAUCSL", "value", "CPI"),  # CPI
    ("PPIACO", "value", "PPI"),  # PPI
    ("DCOILWTICO", "value", "WTI"),  # 原油
    ("CL=F", "value", "Oil_futures"),  # 原油期货
    ("NASDAQCOM", "value", "NASDAQ"),  # 纳指
    ("M2NS", "value", "m2_supply"),  # M2 货币供应(十亿)
    ("INDPRO", "value", "industrial_production"),  # 工业产出指数
    # fedwatch: CME FedWatch 利率概率 (fed_event_collector)
    ("fedwatch", "cut_prob", "cut_probability"),
    ("fedwatch", "hold_prob", "hold_probability"),
    ("fedwatch", "hike_prob", "hike_probability"),
    ("fedwatch", "effr", "fed_effective_rate"),
]
# flow 指标定义 (P1: SPEC-L0-DATA-AGENT §4)
_FLOW_METRICS = [
    ("etf_flow", "total_flow", "etf_total_flow"),  # ETF 总净流入
    ("stablecoins_top_10", "usdt_pct_of_total", "stablecoin_dominance_usdt"),  # USDT 占比
    ("stablecoins_top_10", "usdc_pct_of_total", "stablecoin_dominance_usdc"),  # USDC 占比 (收口 P2)
    # 衍生品/鲸鱼真实指标 (P0 收口: FlowPanel 资金费率/多空比/鲸鱼/清算)
    # OKX 口径单列输出, 由聚合层优先使用 (Binance/panewslab 作为回退/交叉验证)
    ("okx_derivatives", "funding_rate_pct", "funding_rate_pct_okx"),
    ("okx_derivatives", "long_short_ratio", "long_short_ratio_okx"),
    ("funding_rate", "funding_rate_pct", "funding_rate_pct"),
    ("long_short_ratio", "long_short_ratio", "long_short_ratio"),
    ("exchanges_whales", "whale_netflow_to_ex_usd", "whale_netflow_to_ex_usd"),
    ("derivatives_spot", "fut_liq_total_24h_usd", "liquidations_24h_usd"),
    ("derivatives_spot", "fut_liq_long_24h_usd", "liquidations_long_24h_usd"),
    ("derivatives_spot", "fut_liq_short_24h_usd", "liquidations_short_24h_usd"),
    ("tether_current", "usdt_circulating_usd_bln", "usdt_circulating_bln"),  # USDT 流通量
    ("usdc_current", "usdc_circulating_usd_bln", "usdc_circulating_bln"),  # USDC 流通量
    # etf_flow: 分发行商明细 (farside per-issuer, 百万美元)
    ("etf_flow", "IBIT", "etf_ibit"),
    ("etf_flow", "FBTC", "etf_fbtc"),
    ("etf_flow", "ARKB", "etf_arkb"),
    ("etf_flow", "GBTC", "etf_gbtc"),
    ("etf_flow", "BTCO", "etf_btco"),
    ("etf_flow", "BITB", "etf_bitb"),
    ("etf_flow", "EZBC", "etf_ezbc"),
    ("etf_flow", "BTCW", "etf_btcw"),
    ("etf_flow", "BRRR", "etf_brrr"),
    ("etf_flow", "HODL", "etf_hodl"),
    ("etf_flow", "MSBT", "etf_msbt"),
    ("etf_flow", "BTC", "etf_btc"),
]
# breadth 指标定义 (P1)
_BREADTH_METRICS = [
    ("stablecoins_top_10", "USDT_bln", "usdt_bln"),
    ("stablecoins_top_10", "USDC_bln", "usdc_bln"),
    ("social_volume", "social_volume", "social_volume"),
    ("social_volume", "news_count_24h", "news_count_24h"),
    ("overview_market", "btc_dominance_pct", "btc_dominance_pct"),  # BTC 市占率 (panewslab)
    ("chains_summary", "total_tvl_bln", "defi_tvl_bln"),  # DeFi 总 TVL(十亿), tvl_bln 键为 0.0 坏值
    ("overview_market", "global_change24_pct", "global_change_24h"),  # 全球市值24h涨跌%
]
# capital_flow 指标定义 (P1)
_CAPITAL_FLOW_METRICS = [
    ("long_short_ratio", "long_short_ratio", "long_short_ratio"),
    ("long_short_ratio", "long_account_pct", "long_account_pct"),
    ("funding_rate", "funding_rate_pct", "funding_rate_pct"),
    ("funding_rate", "funding_rate_annualized_pct", "funding_rate_annualized_pct"),
    ("open_interest", "open_interest_value", "open_interest_value"),
    ("open_interest", "open_interest_amount", "open_interest_amount"),
]
# intermarket 指标定义 (收口 P2: IntermarketPanel)
_INTERMARKET_METRICS = [
    ("BTC/USDT", "last", "btc_price"),  # ccxt BTC 价格
    ("DX-Y.NYB", "value", "dxy"),  # yfinance 真实值
    ("SP500", "value", "spx_price"),  # FRED 真实值
    ("^VIX", "value", "vix"),  # yfinance 真实值
    ("^TNX", "value", "us10y_yield"),  # yfinance 真实值
    ("NASDAQCOM", "value", "ndx"),  # FRED 真实值
    ("GC=F", "value", "gold_price"),  # yfinance 真实值
    ("DCOILWTICO", "value", "wti"),  # FRED 真实值
]
# sentiment 指标定义 (P1)
_SENTIMENT_METRICS = [
    ("crypto_fear_greed", "value", "crypto_fear_greed"),  # 真实恐惧贪婪指数
    ("fear_greed_enhanced", "momentum", "fg_momentum"),
    ("fear_greed_enhanced", "volatility", "fg_volatility"),
    ("fear_greed_enhanced", "capital_flow", "fg_capital_flow"),
    ("fear_greed_enhanced", "funding", "fg_funding"),
    ("social_volume", "social_volume", "social_volume"),  # 社交讨论量
    ("social_volume", "news_count_24h", "news_count_24h"),  # 24h 新闻数
]


def _query_metric(conn, sub_cat: str, name: str):
    cur = conn.execute(
        "SELECT metric_value, timestamp FROM mm_metrics WHERE sub_category=? AND metric_name=? ORDER BY timestamp DESC LIMIT 1",
        (sub_cat, name),
    )
    return cur.fetchone()


_NEWS_METRICS = [
    ("social_volume", "news_count_24h", "news_count_24h"),
    ("social_volume", "social_volume", "social_volume"),
    ("social_volume", "total_news_records", "total_news_records"),
]

_NARRATIVE_METRICS = [
    ("crypto_fear_greed", "value", "fg_value"),
    ("fear_greed_enhanced", "capital_flow", "capital_flow"),
    ("fear_greed_enhanced", "funding", "funding"),
    ("fear_greed_enhanced", "momentum", "momentum"),
    ("fear_greed_enhanced", "volatility", "volatility"),
]


def _handle_dal_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: SQLite mm_metrics 查询 (chain/market/macro 指标)。

    args: {command: "chain"|"market"|"macro"|"metric", sub_category?, metric_name?}
    """
    import sqlite3
    from datetime import datetime, timezone

    command = args.get("command", "chain")
    db_path = _resolve_core_db()
    if not os.path.isfile(db_path):
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": "core_db_not_found", "path": db_path},
        }

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        output = {"source": "dal", "degraded": False}

        if command == "metric":
            # 单指标查询: {sub_category, metric_name}
            sub_cat = args.get("sub_category", "")
            name = args.get("metric_name", "")
            row = _query_metric(conn, sub_cat, name)
            conn.close()
            if row:
                return {
                    "ok": True,
                    "data": {
                        "value": row[0],
                        "ts": row[1],
                        "sub_category": sub_cat,
                        "metric_name": name,
                    },
                    "error_code": None,
                    "meta": {"shell_id": "data.dal_query"},
                }
            return {
                "ok": True,
                "data": None,
                "error_code": None,
                "meta": {"shell_id": "data.dal_query", "reason": "not_found"},
            }

        if command == "chain":
            for sub_cat, name, out_key in _CHAIN_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    val = row[0]
                    if out_key in ("active_addresses_24h", "large_transfers_24h") and val:
                        val = int(val)
                    output[out_key] = val
                    output[out_key + "_ts"] = row[1]

        elif command == "market":
            sub_cat = args.get("sub_category", "")
            name = args.get("metric_name", "")
            if sub_cat and name:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output["value"] = row[0]
                    output["ts"] = row[1]
                else:
                    output["degraded"] = True
                    output["error"] = f"metric not found: {sub_cat}/{name}"
            else:
                conn.close()
                return {
                    "ok": False,
                    "error_code": "invalid",
                    "meta": {"reason": "market needs sub_category+metric_name"},
                }

        elif command == "macro":
            for sub_cat, name, out_key in _MACRO_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
            # CPI 同比: 最新 CPIAUCSL vs ~1 年前
            try:
                cur_row = _query_metric(conn, "CPIAUCSL", "value")
                if cur_row and cur_row[0]:
                    year_ago_ts = cur_row[1] - 365 * 86400
                    row2 = conn.execute(
                        "SELECT metric_value FROM mm_metrics WHERE sub_category='CPIAUCSL' AND metric_name='value' AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
                        (year_ago_ts,),
                    ).fetchone()
                    if row2 and row2[0]:
                        output["CPI_yoy"] = round((cur_row[0] / row2[0] - 1) * 100, 2)
            except Exception:
                pass
        elif command == "flow":
            for sub_cat, name, out_key in _FLOW_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
        elif command == "breadth":
            for sub_cat, name, out_key in _BREADTH_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
        elif command == "capital_flow":
            for sub_cat, name, out_key in _CAPITAL_FLOW_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
        elif command == "sentiment":
            for sub_cat, name, out_key in _SENTIMENT_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
        elif command == "news":
            for sub_cat, name, out_key in _NEWS_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
            # newsflash 情绪分布 (48h 窗口 200 条, 移植自 9 层 collect_news)
            try:
                import time as _time

                _end = int(_time.time())
                _start = _end - 48 * 3600
                _rows = conn.execute(
                    """SELECT metric_value FROM mm_metrics
                       WHERE metric_name='od_policy_sentiment_0_1'
                         AND sub_category LIKE 'newsflash_%'
                         AND timestamp BETWEEN ? AND ?
                       ORDER BY timestamp DESC LIMIT 200""",
                    (_start, _end),
                ).fetchall()
                _pos = _neg = _neu = 0
                _sents = []
                for _r in _rows:
                    _v = _r[0]
                    if _v is None or not isinstance(_v, (int, float)):
                        continue
                    _sents.append(float(_v))
                    if _v > 0.55:
                        _pos += 1
                    elif _v < 0.45:
                        _neg += 1
                    else:
                        _neu += 1
                output["positive_count"] = _pos
                output["negative_count"] = _neg
                output["neutral_count"] = _neu
                output["avg_sentiment"] = round(sum(_sents) / len(_sents), 3) if _sents else 0.5
                output["high_impact_count"] = sum(1 for _s in _sents if abs(_s - 0.5) > 0.3)
            except Exception:
                pass
        elif command == "narrative":
            for sub_cat, name, out_key in _NARRATIVE_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]
        elif command == "intermarket":
            for sub_cat, name, out_key in _INTERMARKET_METRICS:
                row = _query_metric(conn, sub_cat, name)
                if row:
                    output[out_key] = row[0]

        conn.close()
        output["timestamp"] = datetime.now(timezone.utc).isoformat()
        return {
            "ok": True,
            "data": output,
            "error_code": None,
            "meta": {"shell_id": "data.dal_query", "command": command},
        }

    except Exception as e:
        return {
            "ok": False,
            "error_code": "shell_degraded",
            "meta": {"reason": f"dal_query_error: {type(e).__name__}: {e}"},
        }


# ── Shell stats handler ────────────────────────────────────────────────


def _handle_shell_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    """内联 handler: ShellHandleManager stats (健康度/调用量/活跃壳)。

    args: {command: "stats"|"health"}
    """
    command = args.get("command", "stats")

    # 直接 import manager (不能走 get_manager() 因为我们要统计同一个进程的 manager)
    core_dir = _resolve_34_core_dir()
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    mgr = get_manager()
    specs = mgr._specs_cached()
    shells = mgr._shells  # dict: shell_id → ShellHandle

    alive, dead = 0, 0
    shells_info = []
    for sid, shell in shells.items():
        alive_check = True
        if hasattr(shell, "is_alive"):
            try:
                alive_check = bool(shell.is_alive())
            except Exception:
                alive_check = True
        if alive_check:
            alive += 1
        else:
            dead += 1
        shells_info.append(
            {
                "shell_id": sid,
                "alive": alive_check,
                "status": specs.get(sid, {}).get("status", "unknown"),
                "transport": specs.get(sid, {}).get("transport", "unknown"),
            }
        )

    stats = mgr.stats()

    if command == "health":
        return {
            "ok": True,
            "data": {
                "total_shells": len(shells),
                "alive": alive,
                "dead": dead,
                "registered_specs": len(specs),
                "handles_issued": {k: v.get("handles_issued", 0) for k, v in stats.items()},
                "shells": shells_info,
            },
            "error_code": None,
            "meta": {"shell_id": "shell.stats"},
        }

    # command == "stats" 或其他
    return {
        "ok": True,
        "data": {
            "total_shells": len(shells),
            "alive": alive,
            "dead": dead,
            "registered_specs": len(specs),
            "shell_ids": sorted(specs.keys()),
            "in_process_handlers": sorted(IN_PROCESS_HANDLERS.keys()),
            "handles_issued": stats,
        },
        "error_code": None,
        "meta": {"shell_id": "shell.stats"},
    }


def launcher_factory(spec: Dict[str, Any]) -> Optional[Any]:
    """根据 shell spec 选 launcher, 返回已拉起的壳对象 (带 .call/.is_alive/.close)。

    transport 支持: stdio / ssh-stdio / in-process (http 暂未实现)
    """
    # 确保 repo root 在 sys.path (dreamos, 1-ARCHITECTURE 等需要)
    repo_root = _resolve_repo_root()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    # ssh_shell_launcher.py 有 from core.stdio_shell_launcher import —
    # 需要 34-前端应用训练系统 在 sys.path, 这样 "core" 就是子 package
    parent_of_core = os.path.dirname(_resolve_34_core_dir())  # = repo_root/34-前端应用训练系统
    if parent_of_core not in sys.path:
        sys.path.insert(0, parent_of_core)
    if not isinstance(spec, dict):
        return None
    shell_id = spec.get("shell_id", "")
    transport = spec.get("transport", "stdio")

    # 特殊处理: in-process handler 不在 47 registry, 但 shell_id 可被 ShellHandleManager 查找
    if transport == "in-process" or shell_id in IN_PROCESS_HANDLERS:
        handler_fn = _load_inprocess_handler(shell_id)
        if handler_fn is None:
            return None
        return InProcessShell(handler_fn, shell_id)

    # stdio / ssh-stdio — 走 34-core 现有 launcher
    try:
        if transport == "stdio":
            from stdio_shell_launcher import stdio_launcher  # type: ignore

            return stdio_launcher(spec)
        elif transport == "ssh-stdio":
            from ssh_shell_launcher import ssh_launcher  # type: ignore

            return ssh_launcher(spec)
        else:
            return None
    except Exception:
        return None


# ── ShellHandleManager 单例 ─────────────────────────────────────────────

_manager: Optional[Any] = None


def get_manager() -> Any:
    """获取或创建全局 ShellHandleManager 单例, 带 launcher_factory + flags。"""
    global _manager
    if _manager is not None:
        return _manager
    # 确保 34-core 在 sys.path
    core_dir = _resolve_34_core_dir()
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # flags: 全开
    flags = {
        "enable_shell_handles": True,
        "enable_worker_tool_call": True,
    }
    from shell_handles import ShellHandleManager  # type: ignore

    _manager = ShellHandleManager(launcher=launcher_factory, flags=flags)
    return _manager


# ── 统一 call 入口 ────────────────────────────────────────────────────


def call_tool(
    role: str,
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    trace_id: Optional[str] = None,
    bypass_gate: bool = True,
) -> Dict[str, Any]:
    """完整 DSH 链路调用: [mandate_gate*] → 壳发现 → ShellHandleManager → 壳。

    壳发现顺序:
      1. IN_PROCESS_HANDLERS (非 MCP handler, 直接 import) → 绕过 47 registry,
         直接 shell_id=tool, manager.get_handle(tool)
      2. 47 registry (MCP shell, tool→shell_id 映射) → 走 call_worker_tool 完整链路

    bypass_gate=True (默认): 跳过 mandate_gate (前端桥场景, 用户意图驱动,
    上层 auth 已把关; gate 保护 Worker 内部自动调度, 不适用于前端请求)。
    bypass_gate=False: 正常走 gate (DSH Worker 内部调度场景)。

    返回统一信封 {ok, data, error_code, meta}。
    任意层异常 → ok=false, error_code=unavailable/shell_degraded, meta.degraded=true。
    """
    core_dir = _resolve_34_core_dir()
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    mgr = get_manager()
    checker = (lambda _r, _t: True) if bypass_gate else None

    # ── 路径 A: in-process handler (绕过 47 registry) ──────────────
    if tool in IN_PROCESS_HANDLERS:
        return _call_inprocess(role, tool, args, mgr, checker, trace_id)

    # ── 路径 B: MCP shell (走 call_worker_tool 完整链路) ───────────
    from worker_tool_call import call_worker_tool  # type: ignore

    flags = {"enable_worker_tool_call": True}
    return call_worker_tool(
        role,
        tool,
        args,
        checker=checker,
        manager=mgr,
        flags=flags,
        trace_id=trace_id,
    )


def _call_inprocess(
    role: str,
    shell_id: str,
    args: Optional[Dict[str, Any]],
    mgr: Any,
    checker: Optional[Callable],
    trace_id: Optional[str],
) -> Dict[str, Any]:
    """in-process handler 直调路径: checker → manager.get_handle → handle.call → retry。

    复用 call_worker_tool 的 HC-6/HC-7 retry-degrade 语义, 但绕过
    load_tool_shell_map (in-process handler 不在 47 registry 里)。
    """
    try:
        # 确保 in-process spec 已注入 manager._specs (ShellHandleManager 查 _specs 确认壳存在)
        if shell_id not in mgr._specs_cached():
            mgr._specs[shell_id] = {
                "shell_id": shell_id,
                "transport": "in-process",
                "status": "available",
            }

        # checker (bypass 时恒 True)
        if callable(checker):
            try:
                if not bool(checker(role, shell_id)):
                    return {
                        "ok": False,
                        "data": None,
                        "error_code": "forbidden",
                        "meta": {"trace_id": trace_id, "degraded": True},
                    }
            except Exception:
                return {
                    "ok": False,
                    "data": None,
                    "error_code": "forbidden",
                    "meta": {"trace_id": trace_id, "degraded": True},
                }

        # manager.get_handle — 直接用 shell_id (tool 名就是 shell_id)
        handle = None
        try:
            handle = mgr.get_handle(shell_id)
        except Exception:
            handle = None
        if handle is None:
            return {
                "ok": False,
                "data": None,
                "error_code": "unavailable",
                "meta": {"trace_id": trace_id, "degraded": True, "reason": "handle_none"},
            }

        # HC-6: try-retry
        try:
            result = handle.call(shell_id, args)
        except Exception as exc:
            retry_handle = None
            try:
                retry_handle = mgr.get_handle(shell_id, force_new=True)
            except Exception:
                retry_handle = None
            if retry_handle is not None:
                try:
                    result = retry_handle.call(shell_id, args)
                except Exception as retry_exc:
                    return {
                        "ok": False,
                        "data": None,
                        "error_code": "shell_degraded",
                        "meta": {
                            "trace_id": trace_id,
                            "degraded": True,
                            "reason": str(retry_exc),
                            "original": str(exc),
                        },
                    }
            else:
                return {
                    "ok": False,
                    "data": None,
                    "error_code": "shell_degraded",
                    "meta": {"trace_id": trace_id, "degraded": True, "reason": str(exc)},
                }

        # 统一信封
        if isinstance(result, dict) and ("ok" in result or "error_code" in result):
            envelope = result
            envelope.setdefault("meta", {})
            if isinstance(envelope["meta"], dict):
                envelope["meta"].setdefault("trace_id", trace_id)
            return envelope
        return {
            "ok": True,
            "data": result,
            "error_code": None,
            "meta": {"trace_id": trace_id, "shell_id": shell_id},
        }
    except Exception as exc:
        return {
            "ok": False,
            "data": None,
            "error_code": "unavailable",
            "meta": {
                "trace_id": trace_id,
                "degraded": True,
                "reason": f"{type(exc).__name__}: {exc}",
            },
        }


# ── handler 入口 (兼容 dsh_adapter.py 原调用格式) ──────────────────────
# 现有前端 dsh_adapter.py 用 handler_name (如 technical, c_drive, orchestrator)
# 而不是 tool_name。我们做一个 handler → {shell_id, role, tool} 映射, 保持兼容。

HANDLER_TO_SHELL_ID: Dict[str, str] = {
    "technical": "subagent.technical",
    "sentiment": "subagent.sentiment",
    "macro": "subagent.macro",
    "flow": "subagent.flow",
    "valuation": "subagent.valuation",
    "onchain": "subagent.onchain",
    "risk": "subagent.risk",
    "portfolio": "subagent.portfolio",
    "c_drive": "c-drive",
    "debate": "c-drive.debate",
    "synthesizer": "synthesizer",
    "orchestrator": "orchestrator",
    "orchestrator_status": "orchestrator.status",
    "knowledge_search": "knowledge.search",
    "skill_index": "skill.index",
    "user_memory": "user.memory",
    "dal_query": "data.dal_query",
    "shell_stats": "shell.stats",
}

HANDLER_TO_ROLE: Dict[str, str] = {
    # 8 SubAgent 默认 research (只读, 符合 ADR-9)
    "technical": "research",
    "sentiment": "research",
    "macro": "research",
    "flow": "research",
    "valuation": "research",
    "onchain": "research",
    "risk": "research",
    "portfolio": "research",
    "c_drive": "research",
    "debate": "research",
    "synthesizer": "research",
    "orchestrator": "engineer",
    "orchestrator_status": "research",
    "knowledge_search": "research",
    "skill_index": "research",
    "user_memory": "research",
    "dal_query": "research",
    "shell_stats": "research",
}


def call_handler(handler_name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按 handler_name 调用 (适配现有 dsh_adapter.py 调用方式)。

    内部路由到 call_tool 完整链路。
    """
    shell_id = HANDLER_TO_SHELL_ID.get(handler_name)
    if shell_id is None:
        return {
            "ok": False,
            "error_code": "not_found",
            "meta": {
                "reason": f"unknown handler: {handler_name}",
                "available": sorted(HANDLER_TO_SHELL_ID.keys()),
            },
        }
    role = HANDLER_TO_ROLE.get(handler_name, "research")

    # shell_id 即 tool 名 (InProcessShell 只有一个 handler per shell)
    envelope = call_tool(role=role, tool=shell_id, args=args)

    # 提取 data/output 字段 (handler 原始返回结构)
    if envelope.get("ok"):
        data = envelope.get("data")
        # SubAgent/Orchestrator handler 原返回 {ok:true, output:{...}}
        if isinstance(data, dict):
            if "output" in data:
                return {"ok": True, "output": data["output"]}
            # synthesizer 返回 aggregated result
            return {"ok": True, "output": data, "data": data}
        return {"ok": True, "output": data, "data": data}
    else:
        # 统一返回 ok:false + 错误码 (前端现有 fallback 能消费)
        return {
            "ok": False,
            "error": envelope.get("error_code", "unknown"),
            "meta": envelope.get("meta", {}),
            "traceback": None,
        }


# ── CLI 入口 ──────────────────────────────────────────────────────────


def _safe_print(payload: Any) -> None:
    sys.stdout = sys.__stdout__
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        sys.stdout.write(json.dumps({"ok": False, "error": "json_serialization_failed"}) + "\n")
    sys.stdout.flush()


def main() -> None:
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing subcommand. use: call|handler"})
        return

    subcmd = sys.argv[1]
    payload_raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid payload JSON: {e}"})
        return

    # 确保 import 噪音不污染 stdout
    sys.stdout = sys.stderr

    if subcmd == "call":
        # python3 dsh_frontend_bridge.py call <role> <tool> '<args_json>'
        if len(sys.argv) < 5:
            _safe_print({"ok": False, "error": "usage: call <role> <tool> '<args_json>'"})
            return
        role = sys.argv[2]
        tool = sys.argv[3]
        args_raw = sys.argv[4]
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError as e:
            _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
            return
        trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
        result = call_tool(role, tool, args, trace_id=trace_id)
        _safe_print(result)

    elif subcmd == "handler":
        # python3 dsh_frontend_bridge.py handler <handler_name> '<args_json>'
        if len(sys.argv) < 4:
            _safe_print({"ok": False, "error": "usage: handler <handler_name> '<args_json>'"})
            return
        handler_name = sys.argv[2]
        args_raw = sys.argv[3]
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError as e:
            _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
            return
        result = call_handler(handler_name, args)
        _safe_print(result)

    elif subcmd == "info":
        # python3 dsh_frontend_bridge.py info — 打印 manager stats + registry shells
        mgr = get_manager()
        specs = mgr._specs_cached()
        result = {
            "enabled": mgr._enabled(),
            "stats": mgr.stats(),
            "registry_shells": sorted(specs.keys()),
            "in_process_handlers": sorted(IN_PROCESS_HANDLERS.keys()),
            "handlers": sorted(HANDLER_TO_SHELL_ID.keys()),
        }
        _safe_print(result)

    else:
        _safe_print({"ok": False, "error": f"unknown subcommand: {subcmd}"})


if __name__ == "__main__":
    main()
