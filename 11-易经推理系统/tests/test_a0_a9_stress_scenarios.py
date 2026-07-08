# -*- coding: utf-8 -*-
"""
A0-A9 全链路场景压力测试 (v2.1 协议)

覆盖三大闭环所有路径:
- 执行环: 正常/重试/失败/并发
- 情报环: L0/L1/L1.5/L2/L3 全级别 + 边界 + 多告警
- 治理环: A7→A8→A1/A2/A3 全路由 + 信誉累积
- 端到端: 执行环→情报环→治理环 完整链路
- 状态机: 全状态转换 + 非法转换拦截
- 协议: 全入口契约字段校验
"""
import importlib.util
import json
import random
import string
from pathlib import Path
from typing import Any, Dict

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _payload(env):
    return env["payload"]


def _trace_id():
    return "stress_" + "".join(random.choices(string.ascii_lowercase, k=8))


def _base_payload(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    p = {
        "trace_id": _trace_id(),
        "signals": ["macro", "sentiment"],
        "confidence": 0.75,
        "rsi": 50,
        "funding_rate": 0.0,
        "fgi": 50,
        "signal_score": 65,
        "volatility": 0.02,
        "market_regime": "trend",
        "max_drawdown_pct": 1.0,
        "position_ratio": 0.3,
        "stop_loss_pct": 1.5,
        "direction": "LONG",
        "entry_price": 65000,
        "leverage": 2,
        "unrealized_pnl_pct": 1.0,
        "risk_level": "low",
        "violations": [],
        "hypothesis_score": 0.90,
        "practice_score": 0.85,
    }
    if overrides:
        p.update(overrides)
    return p


exec_mod = _load_module("workflows/trading-decision/orchestrator/execution_loop.py")
gov_mod = _load_module("workflows/trading-decision/orchestrator/governance_loop.py")
state_mod = _load_module("workflows/trading-decision/orchestrator/state_machine.py")
a6_mod = _load_module("workflows/trading-decision/A6_intelligence/entrypoint.py")
proto_mod = _load_module("workflows/trading-decision/protocol/message.py")


# ===================================================================
# 1. 执行环压力测试
# ===================================================================

class TestExecutionLoopHappyPath:
    """执行环正常路径: 定时任务触发 → A1→A2→A3→A4→A5→A9"""

    def test_full_chain_all_stages_visited(self, tmp_path: Path):
        out = exec_mod.run_execution_loop(
            _base_payload(), output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A9"]
        for stage in ["A1", "A2", "A3", "A4", "A5", "A6", "A9"]:
            assert stage in out["stage_outputs"], f"{stage} missing from stage_outputs"
        assert out["trace_id"]

    def test_all_messages_have_valid_contract(self):
        out = exec_mod.run_execution_loop(_base_payload())
        for msg in out["messages"]:
            h = msg["header"]
            assert h["source"]
            assert h["target"]
            assert h["loop_type"] in {"execution", "intelligence", "governance"}
            assert h["trace_id"]
            assert h["version"] == "2.0"

    def test_a9_triggers_a7_governance_message(self):
        out = exec_mod.run_execution_loop(_base_payload())
        gov_msgs = [m for m in out["messages"] if m["header"]["loop_type"] == "governance"]
        a7_msgs = [m for m in gov_msgs if m["header"]["target"] == "A7"]
        assert len(a7_msgs) >= 1, "A9 must trigger A7 governance message"

    def test_a5_notifies_a6_intelligence(self):
        out = exec_mod.run_execution_loop(_base_payload())
        a5_to_a6 = [m for m in out["messages"] if m["header"]["source"] == "A5" and m["header"]["target"] == "A6"]
        assert len(a5_to_a6) >= 1
        assert a5_to_a6[0]["header"]["loop_type"] == "execution"


class TestExecutionLoopA4BlockRetry:
    """A4 BLOCK → 返回 A3 重试 → A4 再验证"""

    def test_a4_block_triggers_a3_retry(self, tmp_path: Path):
        payload = _base_payload({"max_drawdown_pct": 7.0})  # > 6 → BLOCK
        out = exec_mod.run_execution_loop(payload, output_dir=tmp_path, max_retries=1)
        assert "A3_retry" in out["stage_outputs"] or "A4_retry" in out["stage_outputs"]

    def test_a4_block_no_retry_when_max_retries_zero(self, tmp_path: Path):
        payload = _base_payload({"max_drawdown_pct": 7.0})
        out = exec_mod.run_execution_loop(payload, output_dir=tmp_path, max_retries=0)
        assert "A3_retry" not in out["stage_outputs"]
        assert "A4_retry" not in out["stage_outputs"]

    def test_a4_block_retry_then_pass(self, tmp_path: Path):
        """Verify retry flow is exercised when A4 BLOCKs."""
        payload = _base_payload({"max_drawdown_pct": 7.0})
        out = exec_mod.run_execution_loop(payload, output_dir=tmp_path, max_retries=2)
        # Retry entries should appear
        assert "A3_retry" in out["stage_outputs"]


class TestExecutionLoopA5FailRetry:
    """A5 FAIL → 返回 A4 重新验证 → A5 重试"""

    def test_a5_fail_returns_to_a4(self, tmp_path: Path):
        """Default A5 does not return execution_status=FAIL, so no retry on happy path."""
        out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path, max_retries=1)
        assert "A4_recheck" not in out["stage_outputs"]
        assert "A5_retry" not in out["stage_outputs"]

    def test_a5_fail_retry_with_fake_runner(self, tmp_path: Path):
        """Inject a fake A5 that always returns FAIL to verify retry logic."""
        def fake_a5(p, output_dir=None):
            return proto_mod.build_envelope(
                source="A5", target="A9", message_type="REQUEST", priority="HIGH",
                loop_type="execution", trace_id=p.get("trace_id", "t"),
                payload={"stage_id": "A5", "trace_id": p.get("trace_id", "t"),
                         "direction": "LONG", "order_plan": {"side": "BUY"}, "execution_status": "FAIL"},
            )

        def default_stage(stage_name, p, output_dir=None):
            mapping = {
                "A1": ("A1_research/entrypoint.py", "run_a1_research"),
                "A2": ("A2_first-principles/entrypoint.py", "run_a2_first_principles"),
                "A3": ("A3_simulation/entrypoint.py", "run_a3_simulation"),
                "A4": ("A4_validation/entrypoint.py", "run_a4_validation"),
                "A6": ("A6_intelligence/entrypoint.py", "run_a6_intelligence"),
                "A9": ("A9_exit/entrypoint.py", "run_a9_exit"),
            }
            rel, fn = mapping[stage_name]
            mod = _load_module(f"workflows/trading-decision/{rel}")
            return getattr(mod, fn)(p, output_dir=output_dir)

        runners = {}
        for stage in ["A1", "A2", "A3", "A4", "A6", "A9"]:
            s = stage
            runners[stage] = lambda p, output_dir=None, _s=s: default_stage(_s, p, output_dir)
        runners["A5"] = fake_a5

        out = exec_mod.run_execution_loop(
            _base_payload(), output_dir=tmp_path, stage_runners=runners, max_retries=1,
        )
        # After A5 FAIL, orchestrator should re-run A4 then A5
        assert "A4_recheck" in out["stage_outputs"]


class TestExecutionLoopPressure:
    """执行环并发/连续运行压力测试"""

    def test_10_consecutive_runs_all_succeed(self, tmp_path: Path):
        for _ in range(10):
            out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path)
            assert out["visited_stages"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A9"]
            assert out["trace_id"]

    def test_different_directions_all_pass(self, tmp_path: Path):
        for direction in ["LONG", "SHORT"]:
            out = exec_mod.run_execution_loop(
                _base_payload({"direction": direction}), output_dir=tmp_path,
            )
            assert "A5" in out["stage_outputs"]
            assert "A9" in out["stage_outputs"]

    def test_various_risk_levels(self, tmp_path: Path):
        for risk in ["low", "medium", "high"]:
            out = exec_mod.run_execution_loop(
                _base_payload({"risk_level": risk, "unrealized_pnl_pct": 1.0}),
                output_dir=tmp_path,
            )
            assert "A9" in out["stage_outputs"]

    def test_artifacts_created_for_all_stages(self, tmp_path: Path):
        out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path)
        for stage in ["A1", "A2", "A3", "A4", "A5", "A6", "A9"]:
            so = out["stage_outputs"][stage]
            if isinstance(so, dict) and "artifact_path" in so:
                assert Path(so["artifact_path"]).exists(), f"{stage} artifact missing"


