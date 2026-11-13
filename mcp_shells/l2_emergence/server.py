#!/usr/bin/env python3
"""mcp_shells/l2_emergence/server.py — L2 涌现架构观察 MCP（P2，DEC-02）

全只读 / control 层 readonly-observe / 扫 48-涌现架构 文件系统。
三个工具：
  get_emergence_metrics  — 读 metrics/emergence_metrics.jsonl 汇总
  list_experiments       — 列 experiments 目录所有实验 run
  get_experiment_report  — 读指定实验的评估报告（JSON / .jsonl）

硬约束：
  - 全只读 / 零大模型依赖 / 零 DB 直连
  - 壳零业务逻辑（真实涌现逻辑在 48 模块内部）
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l2.emergence.mcp"

# 48-涌现架构 根目录
_EM_DIR = _REPO_ROOT / "48-涌现架构"
_METRICS_FILE = _EM_DIR / "metrics" / "emergence_metrics.jsonl"
_TRIALS_FILE = _EM_DIR / "runtime" / "trials.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_lines(
    path: Path, max_lines: int = 1000, max_bytes: int = 2 * 1024 * 1024
) -> List[str]:
    try:
        if not path.exists():
            return []
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        content = data.decode("utf-8", errors="replace")
        return content.splitlines()[-max_lines:]
    except OSError:
        return []


def _safe_jsonl(path: Path, limit: int = 500) -> List[Dict[str, Any]]:
    lines = _safe_read_lines(path, max_lines=limit)
    out: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


# ── 工具实现 ──


def _handle_get_emergence_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    """读涌现指标汇总——emergence_metrics.jsonl + trials.jsonl 基础统计。"""
    metrics_lines = _safe_jsonl(_METRICS_FILE, limit=500)
    trial_lines = _safe_jsonl(_TRIALS_FILE, limit=500)

    # 简易汇总
    latest_metric = metrics_lines[-1] if metrics_lines else None
    total_trials = len(trial_lines)
    # 成功/失败 trial 统计（如果有 verdict 字段）
    success_trials = sum(
        1
        for t in trial_lines
        if isinstance(t.get("verdict"), str) and "complete" in t["verdict"].lower()
    )

    # 最新 factor 注册（registry/factor_publication.jsonl）
    factor_file = _EM_DIR / "registry" / "factor_publication.jsonl"
    factors = _safe_jsonl(factor_file, limit=100)

    return {
        "ok": True,
        "available": _EM_DIR.exists(),
        "metrics_file": str(_METRICS_FILE),
        "metrics_lines": len(metrics_lines),
        "latest_metric": latest_metric,
        "trials_summary": {
            "total": total_trials,
            "success": success_trials,
            "failure": total_trials - success_trials,
        },
        "latest_factors": factors[-5:] if factors else [],
        "checked_at": _now_iso(),
        "meta": {"source": SHELL_SOURCE, "upstream": "48-涌现架构"},
    }


def _handle_list_experiments(args: Dict[str, Any]) -> Dict[str, Any]:
    """列 experiments 目录所有实验 run + events 子目录 run。"""
    try:
        limit = int(args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    experiments_dir = _EM_DIR / "experiments"
    events_dir = _EM_DIR / "events"

    runs: List[Dict[str, Any]] = []

    # experiments/*/ 下的 run_*.py 或 run_*.json
    if experiments_dir.exists():
        for run_file in sorted(
            experiments_dir.rglob("run_*.py"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]:
            rel = run_file.relative_to(experiments_dir)
            runs.append(
                {
                    "type": "experiment",
                    "name": str(rel.with_suffix("")),
                    "file": str(rel),
                    "mtime": datetime.fromtimestamp(
                        run_file.stat().st_mtime, timezone.utc
                    ).isoformat(),
                }
            )

    # events/asil/ 下的 run 目录 verdict / complete
    if events_dir.exists():
        asil_events = events_dir / "asil"
        if asil_events.exists():
            verdicts = sorted(
                asil_events.glob("*_verdict.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]
            for v in verdicts:
                run_id = v.name.replace("_verdict.jsonl", "")
                runs.append(
                    {
                        "type": "asil",
                        "run_id": run_id,
                        "mtime": datetime.fromtimestamp(
                            v.stat().st_mtime, timezone.utc
                        ).isoformat(),
                        "verdict_count": sum(1 for _ in _safe_read_lines(v, max_lines=9999)),
                    }
                )

    return {
        "ok": True,
        "total": len(runs),
        "runs": runs[:limit],
        "meta": {"source": SHELL_SOURCE},
    }


def _handle_get_experiment_report(args: Dict[str, Any]) -> Dict[str, Any]:
    """读指定 run / 实验的评估报告。

    args:
      run_id / experiment_name (str, req) — 要读的 run / 实验名
      report_type (str, opt) — verdict / complete / summary（默认自动选）
    """
    target = args.get("run_id") or args.get("experiment_name") or ""
    if not target:
        return {"ok": False, "error_code": "invalid", "reason": "run_id 或 experiment_name 必填"}

    candidates: List[Path] = []
    # events/asil/
    asil_dir = _EM_DIR / "events" / "asil"
    if asil_dir.exists():
        for suffix in ("_complete.jsonl", "_verdict.jsonl"):
            p = asil_dir / f"{target}{suffix}"
            if p.exists():
                candidates.append(p)
    # experiments/ 目录
    ex_dir = _EM_DIR / "experiments"
    if ex_dir.exists():
        for match in ex_dir.rglob(f"*{target}*"):
            candidates.append(match)

    if not candidates:
        return {
            "ok": False,
            "error_code": "not_found",
            "reason": f"未找到 run/experiment={target!r} 的报告",
            "searched_in": ["events/asil", "experiments"],
        }

    primary = candidates[0]
    # jsonl → 读最后 N 行；json → 直接 load
    report_lines: List[Dict[str, Any]] = []
    summary: Optional[Dict[str, Any]] = None

    if primary.suffix == ".jsonl":
        report_lines = _safe_jsonl(primary, limit=200)
        summary = {
            "type": "jsonl",
            "file": str(primary.relative_to(_EM_DIR)),
            "entry_count": len(report_lines),
            "last_entry": report_lines[-1] if report_lines else None,
        }
    elif primary.suffix == ".json":
        try:
            summary = json.loads(primary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary = {"error": f"json_parse_failed: {exc}"}
        summary = {
            "type": "json",
            "file": str(primary.relative_to(_EM_DIR)),
            "content": summary if isinstance(summary, dict) else {"raw": str(summary)[:1000]},
        }
    else:
        summary = {"type": primary.suffix, "file": str(primary.relative_to(_EM_DIR))}

    return {
        "ok": True,
        "run_id": target,
        "report": summary,
        "additional_files": [str(p.relative_to(_EM_DIR)) for p in candidates[1:]],
        "meta": {"source": SHELL_SOURCE},
    }


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "get_emergence_metrics": {
        "description": "读 48-涌现架构 metrics 汇总——emergence_metrics.jsonl + trials.jsonl + factors。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_experiments": {
        "description": "列 48 涌现 experiments 目录 + events/asil run（最新优先）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "default 50, max 200"}},
        },
    },
    "get_experiment_report": {
        "description": "读指定 run / experiment 的评估报告（jsonl verdict / json summary）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "experiment_name": {"type": "string"},
                "report_type": {
                    "type": "string",
                    "description": "optional: verdict/complete/summary",
                },
            },
        },
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "get_emergence_metrics": _handle_get_emergence_metrics,
    "list_experiments": _handle_list_experiments,
    "get_experiment_report": _handle_get_experiment_report,
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
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:
            result = {
                "ok": False,
                "error_code": "internal",
                "reason": f"{type(exc).__name__}: {exc}",
            }
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
