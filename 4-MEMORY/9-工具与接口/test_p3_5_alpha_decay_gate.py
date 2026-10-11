"""P3-5 Alpha Decay 自动门禁 TDD RED 测试

借鉴 Vibe-Trading sdm_decay_scan（24.4K★），补齐策略级衰减检测：
SKILL 治理偏治理，缺策略级衰减 —— P3-5 用半衰期公式量化 alpha 衰减。

核心机制:
  1. compute_decayed_confidence(confidence, days_since_verify, half_life)
     — 半衰期衰减: decayed = confidence * 0.5^(days / half_life)
  2. decide_gate_action(decayed_confidence)
     — >= ACTIVE_THRESHOLD (0.5) → "ok"（保持 active）
     — >= SHADOW_THRESHOLD (0.25) → "re-verify"（触发重新验证）
     — < SHADOW_THRESHOLD → "deactivate"（降级 shadow/下线）
  3. scan(entries) — 批量扫描策略/SKILL 条目，返回需行动清单

RED 契约:
  1. alpha_decay_gate 模块不存在 → ImportError
  2. AlphaDecayGate 类不存在
  3. CognitiveLoopEntry 无 alpha_decay_gate 属性

参考: SPEC-CognitiveSystem-Evolution.md §1.1 + §4.3 P3-5
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestDecayComputation:
    """半衰期衰减计算。"""

    def test_import_alpha_decay_gate(self):
        """RED: alpha_decay_gate 模块可导入。"""
        from alpha_decay_gate import AlphaDecayGate  # noqa: F401

    def test_no_decay_at_day_zero(self):
        """RED: days=0 → confidence 不变。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.compute_decayed_confidence(0.8, 0) == pytest.approx(0.8)

    def test_one_half_life_halves(self):
        """RED: days == half_life → confidence 减半。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.compute_decayed_confidence(0.8, 30) == pytest.approx(0.4)

    def test_two_half_lives_quarters(self):
        """RED: days == 2*half_life → confidence 1/4。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.compute_decayed_confidence(0.8, 60) == pytest.approx(0.2)

    def test_decay_failopen_none(self):
        """RED: None/负数输入 → FAIL-OPEN 返回原始 confidence（不阻塞）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.compute_decayed_confidence(None, 30) == 0.0
        # 负天数视为 0（未来验证不算衰减）
        assert gate.compute_decayed_confidence(0.8, -5) == pytest.approx(0.8)
        # 无效 confidence 字符串 → 0.0
        assert gate.compute_decayed_confidence("high", 30) == 0.0


class TestGateActionDecision:
    """门禁决策。"""

    def test_high_confidence_ok(self):
        """RED: 衰减后 >= 0.5 → ok（保持 active）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.decide_gate_action(0.6) == "ok"

    def test_mid_confidence_reverify(self):
        """RED: 衰减后 0.25-0.5 → re-verify（触发重新验证）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.decide_gate_action(0.3) == "re-verify"

    def test_low_confidence_deactivate(self):
        """RED: 衰减后 < 0.25 → deactivate（降级下线）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.decide_gate_action(0.1) == "deactivate"

    def test_boundary_half_is_reverify(self):
        """RED: 边界值 0.5 → ok；0.25 → re-verify（下界含）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.decide_gate_action(0.5) == "ok"
        assert gate.decide_gate_action(0.25) == "re-verify"

    def test_decision_failopen_none(self):
        """RED: None → FAIL-OPEN 返回 ok（不阻塞主流程）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.decide_gate_action(None) == "ok"


class TestBatchScan:
    """批量扫描（自动门禁）。"""

    def test_scan_returns_actions_per_entry(self):
        """RED: scan() 对每项输出 action + decayed_confidence。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        entries = [
            {"skill_id": "fresh-skill", "confidence": 0.9, "days_since_verify": 5},
            {"skill_id": "stale-skill", "confidence": 0.8, "days_since_verify": 60},
            {"skill_id": "dead-skill", "confidence": 0.6, "days_since_verify": 150},
        ]
        results = gate.scan(entries)

        assert len(results) == 3
        by_id = {r["skill_id"]: r for r in results}
        assert by_id["fresh-skill"]["action"] == "ok"
        assert by_id["stale-skill"]["action"] in ("re-verify", "deactivate")
        assert by_id["dead-skill"]["action"] == "deactivate"

    def test_scan_get_actionable_only(self):
        """RED: get_actionable() 过滤出需要行动的条目（非 ok）。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        entries = [
            {"skill_id": "fresh", "confidence": 0.9, "days_since_verify": 1},
            {"skill_id": "stale", "confidence": 0.8, "days_since_verify": 45},
        ]
        actionable = gate.get_actionable(entries)
        assert len(actionable) == 1
        assert actionable[0]["skill_id"] == "stale"

    def test_scan_failopen_invalid_entries(self):
        """RED: 无效条目 → FAIL-OPEN 跳过或标 ok，不抛异常。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        entries = [
            None,  # 无效条目
            {"confidence": 0.9, "days_since_verify": 1},  # 缺 skill_id
            {"skill_id": "ok-entry", "confidence": 0.9, "days_since_verify": 1},
        ]
        results = gate.scan(entries)  # 不应抛异常
        assert isinstance(results, list)

    def test_scan_empty(self):
        """RED: 空列表 → 空结果。"""
        from alpha_decay_gate import AlphaDecayGate

        gate = AlphaDecayGate(half_life_days=30)
        assert gate.scan([]) == []


class TestCognitiveLoopEntryIntegration:
    """CognitiveLoopEntry P3-5 集成点。"""

    def test_alpha_decay_gate_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 alpha_decay_gate 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "alpha_decay_gate" in src
        assert "AlphaDecayGate" in src
