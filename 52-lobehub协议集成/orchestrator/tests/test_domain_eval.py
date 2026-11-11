"""Phase 5 — 45 域评测器适配层测试。

覆盖：45 不可用 fail-open → 缺产物/评测器缺失契约 → 结构分非退化（防 T1 恒 0）
→ BLOCK 归零并排除候选池 → provenance/trace/summary 字段。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ORCH_DIR = Path(__file__).resolve().parents[1]
for path in (str(ORCH_DIR),):
    if path not in sys.path:
        sys.path.insert(0, path)

import brainstorm_orchestrator as orch  # noqa: E402
import domain_eval  # noqa: E402
from proposers import SideAProposer, SideBProposer  # noqa: E402
from registry_tools import RegistryView, ToolInfo  # noqa: E402
from scoring import score  # noqa: E402


def make_registry() -> RegistryView:
    tools = [
        ToolInfo("l0.cognition.mcp", "recall", "cognition", "read"),
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


def _fake_discovery(**overrides):
    info = {
        "available": True,
        "names": ["engineering-scan", "finance-backtest-stats", "ai-stress"],
        "versions": {
            "engineering-scan": ["1.0.0"],
            "finance-backtest-stats": ["1.0.0"],
            "ai-stress": ["1.0.0"],
        },
        "root": str(domain_eval.DEFAULT_EVALUATORS_ROOT),
    }
    info.update(overrides)
    return info


# ---------- ① 45 不可用 → fail-open INCONCLUSIVE ----------


def test_discover_fail_open_when_import_fails(monkeypatch):
    def boom(name, *args, **kwargs):
        raise ImportError("45 unavailable for test")

    monkeypatch.setattr(domain_eval.importlib, "import_module", boom)
    info = domain_eval.discover()
    assert info["available"] is False
    assert "ImportError" in info["error"]
    assert info["names"] == []


def test_score_falls_back_to_structural_when_45_unavailable(monkeypatch):
    def boom(name, *args, **kwargs):
        raise ImportError("45 unavailable for test")

    monkeypatch.setattr(domain_eval.importlib, "import_module", boom)
    result = score(make_card(), allowed_tools=REGISTRY)
    provenance = result["evaluator_provenance"]
    assert result["verdict"] == "INCONCLUSIVE"
    assert provenance["source"] == "structural"
    assert provenance["reason"] == "45_unavailable"
    assert 0.0 <= result["score"] <= 1.0


# ---------- ② 契约：缺产物 / 评测器不存在 ----------


def test_missing_artifacts_is_inconclusive():
    result = domain_eval.evaluate_plan(make_card(), run_id="run-no-artifacts")
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["reason"] == "missing_artifacts", domain_eval.discover()
    assert result["required_artifacts"]
    assert result["required_artifacts"][0].endswith("run-no-artifacts.json")


def test_unknown_evaluator_fails_open():
    discovery = _fake_discovery(names=["e3"], versions={"e3": ["1.0.0"]})
    result = domain_eval.evaluate_plan(
        make_card(), run_id="r1", discovery=discovery, evaluators_root="/tmp/45-root"
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["reason"] == "evaluator_not_found"
    assert result["evaluator"].endswith("@unresolved")


def test_artifact_present_still_not_fabricated(tmp_path):
    run_id = "run-with-artifact"
    artifact_dir = tmp_path / "artifacts" / "inputs"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / f"{run_id}.json").write_text("{}", encoding="utf-8")
    result = domain_eval.evaluate_plan(
        make_card(intent="工程扫描"),
        run_id=run_id,
        discovery=_fake_discovery(),
        evaluators_root=str(tmp_path),
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["reason"] == "artifact_not_evaluated"


# ---------- ③ 域判定 ----------


def test_detect_domain_by_tool_prefix():
    card = make_card(
        plan_steps=[{"step": 1, "action": "回测统计", "tool": "l0.eval.mcp.backtest_stats"}]
    )
    assert domain_eval.detect_domain(card) == "finance"


def test_detect_domain_by_intent_keyword_and_default():
    assert domain_eval.detect_domain(make_card(intent="模型裁判校准怎么做")) == "ai"
    assert domain_eval.detect_domain(make_card(intent="随便聊聊")) == "engineering"


# ---------- ④ 结构分：非退化 + 单调 + 下限 ----------


def test_illegal_tool_lowers_legality_and_score():
    good = make_card()
    bad = make_card(
        plan_steps=[
            {"step": 1, "action": "x", "tool": "l0.ghost.mcp.nope"},
            {"step": 2, "action": "y", "tool": "l0.eval.mcp.eval_analyze"},
        ]
    )
    good_score, good_detail = domain_eval.structural_score(good, REGISTRY)
    bad_score, bad_detail = domain_eval.structural_score(bad, REGISTRY)
    good_legality = next(d for d in good_detail if d["name"] == "tool_legality")
    bad_legality = next(d for d in bad_detail if d["name"] == "tool_legality")
    assert good_legality["raw"] == 1.0
    assert bad_legality["raw"] == pytest.approx(0.5)
    assert good_score > bad_score


def test_structurally_different_cards_have_positive_gap():
    rich = make_card(evidence_refs=[f"recall:e{i}" for i in range(5)])
    poor = make_card(
        plan_steps=[{"step": 1, "action": "只做检索", "tool": "l0.cognition.mcp.recall"}],
        evidence_refs=[],
        validation={},
        risk_flags=["依赖外部数据", "成本偏高"],
        cost_estimate=None,
    )
    rich_score, _ = domain_eval.structural_score(rich, REGISTRY)
    poor_score, _ = domain_eval.structural_score(poor, REGISTRY)
    assert rich_score != poor_score
    assert round(rich_score - poor_score, 3) > 0


def test_risk_flags_monotonic_with_floor():
    none_score, _ = domain_eval.structural_score(make_card(risk_flags=[]), REGISTRY)
    two_score, _ = domain_eval.structural_score(make_card(risk_flags=["a", "b"]), REGISTRY)
    many_score, many_detail = domain_eval.structural_score(
        make_card(risk_flags=[f"r{i}" for i in range(10)]), REGISTRY
    )
    risk_raw = next(d for d in many_detail if d["name"] == "risk_flags")["raw"]
    assert none_score > two_score > many_score
    assert risk_raw == pytest.approx(0.4)


def test_structural_score_is_deterministic_and_three_decimals():
    card = make_card(risk_flags=["依赖外部数据"])
    first, detail = domain_eval.structural_score(card, REGISTRY)
    second, _ = domain_eval.structural_score(make_card(risk_flags=["依赖外部数据"]), REGISTRY)
    assert first == second
    assert round(first, 3) == first
    assert [d["name"] for d in detail] == list(domain_eval.STRUCTURAL_WEIGHTS)


# ---------- ⑤ BLOCK / PASS 分支 ----------


def test_block_zeroes_score_and_excludes_from_pool(monkeypatch):
    block_result = {
        "verdict": "BLOCK",
        "reason": "hard_item_failed",
        "evaluator": "engineering-scan@1.0.0",
        "domain": "engineering",
        "required_artifacts": [],
    }
    monkeypatch.setattr(domain_eval, "evaluate_plan", lambda *a, **k: dict(block_result))
    result = score(make_card(), allowed_tools=REGISTRY)
    assert result["score"] == 0.0
    assert result["verdict"] == "BLOCK"

    proposals = [
        {
            "proposer_id": "side_a",
            "model": "m-a",
            "evidence_path": "p-a",
            "card": make_card(id="pc-block"),
            "error": None,
        }
    ]
    gates, scored = orch.evaluate_proposals(proposals, REGISTRY, run_id="r-block")
    assert gates[0]["verdict"] == "BLOCK"
    assert any(r.startswith("D1:domain_block") for r in gates[0]["reasons"])
    assert scored[0]["gate_verdict"] == "BLOCK"
    viable = [item for item in scored if item.get("gate_verdict") == "PASS"]
    assert viable == []


def test_pass_adds_bonus_over_structural_base(monkeypatch):
    pass_result = {
        "verdict": "PASS",
        "reason": "artifact_ok",
        "evaluator": "engineering-scan@1.0.0",
        "domain": "engineering",
        "required_artifacts": [],
    }
    monkeypatch.setattr(domain_eval, "evaluate_plan", lambda *a, **k: dict(pass_result))
    card = make_card(risk_flags=["依赖外部数据"])
    base, _ = domain_eval.structural_score(card, REGISTRY)
    result = score(card, allowed_tools=REGISTRY)
    assert result["score"] == pytest.approx(round(min(1.0, base + 0.05), 3))


# ---------- ⑥ provenance / trace / summary ----------


def test_provenance_contains_full_fields():
    result = score(make_card(), run_id="prov-run", allowed_tools=REGISTRY)
    provenance = result["evaluator_provenance"]
    assert set(provenance) == {
        "source",
        "evaluator",
        "verdict",
        "reason",
        "structural_detail",
    }
    assert provenance["source"] in {"structural", "45"}
    assert len(provenance["structural_detail"]) == 6
    for item in provenance["structural_detail"]:
        assert set(item) == {"name", "raw", "weight", "contribution"}


def test_run_trace_and_summary_include_domain_eval(tmp_path):
    def a_poster(url, payload, **_kwargs):
        return {
            "ok": True,
            "data": {
                "plancard": make_card(id="pc-a"),
                "model": "qwen-plus",
                "evidence_path": "unified_search+recall",
            },
        }

    def b_poster(url, payload, **_kwargs):
        return {
            "intent_type": "analysis",
            "confidence": 0.8,
            "base_chain": ["A1"],
            "extend_nodes": [],
        }

    trace = tmp_path / "t.jsonl"
    summary = orch.run(
        intent="工程测试这块怎么改",
        trace_path=trace,
        outbox_path=tmp_path / "o.jsonl",
        disable_recall=True,
        force=True,
        proposers=[
            SideAProposer(poster=a_poster, model_hint="qwen-plus"),
            SideBProposer(poster=b_poster, allowed_tools=REGISTRY.allowed()),
        ],
        registry=REGISTRY,
    )
    record = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["domain_eval"]["available"] is True
    assert record["domain_eval"]["names"]
    assert set(record["domain_eval"]["verdicts"]) == {"pc-a", record["proposals"][1]["card_id"]}
    for entry in record["scores"]:
        assert "evaluator_provenance" in entry
        assert entry["evaluator_provenance"]["verdict"] == "INCONCLUSIVE"
    assert summary["evaluators"]["available"] is True
    assert summary["evaluators"]["names"] == len(record["domain_eval"]["names"])