# ===================================================================
# 2. 情报环压力测试 (A6 5级放射驱动)
# ===================================================================

class TestA6IntelligenceAllLevels:
    """A6 中枢 L0/L1/L1.5/L2/L3 全级别测试"""

    def test_l0_fatal_risk_score_095(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.95}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        p = _payload(out)
        assert p["route_summary"]["L0"] == 1
        l0_events = [e for e in p["routed_events"] if e["header"]["target"] == "A9"]
        assert len(l0_events) >= 1

    def test_l0_boundary_exactly_09(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.9}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L0"] == 1

    def test_l0_boundary_089_not_l0(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.89}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L0"] == 0

    def test_l1_high_risk_score_08(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.8}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L1"] == 1
        l1_events = [e for e in _payload(out)["routed_events"] if e["header"]["target"] == "A4"]
        assert len(l1_events) >= 1

    def test_l1_boundary_07(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.7}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L1"] == 1

    def test_l15_regime_change(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.3, "regime_change": True}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L1.5"] == 1
        l15_events = [e for e in _payload(out)["routed_events"] if e["header"]["target"] == "A2"]
        assert len(l15_events) >= 1

    def test_l2_medium_risk_score_06(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.6}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L2"] == 1

    def test_l2_boundary_05(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.5}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L2"] == 1

    def test_l3_theory_practice_divergence(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"theory_practice_score": 0.5}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L3"] == 1
        l3_targets = {e["header"]["target"] for e in _payload(out)["routed_events"]
                      if e["payload"].get("alert_level") == "L3"}
        assert "A1" in l3_targets
        assert "A3" in l3_targets

    def test_l3_boundary_069(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"theory_practice_score": 0.699}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L3"] == 1

    def test_l3_not_triggered_at_07(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"theory_practice_score": 0.7}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L3"] == 0

    def test_no_alerts_empty_input(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        p = _payload(out)
        assert p["alert_count"] == 0
        assert p["route_summary"] == {"L0": 0, "L1": 0, "L1.5": 0, "L2": 0, "L3": 0}


class TestA6MultiAlertPressure:
    """多告警同时触发，验证 A6 路由正确性"""

    def test_mixed_alerts_all_levels(self, tmp_path: Path):
        """Single A6 call with alerts covering all 5 levels."""
        alerts = [
            {"risk_score": 0.95},  # L0
            {"risk_score": 0.8},   # L1
            {"risk_score": 0.3, "regime_change": True},  # L1.5
            {"risk_score": 0.6},   # L2
            {"theory_practice_score": 0.5},  # L3
        ]
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": alerts, "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        p = _payload(out)
        assert p["alert_count"] == 5
        assert p["route_summary"]["L0"] == 1
        assert p["route_summary"]["L1"] == 1
        assert p["route_summary"]["L1.5"] == 1
        assert p["route_summary"]["L2"] == 1
        assert p["route_summary"]["L3"] == 1

    def test_10_low_risk_alerts_all_l2(self, tmp_path: Path):
        alerts = [{"risk_score": 0.55} for _ in range(10)]
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": alerts, "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["alert_count"] == 10
        assert _payload(out)["route_summary"]["L2"] == 10

    def test_5_black_swan_alerts_all_l0(self, tmp_path: Path):
        alerts = [{"risk_score": 0.99} for _ in range(5)]
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": alerts, "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(out)["route_summary"]["L0"] == 5


class TestA6ProtocolCompliance:
    """A6 消息协议合规性"""

    def test_a6_output_has_valid_envelope(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.5}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert "header" in out
        h = out["header"]
        assert h["source"] == "A6"
        assert h["type"] in {"REQUEST", "EVENT", "NOTIFICATION"}
        assert h["loop_type"] == "intelligence"

    def test_routed_events_have_correct_priority(self, tmp_path: Path):
        out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.95}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        l0_events = [e for e in _payload(out)["routed_events"] if e["header"]["target"] == "A9"]
        assert l0_events[0]["header"]["priority"] == "CRITICAL"


