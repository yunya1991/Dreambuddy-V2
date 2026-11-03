#!/usr/bin/env python3
"""shadow_driver.py — 经壳 stdio JSON-RPC 驱动真实工具调用（α 接线）

目的：云端没有任何 MCP host 常驻，L0 壳进程从未被调用，AgentMailShadow
因此永远收不到真实信封。本驱动按 MCP 协议拉起壳进程、发 initialize + tools/call，
让壳内 handler 真实执行 → 壳内 observe_envelope() 落盘 trajectory。

与 collect_real_trajectories.py 的区别：
  - 后者在本进程内直接调域函数再手动 observe（不经过壳）
  - 本驱动**经过壳的 JSON-RPC 边界**，验证的是生产接线本身（含壳内计时/meta 补齐）

硬约束（COMM-SHADOW S1-S3）：只读工具面；只写本地 JSONL；FAIL-OPEN 不中断；
驱动本身不 import torch / 不连 DB / 不起额外服务。

CLI:
  python mcp_shells/_shared/shadow_driver.py --domains data,eval,store_admin
  python mcp_shells/_shared/shadow_driver.py --domains rea --timeout 180
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHELLS_DIR = _REPO_ROOT / "mcp_shells"

# 只读工具面调用计划（域名 → [(tool, args)]）；写面工具一律不进入本计划
SHELL_CALLS: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
    "data": [
        ("data_fetch", {"scope": "yijing.bcrm2"}),
        ("data_fetch", {"scope": "market.ticker", "params": {"symbol": "BTC-USDT-SWAP"}}),
        ("data_collect_once", {}),
        ("data_store_read", {"table": "mm_metrics", "limit": 5}),
    ],
    "eval": [
        ("eval_report", {}),
    ],
    "store_admin": [
        ("store_admin_status", {}),
        ("store_admin_query", {"repo": "trade", "limit": 5}),
    ],
    "rea": [
        ("submit_rea_trace", {"target": "mcp_shells/_shared", "feature": "信封包装"}),
    ],
}

_SHELL_DIR = {
    "data": "l0_data",
    "eval": "l0_eval",
    "store_admin": "l0_store_admin",
    "rea": "l0_rea",
}


def _shell_server(domain: str) -> Path:
    return _SHELLS_DIR / _SHELL_DIR[domain] / "server.py"


def _write_request(proc: subprocess.Popen, req: Dict[str, Any]) -> Dict[str, Any]:
    """写一行请求并读一行响应（壳是同步逐行处理，无并发）。"""
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line.strip():
        return {}
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


def _extract_envelope(resp: Dict[str, Any]) -> Dict[str, Any]:
    """从 JSON-RPC 响应取出壳信封（content[0].text）。解析失败返回空 dict。"""
    try:
        text = resp["result"]["content"][0]["text"]
        env = json.loads(text)
        return env if isinstance(env, dict) else {}
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return {}


def _drive_domain(
    domain: str,
    calls: List[Tuple[str, Dict[str, Any]]],
    python_bin: str,
    timeout: float,
    env: Dict[str, str],
) -> Dict[str, Any]:
    """拉起一个壳进程，按计划调用工具，返回本域调用摘要。"""
    server = _shell_server(domain)
    summary: Dict[str, Any] = {"domain": domain, "shell": str(server), "calls": [], "error": ""}
    if not server.exists():
        summary["error"] = "shell_missing"
        return summary

    started_all = time.perf_counter()
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            [python_bin, str(server)],
            cwd=str(_REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        _write_request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "shadow_driver"}},
            },
        )

        next_id = 2
        for tool, args in calls:
            started = time.perf_counter()
            resp = _write_request(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": next_id,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                },
            )
            next_id += 1
            env_obj = _extract_envelope(resp)
            record: Dict[str, Any] = {
                "tool": tool,
                "wall_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "ok": bool(env_obj.get("ok", False)),
                "degraded": bool(env_obj.get("degraded", False)),
                "error_code": str(env_obj.get("error_code", "") or ""),
            }
            summary["calls"].append(record)

            # REA 两段式：submit 返回 job_id 后追加 poll（真实轮询路径）
            job_id = (env_obj.get("meta") or {}).get("job_id", "")
            if job_id and tool.startswith("submit_rea_"):
                poll_tool = tool.replace("submit_", "poll_", 1)
                poll_resp = _write_request(
                    proc,
                    {
                        "jsonrpc": "2.0",
                        "id": next_id,
                        "method": "tools/call",
                        "params": {"name": poll_tool, "arguments": {"job_id": job_id}},
                    },
                )
                next_id += 1
                poll_env = _extract_envelope(poll_resp)
                summary["calls"].append(
                    {
                        "tool": poll_tool,
                        "wall_ms": 0.0,
                        "ok": bool(poll_env.get("ok", False)),
                        "degraded": bool(poll_env.get("degraded", False)),
                        "error_code": str(poll_env.get("error_code", "") or ""),
                    }
                )
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        summary["error"] = f"{type(e).__name__}: {e}"
    finally:
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                summary["error"] = summary["error"] or "shell_timeout"
            try:
                if proc.stderr:
                    summary["stderr_tail"] = proc.stderr.read()[-500:]
            except Exception:  # noqa: BLE001
                pass

    summary["elapsed_ms"] = round((time.perf_counter() - started_all) * 1000.0, 3)
    return summary


def drive_shadow(
    domains: Optional[List[str]] = None,
    python_bin: Optional[str] = None,
    timeout: float = 180.0,
    store_path: Optional[str] = None,
) -> Dict[str, Any]:
    """驱动全部选定域的壳调用。返回 {domains, calls, degraded, elapsed_ms}。"""
    selected = [d for d in (domains or list(SHELL_CALLS)) if d in SHELL_CALLS]
    env = dict(os.environ)
    if store_path:
        env["AGENT_MAIL_SHADOW_STORE"] = store_path
    python_bin = python_bin or sys.executable

    results = [_drive_domain(d, SHELL_CALLS[d], python_bin, timeout, env) for d in selected]
    calls = [c for r in results for c in r["calls"]]
    return {
        "domains": selected,
        "calls": len(calls),
        "degraded": sum(1 for c in calls if c["degraded"]),
        "shells": results,
        "store": env.get("AGENT_MAIL_SHADOW_STORE", ""),
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="经壳 JSON-RPC 驱动真实调用（AgentMailShadow α 接线）")
    ap.add_argument("--domains", default="", help="逗号分隔: data,eval,store_admin,rea（默认全部）")
    ap.add_argument("--python", default="", help="壳进程解释器（默认当前解释器）")
    ap.add_argument("--timeout", type=float, default=180.0, help="单壳等待上限（秒）")
    ap.add_argument("--store", default="", help="覆盖 AGENT_MAIL_SHADOW_STORE")
    ns = ap.parse_args()
    domains = [d.strip() for d in ns.domains.split(",") if d.strip()] or None
    summary = drive_shadow(
        domains=domains,
        python_bin=ns.python or None,
        timeout=ns.timeout,
        store_path=ns.store or None,
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
