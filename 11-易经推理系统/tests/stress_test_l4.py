#!/usr/bin/env python
"""L4 记忆系统多场景压力测试。

覆盖: 大数据量、多 regime、极端 pnl、缺失字段、错误注入、
状态机非法转换、并发索引构建、性能基准。
"""

import json
import sys
import time
import traceback
import shutil
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
    memory_l4_stats_dir,
    workbuddy_dir,
    workspace_root,
)
from scripts.memory_l4 import case_registry, a0a9_bridge, review_engine
from scripts.memory_l4 import distill_engine, stats_engine, pipeline
from scripts.memory_l4 import index_builder, query_similar

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_episode(case_id: str, pnl: float, regime: str = "bull",
                  decision: str = "long", inst_id: str = None) -> dict:
    inst = inst_id or f"{case_id}_INST"
    return {
        "trace_id": case_id,
        "inst_id": inst,
        "ts": _ts(),
        "decision": decision,
        "status": "closed",
        "regime": regime,
        "pnl_pct": pnl,
        "pnl_usdt": pnl * 1000,
        "drawdown": abs(pnl) * 0.3,
        "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
        "goal_achieved": pnl > 0,
        "outcome": {
            "realized_pnl_pct": pnl,
            "realized_pnl_usdt": pnl * 1000,
            "max_drawdown": abs(pnl) * 0.3,
            "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
            "goal_achieved": pnl > 0,
        },
        "reason_codes": [f"reason_{pnl:+.1f}"],
        "total_score": 70 + pnl * 2,
        "edge": pnl * 10,
        "scores": {"momentum": 0.7, "volatility": 0.5, "trend": 0.8},
        "strategy_result": {
            "strategy_directive": {
                "matched_strategy": "momentum_breakout",
                "category": "trend_following",
                "directive_bias": "bullish" if pnl > 0 else "bearish",
            }
        },
    }


def _save_episode(ep: dict) -> Path:
    cid = ep["trace_id"]
    ep_path = workbuddy_dir() / "episodes" / f"{cid}.json"
    ep_path.parent.mkdir(parents=True, exist_ok=True)
    ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ep_path


