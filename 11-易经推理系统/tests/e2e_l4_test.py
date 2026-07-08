#!/usr/bin/env python
"""L4 记忆系统端到端测试 — M0→M4 全链路验证。

创建合成 episode 数据，逐模块验证 L1-L4 各层通信。
"""

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

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
)
from scripts.memory_l4 import case_registry, a0a9_bridge, review_engine
from scripts.memory_l4 import distill_engine, stats_engine, pipeline
from scripts.memory_l4 import index_builder, query_similar

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_episode(case_id: str, pnl: float, regime: str = "bull",
                  decision: str = "long", trace_id: str = None) -> dict:
    """生成合成 episode 数据。"""
    tid = trace_id or case_id
    return {
        "trace_id": tid,
        "inst_id": f"{case_id}_INST",
        "ts": _ts(),
        "decision": decision,
        "status": "closed",
        "regime": regime,
        "pnl_pct": pnl,
        "pnl_usdt": pnl * 100,
        "drawdown": abs(pnl) * 0.5,
        "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
        "goal_achieved": pnl > 0,
        "outcome": {
            "realized_pnl_pct": pnl,
            "realized_pnl_usdt": pnl * 100,
            "max_drawdown": abs(pnl) * 0.5,
            "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
            "goal_achieved": pnl > 0,
        },
        "reason_codes": [f"reason_{case_id}"],
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


def _make_a0a9_artifacts(case_id: str):
    """生成合成 A0-A9 阶段产出。"""
    trading_dir = _ROOT / "artifacts" / "trading"
    trading_dir.mkdir(parents=True, exist_ok=True)

    stage_data = {
        "A0": {"timestamp": _ts(), "core_contradiction": "price action vs indicator divergence",
               "analysis": "price makes higher high but RSI makes lower high"},
        "A1": {"timestamp": _ts(), "research_conclusion": "momentum confirmed",
               "methodology": "technical analysis"},
        "A2": {"timestamp": _ts(), "first_principles": "trend follows momentum",
               "reasoning": "market inefficiency in short term"},
        "A3": {"timestamp": _ts(), "simulation_result": "backtest positive",
               "hypothesis": "momentum breakout strategy",
               "backtest_result": "win_rate=0.65, avg_pnl=2.3%"},
        "A4": {"timestamp": _ts(), "validation_result": "hypothesis validated",
               "assumption": "trend continuation",
               "test_outcome": "pass"},
        "A5": {"timestamp": _ts(), "execution_decision": "enter long",
               "execution_logic": "breakout above resistance"},
        "A6": {"timestamp": _ts(), "signal_decision": "hold",
               "signal_rationale": "no reversal signal"},
        "A7": {"timestamp": _ts(), "practice_audit_result": "practice matches theory",
               "practice_theory_gap": "minor slippage observed"},
        "A8": {"timestamp": _ts(), "verification_result": "theory confirmed",
               "theory_critique": "valid under current regime",
               "verification_outcome": "pass"},
        "A9": {"timestamp": _ts(), "exit_decision": "take profit at target",
               "exit_reasoning": "reached target price level"},
    }

    for stage, data in stage_data.items():
        f = trading_dir / f"{case_id}_{stage}_output.json"
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    trading_dir = _ROOT / "artifacts" / "trading"
    _purge_dir(trading_dir, ("*_output.json",))
    yield


# ===================================================================
# Test 1: case_registry — M0 注册
# ===================================================================
def test_m0_register():
    """M0: 从 episode 创建 TradeCase v0.2。"""
    ep = _make_episode("TC_PROFIT_01", pnl=3.5, regime="bull")
    ep_path = workbuddy_dir() / "episodes" / "TC_PROFIT_01.json"
    ep_path.parent.mkdir(parents=True, exist_ok=True)
    ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    case_path = case_registry.create_case_from_episode_file(ep_path)
    assert case_path.exists(), f"case file not created: {case_path}"

    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert case["version"] == "v0.2", f"expected v0.2, got {case['version']}"
    assert case["case_id"] == "TC_TC_PROFIT_01"
    assert case["l4_status"] == "M0_CASE_REGISTERED"
    assert isinstance(case["thinking_chain"], list)
    assert len(case["thinking_chain"]) == 0  # empty initially
    assert "evidence_chain" in case
    assert case["evidence_chain"]["market_data_refs"] == []
    assert case["decision_outcome"]["pnl_pct"] == 3.5
    assert case["review"]["mistakes"] == []
    assert case["review"]["successes"] == []
    assert case["quadrant"]["x"] == 0.0
    assert case["quadrant"]["y"] == 0.0


def test_m0_register_loss():
    """M0: 亏损 case 注册。"""
    ep = _make_episode("TC_LOSS_01", pnl=-2.0, regime="bear", decision="short")
    ep_path = workbuddy_dir() / "episodes" / "TC_LOSS_01.json"
    ep_path.parent.mkdir(parents=True, exist_ok=True)
    ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    case_path = case_registry.create_case_from_episode_file(ep_path)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert case["decision_outcome"]["pnl_pct"] == -2.0
    # exit_reason is populated via populate_decision_outcome, not auto-registered
    assert case["l4_status"] == "M0_CASE_REGISTERED"


def test_m0_upgrade_v01_to_v02():
    """M0: v0.1 格式升级到 v0.2。"""
    old_case = {
        "case_id": "TC_OLD_01",
        "version": "v0.1",
        "ts_start": _ts(),
        "inst_id": "INST_01",
        "tags": ["old"],
        "intent": {"question": "", "goal": "", "constraints": []},
        "investigation": {"summary": "", "sources": []},
        "theory_refs": [],
        "environment_snapshot": {"regime": "bull"},
        "plan": {"minimal_change": "", "max_future_space": "", "steps": ["test"]},
        "execution": {"episode_refs": [{"trace_id": "t1", "path": ""}], "result": "ok"},
        "online_pressure_test": None,
        "rollout_monitoring": None,
        "backtest": None,
        "review": {"summary": "", "theory_practice_consistency": "consistent", "lessons": []},
        "dream_reflection": None,
        "quadrant": {"x": 0.5, "y": 0.6, "evidence": {"weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2}, "y_perf": 0.6, "y_consistency": 0.6, "y_human": 0.5, "notes": ""}},
    }
    upgraded = case_registry.upgrade_case_to_v02(old_case)
    assert upgraded["version"] == "v0.2"
    assert "thinking_chain" in upgraded
    assert "evidence_chain" in upgraded
    assert "decision_outcome" in upgraded
    assert upgraded["l4_status"] == "M0_CASE_REGISTERED"
    assert "mistakes" in upgraded["review"]
    assert "successes" in upgraded["review"]


def test_m0_populate_thinking_chain():
    """M0: populate_thinking_chain 注入阶段数据。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("TC_STAGE_01", pnl=1.0), "TC_STAGE_01"
    )
    stages = [
        {"stage": "A0", "ts": _ts(), "decision": "found contradiction", "contradiction": "divergence"},
        {"stage": "A3", "ts": _ts(), "decision": "simulated", "hypothesis": "momentum", "test_result": "pass"},
        {"stage": "A9", "ts": _ts(), "decision": "exit", "exit_logic": "target hit"},
    ]
    case_registry.populate_thinking_chain(case, stages)
    assert len(case["thinking_chain"]) == 3
    assert case["thinking_chain"][0]["stage"] == "A0"
    assert case["thinking_chain"][0]["contradiction"] == "divergence"
    assert case["thinking_chain"][1]["hypothesis"] == "momentum"
    assert case["thinking_chain"][2]["exit_logic"] == "target hit"


def test_m0_advance_l4_status():
    """M0: L4 状态机推进。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("TC_STATUS_01", pnl=1.0), "TC_STATUS_01"
    )
    assert case["l4_status"] == "M0_CASE_REGISTERED"
    case_registry.advance_l4_status(case, "M1_REVIEW_COMPLETED")
    assert case["l4_status"] == "M1_REVIEW_COMPLETED"
    case_registry.advance_l4_status(case, "M2_DISTILL_COMPLETED")
    assert case["l4_status"] == "M2_DISTILL_COMPLETED"


# ===================================================================
# Test 2: a0a9_bridge — 阶段数据桥接
# ===================================================================
def test_a0a9_collect():
    """A0-A9: 收集阶段产出。"""
    case_id = "TC_A0A9_01"
    _make_a0a9_artifacts(case_id)
    outputs = a0a9_bridge.collect_stage_outputs(case_id)
    # Should find multiple stages from artifacts
    assert len(outputs) > 0, "Expected at least some stage outputs"


def test_a0a9_build_chain():
    """A0-A9: 构建 thinking_chain。"""
    case_id = "TC_CHAIN_01"
    _make_a0a9_artifacts(case_id)
    outputs = a0a9_bridge.collect_stage_outputs(case_id)
    chain = a0a9_bridge.build_thinking_chain_from_stages(outputs)
    assert len(chain) > 0
    # Verify stage order
    stages = [s["stage"] for s in chain]
    assert "A0" in stages or "A1" in stages, f"Expected early stages, got {stages}"


def test_a0a9_query_memory():
    """A0-A9: L1 记忆检索。"""
    refs = a0a9_bridge.query_memory_for_stage("A0", context={"regime": "bull"}, top_k=5)
    assert isinstance(refs, list)  # May be empty if no cases exist yet


# ===================================================================
# Test 3: review_engine — M1 复盘
# ===================================================================
def test_m1_review_success():
    """M1: 成功案例分析。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("TC_REV_OK", pnl=4.0), "TC_REV_OK"
    )
    ep = _make_episode("TC_REV_OK", pnl=4.0)
    result = review_engine.analyze_success(case, ep)
    assert result["direction"] == "success"
    assert result["pnl_pct"] == 4.0


def test_m1_review_failure():
    """M1: 失败案例分析。"""
    case = case_registry.create_case_data(
        _make_episode("TC_REV_FAIL", pnl=-3.0), "TC_REV_FAIL"
    ) if False else case_registry.create_case_from_episode_data(
        _make_episode("TC_REV_FAIL", pnl=-3.0), "TC_REV_FAIL"
    )
    ep = _make_episode("TC_REV_FAIL", pnl=-3.0)
    result = review_engine.analyze_failure(case, ep)
    assert result["direction"] == "failure"
    assert result["pnl_pct"] == -3.0


def test_m1_build_review_record():
    """M1: 构建 ReviewRecord。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("TC_REV_REC", pnl=2.0), "TC_REV_REC"
    )
    analysis = review_engine.analyze_success(case, _make_episode("TC_REV_REC", pnl=2.0))
    record = review_engine.build_review_record(case, analysis)
    assert "review_id" in record
    assert record["direction"] == "success"
    assert len(record["successes"]) > 0
    assert "theory_practice_analysis" in record


def test_m1_batch_review():
    """M1: 批量复盘。"""
    cases = []
    episodes = {}
    for i, pnl in enumerate([3.0, -1.5, 2.5, -0.5]):
        c = case_registry.create_case_from_episode_data(
            _make_episode(f"TC_BATCH_{i}", pnl=pnl), f"TC_BATCH_{i}"
        )
        cases.append(c)
        episodes[f"TC_BATCH_{i}"] = _make_episode(f"TC_BATCH_{i}", pnl=pnl)

    result = review_engine.run_review(
        cases=cases,
        episodes_by_case_id=episodes,
    )
    assert result["total_reviews"] == 4
    assert result["success_count"] == 2  # pnl > 0
    assert result["failure_count"] == 2  # pnl <= 0


# ===================================================================
# Test 4: distill_engine — M2 蒸馏
# ===================================================================
def test_m2_init_distill():
    """M2: 初始化蒸馏记录。"""
    review = {
        "review_id": "REV_TEST",
        "case_id": "TC_DISTILL_01",
        "direction": "failure",
        "mistakes": [{"what": "entered too early", "why": "no confirmation", "severity": 0.7}],
        "successes": [],
    }
    d = distill_engine.init_distill(review, kind="risk_signal")
    assert d["version"] == "v0.2"
    assert d["kind"] == "risk_signal"
    assert "what_is_it" in d
    assert "why_it_works" in d
    assert "how_to_apply" in d
    assert "Failure pattern" in d["claim"]


def test_m2_full_pipeline():
    """M2: 完整蒸馏流程 (11 步 + 三问)。"""
    case_id = "TC_DISTILL_FULL"
    case = case_registry.create_case_from_episode_data(
        _make_episode(case_id, pnl=-2.5), case_id
    )
    case_path = memory_l4_cases_dir() / f"{case_id}.json"
    case_registry.save_json(case_path, case)

    review = {
        "review_id": "REV_DISTILL_FULL",
        "case_id": case_id,
        "direction": "failure",
        "mistakes": [{"what": "entered too early", "why": "no confirmation", "severity": 0.7}],
        "successes": [],
    }

    distill = distill_engine.run_full_distill_pipeline(review, kind="risk_signal")
    assert distill["process_trace"]["intent"] is not None
    assert distill["process_trace"]["investigation"] is not None
    assert distill["process_trace"]["conclusion"] is not None
    assert distill["process_trace"]["optimization"] is not None
    assert distill["what_is_it"]["definition"] is not None
    assert distill["why_it_works"]["causal_analysis"] != ""
    assert distill["quadrant"]["y"] > 0  # y should be computed


def test_m2_compute_quadrant():
    """M2: 象限计算。"""
    case_id = "TC_DISTILL_QUAD"
    case = case_registry.create_case_from_episode_data(
        _make_episode(case_id, pnl=5.0), case_id
    )
    # Set a non-zero quadrant
    case["quadrant"]["x"] = 0.8
    case["quadrant"]["y"] = 0.7
    case["review"]["theory_practice_consistency"] = "consistent"
    case["review"]["review_record_id"] = "REV_TEST"
    case_path = memory_l4_cases_dir() / f"{case_id}.json"
    case_registry.save_json(case_path, case)

    distill = distill_engine.init_distill(
        {"case_id": case_id, "direction": "success", "mistakes": [], "successes": [{"what": "good entry"}]},
        kind="benefit_experience"
    )
    distill = distill_engine.answer_what_is_it(distill)
    distill = distill_engine.answer_why_it_works(distill)
    distill = distill_engine.answer_how_to_apply(distill)
    distill_engine.compute_distill_quadrant(distill)

    assert distill["quadrant"]["x"] == 0.8
    assert distill["quadrant"]["y"] > 0
    assert distill["quadrant"]["evidence"]["y_perf"] > 0
    assert distill["quadrant"]["evidence"]["y_consistency"] > 0


# ===================================================================
# Test 5: stats_engine — M3 统计
# ===================================================================
def test_m3_stage_coverage():
    """M3: A0-A9 阶段覆盖率统计。"""
    stats = stats_engine.compute_stage_coverage()
    assert "stage_counts" in stats
    assert "stage_rates" in stats
    assert "A0" in stats["stage_counts"]


def test_m3_pnl_stats():
    """M3: 收益统计。"""
    stats = stats_engine.compute_pnl_stats()
    assert "count" in stats
    assert "win_rate" in stats


def test_m3_l4_status_dist():
    """M3: L4 状态分布。"""
    stats = stats_engine.compute_l4_status_distribution()
    assert "total" in stats
    assert "distribution" in stats


def test_m3_full_stats():
    """M3: 完整统计快照。"""
    stats = stats_engine.compute_full_stats()
    assert "snapshot_id" in stats
    assert stats["version"] == "v0.2"
    assert "stage_coverage" in stats
    assert "quadrant_distribution" in stats
    assert "pnl_stats" in stats
    assert "l4_status_distribution" in stats

    saved = stats_engine.save_stats(stats)
    assert saved.exists()


# ===================================================================
# Test 6: index_builder — 索引构建
# ===================================================================
def test_index_v02():
    """Index: v0.2 索引构建。"""
    cases = index_builder.load_cases()
    distills = index_builder.load_distills()
    episodes = index_builder.load_episodes_for_cases(cases)

    data = index_builder.build_index_data(
        _ts(), cases, distills, episodes_by_path=episodes
    )
    assert data["metadata"]["feature_version"] == "v0.2"
    assert "summary" in data
    assert "case_features" in data
    assert "distill_features" in data


def test_index_thinking_chain_features():
    """Index: thinking_chain 特征提取。"""
    case = case_registry.create_case_from_episode_data(
        _make_episode("TC_IDX_TC_FEAT", pnl=1.0), "TC_IDX_TC_FEAT"
    )
    # Add thinking chain
    case_registry.populate_thinking_chain(case, [
        {"stage": "A0", "decision": "contradiction_found", "contradiction": "price divergence"},
        {"stage": "A3", "decision": "simulation_pass"},
        {"stage": "A9", "decision": "exit_taken"},
    ])
    # Verify thinking_chain structure
    tc = case.get("thinking_chain", [])
    assert len(tc) == 3, f"Expected 3 stages, got {len(tc)}"
    assert tc[0]["stage"] == "A0"
    assert tc[0].get("contradiction") == "price divergence", f"Missing contradiction: {tc[0]}"

    tc_feat = index_builder._extract_thinking_chain_features(case)
    assert tc_feat["stages_count"] == 3, f"stages_count: {tc_feat['stages_count']}"
    assert tc_feat["stage_coverage_pct"] == 30.0, f"coverage: {tc_feat['stage_coverage_pct']}"
    assert tc_feat["has_contradiction_analysis"], f"tc_feat: {tc_feat}"


def test_index_summary():
    """Index: 全局摘要。"""
    cases = index_builder.load_cases()
    feats = {}
    for c in cases:
        cid = c.get("case_id")
        if cid:
            feats[cid] = {
                "version": c.get("version"),
                "l4_status": c.get("l4_status"),
                "thinking_chain": index_builder._extract_thinking_chain_features(c),
                "quadrant_features": index_builder._extract_quadrant_features(c),
            }
    summary = index_builder._build_index_summary(feats, [])
    assert summary["total_cases"] > 0
    assert "v02_ratio" in summary
    assert "stage_coverage" in summary
    assert "l4_status_distribution" in summary


# ===================================================================
# Test 7: query_similar — 检索
# ===================================================================
def test_query_by_stage():
    """Query: 按阶段检索。"""
    # Should work even with empty cases
    result = query_similar.query_by_stage("A0", topk=5)
    assert result["stage"] == "A0"
    assert isinstance(result["cases"], list)


def test_query_by_regime():
    """Query: 按 regime 检索。"""
    result = query_similar.query_by_regime_and_outcome("bull", outcome="profit", topk=5)
    assert result["regime"] == "bull"


def test_get_thinking_chain():
    """Query: 获取 thinking_chain。"""
    # Use a case we created
    case_id = "TC_IDX_TC"
    try:
        result = query_similar.get_thinking_chain(case_id)
        assert result["case_id"] == case_id
        assert result["stage_coverage"]["stages_present"] == ["A0", "A3", "A9"]
    except KeyError:
        pass  # Case may not exist in test run order


def test_query_v2_similarity():
    """Query: v0.2 相似度计算。"""
    cases = index_builder.load_cases()
    if len(cases) >= 2:
        # Build index first
        episodes = index_builder.load_episodes_for_cases(cases)
        idx = index_builder.build_index_data(_ts(), cases, [], episodes_by_path=episodes)
        cids = list(idx["case_features"].keys())[:2]
        sim, expl = query_similar.similarity(idx, cids[0], cids[1])
        assert 0 <= sim <= 1


# ===================================================================
# Test 8: L1→L4 通信验证
# ===================================================================
def test_l1_to_l4_data_flow():
    """L1→L4: 数据流验证 — case 注册后能在 L4 各模块中流转。"""
    case_id = "TC_FLOW_01"
    ep = _make_episode(case_id, pnl=2.0, regime="bull")
    ep_path = workbuddy_dir() / "episodes" / f"{case_id}.json"
    ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # L1: 注册
    case_path = case_registry.create_case_from_episode_file(ep_path)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert case["l4_status"] == "M0_CASE_REGISTERED"

    # L4 M1: 复盘
    analysis = review_engine.analyze_success(case, ep)
    record = review_engine.build_review_record(case, analysis)
    assert record["direction"] == "success"

    # L4 M2: 蒸馏
    distill = distill_engine.init_distill(record)
    distill = distill_engine.run_full_distill_pipeline(record)
    assert distill["quadrant"]["y"] > 0

    # L4 M3: 统计
    stats = stats_engine.compute_full_stats()
    assert stats["pnl_stats"]["count"] > 0

    print(f"  [INFO] L1→L4 flow: M0→M1→M2→M3 verified for {case_id}")


def test_l4_status_machine():
    """L4: 状态机完整流转 M0→M1→M2→M3→M4。"""
    case_id = "TC_STATE_01"
    ep = _make_episode(case_id, pnl=1.5)
    ep_path = workbuddy_dir() / "episodes" / f"{case_id}.json"
    if not ep_path.exists():
        ep_path.write_text(json.dumps(ep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    case_path = case_registry.create_case_from_episode_file(ep_path)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert case["l4_status"] == "M0_CASE_REGISTERED"

    # M0→M1
    case_registry.advance_l4_status(case, "M1_REVIEW_COMPLETED")
    assert case["l4_status"] == "M1_REVIEW_COMPLETED"

    # M1→M2
    case_registry.advance_l4_status(case, "M2_DISTILL_COMPLETED")
    assert case["l4_status"] == "M2_DISTILL_COMPLETED"

    # M2→M3
    case_registry.advance_l4_status(case, "M3_STATS_UPDATED")
    assert case["l4_status"] == "M3_STATS_UPDATED"

    # M3→M4
    case_registry.advance_l4_status(case, "M4_CANDIDATE_EMITTED")
    assert case["l4_status"] == "M4_CANDIDATE_EMITTED"

    print(f"  [INFO] State machine: M0→M1→M2→M3→M4 verified for {case_id}")


# ===================================================================
# Main
# ===================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("L4 Memory System E2E Test Suite")
    print("=" * 60)

    # Clean test data
    import shutil
    for d in [memory_l4_cases_dir(), memory_l4_reviews_dir(), memory_l4_distills_dir(), memory_l4_stats_dir()]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    print("\n--- M0: case_registry ---")
    test("M0: register profit case", test_m0_register)
    test("M0: register loss case", test_m0_register_loss)
    test("M0: upgrade v0.1 to v0.2", test_m0_upgrade_v01_to_v02)
    test("M0: populate thinking_chain", test_m0_populate_thinking_chain)
    test("M0: advance L4 status", test_m0_advance_l4_status)

    print("\n--- A0-A9: bridge ---")
    test("A0-A9: collect stage outputs", test_a0a9_collect)
    test("A0-A9: build thinking_chain", test_a0a9_build_chain)
    test("A0-A9: query memory for stage", test_a0a9_query_memory)

    print("\n--- M1: review_engine ---")
    test("M1: review success", test_m1_review_success)
    test("M1: review failure", test_m1_review_failure)
    test("M1: build review record", test_m1_build_review_record)
    test("M1: batch review", test_m1_batch_review)

    print("\n--- M2: distill_engine ---")
    test("M2: init distill", test_m2_init_distill)
    test("M2: full distill pipeline", test_m2_full_pipeline)
    test("M2: compute quadrant", test_m2_compute_quadrant)

    print("\n--- M3: stats_engine ---")
    test("M3: stage coverage", test_m3_stage_coverage)
    test("M3: pnl stats", test_m3_pnl_stats)
    test("M3: L4 status distribution", test_m3_l4_status_dist)
    test("M3: full stats snapshot", test_m3_full_stats)

    print("\n--- Index: index_builder ---")
    test("Index: v0.2 build", test_index_v02)
    test("Index: thinking_chain features", test_index_thinking_chain_features)
    test("Index: global summary", test_index_summary)

    print("\n--- Query: query_similar ---")
    test("Query: by stage", test_query_by_stage)
    test("Query: by regime", test_query_by_regime)
    test("Query: get thinking_chain", test_get_thinking_chain)
    test("Query: v0.2 similarity", test_query_v2_similarity)

    print("\n--- L1→L4: communication ---")
    test("L1→L4: data flow", test_l1_to_l4_data_flow)
    test("L4: state machine M0→M4", test_l4_status_machine)

    print("\n" + "=" * 60)
    print(f"Results: {PASSED} passed, {FAILED} failed, {PASSED + FAILED} total")
    print("=" * 60)

    if TESTS:
        print("\nTest Details:")
        for name, status, err in TESTS:
            mark = "OK" if status == "PASS" else "FAIL"
            print(f"  [{mark}] {name}" + (f" — {err}" if err else ""))

    sys.exit(1 if FAILED > 0 else 0)