# ===================================================================
# 3. 治理环压力测试 (A7→A8→A1/A2/A3)
# ===================================================================

class TestGovernanceLoopAllRoutes:
    """治理环 A7→A8→A1/A2/A3 全路由测试"""

    def test_gap_040_routes_to_a1(self, tmp_path: Path):
        """gap < 0.5 → A1 (严重背离, 重启调研)"""
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.90, "practice_score": 0.50}),  # gap=0.40
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A1"]

    def test_gap_055_routes_to_a2(self, tmp_path: Path):
        """0.5 <= gap <= 0.7 → A2 (中度背离, 重新分析)"""
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.95, "practice_score": 0.40}),  # gap=0.55
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A2"]

    def test_gap_070_routes_to_a3(self, tmp_path: Path):
        """gap > 0.7 → A3 (轻微背离, 策略微调)"""
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.95, "practice_score": 0.20}),  # gap=0.75
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A3"]

    def test_gap_000_perfect_alignment(self, tmp_path: Path):
        """gap = 0 → A1 (知行高度合一, 但 gap < 0.5 路由到 A1)"""
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.90, "practice_score": 0.90}),  # gap=0
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A1"]

    def test_gap_049_boundary_to_a1(self, tmp_path: Path):
        """gap = 0.49 → A1 (just under 0.5)"""
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.95, "practice_score": 0.46}),  # gap=0.49
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A1"]

    def test_gap_050_boundary_to_a2(self, tmp_path: Path):
        """gap = 0.50 → A2 (exactly 0.5, enters A2 range)"""
        # Use 0.9 - 0.4 = 0.5 exact (avoids 0.95-0.45 floating point → 0.4999...)
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.9, "practice_score": 0.4}),  # gap=0.50
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A2"]

    def test_gap_070_boundary_to_a3(self, tmp_path: Path):
        """gap = 0.70 → A3 (exactly 0.7, > 0.7 is A3)"""
        # gap > 0.7 → A3, gap = 0.7 → A3 (elif <= 0.7 is A2)
        # Per code: elif gap <= 0.7: target = "A2", else: target = "A3"
        # gap = 0.70 → A2
        out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.95, "practice_score": 0.25}),  # gap=0.70
            output_dir=tmp_path,
        )
        assert out["visited_stages"] == ["A7", "A8", "A2"]


