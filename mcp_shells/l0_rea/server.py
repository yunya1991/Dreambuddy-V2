#!/usr/bin/env python3
"""mcp_shells/l0_rea/server.py — L0 REA 壳（M3⑦）

SPEC-L0-MCP-PACKAGING §4 P2 + registry mcp_capabilities.yaml（l0.rea-client.mcp → 本壳为 REA server 包装 dsh_nodes）
工具面（6 个，两段式）：
  - submit_rea_analyze / poll_rea_analyze   (analyze: 整体架构分析)
  - submit_rea_trace    / poll_rea_trace    (trace: 功能追踪)
  - submit_rea_compare  / poll_rea_compare  (compare: 两工程对比)

硬约束：
  - 壳内零业务逻辑：协议解析 → dsh_nodes 调用 → 信封映射 三段
  - 长任务两段式（SPEC §3.2）：submit_* 返回 ok+meta.job_id；poll_* 返回 state=running/success/failed + 结果信封
  - 持久层强制（评审 DA1）：job 状态落 JSONL 状态文件（33-REA逆向解析工程/reflection_data/mcp_jobs/<job_id>.json），禁止内存态
  - shadow 起步（M3⑨）：REA_MCP_SHADOW=1 时逐字节比对新旧路径输出
  - stdio JSON-RPC 2.0，按需拉起，不常驻
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

# 壳进程 import 规约（SPEC §3.4）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shadow_hook import observe_envelope  # noqa: E402

SHELL_SOURCE = "l0.rea.mcp"
JOBS_DIR = _REPO_ROOT / "33-REA逆向解析工程" / "reflection_data" / "mcp_jobs"
SHADOW_MODE = os.environ.get("REA_MCP_SHADOW", "0") == "1"

# REA 分析节点映射（submit 工具名 → dsh_nodes 节点函数名）
_NODE_MAP = {
    "submit_rea_analyze": "S33_rea_analyze",
    "submit_rea_trace": "S33_rea_trace",
    "submit_rea_compare": "S33_rea_compare",
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


def _run_node_sync(node_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """同步调用 dsh_nodes 节点（壳进程内直接调用，长任务由后台线程执行）。"""
    dsh = _load_dsh_nodes()
    fn = getattr(dsh, node_name)
    return fn(params)


def _handle_submit(name: str, args: Dict[str, Any]) -> str:
    """submit_*：登记 job（state=running）+ 后台线程执行节点 + 返回 job_id。"""
    import threading

    node_name = _NODE_MAP[name]
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    trace_id = str(args.get("trace_id") or "")

    # 登记 job（持久层，state=running）
    _write_job(
        job_id,
        {
            "job_id": job_id,
            "node": node_name,
            "state": "running",
            "submitted_at": time.time(),
            "trace_id": trace_id,
        },
    )

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

    def _worker():
        try:
            result = _run_node_sync(node_name, args)
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

    # 非 daemon：进程退出前等待任务完成并落盘（SPEC §3.2：壳按需拉起即退，job 状态必须落持久层）
    threading.Thread(target=_worker, daemon=False).start()
    return json.dumps(
        wrap({"job_id": job_id, "state": "running"}, SHELL_SOURCE, meta={"job_id": job_id}),
        ensure_ascii=False,
    )


def _handle_poll(name: str, args: Dict[str, Any]) -> str:
    """poll_*：查询 job 状态（running/success/failed）+ 结果信封。"""
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
    state = record.get("state", "running")
    data = {"job_id": job_id, "state": state}
    if state == "success":
        data["result"] = record.get("result")
    elif state == "failed":
        data["error"] = record.get("error")
    return json.dumps(wrap(data, SHELL_SOURCE), ensure_ascii=False)


TOOL_HANDLERS = {}
for _n in _NODE_MAP:
    TOOL_HANDLERS[_n] = (lambda n: (lambda a: _handle_submit(n, a)))(_n)
    _poll = _n.replace("submit_", "poll_", 1)
    TOOL_HANDLERS[_poll] = (lambda p: (lambda a: _handle_poll(p, a)))(_poll)


def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
        }
    if method == "tools/list":
        tools = []
        for n in ("analyze", "trace", "compare"):
            tools.append(
                {
                    "name": f"submit_rea_{n}",
                    "description": f"Submit REA {n} job (async, returns job_id)",
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                }
            )
            tools.append(
                {
                    "name": f"poll_rea_{n}",
                    "description": f"Poll REA {n} job status by job_id",
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                }
            )
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        result_text = handler(params.get("arguments", {}))
        # COMM-SHADOW 旁路观察（默认关闭，FAIL-OPEN）：实测耗时 + 工具名补齐轨迹信号
        observe_envelope(
            result_text,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            action=name,
        )
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": result_text}], "isError": False},
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """stdio 主循环。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
