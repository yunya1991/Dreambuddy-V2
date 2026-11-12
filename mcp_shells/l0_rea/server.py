#!/usr/bin/env python3
"""mcp_shells/l0_rea/server.py — L0 REA 壳（M3⑦ + SPEC-33-D）

SPEC-L0-MCP-PACKAGING §4 P2 + 47 registry mcp_capabilities.yaml（l0.rea 包装 dsh_nodes）
工具面（15 个）：
  - submit/poll/cancel_rea_analyze          (analyze: 整体架构分析)
  - submit/poll/cancel_rea_trace            (trace: 功能追踪)
  - submit/poll/cancel_rea_compare          (compare: 两工程对比)
  - submit/poll/cancel_rea_adapt_plan       (adapt_plan: 改造方案，只出方案不改代码)
  - get_rea_snapshot                        (按 section 分页读取 analyze 快照，同步只读)
  - rea_audit / get_rea_methodology          (同步只读)

硬约束：
  - 壳内零业务逻辑：协议解析 → dsh_nodes 调用 → 信封映射 三段
  - 长任务两段式（SPEC §3.2）：submit_* 返回 ok+meta.job_id；poll_* 返回 running/cancel_requested 或 success/failed/timeout/cancelled 终态
  - 持久层强制（评审 DA1）：job 状态落 JSONL 状态文件（33-REA逆向解析工程/reflection_data/mcp_jobs/<job_id>.json），禁止内存态
  - shadow 起步（M3⑨）：REA_MCP_SHADOW=1 时逐字节比对新旧路径输出
  - stdio JSON-RPC 2.0，按需拉起，不常驻
  - 壳内不写认知库：只透传 cognitive_hint（SPEC-33-D §2.6）
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# 壳进程 import 规约（SPEC §3.4）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l0.rea.mcp"
JOBS_DIR = _REPO_ROOT / "33-REA逆向解析工程" / "reflection_data" / "mcp_jobs"
SHADOW_MODE = os.environ.get("REA_MCP_SHADOW", "0") == "1"
_DEADLINE_ENABLED_ENV = "REA_DEADLINE_ENABLED"
_DEFAULT_DEADLINE_MS = 120_000
_CANCEL_GRACE_SECONDS = 5.0
_TERMINAL_STATES = {"success", "failed", "cancelled", "timeout"}

# REA 分析节点映射（submit 工具名 → dsh_nodes 节点函数名）
_NODE_MAP = {
    "submit_rea_analyze": "S33_rea_analyze",
    "submit_rea_trace": "S33_rea_trace",
    "submit_rea_compare": "S33_rea_compare",
    "submit_rea_adapt_plan": "S33_rea_adapt_plan",
}


def _load_dsh_nodes():
    sys.path.insert(0, str(_REPO_ROOT / "33-REA逆向解析工程"))
    import dsh_nodes

    return dsh_nodes


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_job(job_id: str, record: Dict[str, Any]) -> None:
    """job 状态落 JSONL 持久层（追加写，禁止内存态）。"""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_job_path(job_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_job(job_id: str) -> Dict[str, Any]:
    """读取 job 最新状态（JSONL 末行）。"""
    p = _job_path(job_id)
    if not p.exists():
        return {}
    last = ""
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last) if last else {}


def _deadline_enabled() -> bool:
    return os.environ.get(_DEADLINE_ENABLED_ENV, "1") != "0"


def _finish_job(
    job_id: str,
    record: Dict[str, Any],
    state: str,
    reason: str,
    *,
    forced: Optional[bool] = None,
) -> Dict[str, Any]:
    finished = dict(record)
    finished.update(
        {
            "job_id": job_id,
            "state": state,
            "finished_at": time.time(),
            "reason": reason,
        }
    )
    finished.pop("result", None)
    if forced is not None:
        finished["forced"] = forced
    _write_job(job_id, finished)
    return finished


def _refresh_job(job_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """poll/节点边界共用的持久状态推进，覆盖壳进程重启后的超时与强制取消。"""
    if not _deadline_enabled():
        return record
    state = record.get("state")
    now = time.time()
    if state == "running" and record.get("deadline_at") is not None:
        if now >= float(record["deadline_at"]):
            return _finish_job(
                job_id,
                record,
                "timeout",
                f"deadline exceeded: {record.get('deadline_ms')}ms",
            )
    if state == "cancel_requested":
        requested_at = float(record.get("cancel_requested_at") or now)
        if now - requested_at >= _CANCEL_GRACE_SECONDS:
            return _finish_job(
                job_id,
                record,
                "cancelled",
                f"cancel grace exceeded: {_CANCEL_GRACE_SECONDS}s",
                forced=True,
            )
    return record


def _enforce_deadline(job_id: str) -> None:
    record = _read_job(job_id)
    if _deadline_enabled() and record.get("state") == "running":
        _finish_job(
            job_id,
            record,
            "timeout",
            f"deadline exceeded: {record.get('deadline_ms')}ms",
        )


def _run_node_sync(node_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """同步调用 dsh_nodes 节点（壳进程内直接调用，长任务由后台线程执行）。"""
    dsh = _load_dsh_nodes()
    fn = getattr(dsh, node_name)
    return fn(params)


def _handle_submit(name: str, args: Dict[str, Any]) -> str:
    """submit_*：登记持久 job + deadline watchdog + 后台节点执行。"""
    import threading

    node_name = _NODE_MAP[name]
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    trace_id = str(args.get("trace_id") or "")
    deadline_enabled = _deadline_enabled()
    raw_deadline = args.get("deadline_ms")
    deadline_ms = _DEFAULT_DEADLINE_MS if raw_deadline is None else raw_deadline
    if deadline_enabled:
        try:
            if isinstance(deadline_ms, bool):
                raise ValueError
            deadline_ms = int(deadline_ms)
            if deadline_ms < 1:
                raise ValueError
        except (TypeError, ValueError):
            return json.dumps(
                wrap(
                    None,
                    SHELL_SOURCE,
                    degraded=True,
                    error_code="invalid",
                    meta={"reason": "deadline_ms must be a positive integer"},
                ),
                ensure_ascii=False,
            )

    submitted_at = time.time()
    job_record: Dict[str, Any] = {
        "job_id": job_id,
        "node": node_name,
        "state": "running",
        "submitted_at": submitted_at,
        "trace_id": trace_id,
    }
    if deadline_enabled:
        job_record.update(
            {
                "deadline_ms": deadline_ms,
                "deadline_at": submitted_at + deadline_ms / 1000,
            }
        )
    _write_job(job_id, job_record)

    def _normalize(obj: Any) -> Any:
        """剥离节点输出的非确定性字段（时间戳/随机 ID），仅用于 shadow 比对。"""
        volatile_keys = {"ts", "created_at", "evidence_id", "replay_tree_id"}
        if isinstance(obj, dict):
            return {k: _normalize(v) for k, v in obj.items() if k not in volatile_keys}
        if isinstance(obj, list):
            return [_normalize(x) for x in obj]
        return obj

    def _shadow_compare(new_result: Dict[str, Any]) -> Dict[str, Any]:
        """M3⑨ shadow 双跑：旧路径（直调节点函数，即既有 REA client 方式）同参数重放，
        规范化（剥离时间戳/随机 ID 等非确定性字段）后逐字节比对。"""
        try:
            old_result = _run_node_sync(node_name, args)
            new_bytes = json.dumps(_normalize(new_result), ensure_ascii=False, sort_keys=True)
            old_bytes = json.dumps(_normalize(old_result), ensure_ascii=False, sort_keys=True)
            return {
                "shadow": True,
                "match": new_bytes == old_bytes,
                "new_sha256": __import__("hashlib").sha256(new_bytes.encode("utf-8")).hexdigest(),
                "old_sha256": __import__("hashlib").sha256(old_bytes.encode("utf-8")).hexdigest(),
            }
        except Exception as se:  # shadow 失败不阻断主路径（FAIL-OPEN）
            return {"shadow": True, "match": None, "shadow_error": str(se)}

    def _boundary_record() -> Dict[str, Any]:
        current = _refresh_job(job_id, _read_job(job_id))
        if current.get("state") == "cancel_requested":
            return _finish_job(
                job_id,
                current,
                "cancelled",
                "cancel acknowledged at node boundary",
                forced=False,
            )
        return current

    deadline_timer: Optional[threading.Timer] = None

    def _worker():
        try:
            if _boundary_record().get("state") in _TERMINAL_STATES:
                return
            result = _run_node_sync(node_name, args)
            if _boundary_record().get("state") in _TERMINAL_STATES:
                return
            record = {
                "job_id": job_id,
                "node": node_name,
                "state": "success",
                "finished_at": time.time(),
                "trace_id": trace_id,
                "result": result,
            }
            if SHADOW_MODE:
                record.update(_shadow_compare(result))
            _write_job(job_id, record)
        except Exception as e:
            if _boundary_record().get("state") in _TERMINAL_STATES:
                return
            _write_job(
                job_id,
                {
                    "job_id": job_id,
                    "node": node_name,
                    "state": "failed",
                    "finished_at": time.time(),
                    "trace_id": trace_id,
                    "error": str(e),
                },
            )
        finally:
            if deadline_timer is not None:
                deadline_timer.cancel()

    # 非 daemon：进程退出前等待任务完成并落盘（SPEC §3.2：壳按需拉起即退，job 状态必须落持久层）
    if deadline_enabled:
        deadline_timer = threading.Timer(
            deadline_ms / 1000,
            _enforce_deadline,
            args=(job_id,),
        )
        deadline_timer.start()
    threading.Thread(target=_worker, daemon=False).start()
    data = {"job_id": job_id, "state": "running"}
    if deadline_enabled:
        data["deadline_ms"] = deadline_ms
    return json.dumps(
        wrap(data, SHELL_SOURCE, meta={"job_id": job_id}),
        ensure_ascii=False,
    )


def _handle_poll(name: str, args: Dict[str, Any]) -> str:
    """poll_*：推进并查询 running/cancel_requested/成功及四类终态。"""
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "job_id is required"},
            ),
            ensure_ascii=False,
        )
    record = _read_job(job_id)
    if not record:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"reason": f"job not found: {job_id}"},
            ),
            ensure_ascii=False,
        )
    record = _refresh_job(job_id, record)
    state = record.get("state", "running")
    data = {"job_id": job_id, "state": state}
    if state == "success":
        data["result"] = record.get("result")
    elif state == "failed":
        data["error"] = record.get("error")
    elif state in ("cancelled", "timeout"):
        data["reason"] = record.get("reason") or state
        if state == "cancelled":
            data["forced"] = bool(record.get("forced", False))
        if "partial_stats" in record:
            data["partial_stats"] = record["partial_stats"]
    if record.get("cancel_requested"):
        data["cancel_requested"] = True
    return json.dumps(wrap(data, SHELL_SOURCE), ensure_ascii=False)


def _handle_cancel(name: str, args: Dict[str, Any]) -> str:
    """cancel_*：持久标记，等待节点边界；超过 5s 仅强制置终态，不强杀线程。"""
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "job_id is required"},
            ),
            ensure_ascii=False,
        )
    record = _read_job(job_id)
    if not record:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"reason": f"job not found: {job_id}"},
            ),
            ensure_ascii=False,
        )
    expected_node = _NODE_MAP[name.replace("cancel_", "submit_", 1)]
    if record.get("node") != expected_node:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": f"job kind mismatch: expected {expected_node}"},
            ),
            ensure_ascii=False,
        )

    def _response(current: Dict[str, Any]) -> str:
        state = current.get("state", "running")
        data = {
            "job_id": job_id,
            "state": state,
            "cancel_requested": bool(current.get("cancel_requested")),
        }
        if state == "cancelled":
            data["forced"] = bool(current.get("forced", False))
        if current.get("reason"):
            data["reason"] = current["reason"]
        return json.dumps(wrap(data, SHELL_SOURCE, meta={"job_id": job_id}), ensure_ascii=False)

    if record.get("state") in _TERMINAL_STATES:
        return _response(record)

    marked = dict(record)
    marked["cancel_requested"] = True
    marked["cancel_requested_at"] = time.time()
    if not _deadline_enabled():
        _write_job(job_id, marked)
        return _response(marked)

    marked["state"] = "cancel_requested"
    marked["reason"] = "cancel requested"
    _write_job(job_id, marked)
    grace_deadline = time.monotonic() + _CANCEL_GRACE_SECONDS
    while True:
        current = _read_job(job_id)
        if current.get("state") in _TERMINAL_STATES:
            return _response(current)
        remaining = grace_deadline - time.monotonic()
        if remaining <= 0:
            current = _refresh_job(job_id, current)
            if current.get("state") == "cancel_requested":
                current = _finish_job(
                    job_id,
                    current,
                    "cancelled",
                    f"cancel grace exceeded: {_CANCEL_GRACE_SECONDS}s",
                    forced=True,
                )
            return _response(current)
        time.sleep(min(0.05, remaining))


TOOL_DEFS = {
    "submit_rea_analyze": {
        "description": (
            "Submit REA analyze job (async, returns job_id). "
            "scope=summary (default, ≤16KB) / architecture (≤64KB) / full (snapshot_id only, ≤4KB)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "本地目录或文件路径"},
                "scope": {
                    "type": "string",
                    "enum": ["summary", "architecture", "full"],
                    "default": "summary",
                    "description": "输出粒度：summary 默认（≤16384B）/ architecture（≤65536B）/ full（仅 snapshot_id）",
                },
                "force": {"type": "boolean", "default": False, "description": "跳过读缓存并重扫"},
                "incremental": {
                    "type": "boolean",
                    "default": False,
                    "description": "附加文件级 Merkle 增量 diff（不改变分析结果）",
                },
                "index_path": {
                    "type": "string",
                    "description": "incremental=true 时的索引路径（缺省落 reflection_data/index/）",
                },
                "trace_id": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    "submit_rea_trace": {
        "description": "Submit REA trace job (async, returns job_id)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "本地目录或文件路径"},
                "feature": {"type": "string", "description": "要追踪的功能"},
                "entry": {"type": "string", "description": "可选入口函数/模块"},
                "algorithm": {
                    "type": "string",
                    "enum": ["ppr", "legacy"],
                    "default": "ppr",
                    "description": "ppr=PPR 相关性排序（默认）；legacy=旧版一跳上下游",
                },
                "budget_bytes": {
                    "type": "integer",
                    "minimum": 512,
                    "maximum": 65536,
                    "default": 8192,
                    "description": "整个响应字节预算，超出时裁剪 ranked_nodes/edges 并写 trimmed",
                },
                "hops": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3,
                    "default": 2,
                    "description": "PPR 候选节点的最大跳数",
                },
                "lsp": {
                    "type": "boolean",
                    "default": False,
                    "description": "使用 Jedi/tsserver 引用扩展 trace 种子；失败时降级",
                },
                "trace_id": {"type": "string"},
            },
            "required": ["target", "feature"],
        },
    },
    "submit_rea_compare": {
        "description": "Submit REA compare job (async, returns job_id)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_a": {"type": "string", "description": "工程 A 路径"},
                "target_b": {"type": "string", "description": "工程 B 路径"},
                "feature": {"type": "string"},
                "scope": {
                    "type": "string",
                    "enum": ["summary", "architecture", "full"],
                    "default": "summary",
                },
                "trace_id": {"type": "string"},
            },
            "required": ["target_a", "target_b"],
        },
    },
    "rea_audit": {
        "description": (
            "SPEC-33-E 假设门禁（同步只读）：传 hypotheses 时校验 falsifier + target_refs 静态复核 "
            "+ PoE gate，返回 pass/review/reject 与认知写入建议；不传 hypotheses 时审计 AI 生成代码目录"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "工程根或目录路径"},
                "hypotheses": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "假设列表，每条需 hypothesis_id/claim/target_refs/falsifier；"
                        "缺 falsifier 直接 reject"
                    ),
                },
                "ai_context": {"type": "object", "description": "代码审计模式的 AI 上下文"},
                "lsp": {
                    "type": "boolean",
                    "default": False,
                    "description": "使用 Jedi/tsserver 对 target_refs 做符号级精确复核",
                },
                "trace_id": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    "get_rea_methodology": {
        "description": (
            "方法论抽象（同步只读）：同一模式需 ≥2 个项目才蒸馏模板；"
            "可传 investigations 或 targets，无证据的模式不入聚类"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "investigations": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "多项目调查结果（target + patterns[{pattern,evidence}]）",
                },
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需先分析的本地项目路径",
                },
                "trace_id": {"type": "string"},
            },
        },
    },
    "get_rea_snapshot": {
        "description": (
            "Read analyze snapshot by section with pagination "
            "(read-only; section=modules/dependencies/cycles/call_graph/components/"
            "routes/api_routes/stores/god_components/external_deps/patterns/evidence; "
            "section=metrics/rules 现场采集度量与规则扫描（适配环，缺工具时 degraded=true；"
            "metrics 可选 metrics_config 阈值与 metrics_history 历史快照）; "
            "section=pack 按文件→符号→依赖生成确定性 Markdown（budget_bytes 控制预算）; "
            "section=archaeology 通过只读 git log 输出变更考古（无网络）; "
            "section=dependency_hygiene 输出未使用依赖、OSV CVE 与 CycloneDX SBOM; "
            "section=runtime 对账 coverage.xml 与可选 OTel JSON/JSONL span（缺报告 degraded）; "
            "section=semantic 复用 41 文件索引系统的本机向量桥做语义检索"
            "（REA_SEMANTIC_ENABLED=1 才启用；通道缺失时 degraded=true，不伪造命中）; "
            "section=evolution returns pending evolution actions with diff and rollback_point, "
            "no snapshot_id needed)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "analyze 返回的 snapshot_id（section=evolution 时可不填）",
                },
                "section": {
                    "type": "string",
                    "enum": [
                        "modules",
                        "dependencies",
                        "cycles",
                        "call_graph",
                        "components",
                        "routes",
                        "api_routes",
                        "stores",
                        "god_components",
                        "external_deps",
                        "patterns",
                        "evidence",
                        "metrics",
                        "rules",
                        "pack",
                        "archaeology",
                        "dependency_hygiene",
                        "diagnostics",
                        "runtime",
                        "sarif",
                        "evolution",
                        "graph",
                        "taint",
                        "diagram",
                        "semantic",
                    ],
                    "default": "modules",
                },
                "target": {
                    "type": "string",
                    "description": "section=metrics/rules 时的采集目标；缺省取快照 payload.target",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                },
                "cursor": {"type": "integer", "minimum": 0, "default": 0},
                "query": {
                    "type": "string",
                    "description": (
                        "section=graph 的受限 DSL：nodes / edges / neighbors <node> [depth=N]，"
                        "过滤仅支持 field=value 与 field~=regex（白名单字段，无 eval）；"
                        "section=semantic 的检索语句（必填）"
                    ),
                },
                "include_taint": {
                    "type": "boolean",
                    "default": True,
                    "description": "section=sarif 时是否汇入污点分析 findings（默认 true）",
                },
                "budget_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 32768,
                    "description": "section=pack 的 Markdown 内容字节预算",
                },
                "metrics_config": {
                    "type": "string",
                    "description": "section=metrics 的可选阈值配置（JSON/YAML）路径",
                },
                "metrics_history": {
                    "type": "string",
                    "description": "section=metrics 的可选历史 metrics JSON 快照路径",
                },
                "otel_path": {
                    "type": "string",
                    "description": "section=runtime 的可选 OpenTelemetry JSON/JSONL 报告路径",
                },
            },
            "required": [],
        },
    },
    "submit_rea_adapt_plan": {
        "description": (
            "SPEC-33-E T-E5 改造方案（异步，只出方案不改代码）："
            "每条需 plan_id/target_module/change/evidence_ref/rollback/acceptance，"
            "缺一即丢弃并计入 known_gaps；与 target+hypotheses 同传时只采纳 PoE pass"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plans": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "改造方案数组（缺 rollback/acceptance 的方案会被丢弃）",
                },
                "target": {
                    "type": "string",
                    "description": "可选工程根；提供时用于假设静态复核",
                },
                "hypotheses": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "可选假设数组（需 target），用于计算 gate 并只采纳 pass",
                },
                "trace_id": {"type": "string"},
            },
            "required": ["plans"],
        },
    },
}
for _n in ("analyze", "trace", "compare", "adapt_plan"):
    TOOL_DEFS[f"submit_rea_{_n}"]["inputSchema"]["properties"]["deadline_ms"] = {
        "type": "integer",
        "minimum": 1,
        "default": _DEFAULT_DEADLINE_MS,
        "description": "任务截止时间（毫秒），超时进入 timeout 终态",
    }
    TOOL_DEFS[f"poll_rea_{_n}"] = {
        "description": f"Poll REA {_n} job status by job_id",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    }
    TOOL_DEFS[f"cancel_rea_{_n}"] = {
        "description": f"Cancel REA {_n} job cooperatively by job_id",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    }

TOOL_HANDLERS = {}
for _n in _NODE_MAP:
    TOOL_HANDLERS[_n] = (lambda n: (lambda a: _handle_submit(n, a)))(_n)
    _poll = _n.replace("submit_", "poll_", 1)
    TOOL_HANDLERS[_poll] = (lambda p: (lambda a: _handle_poll(p, a)))(_poll)
    _cancel = _n.replace("submit_", "cancel_", 1)
    TOOL_HANDLERS[_cancel] = (lambda c: (lambda a: _handle_cancel(c, a)))(_cancel)


def _handle_snapshot(args: Dict[str, Any]) -> str:
    """get_rea_snapshot：同步只读，直接透传节点结果到统一信封。"""
    return json.dumps(
        wrap(_run_node_sync("get_rea_snapshot", args), SHELL_SOURCE),
        ensure_ascii=False,
    )


TOOL_HANDLERS["get_rea_snapshot"] = _handle_snapshot


def _handle_rea_audit(args: Dict[str, Any]) -> str:
    """rea_audit：同步只读，假设门禁或代码审计（节点内分流）。"""
    return json.dumps(wrap(_run_node_sync("S33_rea_audit", args), SHELL_SOURCE), ensure_ascii=False)


def _handle_methodology(args: Dict[str, Any]) -> str:
    """get_rea_methodology：同步只读，方法论模板抽象。"""
    return json.dumps(
        wrap(_run_node_sync("get_rea_methodology", args), SHELL_SOURCE),
        ensure_ascii=False,
    )


TOOL_HANDLERS["rea_audit"] = _handle_rea_audit
TOOL_HANDLERS["get_rea_methodology"] = _handle_methodology


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)