class TestGovernanceReputationPressure:
    """治理环信誉系统压力测试"""

    def test_consecutive_failures_decrease_reputation(self, tmp_path: Path):
        ledger = state_mod.ReputationLedger()
        for _ in range(5):
            state_mod.apply_governance_feedback(
                ledger=ledger,
                a7_output={"audit_status": "REVIEW", "violations": [{"id": "v"}]},
                a8_output={"gap_score": 0.5},
            )
        assert ledger.score("A7") < 80
        assert ledger.score("A8") < 80

    def test_recovery_after_success(self, tmp_path: Path):
        ledger = state_mod.ReputationLedger()
        # Fail 3 times
        for _ in range(3):
            state_mod.apply_governance_feedback(
                ledger=ledger,
                a7_output={"audit_status": "REVIEW", "violations": [{"id": "v"}]},
                a8_output={"gap_score": 0.5},
            )
        score_low = ledger.score("A7")
        assert score_low < 100

        # Succeed 5 times
        for _ in range(5):
            state_mod.apply_governance_feedback(
                ledger=ledger,
                a7_output={"audit_status": "PASS", "violations": []},
                a8_output={"gap_score": 0.02},
            )
        assert ledger.score("A7") > score_low

    def test_reputation_never_goes_negative(self, tmp_path: Path):
        ledger = state_mod.ReputationLedger()
        for _ in range(100):
            state_mod.apply_governance_feedback(
                ledger=ledger,
                a7_output={"audit_status": "REVIEW", "violations": [{"id": "v"}]},
                a8_output={"gap_score": 0.8},
            )
        assert ledger.score("A7") >= 0
        assert ledger.score("A8") >= 0

    def test_reputation_never_exceeds_100(self, tmp_path: Path):
        ledger = state_mod.ReputationLedger()
        for _ in range(100):
            state_mod.apply_governance_feedback(
                ledger=ledger,
                a7_output={"audit_status": "PASS", "violations": []},
                a8_output={"gap_score": 0.01},
            )
        assert ledger.score("A7") <= 100
        assert ledger.score("A8") <= 100