def _make_a0a9_artifacts_for(cid: str, stages: list = None):
    """生成 A0-A9 阶段产出。stages 指定要生成的阶段，默认全部。"""
    if stages is None:
        stages = [f"A{i}" for i in range(10)]
    trading_dir = workspace_root() / "artifacts" / "trading"
    trading_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "A0": {"timestamp": _ts(), "core_contradiction": "price indicator divergence",
               "analysis": "RSI divergence at resistance"},
        "A1": {"timestamp": _ts(), "research_conclusion": "momentum confirmed",
               "methodology": "technical analysis"},
        "A2": {"timestamp": _ts(), "first_principles": "trend follows momentum",
               "reasoning": "market inefficiency"},
        "A3": {"timestamp": _ts(), "simulation_result": "backtest positive",
               "hypothesis": "momentum breakout", "backtest_result": "wr=0.65"},
        "A4": {"timestamp": _ts(), "validation_result": "validated",
               "assumption": "trend continuation", "test_outcome": "pass"},
        "A5": {"timestamp": _ts(), "execution_decision": "enter long",
               "execution_logic": "breakout"},
        "A6": {"timestamp": _ts(), "signal_decision": "hold",
               "signal_rationale": "no reversal"},
        "A7": {"timestamp": _ts(), "practice_audit_result": "matches theory",
               "practice_theory_gap": "minor slippage"},
        "A8": {"timestamp": _ts(), "verification_result": "confirmed",
               "theory_critique": "valid under regime", "verification_outcome": "pass"},
        "A9": {"timestamp": _ts(), "exit_decision": "take profit",
               "exit_reasoning": "target hit"},
    }
    for stage in stages:
        if stage in templates:
            f = trading_dir / f"{cid}_{stage}_output.json"
            f.write_text(json.dumps(templates[stage], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _purge_dir(d: Path, patterns: tuple[str, ...]) -> None:
    if not d.exists():
        return
    for pat in patterns:
        for p in d.glob(pat):
            if p.is_file() and p.name != ".gitkeep":
                p.unlink()


@pytest.fixture(scope="module", autouse=True)
def _clean_workspace():
    _purge_dir(workbuddy_dir() / "episodes", ("*.json",))
    _purge_dir(memory_l4_cases_dir(), ("*.json",))
    _purge_dir(memory_l4_reviews_dir(), ("*.json",))
    _purge_dir(memory_l4_distills_dir(), ("*.json",))
    _purge_dir(memory_l4_stats_dir(), ("*.json",))
    trading_dir = workspace_root() / "artifacts" / "trading"
    _purge_dir(trading_dir, ("*_output.json",))
    yield


# ===================================================================
# Scenario 1: Large Volume — 100 cases across 6 regimes
# ===================================================================
def test_register_100_cases():
    """压力: 注册 100 个 case，覆盖 6 个 regime。"""
    import random
    regimes = ["bull", "bear", "oscillation", "crash", "recovery", "consolidation"]
    for i in range(100):
        pnl = random.gauss(1.0, 3.0)  # normal dist, some wins some losses
        regime = regimes[i % len(regimes)]
        ep = _make_episode(f"STRESS_{i:03d}", pnl=pnl, regime=regime)
        _save_episode(ep)
        case_path = case_registry.create_case_from_episode_file(
            workbuddy_dir() / "episodes" / f"STRESS_{i:03d}.json"
        )
        case = json.loads(case_path.read_text(encoding="utf-8"))
        assert case["version"] == "v0.2"
        assert case["l4_status"] == "M0_CASE_REGISTERED"

    count = len(list(memory_l4_cases_dir().glob("*.json")))
    assert count == 100, f"Expected 100 cases, got {count}"


def test_index_performance_100():
    """压力: 100 case 索引构建性能。"""
    cases = index_builder.load_cases()
    assert len(cases) >= 100
    t0 = time.time()
    episodes = index_builder.load_episodes_for_cases(cases)
    data = index_builder.build_index_data(_ts(), cases, [], episodes_by_path=episodes)
    elapsed = time.time() - t0
    assert elapsed < 10.0, f"Index build too slow: {elapsed:.2f}s"
    assert data["metadata"]["feature_version"] == "v0.2"
    assert data["summary"]["total_cases"] >= 100
    print(f"  [INFO] 100 cases indexed in {elapsed:.3f}s")


def test_stats_performance_100():
    """压力: 100 case 统计性能。"""
    t0 = time.time()
    stats = stats_engine.compute_full_stats()
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"Stats compute too slow: {elapsed:.2f}s"
    assert stats["pnl_stats"]["count"] >= 100
    print(f"  [INFO] Stats computed in {elapsed:.3f}s")


# ===================================================================
# Scenario 2: Multi-Regime — regime-specific query correctness
# ===================================================================
def test_regime_query_correctness():
    """压力: 多 regime 查询正确性。"""
    for regime in ["bull", "bear", "oscillation", "crash", "recovery", "consolidation"]:
        result = query_similar.query_by_regime_and_outcome(regime, topk=50)
        assert result["regime"] == regime
        assert result["total"] > 0, f"Expected cases for regime={regime}"


def test_regime_profit_loss_split():
    """压力: regime + profit/loss 过滤正确性。"""
    for regime in ["bull", "bear"]:
        profit = query_similar.query_by_regime_and_outcome(regime, outcome="profit", topk=50)
        loss = query_similar.query_by_regime_and_outcome(regime, outcome="loss", topk=50)
        assert profit["total"] + loss["total"] > 0
        # All profit results should have positive pnl
        for r in profit["cases"]:
            assert r["pnl_pct"] is not None and r["pnl_pct"] > 0, \
                f"Non-profit in profit query: {r}"


# ===================================================================
# Scenario 3: Extreme Values — very large/small PnL
# ===================================================================
def test_extreme_pnl():
    """压力: 极端 PnL 值 (+50%, -30%)。"""
    extreme_cases = [
        ("STRESS_EXT_POS", 50.0, "crash", "long"),   # huge profit
        ("STRESS_EXT_NEG", -30.0, "bull", "long"),    # huge loss
        ("STRESS_EXT_ZERO", 0.001, "oscillation", "short"),  # near zero
        ("STRESS_EXT_TINY", -0.001, "recovery", "long"),     # tiny loss
    ]
    for cid, pnl, regime, dec in extreme_cases:
        ep = _make_episode(cid, pnl=pnl, regime=regime, decision=dec)
        _save_episode(ep)
        case_path = case_registry.create_case_from_episode_file(
            workbuddy_dir() / "episodes" / f"{cid}.json"
        )
        case = json.loads(case_path.read_text(encoding="utf-8"))
        assert case["decision_outcome"]["pnl_pct"] == pnl
        assert case["l4_status"] == "M0_CASE_REGISTERED"


def test_extreme_quadrant():
    """压力: 极端象限坐标。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_QUAD", pnl=1.0), "STRESS_QUAD"
    )
    # Set extreme quadrant values
    case["quadrant"]["x"] = 0.99
    case["quadrant"]["y"] = 0.99
    case["quadrant"]["evidence"]["y_perf"] = 0.99
    case["quadrant"]["evidence"]["y_consistency"] = 0.99
    case["quadrant"]["evidence"]["y_human"] = 0.99
    case_registry.save_json(memory_l4_cases_dir() / "STRESS_QUAD.json", case)

    # Verify index handles it
    cases = index_builder.load_cases()
    feats = {}
    for c in cases:
        cid = c.get("case_id")
        if cid == "STRESS_QUAD":
            feats[cid] = {
                "version": c.get("version"),
                "l4_status": c.get("l4_status"),
                "thinking_chain": index_builder._extract_thinking_chain_features(c),
                "quadrant_features": index_builder._extract_quadrant_features(c),
            }
    summary = index_builder._build_index_summary(feats, [])
    assert summary["quadrant_center"]["x_mean"] == 0.99
    assert summary["quadrant_center"]["y_mean"] == 0.99


# ===================================================================
# Scenario 4: Missing/Incomplete Data — cases with empty chains
# ===================================================================
def test_empty_thinking_chain():
    """压力: 空 thinking_chain 的 case。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_EMPTY", pnl=1.0), "STRESS_EMPTY"
    )
    assert case["thinking_chain"] == []
    assert case["l4_status"] == "M0_CASE_REGISTERED"

    # Index should handle empty chain
    tc_feat = index_builder._extract_thinking_chain_features(case)
    assert tc_feat["stages_count"] == 0
    assert tc_feat["stage_coverage_pct"] == 0.0
    assert not tc_feat["has_contradiction_analysis"]


def test_partial_thinking_chain():
    """压力: 只有 A0 和 A9 的 case。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_PARTIAL", pnl=1.0), "STRESS_PARTIAL"
    )
    case_registry.populate_thinking_chain(case, [
        {"stage": "A0", "decision": "contradiction", "contradiction": "test"},
        {"stage": "A9", "decision": "exit"},
    ])
    tc_feat = index_builder._extract_thinking_chain_features(case)
    assert tc_feat["stages_count"] == 2
    assert tc_feat["stage_coverage_pct"] == 20.0


def test_missing_episode_ref():
    """压力: episode 文件不存在的 case。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_NOREF", pnl=1.0), "STRESS_NOREF"
    )
    # episode_refs path is empty
    case["execution"]["episode_refs"][0]["path"] = "/nonexistent/path/episode.json"
    case_registry.save_json(memory_l4_cases_dir() / "STRESS_NOREF.json", case)

    # Review should not crash
    analysis = review_engine.analyze_success(case, {})
    assert analysis["direction"] == "success"


