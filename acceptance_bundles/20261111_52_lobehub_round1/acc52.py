import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/52-lobehub协议集成")
sys.path.insert(0, str(ROOT / "orchestrator"))
sys.path.insert(0, str(ROOT / "bridge"))

import distill_bridge  # noqa: E402
import domain_eval  # noqa: E402
import registry_tools  # noqa: E402
import scoring  # noqa: E402

out = {}

reg = registry_tools.load_registry()
allowed = reg.allowed()
domains = reg.domains
trade_tools = sorted(t for t, d in domains.items() if d == "trade-exec")
safe_tools = sorted(t for t in allowed if t.startswith("l0.") and domains.get(t) != "trade-exec")
out["registry"] = {
    "allowed_count": len(allowed),
    "domain_count": len(set(domains.values())),
    "trade_exec_tools": trade_tools[:5],
    "safe_tool_sample": safe_tools[:3],
}

base_card = {
    "id": "pc-acc-0001",
    "intent": "验收：回撤控制方案对比",
    "plan_steps": [{"step": 1, "action": "查询回测", "tool": safe_tools[0]}],
    "validation": {"evaluator_refs": ["45.heuristic@1.0.0"]},
}
out["gate_clean"] = scoring.gate(base_card, reg)

trade_card = json.loads(json.dumps(base_card))
trade_card["id"] = "pc-acc-0002"
trade_card["plan_steps"][0]["tool"] = (
    trade_tools[0] if trade_tools else "l0.tradeexec.mcp.place_order"
)
out["gate_trade_exec"] = scoring.gate(trade_card, reg)

live_card = json.loads(json.dumps(base_card))
live_card["id"] = "pc-acc-0003"
live_card["risk_flags"] = ["实盘下单回撤 3%"]
out["gate_live_flag"] = scoring.gate(live_card, reg)

disc = domain_eval.discover()
out["evaluators"] = {
    "available": disc.get("available"),
    "names": len(disc.get("evaluators") or disc.get("names") or []),
    "reason": disc.get("reason"),
}
ev = domain_eval.evaluate_plan(base_card, run_id="acc-run-001", discovery=disc)
out["evaluate_plan"] = {"verdict": ev.get("verdict"), "reason": ev.get("reason")}
base, detail = domain_eval.structural_score(base_card, reg)
out["structural"] = {"base": base, "dims": [(d["name"], d["contribution"]) for d in detail]}


class FakeShell:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"ok": True}


tmp = pathlib.Path(tempfile.mkdtemp(prefix="acc52_bridge_"))
outbox = tmp / "outbox.jsonl"
entries = [
    {
        "type": "brainstorm_winner",
        "content": "[验收] 方案A 胜出 plancard=pc-1 score=0.91",
        "tags": ["protocol-bridge", "brainstorm"],
        "source_ref": "acc-run-001:pc-1",
        "bridge_ts": "2026-11-11T20:00:00+0800",
    },
    {
        "type": "brainstorm_winner",
        "content": "[验收] 方案A 胜出 plancard=pc-1 score=0.91",
        "tags": ["protocol-bridge", "brainstorm"],
        "source_ref": "acc-run-001:pc-1",
        "bridge_ts": "2026-11-11T20:00:00+0800",
    },
    {
        "type": "unknown_type",
        "content": "非法类型应被拒",
        "tags": ["protocol-bridge"],
        "source_ref": "acc-run-001:pc-x",
        "bridge_ts": "2026-11-11T20:00:00+0800",
    },
]
outbox.write_text(
    "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8"
)
cursor = tmp / ".cursor"
seen = tmp / ".seen"
shell = FakeShell()
stats1 = distill_bridge.process_outbox(outbox, cursor, shell_factory=lambda: shell, seen_path=seen)
out["bridge"] = {
    "first": stats1,
    "cursor_after": cursor.read_text(encoding="utf-8"),
    "seen_lines": len(seen.read_text(encoding="utf-8").strip().splitlines()),
    "shell_calls": len(shell.calls),
}
cursor.write_text("0", encoding="utf-8")
stats2 = distill_bridge.process_outbox(outbox, cursor, shell_factory=lambda: shell, seen_path=seen)
out["bridge"]["cursor_rollback_rerun"] = stats2
out["bridge"]["shell_calls_after_rerun"] = len(shell.calls)

print(json.dumps(out, ensure_ascii=False, indent=1))