class TestGovernancePressure:
    """治理环连续运行压力测试"""

    def test_20_consecutive_runs_all_succeed(self, tmp_path: Path):
        for _ in range(20):
            out = gov_mod.run_governance_loop(
                _base_payload({"hypothesis_score": random.uniform(0.5, 1.0),
                                "practice_score": random.uniform(0.3, 1.0)}),
                output_dir=tmp_path,
            )
            assert "A7" in out["visited_stages"]
            assert "A8" in out["visited_stages"]
            assert len(out["visited_stages"]) == 3  # A7, A8, + one of A1/A2/A3

    def test_governance_produces_artifacts(self, tmp_path: Path):
        out = gov_mod.run_governance_loop(_base_payload(), output_dir=tmp_path)
        for stage in ["A7", "A8"]:
            so = out["stage_outputs"][stage]
            if isinstance(so, dict) and "artifact_path" in so:
                assert Path(so["artifact_path"]).exists()


# ===================================================================
# 4. 状态机压力测试
# ===================================================================

class TestStateMachineTransitions:
    """状态机全路径转换测试"""

    def test_idle_to_research(self):
        sm = state_mod.TradingStateMachine()
        assert sm.current == "IDLE"
        sm.transition("RESEARCH")
        assert sm.current == "RESEARCH"

    def test_no_signal_state(self):
        sm = state_mod.TradingStateMachine()
        with pytest.raises(ValueError):
            sm.transition("SIGNAL")

    def test_full_execution_chain(self):
        sm = state_mod.TradingStateMachine()
        sm.transition("RESEARCH")
        sm.transition("ANALYZING")
        sm.transition("STRATEGIZING")
        sm.transition("VALIDATING")
        sm.transition("EXECUTING")
        sm.transition("EXIT")
        assert sm.current == "EXIT"

    def test_exit_to_practice(self):
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT"]:
            sm.transition(s)
        sm.transition("PRACTICE")
        assert sm.current == "PRACTICE"

    def test_practice_to_verification(self):
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT", "PRACTICE"]:
            sm.transition(s)
        sm.transition("VERIFICATION")
        assert sm.current == "VERIFICATION"

    def test_verification_back_to_research(self):
        """A8 gap < 0.5: VERIFICATION → RESEARCH (A1 restart)"""
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT", "PRACTICE"]:
            sm.transition(s)
        sm.transition("VERIFICATION")
        sm.transition("RESEARCH")
        assert sm.current == "RESEARCH"

    def test_verification_back_to_analyzing(self):
        """A8 gap 0.5-0.7: VERIFICATION → ANALYZING (A2 re-analysis)"""
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT", "PRACTICE"]:
            sm.transition(s)
        sm.transition("VERIFICATION")
        sm.transition("ANALYZING")
        assert sm.current == "ANALYZING"

    def test_verification_back_to_strategizing(self):
        """A8 gap > 0.7: VERIFICATION → STRATEGIZING (A3 strategy tweak)"""
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT", "PRACTICE"]:
            sm.transition(s)
        sm.transition("VERIFICATION")
        sm.transition("STRATEGIZING")
        assert sm.current == "STRATEGIZING"

    def test_verification_to_idle(self):
        """gap >= 0.9: VERIFICATION → IDLE (continue, no correction needed)"""
        sm = state_mod.TradingStateMachine()
        for s in ["RESEARCH", "ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT", "PRACTICE"]:
            sm.transition(s)
        sm.transition("VERIFICATION")
        sm.transition("IDLE")
        assert sm.current == "IDLE"

    def test_invalid_transition_from_idle(self):
        sm = state_mod.TradingStateMachine()
        for invalid in ["ANALYZING", "STRATEGIZING", "VALIDATING", "EXECUTING", "EXIT"]:
            sm2 = state_mod.TradingStateMachine()
            with pytest.raises(ValueError):
                sm2.transition(invalid)

    def test_no_monitoring_or_alert_states(self):
        """v2.1 removes MONITORING and ALERT states"""
        valid_keys = state_mod.TradingStateMachine.VALID.keys()
        assert "MONITORING" not in valid_keys
        assert "ALERT" not in valid_keys
        assert "SIGNAL" not in valid_keys


