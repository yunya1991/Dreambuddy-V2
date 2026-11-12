"""R1+R2+R3 验收复测脚本（可复现；只读项目代码，不写业务数据）。

R1：15 条历史 G4 误伤风险描述 → 期望 PASS + notes（不拦截）；动作/裸声明 → 仍 BLOCK。
R2：--force 时 trace/summary 的 mode_basis=force，route 保持 router 原文。
R3：trace 顶层 executed 显式存在且与 summary 一致。
"""

import json
import pathlib
import subprocess
import sys

BASE = pathlib.Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2")
MODULE = BASE / "52-lobehub协议集成"
ORCH = MODULE / "orchestrator"
BUNDLE = BASE / "acceptance_bundles/20261111_52_lobehub_r1r2r3"
sys.path.insert(0, str(ORCH))

import registry_tools  # noqa: E402
import scoring  # noqa: E402

# 从 traces/brainstorm.jsonl 实测提取的 15 条 G4 误伤旗标（原样保留）
HISTORICAL_FLAGS = [
    "证据仅来自检索与记忆，缺少实盘验证",
    "证据仅覆盖检索与记忆，缺少实盘验证",
    "需确保参数切换可回滚，避免实盘误用",
    "实盘与回测偏离",
    "实盘与回测滑点差异",
    "实盘滑点与回测偏差",
    "实盘持仓范围未确认前改动存在敞口风险",
    "历史回测与实盘执行差异（流动性、成交假设）",
    "回滚机制未验证前存在实盘风险",
    "回测与实盘偏差：滑点与流动性假设可能低估成本",
    "回测与实盘滑点差异",
    "回测与实盘滑点/流动性差异",
    "回测样本期与实盘波动率分布可能不一致",
    "成本估计依赖历史数据，实盘滑点未纳入",
    "参数切换缺少回滚点，实盘切换风险",
]

# 安全下限守卫：这些必须仍然 BLOCK（铁律④未被放宽）
BLOCK_GUARDS = [
    "实盘",
    "下单",
    "live",
    "order",
    "live trading",
    "实盘下单",
    "接入实盘",
    "live_trading",
    "place order",
    "直接下单",
    "真实账户下单",
]

out = {}
reg = registry_tools.load_registry()
safe_tools = sorted(
    t for t in reg.allowed() if t.startswith("l0.") and reg.domains.get(t) != "trade-exec"
)
base_card = {
    "id": "pc-acc-replay-0001",
    "intent": "验收：回撤控制方案对比",
    "context_refs": ["l0.cognition.mcp.health"],
    "plan_steps": [
        {"step": 1, "action": "查询回测", "tool": safe_tools[0], "args_hint": {}},
        {"step": 2, "action": "读取健康度", "tool": safe_tools[1], "args_hint": {}},
    ],
    "evidence_refs": ["backtest:acc-replay-001", "recall:VM-1794396006591-dfb79907"],
    "cost_estimate": {"tokens": 800, "tool_calls": 2},
    "expected_outcome": "输出回测对比结论，不产生任何写操作",
    "validation": {
        "evaluator_refs": ["45.heuristic@1.0.0"],
        "acceptance_checks": ["回测数据可读", "结论可复核"],
    },
}

out["R1_replay"] = []
for flag in HISTORICAL_FLAGS:
    card = json.loads(json.dumps(base_card))
    card["risk_flags"] = [flag]
    result = scoring.gate(card, reg)
    out["R1_replay"].append(
        {
            "flag": flag,
            "verdict": result["verdict"],
            "reasons": result["reasons"],
            "notes": result.get("notes") or [],
        }
    )

out["R1_guards"] = []
for flag in BLOCK_GUARDS:
    card = json.loads(json.dumps(base_card))
    card["risk_flags"] = [flag]
    result = scoring.gate(card, reg)
    out["R1_guards"].append({"flag": flag, "verdict": result["verdict"]})

out["R1_summary"] = {
    "replay_total": len(out["R1_replay"]),
    "replay_pass": sum(1 for r in out["R1_replay"] if r["verdict"] == "PASS"),
    "replay_with_notes": sum(1 for r in out["R1_replay"] if r["notes"]),
    "guards_total": len(out["R1_guards"]),
    "guards_block": sum(1 for r in out["R1_guards"] if r["verdict"] == "BLOCK"),
}

# R2/R3 端到端：--force + 含风险描述的 side-A 卡
run_dir = BUNDLE / "run"
run_dir.mkdir(parents=True, exist_ok=True)
trace = run_dir / "t.jsonl"
outbox = run_dir / "o.jsonl"
for p in (trace, outbox):
    if p.exists():
        p.unlink()
cmd = [
    sys.executable,
    str(ORCH / "brainstorm_orchestrator.py"),
    "--intent",
    "离场模块要不要加波动率自适应阈值，哪种更好，看回测和成本",
    "--side-a-plancard",
    str(BUNDLE / "plancard_side_a.json"),
    "--disable-recall",
    "--n-per-side",
    "2",
    "--force",
    "--trace-path",
    str(trace),
    "--outbox-path",
    str(outbox),
    "--json-out",
]
proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
summary = json.loads(proc.stdout) if proc.stdout.strip() else {}
record = (
    json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    if trace.exists() and trace.read_text(encoding="utf-8").strip()
    else {}
)
out["E2E"] = {
    "cli_exit": proc.returncode,
    "stderr_tail": (proc.stderr or "").strip().splitlines()[-3:],
    "summary_mode": summary.get("mode"),
    "summary_mode_basis": summary.get("mode_basis"),
    "summary_executed": summary.get("executed"),
    "trace_mode": record.get("mode"),
    "trace_mode_basis": record.get("mode_basis"),
    "trace_route": record.get("route"),
    "trace_executed": record.get("executed"),
    "decision": (summary.get("decision") or {}).get("kind"),
    "gates": [
        {
            "card_id": g.get("card_id"),
            "verdict": g.get("verdict"),
            "reasons": g.get("reasons"),
            "notes": g.get("notes") or [],
        }
        for g in record.get("gates") or []
    ],
}

# R2 复现原场景：router=workers + --force → mode=debate，必须由 mode_basis 解释
trace2 = run_dir / "t_workers_force.jsonl"
for p in (trace2, outbox):
    if p.exists():
        p.unlink()
cmd2 = list(cmd)
cmd2[cmd2.index("--intent") + 1] = "帮我整理一下最近的工程改动"
cmd2[cmd2.index("--trace-path") + 1] = str(trace2)
proc2 = subprocess.run(cmd2, capture_output=True, text=True, check=False)
summary2 = json.loads(proc2.stdout) if proc2.stdout.strip() else {}
record2 = (
    json.loads(trace2.read_text(encoding="utf-8").strip().splitlines()[-1])
    if trace2.exists()
    else {}
)
out["E2E_workers_force"] = {
    "cli_exit": proc2.returncode,
    "summary_route": summary2.get("route"),
    "summary_mode": summary2.get("mode"),
    "summary_mode_basis": summary2.get("mode_basis"),
    "trace_route": record2.get("route"),
    "trace_mode": record2.get("mode"),
    "trace_mode_basis": record2.get("mode_basis"),
    "trace_executed": record2.get("executed"),
    "decision": (summary2.get("decision") or {}).get("kind"),
}

print(json.dumps(out, ensure_ascii=False, indent=1))
