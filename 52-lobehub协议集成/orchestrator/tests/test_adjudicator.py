"""Phase 4.5 论证学裁决器测试（纯离线，确定性）。

覆盖三场景：唯一胜者 / 互攻致 UNDEC → INCONCLUSIVE / 门禁否决根论点，
外加与启发式一致性字段（由编排器写入 trace）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parents[1]
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))

from adjudicator import adjudicate  # noqa: E402


def make_card(card_id: str, steps, risk_flags=None):
    return {
        "id": card_id,
        "intent": "评估是否给离场模块增加波动率自适应阈值",
        "plan_steps": steps,
        "risk_flags": risk_flags or [],
    }


def scored(card, side):
    return {"card": card, "side": side, "score": 0.5, "gate_verdict": "PASS"}


def gates(*pairs):
    return [
        {"card_id": cid, "verdict": verdict, "reasons": reasons} for cid, verdict, reasons in pairs
    ]


def test_unique_winner_via_risk_flag_attack():
    a = make_card(
        "pc-a",
        [{"step": 1, "action": "检索阈值经验", "tool": "l0.cognition.mcp.recall"}],
        risk_flags=["l0.eval.mcp.eval_analyze 结果可能不稳定"],
    )
    b = make_card(
        "pc-b",
        [{"step": 1, "action": "评估候选方案", "tool": "l0.eval.mcp.eval_analyze"}],
    )
    result = adjudicate([scored(a, "side_a"), scored(b, "side_b")], gates())

    assert result["winner"] == "pc-a"
    assert result["verdict"] == "WIN"
    assert "pc-b:step:1" in result["out_set"]
    assert "pc-a:card" in result["in_set"]
    assert any(edge["rule"] == "R-c" for edge in result["attack_edges"])
    assert any("pc-a" in line and "pc-b:step:1" in line for line in result["explain"])


def test_mutual_attack_yields_inconclusive():
    a = make_card(
        "pc-a",
        [{"step": 1, "action": "用 recall 做检索", "tool": "l0.cognition.mcp.recall"}],
    )
    b = make_card(
        "pc-b",
        [{"step": 1, "action": "用 recall 做经验回捞", "tool": "l0.cognition.mcp.recall"}],
    )
    result = adjudicate([scored(a, "side_a"), scored(b, "side_b")], gates())

    assert result["winner"] is None
    assert result["verdict"] == "INCONCLUSIVE"
    assert "pc-a:step:1" in result["undec_set"]
    assert "pc-b:step:1" in result["undec_set"]
    assert "pc-a:card" in result["in_set"]
    assert "pc-b:card" in result["in_set"]


def test_gate_veto_root_argument_knocks_out_blocked_card():
    a = make_card(
        "pc-a",
        [{"step": 1, "action": "检索经验", "tool": "l0.cognition.mcp.recall"}],
    )
    b = make_card(
        "pc-b",
        [{"step": 1, "action": "下单执行", "tool": "l0.trade-exec.mcp.place_order"}],
    )
    result = adjudicate(
        [scored(a, "side_a"), scored(b, "side_b")],
        gates(("pc-a", "PASS", []), ("pc-b", "BLOCK", ["G3:trade_exec_forbidden"])),
    )

    assert "gate:pc-b" in result["in_set"]
    assert result["winner"] == "pc-a"
    assert "pc-b:card" in result["out_set"]
    assert any(
        edge["rule"] == "R-a" and edge["from"] == "gate:pc-b" for edge in result["attack_edges"]
    )


def test_adjudication_consistency_field_written_to_trace(tmp_path):
    """编排器 trace.adjudication 记录 heuristic_top / grounded_winner / agree。"""
    import brainstorm_orchestrator as orch
    from proposers import SideAProposer, SideBProposer

    a = make_card(
        "pc-a",
        [
            {"step": 1, "action": "检索阈值经验", "tool": "l0.cognition.mcp.recall"},
            {"step": 2, "action": "评估候选", "tool": "l0.eval.mcp.eval_analyze"},
        ],
    )
    a.update(
        {
            "intent": "阈值评估",
            "context_refs": [],
            "evidence_refs": ["recall:x", "recall:y"],
            "risk_flags": ["l0.data.mcp.data_fetch 数据可能过期"],
            "cost_estimate": {"tokens": 100},
            "expected_outcome": "回测计划",
            "validation": {"evaluator_refs": ["45.heuristic@1.0.0"], "acceptance_checks": ["x"]},
        }
    )

    def a_poster(url, payload, **_kwargs):
        return {"ok": True, "data": {"plancard": a, "model": "qwen-plus", "evidence_path": "p-a"}}

    def b_poster(url, payload, **_kwargs):
        return {"intent_type": "analysis", "base_chain": ["F1"], "extend_nodes": []}

    trace = tmp_path / "t.jsonl"
    orch.run(
        intent="阈值评估",
        trace_path=trace,
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=[
            SideAProposer(poster=a_poster, model_hint="qwen-plus"),
            SideBProposer(poster=b_poster, allowed_tools={"l0.data.mcp.data_fetch"}),
        ],
        registry=orch.load_registry(),
    )
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    adjudication = record["adjudication"]
    assert adjudication["heuristic_top"] == "pc-a"
    assert adjudication["agree"] is True
    assert adjudication["grounded_winner"] == "pc-a"