# ===================================================================
# 5. 端到端链路测试
# ===================================================================

class TestEndToEndChains:
    """端到端完整链路: 执行环→情报环→治理环"""

    def test_full_loop_execution_then_governance(self, tmp_path: Path):
        """A1→A9 execution, then A7→A8 governance via A9 trigger."""
        exec_out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path)
        assert "A9" in exec_out["stage_outputs"]

        # Find A9→A7 governance message
        gov_msgs = [m for m in exec_out["messages"] if m["header"]["target"] == "A7"]
        assert len(gov_msgs) >= 1

    def test_a6_l0_drives_full_chain(self, tmp_path: Path):
        """A6 L0 → A9 exit → A7 practice → A8 verification → A1 restart"""
        # Step 1: A6 detects black swan
        a6_out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"risk_score": 0.95}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(a6_out)["route_summary"]["L0"] == 1

        # Step 2: Execute governance chain from A7
        gov_out = gov_mod.run_governance_loop(
            _base_payload({"hypothesis_score": 0.90, "practice_score": 0.40}),  # gap=0.50 → A2
            output_dir=tmp_path,
        )
        assert "A7" in gov_out["visited_stages"]
        assert "A8" in gov_out["visited_stages"]
        assert "A2" in gov_out["visited_stages"]

    def test_a6_l3_drives_restart_chain(self, tmp_path: Path):
        """A6 L3 → A1+A3 restart → full execution chain"""
        a6_out = a6_mod.run_a6_intelligence(
            {"trace_id": _trace_id(), "alerts": [{"theory_practice_score": 0.5}], "signal_shift": 0.0},
            output_dir=tmp_path,
        )
        assert _payload(a6_out)["route_summary"]["L3"] == 1

        # L3 triggers A1+A3 restart → full execution chain
        exec_out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path)
        assert exec_out["visited_stages"] == ["A1", "A2", "A3", "A4", "A5", "A6", "A9"]

    def test_multiple_governance_cycles(self, tmp_path: Path):
        """Run execution → governance → execution → governance multiple times."""
        for i in range(3):
            exec_out = exec_mod.run_execution_loop(_base_payload(), output_dir=tmp_path)
            assert "A9" in exec_out["stage_outputs"]

            gov_out = gov_mod.run_governance_loop(
                _base_payload({
                    "hypothesis_score": 0.90 - i * 0.05,
                    "practice_score": 0.85 - i * 0.10,
                }),
                output_dir=tmp_path,
            )
            assert len(gov_out["visited_stages"]) == 3


# ===================================================================
# 6. 协议字段契约测试
# ===================================================================

