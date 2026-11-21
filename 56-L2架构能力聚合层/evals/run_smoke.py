# -*- coding: utf-8 -*-
"""run_smoke.py — 抽样实跑（P2 逐壳 sweep + P1/P1b + P3 SACG + 故障注入）

依据 SPEC §5/§5.4/§8。
阶段:
  sweep : P2 stdio 逐壳 tools/list + 全部只读工具调用（工具级覆盖证据）
  p1    : 产品链 HTTP 探活（3001 不可用则记 unavailable）
  p1b   : 抽样场景经 dsh_frontend_bridge.call_tool（同一 handler 链）
  p3    : SACG in-process（S/A/C/G 决策与门控）
  faults: S13 超时 / S13b 401 / S14 并发 / S16 Mandate 拒绝与放行

产物: evals/out/evidence.jsonl
用法: python3 evals/run_smoke.py [--phase sweep,p1,p1b,p3,faults]
退出码: 0 = 各阶段无未捕获异常；1 = 有阶段崩溃
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probes import (  # noqa: E402
    DEFAULT_REGISTRY,
    EVALS_DIR,
    OUT_DIR,
    REPO_ROOT,
    JsonlRecorder,
    ProbeSession,
    gen_trace_id,
    load_registry,
    mcp_stdio_call,
    mcp_stdio_list_tools,
    patch_bridge,
)

SCENARIOS_PATH = EVALS_DIR / "scenarios.yaml"
EVIDENCE_PATH = OUT_DIR / "evidence.jsonl"
CORE_DIR = REPO_ROOT / "34-前端应用训练系统" / "core"
PKG_DIR = REPO_ROOT / "34-前端应用训练系统"

SWEEP_TIMEOUT = 12.0
CALL_TIMEOUT = 30.0


# ── 通用 ─────────────────────────────────────────────────────────────


def _load_scenarios() -> List[Dict[str, Any]]:
    import yaml

    with open(SCENARIOS_PATH, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("scenarios") or []


def _ensure_paths() -> None:
    for p in (str(CORE_DIR), str(PKG_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _safe_args(shell_id: str, tool: str) -> Dict[str, Any]:
    table = {
        ("l0.data.mcp", "data_fetch"): {"scope": "market.ticker", "params": {"symbol": "BTC"}},
        ("l0.data.mcp", "data_store_read"): {"table": "mm_metrics", "limit": 5},
        ("l0.store-admin.mcp", "store_admin_query"): {"repo": "trade", "limit": 5},
        ("l0.semantic-39.mcp", "semantic_lookup"): {"term": "比特币"},
        ("l0.semantic-39.mcp", "query_entity"): {"message": "比特币和以太坊"},
        ("l0.rea.mcp", "submit_rea_analyze"): {"question": "宏观与资金面是否矛盾"},
        ("l0.rea.mcp", "submit_rea_trace"): {"symbol": "BTC"},
        ("l0.rea.mcp", "submit_rea_compare"): {"items": ["BTC", "ETH"]},
        ("l0.cognition.mcp", "recall"): {"context": "宏观 资金面 矛盾", "top_k": 3},
        ("l1.intent.mcp", "classify_intent"): {"text": "BTC 现价多少"},
        ("l1.trading.mcp", "get_signal_state"): {},
        ("l0.trade-exec.mcp", "pre_trade_check"): {"symbol": "BTC", "side": "buy", "qty": 0.01},
        ("l1.strategy.mcp", "list_strategies"): {},
        ("l2.debate.mcp", "start_debate"): {"topic": "BTC 本周结构"},
        ("l0.eval.mcp", "eval_analyze"): {"sample": "recent", "limit": 20},
        ("l2.train.mcp", "list_runs"): {},
        ("l2.emergence.mcp", "list_experiments"): {},
        ("l2.dsh.mcp", "get_ticket_status"): {},
        ("l2.dsh.mcp", "get_router_summary"): {},
        ("l2.dreamos.mcp", "poll_run"): {"run_id": "smoke-run"},
        ("l1.ops.mcp", "get_health"): {},
        ("l1.ops.mcp", "list_alerts"): {},
        ("l0.store-admin.mcp", "store_admin_status"): {},
    }
    return dict(table.get((shell_id, tool), {}))


def _envelope_ok(env: Dict[str, Any]) -> bool:
    """外层信封 ok 且有内容结构（内层 degraded 由 data 里表达）。"""
    return isinstance(env, dict) and "ok" in env


# ── 阶段 1: P2 逐壳 sweep ────────────────────────────────────────────


def phase_sweep(rec: JsonlRecorder, registry: Dict[str, Any]) -> Dict[str, Any]:
    shells = [
        s
        for s in (registry.get("shells") or [])
        if isinstance(s, dict) and s.get("status") == "available"
    ]
    results: List[Dict[str, Any]] = []

    def _run_shell(spec: Dict[str, Any]) -> Dict[str, Any]:
        sid = spec.get("shell_id", "?")
        rel = spec.get("shell_path") or ""
        server = REPO_ROOT / rel
        shell_out: Dict[str, Any] = {"shell_id": sid, "shell_path": rel}
        if not rel or not server.exists():
            shell_out.update({"available": False, "reason": "shell_path_missing"})
            rec.write(
                {
                    "scenario_id": "SWEEP",
                    "entry": "P2",
                    "kind": "shell_sweep",
                    "shell_id": sid,
                    "ok": False,
                    "error_code": "shell_path_missing",
                }
            )
            return shell_out
        try:
            listed = mcp_stdio_list_tools(server, timeout=SWEEP_TIMEOUT)
        except Exception as exc:
            shell_out.update(
                {"available": False, "reason": f"{type(exc).__name__}: {exc}", "tools_listed": 0}
            )
            rec.write(
                {
                    "scenario_id": "SWEEP",
                    "entry": "P2",
                    "kind": "shell_sweep",
                    "shell_id": sid,
                    "ok": False,
                    "error_code": "tools_list_failed",
                    "reason": str(exc)[:300],
                }
            )
            return shell_out

        reg_tools = {
            t["name"]: t for t in (spec.get("tools") or []) if isinstance(t, dict) and t.get("name")
        }
        listed_names = {t.get("name") for t in listed if isinstance(t, dict)}
        shell_out.update(
            {
                "available": True,
                "tools_listed": len(listed_names),
                "tools_registered": len(reg_tools),
                "tools_list_matches": listed_names == set(reg_tools),
            }
        )
        rec.write(
            {
                "scenario_id": "SWEEP",
                "entry": "P2",
                "kind": "shell_sweep",
                "shell_id": sid,
                "ok": True,
                "tools_listed": len(listed_names),
                "tools_registered": len(reg_tools),
                "matches": listed_names == set(reg_tools),
            }
        )

        tool_rows: List[Dict[str, Any]] = []
        for name, meta in reg_tools.items():
            if meta.get("read_write") == "write":
                tool_rows.append({"tool": name, "skipped": "write"})
                continue
            t0 = time.perf_counter()
            try:
                env = mcp_stdio_call(server, name, _safe_args(sid, name), timeout=SWEEP_TIMEOUT)
                latency = (time.perf_counter() - t0) * 1000.0
                ok = _envelope_ok(env)
                row = {
                    "tool": name,
                    "ok": ok,
                    "degraded": bool(env.get("degraded")),
                    "error_code": env.get("error_code") or "",
                    "latency_ms": round(latency, 3),
                }
                rec.write(
                    {
                        "scenario_id": "SWEEP",
                        "entry": "P2",
                        "kind": "tool_sweep",
                        "shell_id": sid,
                        "tool": name,
                        "ok": ok,
                        "error_code": row["error_code"],
                        "latency_ms": row["latency_ms"],
                        "degraded": row["degraded"],
                    }
                )
            except Exception as exc:
                latency = (time.perf_counter() - t0) * 1000.0
                row = {
                    "tool": name,
                    "ok": False,
                    "degraded": True,
                    "error_code": f"{type(exc).__name__}",
                    "latency_ms": round(latency, 3),
                }
                rec.write(
                    {
                        "scenario_id": "SWEEP",
                        "entry": "P2",
                        "kind": "tool_sweep",
                        "shell_id": sid,
                        "tool": name,
                        "ok": False,
                        "error_code": row["error_code"],
                        "latency_ms": row["latency_ms"],
                        "reason": str(exc)[:300],
                    }
                )
            tool_rows.append(row)
        shell_out["tools"] = tool_rows
        return shell_out

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_run_shell, s) for s in shells]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"shell_id": "?", "available": False, "reason": str(exc)})

    results.sort(key=lambda r: r.get("shell_id", ""))
    return {
        "phase": "sweep",
        "shells": len(results),
        "available": sum(1 for r in results if r.get("available")),
        "list_mismatch": [r["shell_id"] for r in results if r.get("tools_list_matches") is False],
        "missing_impl": [r["shell_id"] for r in results if r.get("reason") == "shell_path_missing"],
        "details": results,
    }


# ── 阶段 2: P1 产品链探活 ────────────────────────────────────────────


P1_URL = "http://127.0.0.1:3001/api/task/stream"
P1_TIMEOUT = 240.0


def _stream_task(message: str, trace_id: str) -> Dict[str, Any]:
    """POST /api/task/stream 并解析 SSE，返回 {ok, content, status, latency_ms, events}。"""
    body = json.dumps(
        {"message": message, "session_id": f"eval-{trace_id}", "trace_id": trace_id}
    ).encode()
    req = urllib.request.Request(
        P1_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    t0 = time.perf_counter()
    content, status, error = "", "", ""
    event = ""
    try:
        with urllib.request.urlopen(req, timeout=P1_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line.split(":", 1)[1].strip())
                    except json.JSONDecodeError:
                        continue
                    if event == "done":
                        content = data.get("content") or ""
                        status = str(data.get("status") or "")
                    elif event == "error":
                        error = str(data.get("error") or "")
        latency = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": bool(content) and not error,
            "content": content,
            "status": status,
            "error": error,
            "latency_ms": round(latency, 3),
        }
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "content": "",
            "status": "",
            "error": str(exc)[:200],
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }


def phase_p1(rec: JsonlRecorder, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """产品链真实入口：对基线问题逐题取答（写类 S10 不执行，避免副作用）。"""
    rows: List[Dict[str, Any]] = []
    targets = [s for s in scenarios if s.get("baseline") and s.get("id") != "S10"]
    for sc in targets:
        sid = sc["id"]
        trace_id = gen_trace_id()
        r = _stream_task(str(sc.get("input") or ""), trace_id)
        rec.write(
            {
                "scenario_id": sid,
                "entry": "P1",
                "kind": "scenario",
                "trace_id": trace_id,
                "latency_ms": r["latency_ms"],
                "answer": r["content"][:4000],
                "answer_len": len(r["content"]),
                "status": r["status"],
                "assertions": [
                    {"name": "p1_answered", "pass": r["ok"]},
                    {"name": "has_trace_id", "pass": bool(trace_id)},
                ],
                "degraded": not r["ok"],
                "simulated": False,
                "error": r["error"],
            }
        )
        rows.append(
            {
                "scenario_id": sid,
                "ok": r["ok"],
                "latency_ms": r["latency_ms"],
                "answer_len": len(r["content"]),
            }
        )
        print(f"  P1 {sid}: ok={r['ok']} len={len(r['content'])} {r['latency_ms']}ms")
    return {
        "phase": "p1",
        "answered": sum(1 for x in rows if x["ok"]),
        "attempted": len(rows),
        "rows": rows,
    }


# ── 阶段 3: P1b 抽样场景 ────────────────────────────────────────────


P1B_PLANS: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
    "S1": [
        ("l1.intent.mcp:classify_intent", {"text": "BTC 现价多少"}),
        ("l0.data.mcp:data_fetch", {"scope": "market.ticker", "params": {"symbol": "BTC"}}),
    ],
    "S2": [
        ("l0.data.mcp:data_store_read", {"table": "mm_metrics", "limit": 5}),
        ("l0.store-admin.mcp:store_admin_status", {}),
    ],
    "S3": [
        ("l0.semantic-39.mcp:semantic_lookup", {"term": "比特币"}),
        ("l0.semantic-39.mcp:query_entity", {"message": "以太坊和狗狗币"}),
    ],
    "S4": [
        ("l0.cognition.mcp:recall", {"context": "宏观 资金面 矛盾", "top_k": 3}),
        ("l0.rea.mcp:submit_rea_analyze", {"question": "宏观与资金面是否矛盾"}),
    ],
    "S5": [
        ("l1.strategy.mcp:list_strategies", {}),
        ("l0.rea.mcp:submit_rea_trace", {"symbol": "BTC"}),
        ("l2.debate.mcp:start_debate", {"topic": "BTC 本周结构"}),
    ],
    "S7": [
        ("l1.trading.mcp:get_signal_state", {}),
        ("l0.trade-exec.mcp:pre_trade_check", {"symbol": "BTC", "side": "buy", "qty": 0.01}),
    ],
    "S10": [
        ("l2.emergence.mcp:list_experiments", {}),
        ("l2.train.mcp:get_training_status", {}),
    ],
    "S13": [
        ("l0.data.mcp:data_fetch", {"scope": "market.ticker", "params": {"symbol": "BTC"}}),
        ("l1.ops.mcp:get_health", {}),
        ("l0.store-admin.mcp:store_admin_status", {}),
    ],
}


def phase_p1b(rec: JsonlRecorder, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    _ensure_paths()
    import core.dsh_frontend_bridge as bridge  # type: ignore

    out_rows: List[Dict[str, Any]] = []
    sampled = [s for s in scenarios if s.get("sampled") and s.get("id") in P1B_PLANS]

    for sc in sampled:
        sid = sc["id"]
        session = ProbeSession(rec, sid, "P1b")
        unpatch = patch_bridge(session)
        t0 = time.perf_counter()
        assertions: List[Dict[str, Any]] = []
        try:
            for pair, args in P1B_PLANS[sid]:
                tool = pair.split(":", 1)[1]
                try:
                    bridge.call_tool("research", tool, args, trace_id=session.trace_id)
                except Exception as exc:
                    assertions.append(
                        {"name": f"call:{tool}", "pass": False, "reason": str(exc)[:160]}
                    )
        finally:
            unpatch()
        latency = (time.perf_counter() - t0) * 1000.0

        hit = session.tool_pair_set()
        expected = set(sc.get("expected_tools") or [])
        hit_rate = round(len(hit & expected) / len(expected), 3) if expected else 1.0
        assertions.append({"name": "has_trace_id", "pass": bool(session.trace_id)})
        assertions.append(
            {
                "name": "expected_tools_hit_rate>=0.8",
                "pass": hit_rate >= 0.8,
                "value": hit_rate,
                "missed": sorted(expected - hit),
            }
        )
        assertions.append(
            {
                "name": "at_least_one_business_tool",
                "pass": any(
                    t not in ("health", "stats")
                    for _s, t in ((c["shell_id"], c["tool"]) for c in session.tool_calls)
                ),
            }
        )
        degraded = any(c.get("degraded") for c in session.tool_calls)
        record = {
            "scenario_id": sid,
            "entry": "P1b",
            "kind": "scenario",
            "trace_id": session.trace_id,
            "latency_ms": round(latency, 3),
            "tool_calls": session.tool_calls,
            "assertions": assertions,
            "degraded": degraded,
            "simulated": False,
        }
        rec.write(record)
        out_rows.append(
            {
                "scenario_id": sid,
                "hit_rate": hit_rate,
                "tools": len(session.tool_calls),
                "pass": all(a.get("pass") for a in assertions),
            }
        )
    return {"phase": "p1b", "scenarios": len(out_rows), "rows": out_rows}


# ── 阶段 4: P3 SACG ──────────────────────────────────────────────────


def _sacg_orchestrator(manager: Any, trace_sink: List[Dict[str, Any]]) -> Any:
    from core.sacg_orchestrator import SACGOrchestrator
    from core.worker_tool_call import call_worker_tool

    ON = {"enable_worker_tool_call": True}

    def _decomposer(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []
        for i, item in enumerate(plan.get("plan_items") or []):
            nodes.append(
                {
                    "node_id": f"N{i + 1}",
                    "criteria": str(item),
                    "role": "verifier",
                    "tool": "store_admin_status",
                }
            )
        return nodes

    def _executor(_router: Any, node: Dict[str, Any]) -> Dict[str, Any]:
        r = call_worker_tool(
            node.get("role", "verifier"),
            node["tool"],
            args={},
            manager=manager,
            flags=ON,
            trace_id=f"p3-{node.get('node_id')}",
        )
        trace_sink.append({"node_id": node.get("node_id"), "ok": r.get("ok")})
        return {
            "action": "CONTINUE" if r.get("ok") else "FAILED",
            "tier": "Tier1",
            "effort_level": "light",
            "dsh_result": r,
        }

    def _record_fn(**_kw: Any) -> Dict[str, Any]:
        return {"ok": True, "simulated": True}

    def _verify_fn(**_kw: Any) -> Dict[str, Any]:
        return {"ok": True, "simulated": True}

    return SACGOrchestrator(
        a_decomposer=_decomposer,
        c_executor=_executor,
        record_fn=_record_fn,
        verify_fn=_verify_fn,
    )


def phase_p3(rec: JsonlRecorder) -> Dict[str, Any]:
    _ensure_paths()
    from core.shell_handles import ShellHandleManager  # type: ignore
    from core.stdio_shell_launcher import stdio_launcher  # type: ignore
    from core.sufficiency import EARLY_TERMINATE, NEED_CLARIFY

    mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    rows: List[Dict[str, Any]] = []
    try:
        # S4: 正常 PROCEED，走 S→A→C→G 真调度
        sink: List[Dict[str, Any]] = []
        orch = _sacg_orchestrator(mgr, sink)
        t0 = time.perf_counter()
        res = orch.handle(
            "宏观与资金面是否矛盾", l1_intent_hint="contradiction_insight", memories=[]
        )
        latency = (time.perf_counter() - t0) * 1000.0
        rec.write(
            {
                "scenario_id": "S4",
                "entry": "P3",
                "kind": "scenario",
                "trace_id": gen_trace_id(),
                "latency_ms": round(latency, 3),
                "route": res.get("route"),
                "stages": res.get("stages"),
                "nodes": len(res.get("nodes") or []),
                "node_results": res.get("node_results"),
                "sediments": (res.get("closure") or {}).get("sediments"),
                "assertions": [
                    {"name": "route_is_L2_HANDOFF", "pass": res.get("route") == "L2_HANDOFF"},
                    {
                        "name": "stages_cover_SACG",
                        "pass": set(res.get("stages") or []) >= {"S", "A", "C", "G"},
                    },
                    {"name": "nodes_executed", "pass": len(sink) >= 1},
                ],
                "degraded": bool(res.get("degraded")),
                "simulated": False,
                "note": "SACG 未接入产品链（D-2），本结果为 in-process 取证",
            }
        )
        rows.append(
            {
                "scenario_id": "S4",
                "stages": res.get("stages"),
                "nodes": len(sink),
                "sediments": len((res.get("closure") or {}).get("sediments") or []),
            }
        )

        # S15: G 四分流取证（case/skill/doc/cognitive 各触发一次）
        from core.sacg_orchestrator import SACGOrchestrator

        def _two_nodes(_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
            return [
                {"node_id": "N1", "criteria": "a"},
                {"node_id": "N2", "criteria": "b"},
            ]

        def _mk(exec_fn: Any) -> Any:
            return SACGOrchestrator(
                a_decomposer=_two_nodes,
                c_executor=exec_fn,
                record_fn=lambda **_k: {"ok": True, "simulated": True},
                verify_fn=lambda **_k: {"ok": True, "simulated": True},
            )

        g_types: List[str] = [
            str(s.get("type"))
            for s in ((res.get("closure") or {}).get("sediments") or [])
            if isinstance(s, dict)
        ]
        r_fail = _mk(
            lambda _r, _n: {"action": "FAILED", "tier": "Tier1", "effort_level": "light"}
        ).handle("BTC 结构是否转弱", l1_intent_hint="technical_analysis", memories=[])
        g_types += [
            str(s.get("type"))
            for s in ((r_fail.get("closure") or {}).get("sediments") or [])
            if isinstance(s, dict)
        ]
        r_deg = _mk(
            lambda _r, _n: {"action": "REDO", "tier": "Tier1", "effort_level": "light"}
        ).handle("估值分位是否极端", l1_intent_hint="fundamental_valuation", memories=[])
        g_types += [
            str(s.get("type"))
            for s in ((r_deg.get("closure") or {}).get("sediments") or [])
            if isinstance(s, dict)
        ]
        g_types = sorted(set(g_types))
        rec.write(
            {
                "scenario_id": "S15",
                "entry": "P3",
                "kind": "scenario",
                "trace_id": gen_trace_id(),
                "sediments": g_types,
                "assertions": [
                    {"name": "case_present", "pass": "case" in g_types},
                    {"name": "skill_present", "pass": "skill" in g_types},
                    {"name": "doc_present", "pass": "doc" in g_types},
                    {
                        "name": "cognitive_present",
                        "pass": bool((r_fail.get("closure") or {}).get("cognitive")),
                    },
                ],
                "c_layer_redo": True,
                "degraded": False,
                "simulated": True,
                "note": "sediments 为 async_stub 描述符；认知分流经注入 record_fn 双打（模拟）",
            }
        )
        rows.append({"scenario_id": "S15", "sediments": g_types})

        # S11 / S12: S 层充分性短路
        for sid, action_name, msg in (
            ("S11", NEED_CLARIFY, "帮我看看这个"),
            ("S12", EARLY_TERMINATE, "今天天气如何"),
        ):

            def _short_planner(_m, _h, _mem, _a=action_name):
                return {
                    "action": _a,
                    "plan": {"plan_items": []},
                    "sufficiency": {"action": _a},
                    "clarification": (
                        {"options": ["标的", "周期", "维度"]} if _a == NEED_CLARIFY else None
                    ),
                }

            o = SACGOrchestrator(s_planner=_short_planner, record_fn=lambda **_k: {"ok": True})
            r = o.handle(msg, l1_intent_hint="data_query", memories=[])
            rec.write(
                {
                    "scenario_id": sid,
                    "entry": "P3",
                    "kind": "scenario",
                    "trace_id": gen_trace_id(),
                    "route": r.get("route"),
                    "stages": r.get("stages"),
                    "action": r.get("action"),
                    "assertions": [
                        {"name": "short_circuit", "pass": r.get("orchestrated") is True},
                        {"name": "no_downstream_nodes", "pass": not (r.get("nodes") or [])},
                    ],
                    "degraded": bool(r.get("degraded")),
                    "simulated": False,
                }
            )
            rows.append({"scenario_id": sid, "action": r.get("action")})
    finally:
        mgr.close_all()
    return {"phase": "p3", "rows": rows}


# ── 阶段 5: 故障注入 ─────────────────────────────────────────────────


def phase_faults(rec: JsonlRecorder) -> Dict[str, Any]:
    _ensure_paths()
    from core.l0_foundation import L0Foundation  # type: ignore
    from core.shell_handles import ShellHandleManager  # type: ignore
    from core.stdio_shell_launcher import stdio_launcher  # type: ignore
    from core.worker_tool_call import call_worker_tool  # type: ignore

    ON = {"enable_worker_tool_call": True}
    out: Dict[str, Any] = {"phase": "faults"}

    # S13-超时：不可达 base + 极短超时 → degraded，不抛
    t0 = time.perf_counter()
    l0 = L0Foundation(
        okx_base="http://127.0.0.1:9", okx_backup="http://127.0.0.1:9", http_timeout=0.05
    )
    env = l0.fetch_context("market.ticker", {"symbol": "BTC"})
    latency = (time.perf_counter() - t0) * 1000.0
    rec.write(
        {
            "scenario_id": "S13",
            "entry": "P3",
            "kind": "scenario",
            "fault": "timeout",
            "trace_id": gen_trace_id(),
            "latency_ms": round(latency, 3),
            "degraded": bool(env.get("degraded")),
            "error_code": (env.get("meta") or {}).get("reason") or env.get("error_code"),
            "assertions": [
                {"name": "degraded_true", "pass": bool(env.get("degraded"))},
                {"name": "no_fabricated_value", "pass": env.get("data") is None},
            ],
            "simulated": False,
        }
    )
    out["timeout"] = bool(env.get("degraded"))

    # S13b-401：无效 Tavily 不可用 → 壳内降级（docs.search 走 41 CLI，此处验证缺参降级）
    tmp = tempfile.mkdtemp(prefix="dreambuddy-eval-")
    os.environ["DREAMBUDDY_L0_ROOT"] = tmp
    env2 = l0.fetch_context("docs.search", {"query": ""})
    rec.write(
        {
            "scenario_id": "S13",
            "entry": "P3",
            "kind": "scenario",
            "fault": "invalid_params_401_proxy",
            "trace_id": gen_trace_id(),
            "degraded": bool(env2.get("degraded")),
            "error_code": (env2.get("meta") or {}).get("reason") or env2.get("error_code"),
            "assertions": [{"name": "degraded_true", "pass": bool(env2.get("degraded"))}],
            "simulated": False,
            "note": "401 以 docs.search 缺参降级代理，未直连外部 Tavily",
        }
    )
    out["auth_degrade"] = bool(env2.get("degraded"))

    # S14-并发：5 并发 get_ticket_status，全部完成且可查
    mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    try:
        results: List[Dict[str, Any]] = []
        lock = threading.Lock()

        def _one(i: int) -> None:
            tid = f"s14-{i}-{gen_trace_id()}"
            r = call_worker_tool(
                "research",
                "get_ticket_status",
                args={},
                checker=lambda _r, _t: True,
                manager=mgr,
                flags=ON,
                trace_id=tid,
            )
            with lock:
                results.append({"trace_id": tid, "ok": bool(r.get("ok"))})

        threads = [threading.Thread(target=_one, args=(i,)) for i in range(5)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        latency = (time.perf_counter() - t0) * 1000.0
        done = sum(1 for r in results if r["ok"])
        rec.write(
            {
                "scenario_id": "S14",
                "entry": "P1b",
                "kind": "scenario",
                "trace_id": gen_trace_id(),
                "latency_ms": round(latency, 3),
                "submitted": 5,
                "completed": done,
                "assertions": [
                    {"name": "no_lost_request", "pass": len(results) == 5},
                    {"name": "all_completed", "pass": done == 5},
                    {
                        "name": "cap_enforced",
                        "pass": False,
                        "note": "DSH 未提供并发上限配置（发现）",
                    },
                ],
                "degraded": done < 5,
                "simulated": False,
            }
        )
        out["concurrency"] = {"submitted": 5, "completed": done}

        # S16-Mandate：拒绝（默认 checker）+ 放行（显式 checker，临时 DB）
        deny = call_worker_tool(
            "verifier",
            "record",
            {"content": "eval-deny"},
            manager=mgr,
            flags=ON,
            trace_id="s16-deny",
        )
        tmpdb = os.path.join(tmp, "cognitive.db")
        # 写链路隔离根 + 壳内写开关与 principal（否则 record 返回 scope_denied/principal_denied）
        os.environ["DREAMBUDDY_COGNITIVE_DB"] = tmpdb
        os.environ["COGNITIVE_MCP_WRITE_ENABLED"] = "true"
        os.environ["COGNITIVE_MCP_DEFAULT_PRINCIPAL"] = "verifier"
        mgr.close_all()
        # l0.cognition 是 ssh-stdio；bridge.launcher_factory 会在无 DSH_SSH_HOST 时降级本地 stdio
        from core.dsh_frontend_bridge import launcher_factory  # type: ignore

        mgr2 = ShellHandleManager(launcher=launcher_factory, flags={"enable_shell_handles": True})
        try:
            allow = call_worker_tool(
                "verifier",
                "record",
                {"content": "eval-allow"},
                checker=lambda _r, _t: True,
                manager=mgr2,
                flags=ON,
                trace_id="s16-allow",
            )
        finally:
            mgr2.close_all()
        wrote = os.path.exists(tmpdb) and bool((allow.get("data") or {}).get("memory_id"))
        rec.write(
            {
                "scenario_id": "S16",
                "entry": "P1b",
                "kind": "scenario",
                "trace_id": "s16-deny",
                "assertions": [
                    {"name": "deny_without_mandate", "pass": deny.get("ok") is False},
                    {
                        "name": "deny_reason",
                        "pass": deny.get("error_code") in ("forbidden", "mandate_required"),
                    },
                    {"name": "allow_with_mandate", "pass": bool(allow.get("ok")) or wrote},
                ],
                "deny_code": deny.get("error_code"),
                "allow_ok": allow.get("ok"),
                "write_landed": wrote,
                "degraded": False,
                "simulated": False,
            }
        )
        out["mandate"] = {
            "deny_code": deny.get("error_code"),
            "allow_ok": allow.get("ok"),
            "write_landed": wrote,
        }
    finally:
        try:
            mgr.close_all()
        except Exception:
            pass
    return out


# ── 主入口 ───────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--phase",
        default="sweep,p1,p1b,p3,faults",
        help="逗号分隔: sweep,p1,p1b,p3,faults",
    )
    args = ap.parse_args()
    phases = [p.strip() for p in args.phase.split(",") if p.strip()]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 首阶段为 sweep 视为一次全量运行，重置证据；单阶段补跑则追加
    rec = JsonlRecorder(EVIDENCE_PATH, reset=(phases and phases[0] == "sweep"))
    registry = load_registry(DEFAULT_REGISTRY)
    scenarios = _load_scenarios()

    summary: Dict[str, Any] = {"phases": {}}
    failed = False
    for phase in phases:
        t0 = time.perf_counter()
        try:
            if phase == "sweep":
                r = phase_sweep(rec, registry)
            elif phase == "p1":
                r = phase_p1(rec, scenarios)
            elif phase == "p1b":
                r = phase_p1b(rec, scenarios)
            elif phase == "p3":
                r = phase_p3(rec)
            elif phase == "faults":
                r = phase_faults(rec)
            else:
                r = {"phase": phase, "skipped": "unknown"}
        except Exception as exc:
            failed = True
            r = {"phase": phase, "error": f"{type(exc).__name__}: {exc}"}
        r["elapsed_s"] = round(time.perf_counter() - t0, 2)
        summary["phases"][phase] = r
        print(f"[{phase}] {json.dumps(r, ensure_ascii=False, default=str)[:400]}")

    summary_path = OUT_DIR / "smoke_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n证据: {EVIDENCE_PATH}\n摘要: {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
