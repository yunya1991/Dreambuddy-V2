#!/usr/bin/env python3
"""collect_real_trajectories.py — 真实域调用 → 信封 → AgentMailShadow 旁路采集

背景：`.workbuddy/agent_mail/trajectories.jsonl` 里的历史条目是合成 envelope，
AgentMailShadow.observe() 从未被生产代码调用（全仓仅测试命中）。
本模块用**真实域操作**（真实文件读取 / 真实 AST 静态分析 / 真实认知库 recall /
真实 HTTP 探测）产生真实信封，再交给 AgentMailShadow.observe() 落盘。

真实域操作（离线优先，FAIL-OPEN）：
  - data    34 L0Foundation 11 scope（读取本地真实 JSON/日志，PG/HTTP 不可用则真实降级）
  - rea     33 dsh_nodes 静态分析节点（子进程隔离 sys.path）
  - cognition 4-MEMORY 认知库 recall（真实本地 memory DB）
  - search  41 search_cli recall（子进程；索引/PG 不可用则真实降级）
  - semantic 39 mcp_server 语义表查询（真实实体别名表）
  - eval    45 评测 HTTP /api/v1/eval/metrics（探测真实服务可达性）

硬约束（COMM-SHADOW S1-S3）：只写本地 JSONL；trace_id shadow- 前缀；
默认 head_infer=False（不 import torch）；任何域操作异常 → degraded 信封，不中断采集。

CLI:
  python mcp_shells/_shared/collect_real_trajectories.py --waves 3 --domains data,rea
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.agent_mail_shadow import AgentMailShadow  # noqa: E402
from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402

DOMAIN_SOURCES = {
    "cognition": "l0.cognition.mcp",
    "rea": "l0.rea.mcp",
    "search": "l0.search.mcp",
    "semantic": "l0.semantic-39.mcp",
    "data": "l0.data.mcp",
    "eval": "l0.eval.mcp",
}

# 数据域真实 scope（34 L0Foundation 本地文件类；PG/HTTP 类允许真实降级）
_DATA_SCOPES = [
    ("data_fetch", {"scope": "yijing.bcrm2"}),
    ("data_fetch", {"scope": "yijing.bdsm"}),
    ("data_fetch", {"scope": "yijing.strategic"}),
    ("data_fetch", {"scope": "event.state"}),
    ("data_fetch", {"scope": "evolution.snapshot"}),
    ("data_fetch", {"scope": "evolution.contradiction"}),
    ("data_fetch", {"scope": "riskcontrol.trailing"}),
    ("data_fetch", {"scope": "datacenter.record", "params": {"source": "fear_greed"}}),
    ("data_fetch", {"scope": "market.ticker", "params": {"symbol": "BTC-USDT-SWAP"}}),
]

_REA_CODE = """
import json, sys
sys.path.insert(0, "33-REA逆向解析工程")
import dsh_nodes
params = json.loads(sys.argv[1])
fn = getattr(dsh_nodes, params.pop("_node"))
print(json.dumps(fn(params), ensure_ascii=False))
"""

_REA_OPS = [
    (
        "submit_rea_analyze",
        {"_node": "S33_rea_analyze", "target": "mcp_shells/_shared", "scope": "architecture"},
    ),
    (
        "submit_rea_trace",
        {"_node": "S33_rea_trace", "target": "mcp_shells/_shared", "feature": "信封包装"},
    ),
    (
        "submit_rea_compare",
        {
            "_node": "S33_rea_compare",
            "target_a": "dreambuddy_l0",
            "target_b": "mcp_shells/_shared",
            "feature": "端口协议",
        },
    ),
]


def _load_module_from_path(name: str, path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 各域真实操作（返回 (data, degraded, error_code)） ----------
_LEGACY_L0: Optional[Any] = None


def _legacy_l0() -> Any:
    global _LEGACY_L0
    if _LEGACY_L0 is None:
        mod = _load_module_from_path(
            "dreambuddy_l0_legacy34",
            _REPO_ROOT / "34-前端应用训练系统" / "core" / "l0_foundation.py",
        )
        _LEGACY_L0 = mod.get_l0()
    return _LEGACY_L0


def _data_op(_name: str, args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    inner = _legacy_l0().fetch_context(args["scope"], args.get("params"))
    degraded = bool(inner.get("degraded", False))
    reason = str((inner.get("meta") or {}).get("reason", "")) if degraded else ""
    return inner.get("data"), degraded, "degraded" if degraded else "", reason


def _rea_op(name: str, args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    params = dict(args)
    pool_dir = str(_REPO_ROOT / ".workbuddy" / "agent_mail" / "replay_pool")
    params.setdefault("pool_dir", pool_dir)
    proc = subprocess.run(
        [sys.executable, "-c", _REA_CODE, json.dumps(params, ensure_ascii=False)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        return {"stderr": proc.stderr[-500:]}, True, "unavailable", "rea_node_failed"
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ok = bool(out.get("ok"))
    return out.get("result"), not ok, ("degraded" if not ok else ""), str(out.get("error") or "")


def _cognition_op(_name: str, args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    cog_path = str(_REPO_ROOT / "4-MEMORY" / "9-工具与接口")
    if cog_path not in sys.path:
        sys.path.insert(0, cog_path)
    from cognitive_loop_entry import get_cle

    memories = get_cle().recall(args.get("context", ""), top_k=5, min_quality="C")
    return (
        {"count": len(memories or []), "ids": [m.get("id") for m in (memories or [])][:5]},
        False,
        "",
    )


def _search_op(_name: str, args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    cli = _REPO_ROOT / "41-文件索引系统" / "scripts" / "search_cli.py"
    if not cli.exists():
        return None, True, "not_found", "search_cli_missing"
    proc = subprocess.run(
        [sys.executable, str(cli)],
        input=json.dumps(
            {"cmd": "recall", "query": args.get("query", ""), "limit": 3}, ensure_ascii=False
        ),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cli.parents[1]),
    )
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        return {"stderr": (proc.stderr or "")[-300:]}, True, "unavailable", "search_cli_failed"
    res = json.loads(text.splitlines()[-1])
    ok = bool(res.get("success", True))
    return res, not ok, ("degraded" if not ok else ""), str(res.get("error") or "")


def _semantic_op(_name: str, args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    mod = _load_module_from_path(
        "dreambuddy_semantic39_mcp",
        _REPO_ROOT / "39-金融语义蒸馏系统" / "scripts" / "mcp_server.py",
    )
    res: Any = None
    if args.get("kind") == "entity":
        res = mod.tool_query_entity(args.get("message", ""))
    else:
        res = mod.tool_semantic_lookup(args.get("term", ""))
    degraded = not bool(res) or (isinstance(res, dict) and "error" in res)
    return res, degraded, ("degraded" if degraded else ""), "semantic_lookup_empty"


def _eval_op(_name: str, _args: Dict[str, Any]) -> Tuple[Any, bool, str]:
    url = "http://127.0.0.1:8790/api/v1/eval/metrics"
    with urllib.request.urlopen(url, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8")), False, ""


# ---------- 采集编排 ----------
_OPS: Dict[str, List[Tuple[str, Dict[str, Any], Callable[..., Tuple[Any, bool, str]]]]] = {
    "data": [(n, a, _data_op) for n, a in _DATA_SCOPES],
    "rea": [(n, a, _rea_op) for n, a in _REA_OPS],
    "cognition": [("recall", {"context": "真实 trajectory 采集 域壳 信封"}, _cognition_op)],
    "search": [("unified_search", {"query": "域耦合 信封"}, _search_op)],
    "semantic": [
        ("semantic_lookup", {"term": "资金费率"}, _semantic_op),
        ("query_entity", {"kind": "entity", "message": "BTC 永续合约资金费率转负"}, _semantic_op),
    ],
    "eval": [("eval_report", {}, _eval_op)],
}


def _run_op(
    domain: str, name: str, args: Dict[str, Any], fn: Callable[..., Tuple[Any, bool, str]]
) -> Dict[str, Any]:
    started = time.time()
    reason = ""
    try:
        raw = fn(name, args)
        data, degraded, error_code = raw[0], raw[1], raw[2]
        reason = raw[3] if len(raw) > 3 else ""
    except Exception as e:  # noqa: BLE001 — 域操作失败 → 真实 degraded 信封
        data, degraded, error_code, reason = None, True, "unavailable", f"{type(e).__name__}: {e}"
    latency_ms = round((time.time() - started) * 1000.0, 3)
    meta: Dict[str, Any] = {
        "event_type": name,
        "latency_ms": latency_ms,
        "messages_sent": 1,
        "poe_score": 0.8 if not degraded else 0.0,
    }
    if reason:
        meta["reason"] = reason
    return wrap(data, DOMAIN_SOURCES[domain], degraded=degraded, error_code=error_code, meta=meta)


def collect_real_trajectories(
    waves: int = 2,
    domains: Optional[List[str]] = None,
    store_path: Optional[str] = None,
    shadow: Optional[AgentMailShadow] = None,
) -> Dict[str, Any]:
    """跑 N 波真实域操作 → observe 落盘。返回采集摘要。"""
    selected = [d for d in (domains or list(DOMAIN_SOURCES)) if d in DOMAIN_SOURCES]
    shadow = shadow or AgentMailShadow(trajectory_store_path=store_path, head_infer=False)
    observed = 0
    degraded = 0
    per_domain: Dict[str, int] = {}
    for _ in range(max(1, int(waves))):
        for domain in selected:
            envelopes: List[Dict[str, Any]] = []
            for name, args, fn in _OPS[domain]:
                env = _run_op(domain, name, args, fn)
                envelopes.append(env)
                observed += 1
                degraded += 1 if env["degraded"] else 0
                per_domain[domain] = per_domain.get(domain, 0) + 1
            shadow.observe(envelopes)
    return {
        "observed": observed,
        "degraded": degraded,
        "domains": sorted(per_domain),
        "per_domain": per_domain,
        "store": str(shadow._store_path),  # noqa: SLF001 — 摘要用
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="真实 trajectory 采集")
    ap.add_argument("--waves", type=int, default=2)
    ap.add_argument("--domains", default="", help="逗号分隔，默认全部 6 域")
    ap.add_argument("--store", default="", help="覆盖 trajectory store 路径")
    ns = ap.parse_args()
    domains = [d.strip() for d in ns.domains.split(",") if d.strip()] or None
    summary = collect_real_trajectories(
        waves=ns.waves, domains=domains, store_path=ns.store or None
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