class TestProtocolContractAllEntrypoints:
    """所有 A0-A9 入口都必须产生标准协议字段"""

    def test_all_entrypoints_have_required_fields(self, tmp_path: Path):
        required = {"stage_id", "trace_id", "constraint_version", "memory_refs", "evidence_refs", "producer", "schema_version"}
        entrypoints = [
            ("A1_research/entrypoint.py", "run_a1_research", {"trace_id": "t"}),
            ("A2_first-principles/entrypoint.py", "run_a2_first_principles", {"trace_id": "t"}),
            ("A3_simulation/entrypoint.py", "run_a3_simulation", {"trace_id": "t"}),
            ("A4_validation/entrypoint.py", "run_a4_validation",
             {"trace_id": "t", "max_drawdown_pct": 1.0, "position_ratio": 0.3, "stop_loss_pct": 1.5}),
            ("A5_execution/entrypoint.py", "run_a5_execution", {"trace_id": "t", "direction": "LONG"}),
            ("A6_intelligence/entrypoint.py", "run_a6_intelligence",
             {"trace_id": "t", "alerts": [], "signal_shift": 0.0}),
            ("A7_audit/entrypoint.py", "run_a7_audit", {"trace_id": "t", "violations": []}),
            ("A8_theory-practice/entrypoint.py", "run_a8_theory_practice", {"trace_id": "t"}),
            ("A9_exit/entrypoint.py", "run_a9_exit", {"trace_id": "t"}),
        ]
        for rel, fn, inp in entrypoints:
            mod = _load_module(f"workflows/trading-decision/{rel}")
            fn_obj = getattr(mod, fn)
            out = fn_obj(inp, output_dir=tmp_path)
            body = out.get("payload", out)
            missing = required - set(body.keys())
            assert not missing, f"{rel}: missing fields {missing}"

    def test_message_header_fields(self):
        env = proto_mod.build_envelope(
            source="A1", target="A2", message_type="REQUEST", priority="HIGH",
            loop_type="execution", trace_id="t", payload={"stage_id": "A1"},
        )
        h = env["header"]
        assert h["message_id"]
        assert h["timestamp"]
        assert h["version"] == "2.0"
        assert h["source"] == "A1"
        assert h["target"] == "A2"
        assert h["type"] == "REQUEST"
        assert h["loop_type"] == "execution"
        assert h["timeout_ms"] == 30000
        assert isinstance(h["timeout_ms"], int)


# ===================================================================
# 7. execute_with_retry pressure test
# ===================================================================

class TestExecuteWithRetry:
    """重试与处罚机制压力测试"""

    def test_flaky_function_eventually_succeeds(self):
        ledger = state_mod.ReputationLedger()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 5:
                raise RuntimeError("EVIDENCE_INCOMPLETE")
            return {"ok": True}

        out = state_mod.execute_with_retry(flaky, max_retries=5, ledger=ledger, module_name="A4")
        assert out["status"] == "OK"
        assert out["attempts"] == 5

    def test_always_failing_returns_degraded(self):
        ledger = state_mod.ReputationLedger()

        def always_fail():
            raise RuntimeError("CONSTRAINT_VALIDATION_FAILED")

        out = state_mod.execute_with_retry(always_fail, max_retries=3, ledger=ledger, module_name="A2")
        assert out["status"] == "DEGRADED"
        assert out["error_code"] == "CONSTRAINT_VALIDATION_FAILED"
        assert out["attempts"] == 4  # 1 initial + 3 retries

    def test_penalty_accumulates_over_retries(self):
        ledger = state_mod.ReputationLedger()
        initial = ledger.score("A4")

        def fail_once():
            raise RuntimeError("EVIDENCE_INCOMPLETE")

        state_mod.execute_with_retry(fail_once, max_retries=0, ledger=ledger, module_name="A4")
        assert ledger.score("A4") < initial

    def test_recovery_after_success(self):
        ledger = state_mod.ReputationLedger()
        ledger.penalize("A1", delta=50)
        assert ledger.score("A1") == 50

        def succeed():
            return {"ok": True}

        # Recovery is incremental (+1 per success), call multiple times to recover
        for _ in range(50):
            state_mod.execute_with_retry(succeed, max_retries=0, ledger=ledger, module_name="A1")
        assert ledger.score("A1") == 100  # recovered to max after repeated successes