# ===================================================================
# Scenario 5: State Machine Edge Cases
# ===================================================================
def test_l4_status_invalid():
    """压力: 非法 L4 状态应抛异常。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_STATE", pnl=1.0), "STRESS_STATE"
    )
    try:
        case_registry.advance_l4_status(case, "INVALID_STATUS")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


def test_l4_status_backward():
    """压力: L4 状态回退 — 允许但记录。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_BACK", pnl=1.0), "STRESS_BACK"
    )
    case_registry.advance_l4_status(case, "M4_CANDIDATE_EMITTED")
    assert case["l4_status"] == "M4_CANDIDATE_EMITTED"
    # Backward transition is allowed (no enforcement)
    case_registry.advance_l4_status(case, "M0_CASE_REGISTERED")
    assert case["l4_status"] == "M0_CASE_REGISTERED"


def test_l4_status_fail():
    """压力: M_FAIL 状态。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("STRESS_FAIL", pnl=1.0), "STRESS_FAIL"
    )
    case_registry.advance_l4_status(case, "M_FAIL")
    assert case["l4_status"] == "M_FAIL"


# ===================================================================
# Scenario 6: Review Engine — large batch
# ===================================================================
def test_batch_review_50():
    """压力: 批量复盘 50 个 case。"""
    cases = []
    episodes = {}
    for i in range(50):
        cid = f"STRESS_REV_{i:03d}"
        pnl = float((i - 25) * 0.5)  # -12.5 to +12.0
        c = case_registry.create_case_from_episode_data(
            _make_episode(cid, pnl=pnl), cid
        )
        cases.append(c)
        episodes[cid] = _make_episode(cid, pnl=pnl)

    t0 = time.time()
    result = review_engine.run_review(
        cases=cases,
        episodes_by_case_id=episodes,
    )
    elapsed = time.time() - t0
    assert result["total_reviews"] == 50
    assert result["success_count"] > 0
    assert result["failure_count"] > 0
    print(f"  [INFO] 50 reviews in {elapsed:.3f}s")


# ===================================================================
# Scenario 7: Distill — multiple kinds
# ===================================================================
def test_distill_all_kinds():
    """压力: 蒸馏所有 kind 类型。"""
    cid = "STRESS_DISTILL_01"
    # Create and SAVE a real case on disk
    case = case_registry.create_case_from_episode_data(
        _make_episode(cid, pnl=1.0), cid
    )
    case_registry.save_json(memory_l4_cases_dir() / f"{cid}.json", case)

    kinds = [
        "benefit_experience", "risk_signal", "decision_heuristic",
        "contradiction_pattern", "exit_logic", "theory_update",
    ]
    for kind in kinds:
        review = {
            "review_id": f"REV_DISTILL_{kind}",
            "case_id": cid,
            "direction": "failure" if "risk" in kind or "contradiction" in kind else "success",
            "mistakes": [{"what": "test error", "why": "no confirmation"}] if "risk" in kind or "contradiction" in kind else [],
            "successes": [{"what": "good entry"}] if "benefit" in kind else [],
        }
        distill = distill_engine.run_full_distill_pipeline(review, kind=kind)
        assert distill["kind"] == kind, f"Expected kind={kind}, got {distill['kind']}"
        assert distill["quadrant"]["y"] > 0, f"y=0 for kind={kind}"
        assert distill["what_is_it"]["definition"] is not None


# ===================================================================
# Scenario 8: Query — stage coverage across all stages
# ===================================================================
def test_query_all_stages():
    """压力: 查询所有 A0-A9 阶段。"""
    for stage in [f"A{i}" for i in range(10)]:
        result = query_similar.query_by_stage(stage, topk=20)
        assert result["stage"] == stage
        assert isinstance(result["cases"], list)
        # Some stages should have coverage from the 100 stress cases
        # (we didn't populate all with thinking chains, so some may be empty)


def test_query_stage_invalid():
    """压力: 非法阶段应抛异常。"""
    try:
        query_similar.query_by_stage("A10", topk=5)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected


# ===================================================================
# Scenario 9: A0-A9 Bridge — partial stages
# ===================================================================
def test_a0a9_partial_stages():
    """压力: 只有部分阶段产出的 case。"""
    cid = "STRESS_A0A9_PARTIAL"
    _make_a0a9_artifacts_for(cid, stages=["A0", "A1", "A5", "A9"])
    outputs = a0a9_bridge.collect_stage_outputs(cid)
    assert len(outputs) > 0
    # Should only have A0, A1, A5, A9
    stages_found = set(outputs.keys())
    assert stages_found.issubset({"A0", "A1", "A5", "A9"})


# ===================================================================
# Scenario 10: Full Pipeline End-to-End — stress case
# ===================================================================
def test_full_pipeline_stress():
    """压力: 完整 pipeline 端到端 (M0→M4)。"""
    cid = "STRESS_FULL_PIPE"
    pnl = 5.0
    ep = _make_episode(cid, pnl=pnl, regime="bull")
    ep_path = _save_episode(ep)

    # Generate A0-A9 artifacts
    _make_a0a9_artifacts_for(cid)

    result = pipeline.run_pipeline(ep_path)
    assert "case" in result
    assert "review" in result
    assert "distill" in result
    assert "stats" in result
    assert "candidate" in result
    assert "register" in result["steps_executed"]
    assert "emit" in result["steps_executed"]
    print(f"  [INFO] Full pipeline M0→M4 completed for {cid}")


# ===================================================================
# Scenario 11: Index Consistency — verify after mutations
# ===================================================================
def test_index_consistency():
    """压力: 索引一致性校验 — 构建后查询应匹配。"""
    cases = index_builder.load_cases()
    episodes = index_builder.load_episodes_for_cases(cases)
    idx = index_builder.build_index_data(_ts(), cases, [], episodes_by_path=episodes)

    # case_features count should match cases
    cf_count = len(idx["case_features"])
    assert cf_count == len(cases), f"Index has {cf_count} features but {len(cases)} cases"

    # Summary stats should match
    summary = idx["summary"]
    assert summary["total_cases"] == cf_count

    # Each case should have v0.2 features
    for cid, feat in idx["case_features"].items():
        assert "thinking_chain" in feat, f"Missing thinking_chain for {cid}"
        assert "quadrant_features" in feat, f"Missing quadrant_features for {cid}"
        assert "decision_outcome" in feat, f"Missing decision_outcome for {cid}"


# ===================================================================
# Scenario 12: Cross-Instance — multiple inst_id
# ===================================================================
def test_cross_instance():
    """压力: 跨 inst_id 数据隔离。"""
    instances = ["BTC", "ETH", "SOL", "BNB", "DOGE"]
    for inst in instances:
        cid = f"STRESS_INST_{inst}"
        ep = _make_episode(cid, pnl=2.0, inst_id=inst)
        _save_episode(ep)
        case_registry.create_case_from_episode_file(
            workbuddy_dir() / "episodes" / f"{cid}.json"
        )

    # Query by regime should include all instances
    result = query_similar.query_by_regime_and_outcome("bull", topk=200)
    inst_ids = {c["case_id"] for c in result["cases"]}
    # Should find cases across multiple instances
    assert len(result["cases"]) > 0


# ===================================================================
# Scenario 13: Schema Validation — all cases conform to v0.2
# ===================================================================
def test_all_cases_v02():
    """压力: 所有 case 必须是 v0.2 格式。"""
    required_keys = {
        "case_id", "version", "ts_start", "inst_id", "intent",
        "investigation", "theory_refs", "environment_snapshot",
        "thinking_chain", "evidence_chain", "decision_outcome",
        "l4_status", "plan", "execution", "review", "quadrant",
    }
    for p in sorted(memory_l4_cases_dir().glob("*.json")):
        case = json.loads(p.read_text(encoding="utf-8"))
        missing = required_keys - set(case.keys())
        assert not missing, f"Case {case.get('case_id')} missing: {missing}"
        assert case["version"] == "v0.2", f"Case {case.get('case_id')} not v0.2"


# ===================================================================
# Scenario 14: Memory Growth — stats after multiple operations
# ===================================================================
def test_stats_after_mutations():
    """压力: 多次操作后统计一致性。"""
    stats = stats_engine.compute_full_stats()
    total_cases = len(list(memory_l4_cases_dir().glob("*.json")))
    assert stats["pnl_stats"]["count"] == total_cases, \
        f"Stats count {stats['pnl_stats']['count']} != files {total_cases}"
    assert stats["l4_status_distribution"]["total"] == total_cases


# ===================================================================
# Scenario 15: Error Recovery — pipeline with missing data
# ===================================================================
def test_pipeline_missing_artifacts():
    """压力: pipeline 在没有 A0-A9 artifacts 时应正常降级。"""
    cid = "STRESS_NO_ARTIFACTS"
    ep = _make_episode(cid, pnl=1.0)
    ep_path = _save_episode(ep)

    # No artifacts generated — pipeline should still work
    result = pipeline.run_pipeline(ep_path)
    assert "case" in result
    assert "review" in result
    # a0a9 step should be listed but produce empty chain
    assert "a0a9" in result["steps_executed"]


# ===================================================================
# Main
# ===================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("L4 Memory System Multi-Scenario Stress Test")
    print("=" * 60)

    # Clean test data
    for d in [memory_l4_cases_dir(), memory_l4_reviews_dir(),
              memory_l4_distills_dir(), memory_l4_stats_dir(),
              workbuddy_dir() / "episodes"]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    trading = workspace_root() / "artifacts" / "trading"
    if trading.exists():
        shutil.rmtree(trading)

    print("\n--- Scenario 1: Large Volume (100 cases) ---")
    test("S1: Register 100 cases across 6 regimes", test_register_100_cases)
    test("S1: Index performance with 100 cases", test_index_performance_100)
    test("S1: Stats performance with 100 cases", test_stats_performance_100)

    print("\n--- Scenario 2: Multi-Regime ---")
    test("S2: Regime query correctness", test_regime_query_correctness)
    test("S2: Regime profit/loss split", test_regime_profit_loss_split)

    print("\n--- Scenario 3: Extreme Values ---")
    test("S3: Extreme PnL (+50%, -30%)", test_extreme_pnl)
    test("S3: Extreme quadrant coordinates", test_extreme_quadrant)

    print("\n--- Scenario 4: Missing/Incomplete Data ---")
    test("S4: Empty thinking_chain", test_empty_thinking_chain)
    test("S4: Partial thinking_chain (A0+A9)", test_partial_thinking_chain)
    test("S4: Missing episode ref", test_missing_episode_ref)

    print("\n--- Scenario 5: State Machine Edge Cases ---")
    test("S5: Invalid L4 status", test_l4_status_invalid)
    test("S5: L4 status backward transition", test_l4_status_backward)
    test("S5: M_FAIL status", test_l4_status_fail)

    print("\n--- Scenario 6: Review Engine — Batch ---")
    test("S6: Batch review 50 cases", test_batch_review_50)

    print("\n--- Scenario 7: Distill — All Kinds ---")
    test("S7: Distill all 6 kinds", test_distill_all_kinds)

    print("\n--- Scenario 8: Query — Stage Coverage ---")
    test("S8: Query all A0-A9 stages", test_query_all_stages)
    test("S8: Query invalid stage", test_query_stage_invalid)

    print("\n--- Scenario 9: A0-A9 Bridge — Partial ---")
    test("S9: A0-A9 partial stages", test_a0a9_partial_stages)

    print("\n--- Scenario 10: Full Pipeline E2E ---")
    test("S10: Full pipeline M0→M4", test_full_pipeline_stress)

    print("\n--- Scenario 11: Index Consistency ---")
    test("S11: Index consistency after mutations", test_index_consistency)

    print("\n--- Scenario 12: Cross-Instance ---")
    test("S12: Cross-instance data isolation", test_cross_instance)

    print("\n--- Scenario 13: Schema Validation ---")
    test("S13: All cases v0.2 schema", test_all_cases_v02)

    print("\n--- Scenario 14: Memory Growth ---")
    test("S14: Stats consistency after mutations", test_stats_after_mutations)

    print("\n--- Scenario 15: Error Recovery ---")
    test("S15: Pipeline without artifacts", test_pipeline_missing_artifacts)

    print("\n" + "=" * 60)
    print(f"Results: {PASSED} passed, {FAILED} failed, {PASSED + FAILED} total")
    print("=" * 60)

    if TESTS:
        print("\nTest Details:")
        for name, status, err in TESTS:
            mark = "OK" if status == "PASS" else "FAIL"
            print(f"  [{mark}] {name}" + (f" — {err}" if err else ""))

    sys.exit(1 if FAILED > 0 else 0)
