"""52-LobeHub Phase 4 脑暴编排器测试（不触真实服务：HTTP/MCP/辩论壳全部 mock）。

覆盖：多样性校验（铁律⑤）→ 门禁 G1-G4 → 评分单调性 → 触发器 T1-T4 →
shadow 决策与 trace/outbox 落盘（胜 B / 负 D 经桥映射）→ 离线端到端。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ORCH_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ORCH_DIR.parents[1]
BRIDGE_DIR = REPO_ROOT / "52-lobehub协议集成" / "bridge"
for path in (str(ORCH_DIR), str(BRIDGE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import brainstorm_orchestrator as orch  # noqa: E402
from distill_bridge import R6_QUALITY_MAP, build_record_arguments, validate_entry  # noqa: E402
from plancard import from_dreamos_intent, validate_plancard  # noqa: E402
from proposers import SideAProposer, SideBProposer  # noqa: E402
from registry_tools import RegistryView, ToolInfo  # noqa: E402
from scoring import gate, score, triggers  # noqa: E402


def make_registry() -> RegistryView:
    tools = [
        ToolInfo("l0.cognition.mcp", "recall", "cognition", "read"),
        ToolInfo("l0.cognition.mcp", "unified_search", "search", "read"),
        ToolInfo("l0.eval.mcp", "eval_analyze", "eval", "read"),
        ToolInfo("l0.trade-exec.mcp", "place_order", "trade-exec", "write"),
    ]
    return RegistryView({t.full_name: t for t in tools}, source="test")


REGISTRY = make_registry()


def make_card(**overrides):
    card = {
        "id": "pc-test0001",
        "intent": "评估是否给离场模块增加波动率自适应阈值",
        "context_refs": ["unified_search:vol"],
        "plan_steps": [
            {"step": 1, "action": "检索历史阈值经验", "tool": "l0.cognition.mcp.recall"},
            {"step": 2, "action": "评估候选方案", "tool": "l0.eval.mcp.eval_analyze"},
        ],
        "evidence_refs": ["recall:VM-001", "unified_search:doc-7"],
        "risk_flags": [],
        "cost_estimate": {"tokens": 3000, "tool_calls": 2},
        "expected_outcome": "给出阈值候选与回测验证计划",
        "validation": {
            "evaluator_refs": ["45.heuristic@1.0.0"],
            "acceptance_checks": ["回测最大回撤不劣于基线"],
        },
    }
    card.update(overrides)
    return card


def proposal(side: str, card, model: str, evidence_path: str):
    return {
        "proposer_id": side,
        "model": model,
        "evidence_path": evidence_path,
        "card": card,
        "error": None,
    }


# ---------- ① 多样性校验（铁律⑤） ----------


def test_diversity_rejects_same_model():
    proposals = [
        proposal("side_a", make_card(id="pc-a"), "qwen-plus", "path-x"),
        proposal("side_b", make_card(id="pc-b"), "qwen-plus", "path-y"),
    ]
    violations = orch.check_diversity(proposals)
    assert len(violations) == 1
    assert violations[0]["same_model"] is True
    assert violations[0]["same_evidence_path"] is False


def test_diversity_rejects_same_evidence_path():
    proposals = [
        proposal("side_a", make_card(id="pc-a"), "m-a", "same-path"),
        proposal("side_b", make_card(id="pc-b"), "m-b", "same-path"),
    ]
    violations = orch.check_diversity(proposals)
    assert len(violations) == 1
    assert violations[0]["same_evidence_path"] is True


def test_diversity_passes_when_model_and_path_differ():
    proposals = [
        proposal("side_a", make_card(id="pc-a"), "m-a", "path-a"),
        proposal("side_b", make_card(id="pc-b"), "m-b", "path-b"),
    ]
    assert orch.check_diversity(proposals) == []


# ---------- ② 门禁 G1-G4 ----------


def test_gate_g1_schema_invalid():
    broken = make_card(validation={})
    result = gate(broken, REGISTRY)
    assert result["verdict"] == "BLOCK"
    assert any(r.startswith("G1:schema_invalid") for r in result["reasons"])


def test_gate_g2_unknown_tool():
    card = make_card(
        plan_steps=[{"step": 1, "action": "x", "tool": "l0.ghost.mcp.nope"}],
    )
    result = gate(card, REGISTRY)
    assert result["verdict"] == "BLOCK"
    assert "G2:unknown_tool:l0.ghost.mcp.nope" in result["reasons"]


def test_gate_g3_trade_exec_domain():
    card = make_card(
        plan_steps=[{"step": 1, "action": "下单", "tool": "l0.trade-exec.mcp.place_order"}],
    )
    result = gate(card, REGISTRY)
    assert result["verdict"] == "BLOCK"
    assert "G3:trade_exec_forbidden:l0.trade-exec.mcp.place_order" in result["reasons"]


@pytest.mark.parametrize("flag", ["实盘", "live trading", "下单", "Order"])
def test_gate_g4_live_trading_flag(flag):
    result = gate(make_card(risk_flags=[flag]), REGISTRY)
    assert result["verdict"] == "BLOCK"
    assert any(r.startswith("G4:live_trading_flag") for r in result["reasons"])


def test_gate_pass_clean_card():
    assert gate(make_card(), REGISTRY) == {"verdict": "PASS", "reasons": []}


# ---------- ③ 评分单调性 ----------


def test_score_monotonic_with_more_evidence():
    low = score(make_card(evidence_refs=["recall:only-one"]))
    high = score(make_card(evidence_refs=[f"recall:x{i}" for i in range(5)]))
    assert high["score"] > low["score"]


def test_score_penalizes_risk_flags_and_cost():
    low = score(make_card(evidence_refs=["recall:only-one"]))
    flagged = score(make_card(evidence_refs=["recall:only-one"], risk_flags=["依赖外部数据"]))
    costly = score(make_card(evidence_refs=["recall:only-one"], cost_estimate={"tokens": 50000}))
    assert flagged["score"] == pytest.approx(round(low["score"] - 0.10, 4))
    assert costly["score"] == pytest.approx(round(low["score"] - 0.05, 4))


def test_score_clamped_zero_to_one():
    minimal = {"id": "pc-x", "intent": "i", "plan_steps": [], "validation": {}}
    assert 0.0 <= score(minimal)["score"] <= 1.0


# ---------- ④ 触发器 T1-T4 ----------


def _scored(card_id: str, value: float, verdict: str = "PASS"):
    return {
        "card": make_card(id=card_id),
        "side": card_id,
        "score": value,
        "gate_verdict": verdict,
    }


def _gates(*pairs):
    return [{"card_id": cid, "verdict": verdict, "reasons": []} for cid, verdict in pairs]


def test_t1_fires_on_close_gap():
    result = triggers(
        [_scored("pc-a", 0.85), _scored("pc-b", 0.80)],
        _gates(("pc-a", "PASS"), ("pc-b", "PASS")),
        recall_hits=None,
    )
    assert "T1" in result["fired"]
    assert result["escalate"] is True


def test_t1_not_fired_on_clear_gap():
    result = triggers(
        [_scored("pc-a", 0.95), _scored("pc-b", 0.60)],
        _gates(("pc-a", "PASS"), ("pc-b", "PASS")),
        recall_hits=[],
    )
    assert "T1" not in result["fired"]
    assert result["escalate"] is False


def test_t2_fires_when_blocked_scores_higher():
    result = triggers(
        [_scored("pc-a", 0.40), _scored("pc-b", 0.90, "BLOCK")],
        _gates(("pc-a", "PASS"), ("pc-b", "BLOCK")),
        recall_hits=[],
    )
    assert "T2" in result["fired"]


def test_t2_not_fired_when_blocked_scores_lower():
    result = triggers(
        [_scored("pc-a", 0.90), _scored("pc-b", 0.30, "BLOCK")],
        _gates(("pc-a", "PASS"), ("pc-b", "BLOCK")),
        recall_hits=[],
    )
    assert "T2" not in result["fired"]


def test_t3_skipped_without_recall():
    result = triggers(
        [_scored("pc-a", 0.90), _scored("pc-b", 0.60)],
        _gates(("pc-a", "PASS"), ("pc-b", "PASS")),
        recall_hits=None,
    )
    assert result["detail"]["T3"]["status"] == "skipped"
    assert "T3" not in result["fired"]


def test_t3_fires_on_conflicting_d_memory():
    hits = [
        {
            "id": "VM-D-1",
            "quality_level": "D",
            "content": "波动率自适应阈值导致离场模块回测失效（已证伪）",
        }
    ]
    result = triggers(
        [_scored("pc-a", 0.90), _scored("pc-b", 0.60)],
        _gates(("pc-a", "PASS"), ("pc-b", "PASS")),
        recall_hits=hits,
    )
    assert "T3" in result["fired"]
    assert result["detail"]["T3"]["conflicts"]


def test_t4_user_requested():
    result = triggers(
        [_scored("pc-a", 0.90), _scored("pc-b", 0.60)],
        _gates(("pc-a", "PASS"), ("pc-b", "PASS")),
        recall_hits=[],
        user_requested=True,
    )
    assert "T4" in result["fired"]


# ---------- ⑤ shadow 决策 + trace/outbox ----------


def _fake_b_response():
    # B 侧仅 1 步且工具未注册 → 分数明显低于 A，用于覆盖「无争议 → dispatch」分支
    return {
        "intent_type": "analysis",
        "confidence": 0.82,
        "recommended_chain": "F",
        "base_chain": ["F1"],
        "extend_nodes": [],
        "rationale": "测试",
        "clarify_needed": False,
    }


def _build_proposers(b_payload=None, a_model="qwen-plus", b_model="dreamos-intent-engine"):
    def a_poster(url, payload, **_kwargs):
        return {
            "ok": True,
            "data": {
                "plancard": make_card(id="pc-a"),
                "model": a_model,
                "evidence_path": "unified_search+recall",
            },
        }

    def b_poster(url, payload, **_kwargs):
        return b_payload if b_payload is not None else _fake_b_response()

    return [
        SideAProposer(poster=a_poster, model_hint=a_model),
        SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed(), model_hint=b_model),
    ]


def test_shadow_run_writes_trace_and_outbox(tmp_path):
    trace = tmp_path / "brainstorm.jsonl"
    outbox = tmp_path / "outbox.jsonl"
    summary = orch.run(
        intent="评估是否给离场模块增加波动率自适应阈值",
        shadow=True,
        trace_path=trace,
        outbox_path=outbox,
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
    )
    assert summary["shadow"] is True
    assert summary["decision"]["executed"] is False
    assert summary["decision"]["kind"] == "dispatch"

    lines = trace.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["shadow"] is True
    assert record["dispatch"]["executed"] is False
    assert record["triggers"]["escalate"] is False
    assert len(record["gates"]) == 2

    entries = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    types = {e["type"] for e in entries}
    assert types == {"brainstorm_winner", "brainstorm_loser"}
    # 桥侧校验 + R6 映射：胜方 B / 败方 D
    for entry in entries:
        validated = validate_entry(entry)
        args = build_record_arguments(validated)
        expected = "B" if entry["type"] == "brainstorm_winner" else "D"
        assert args["quality_level"] == expected


def test_trace_appends_not_overwrites(tmp_path):
    trace = tmp_path / "brainstorm.jsonl"
    outbox = tmp_path / "outbox.jsonl"
    for _ in range(2):
        orch.run(
            intent="追加测试",
            trace_path=trace,
            outbox_path=outbox,
            disable_recall=True,
            proposers=_build_proposers(),
            registry=REGISTRY,
        )
    assert len(trace.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_diversity_violation_blocks_decision(tmp_path):
    summary = orch.run(
        intent="同模型应被拒",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=_build_proposers(a_model="same-model", b_model="same-model"),
        registry=REGISTRY,
    )
    assert summary["decision"]["kind"] == "diversity_violation"
    assert summary["decision"]["executed"] is False
    assert any(e["step"] == "diversity" for e in summary["errors"])


def test_debate_escalation_records_debate_id(tmp_path):
    captured = {}

    def fake_opener(topic, background, model_pair, plancards):
        captured["topic"] = topic
        captured["model_pair"] = model_pair
        captured["plancards"] = plancards
        return "debate-xyz"

    summary = orch.run(
        intent="用户要求辩论",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        user_requested_debate=True,
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
        debate_opener=fake_opener,
    )
    assert summary["decision"]["kind"] == "escalate_debate"
    assert summary["debate"]["debate_id"] == "debate-xyz"
    assert summary["decision"]["executed"] is False
    assert len(captured["model_pair"]) == 2
    assert captured["model_pair"][0] != captured["model_pair"][1]
    assert len(captured["plancards"]) == 2


def test_live_branch_not_implemented():
    with pytest.raises(NotImplementedError):
        orch.run(intent="x", shadow=False)


def test_side_b_unreachable_degrades_gracefully(tmp_path):
    def boom(url, payload, **_kwargs):
        raise OSError("connection refused")

    side_a = SideAProposer(poster=boom, model_hint="m-a")
    side_b = SideBProposer(poster=boom, allowed_tools=REGISTRY.allowed())
    summary = orch.run(
        intent="服务不可用",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=[side_a, side_b],
        registry=REGISTRY,
    )
    assert summary["decision"]["kind"] == "no_proposal"
    assert any(e["step"] == "propose" for e in summary["errors"])
    assert (tmp_path / "t.jsonl").exists()


# ---------- ⑥ 离线端到端（--side-a-plancard + SideB mock） ----------


def test_offline_e2e_with_side_a_plancard(tmp_path):
    side_a_file = tmp_path / "side_a.json"
    card = make_card(id="pc-offline-a", evidence_refs=[f"recall:e{i}" for i in range(5)])
    side_a_file.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    trace = tmp_path / "traces" / "brainstorm.jsonl"
    outbox = tmp_path / "outbox.jsonl"

    def b_poster(url, payload, **_kwargs):
        return _fake_b_response()

    summary = orch.run(
        intent="评估是否给离场模块增加波动率自适应阈值",
        side_a_plancard=side_a_file,
        trace_path=trace,
        outbox_path=outbox,
        disable_recall=True,
        proposers=[
            SideAProposer(poster=b_poster),
            SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed()),
        ],
        registry=REGISTRY,
    )
    assert summary["proposals"] == 2
    assert summary["scored"] == 2
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    sides = {p["proposer_id"] for p in record["proposals"]}
    assert sides == {"side_a", "side_b"}
    assert record["decision"]["executed"] is False
    # 胜方来自证据更充足的 A 卡（5 条 evidence_refs）
    winner = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()][0]
    assert winner["type"] == "brainstorm_winner"
    assert "pc-offline-a" in winner["content"]


# ---------- ⑦ PlanCard / side-B 构造 ----------


def test_from_dreamos_intent_maps_and_flags_unmapped():
    card = from_dreamos_intent(
        "测试意图",
        {
            "intent_type": "analysis",
            "confidence": 0.7,
            "base_chain": ["A1", "ZZ9"],
            "extend_nodes": ["F1"],
            "recommended_chain": "A",
        },
        allowed_tools=REGISTRY.allowed(),
    )
    assert validate_plancard(card)[0] is True
    tools = [s["tool"] for s in card["plan_steps"]]
    assert tools[0] == "l0.eval.mcp.eval_analyze"
    assert "l0.cognition.mcp.recall" in tools  # ZZ9 无映射 → 回退
    assert "chain_unmapped" in card["risk_flags"]


def test_r6_map_contains_brainstorm_types():
    assert R6_QUALITY_MAP["brainstorm_winner"] == "B"
    assert R6_QUALITY_MAP["brainstorm_loser"] == "D"


# ---------- ⑧ Phase 4.5：N-per-side 发散 / 铁律⑤加固 ----------


def test_side_a_propose_rotates_focus_and_returns_unique_cards():
    payloads = []

    def poster(url, payload, **_kwargs):
        payloads.append(payload)
        seed = payload["variant"]["seed"]
        return {
            "ok": True,
            "data": {
                "plancard": make_card(id=f"pc-a{seed}"),
                "model": "qwen-plus",
                "evidence_path": "unified_search+recall",
            },
        }

    proposer = SideAProposer(poster=poster, model_hint="qwen-plus")
    results = proposer.propose("意图", [], n=2)

    assert [p["variant"]["focus"] for p in payloads] == ["risk-first", "cost-first"]
    assert [p["variant"]["seed"] for p in payloads] == [0, 1]
    assert [r["card"]["id"] for r in results] == ["pc-a0", "pc-a1"]
    assert all(r["selection_basis"] for r in results)


def test_side_b_propose_variants_have_unique_ids_and_basis():
    def poster(url, payload, **_kwargs):
        return {
            "intent_type": "analysis",
            "confidence": 0.8,
            "base_chain": ["A1"],
            "extend_nodes": ["F1", "C1"],
        }

    proposer = SideBProposer(poster=poster, allowed_tools=REGISTRY.allowed())
    results = proposer.propose("意图", [], n=3)

    assert len(results) == 3
    assert len({r["card"]["id"] for r in results}) == 3
    assert all(r["selection_basis"] for r in results)
    assert len(results[0]["card"]["plan_steps"]) == 3
    assert len(results[1]["card"]["plan_steps"]) == 1
    reversed_actions = [s["action"] for s in results[2]["card"]["plan_steps"]]
    assert "C1" in reversed_actions[1] and "F1" in reversed_actions[2]


def test_run_n_per_side_pool_and_trace_fields(tmp_path):
    def a_poster(url, payload, **_kwargs):
        seed = payload["variant"]["seed"]
        evidence = [f"recall:a{i}" for i in range(5 if seed == 0 else 2)]
        return {
            "ok": True,
            "data": {
                "plancard": make_card(id=f"pc-a{seed}", evidence_refs=evidence),
                "model": "qwen-plus",
                "evidence_path": "unified_search+recall",
            },
        }

    def b_poster(url, payload, **_kwargs):
        return _fake_b_response()

    trace = tmp_path / "t.jsonl"
    outbox = tmp_path / "o.jsonl"
    summary = orch.run(
        intent="N 张发散",
        trace_path=trace,
        outbox_path=outbox,
        disable_recall=True,
        n_per_side=2,
        proposers=[
            SideAProposer(poster=a_poster, model_hint="qwen-plus"),
            SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed()),
        ],
        registry=REGISTRY,
        debate_opener=lambda topic, bg, models, cards: "debate-n",
        # Phase 4.6：该用例专测 N-per-side 发散，显式 --force 跳过意图路由（否则 workers 单边 n=1）
        force=True,
    )

    assert summary["n_per_side"] == 2
    assert summary["pool_size"] == 4
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["n_per_side"] == 2
    assert record["pool_size"] == 4
    assert summary["diversity_violations"] == []
    assert record["adjudication"]["mode"] == "both"
    assert isinstance(record["adjudication"]["agree"], bool)
    assert len(record["gates"]) == 4

    entries = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in entries if e["type"] == "brainstorm_winner") == 1
    assert sum(1 for e in entries if e["type"] == "brainstorm_loser") == 3


def test_diversity_rejects_unknown_model_and_skips_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDE_A_MODEL", "unknown")
    side_a_file = tmp_path / "side_a.json"
    side_a_file.write_text(json.dumps(make_card(id="pc-offline-a")), encoding="utf-8")
    outbox = tmp_path / "o.jsonl"
    trace = tmp_path / "t.jsonl"

    def b_poster(url, payload, **_kwargs):
        return _fake_b_response()

    summary = orch.run(
        intent="unknown 模型应被拒",
        side_a_plancard=side_a_file,
        trace_path=trace,
        outbox_path=outbox,
        disable_recall=True,
        proposers=[
            SideAProposer(poster=b_poster),
            SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed()),
        ],
        registry=REGISTRY,
    )

    assert summary["decision"]["kind"] == "diversity_violation"
    assert any(v["rule"] == "model_unknown" for v in summary["diversity_violations"])
    assert summary["outbox_written"] == 0
    assert not outbox.exists()
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["diversity_violations"]
    assert record["decision"]["executed"] is False


# ---------- ⑨ Phase 4.6：意图路由接编排器 ----------


def test_trade_intent_route_skipped_writes_trace_no_outbox(tmp_path):
    trace = tmp_path / "t.jsonl"
    outbox = tmp_path / "o.jsonl"
    summary = orch.run(
        intent="帮我买入 100 股茅台",
        trace_path=trace,
        outbox_path=outbox,
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
    )

    assert summary["skipped"] is True
    assert summary["route"] == "trade_deny"
    assert summary["winner"] is None
    assert summary["outbox_written"] == 0
    assert not outbox.exists()
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["route"] == "trade_deny"
    assert record["route_rules_version"] == "r9-v1"
    assert record["decision"]["kind"] == "route_skipped"
    assert record["decision"]["executed"] is False


def test_high_risk_intent_route_skipped(tmp_path):
    summary = orch.run(
        intent="要不要全仓押注这个方向",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
    )
    assert summary["skipped"] is True
    assert summary["route"] == "high_risk_human"
    assert summary["reason"]


def test_workers_route_single_pass_no_debate_escalation(tmp_path):
    calls = {"a": 0}

    def a_poster(url, payload, **_kwargs):
        calls["a"] += 1
        return {
            "ok": True,
            "data": {
                "plancard": make_card(id="pc-a"),
                "model": "qwen-plus",
                "evidence_path": "unified_search+recall",
            },
        }

    def b_poster(url, payload, **_kwargs):
        return _fake_b_response()

    trace = tmp_path / "t.jsonl"
    summary = orch.run(
        intent="帮我整理一下最近的工程改动",
        trace_path=trace,
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        n_per_side=3,
        proposers=[
            SideAProposer(poster=a_poster, model_hint="qwen-plus"),
            SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed()),
        ],
        registry=REGISTRY,
        debate_opener=lambda *args: "should-not-open",
    )

    assert summary["route"] == "workers"
    assert summary["mode"] == "workers"
    assert summary["n_per_side"] == 1
    assert calls["a"] == 1  # side-A 只走一次（单边语义）
    assert summary["decision"]["kind"] == "dispatch"
    assert summary["debate"]["debate_id"] is None
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["mode"] == "workers"
    assert record["triggers"]["escalate"] is False


def test_debate_route_keeps_dual_chain(tmp_path):
    summary = orch.run(
        intent="离场模块要不要加波动率自适应阈值，哪种更好，看回测和风险",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
    )
    assert summary["route"] == "debate"
    assert summary["mode"] == "debate"
    assert summary["skipped"] is False


def test_force_bypasses_router_skip(tmp_path):
    summary = orch.run(
        intent="帮我买入 100 股茅台",
        trace_path=tmp_path / "t.jsonl",
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        proposers=_build_proposers(),
        registry=REGISTRY,
        force=True,
    )
    assert summary["skipped"] is False
    assert summary["force"] is True
    assert summary["mode"] == "debate"
    assert summary["decision"]["kind"] == "dispatch"
