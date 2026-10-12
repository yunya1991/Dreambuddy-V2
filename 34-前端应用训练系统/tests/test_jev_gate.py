"""P7: L4 jev 全局裁决测试。

测试 jev_gate 模块的纯规则零 token 裁决 + 防震荡机制。
RED 阶段：assert ModuleNotFoundError / ImportError
GREEN 阶段：实现 jev_gate.py 使测试通过
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# 1. 模块导入测试 (RED: ModuleNotFoundError)
# ============================================================

class TestModuleImport:
    """验证 jev_gate 模块可导入"""

    def test_import_jev_gate(self):
        from core.jev_gate import jev_gate
        assert callable(jev_gate)

    def test_import_jev_anti_oscillation(self):
        from core.jev_gate import JevAntiOscillation
        assert JevAntiOscillation is not None

    def test_module_constants(self):
        from core.jev_gate import (
            MAX_CONSECUTIVE_OVERRIDE,
            DEGRADATION_THRESHOLD,
            RECOVERY_COUNT,
        )
        assert MAX_CONSECUTIVE_OVERRIDE == 2
        assert DEGRADATION_THRESHOLD == 3
        assert RECOVERY_COUNT == 5

    def test_fast_path_constants(self):
        from core.jev_gate import FAST_PATH_MATCH, FAST_PATH_DENSITY
        assert FAST_PATH_MATCH == 0.8
        assert FAST_PATH_DENSITY == 5


# ============================================================
# 2. jev_gate — Fast-path 跳过
# ============================================================

class TestJevGateFastPath:
    """高可信度场景跳过 jev 裁决"""

    def test_fast_path_skip_high_match_high_density(self):
        """match_score >= 0.8 且 case_density >= 5 → 返回原始决策"""
        from core.jev_gate import jev_gate, CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.85,
            case_density=6,
            rea_confidence=0.5,
            debate_result=None,
        )
        assert result == CONTINUE

    def test_fast_path_boundary_match(self):
        """match_score == 0.8 边界值 → 跳过"""
        from core.jev_gate import jev_gate, CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.8,
            case_density=5,
            rea_confidence=0.1,
            debate_result=None,
        )
        assert result == CONTINUE

    def test_fast_path_not_triggered_low_density(self):
        """match_score 高但 density < 5 → 不跳过，进入裁决"""
        from core.jev_gate import jev_gate, CONTINUE, REDO
        # match_score=0.85, density=3 → 不跳过
        # rea_confidence=0.1 → prediction_error=0.75 > 0.3 → REDO
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.85,
            case_density=3,
            rea_confidence=0.1,
            debate_result=None,
        )
        assert result == REDO

    def test_fast_path_not_triggered_low_match(self):
        """match_score < 0.8 → 不跳过"""
        from core.jev_gate import jev_gate, CONTINUE
        # match_score=0.7, density=10 → 不跳过
        # rea_confidence=0.7 → prediction_error=0 → CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.7,
            case_density=10,
            rea_confidence=0.7,
            debate_result=None,
        )
        assert result == CONTINUE


# ============================================================
# 3. jev_gate — 预测误差门控
# ============================================================

class TestJevGatePredictionError:
    """预测误差 > 0.3 且 CONTINUE → REDO"""

    def test_high_prediction_error_continue_to_redo(self):
        from core.jev_gate import jev_gate, CONTINUE, REDO
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.8,
            case_density=3,
            rea_confidence=0.4,  # error = |0.8 - 0.4| = 0.4 > 0.3
            debate_result=None,
        )
        assert result == REDO

    def test_prediction_error_boundary(self):
        """prediction_error == 0.3 边界 → 不降级（> 0.3 才降级）"""
        from core.jev_gate import jev_gate, CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.6,
            case_density=3,
            rea_confidence=0.3,  # error = 0.3, not > 0.3
            debate_result=None,
        )
        assert result == CONTINUE

    def test_prediction_error_uses_debate_fallback(self):
        """rea_confidence=0 时使用 debate_result 的 bull_confidence"""
        from core.jev_gate import jev_gate, CONTINUE, REDO
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.8,
            case_density=3,
            rea_confidence=0.0,  # falsy → fallback to debate
            debate_result={"bull_confidence": 0.4},  # error = |0.8 - 0.4| = 0.4 > 0.3
        )
        assert result == REDO

    def test_prediction_error_no_debate_no_rea(self):
        """rea_confidence=0 且无 debate → actual=0.5"""
        from core.jev_gate import jev_gate, CONTINUE, REDO
        # match_score=0.85, actual=0.5 → error=0.35 > 0.3 → REDO
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.85,
            case_density=3,
            rea_confidence=0.0,
            debate_result=None,
        )
        assert result == REDO


# ============================================================
# 4. jev_gate — Believability-weighted
# ============================================================

class TestJevGateBelievability:
    """believability = case_density * match_score < 0.5 且 CONTINUE → INSERT_BEFORE"""

    def test_low_believability_continue_to_insert_before(self):
        from core.jev_gate import jev_gate, CONTINUE, INSERT_BEFORE
        # match_score=0.4, density=1 → believability=0.4 < 0.5
        # rea_confidence=0.4 → prediction_error=0 → not > 0.3
        # → believability check: 0.4 < 0.5 → INSERT_BEFORE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.4,
            case_density=1,
            rea_confidence=0.4,
            debate_result=None,
        )
        assert result == INSERT_BEFORE

    def test_believability_boundary(self):
        """believability == 0.5 边界 → 不降级（< 0.5 才降级）"""
        from core.jev_gate import jev_gate, CONTINUE
        # match_score=0.5, density=1 → believability=0.5, not < 0.5
        # rea_confidence=0.5 → error=0 → CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.5,
            case_density=1,
            rea_confidence=0.5,
            debate_result=None,
        )
        assert result == CONTINUE


# ============================================================
# 5. jev_gate — HOT Self-Model
# ============================================================

class TestJevGateHOT:
    """REDO/EARLY_TERMINATE + 有足够案例支撑 → CONTINUE"""

    def test_hot_redo_to_continue(self):
        from core.jev_gate import jev_gate, CONTINUE, REDO
        # decision=REDO, density=3, match=0.6 → HOT → CONTINUE
        result = jev_gate(
            decision=REDO,
            match_score=0.6,
            case_density=3,
            rea_confidence=0.6,
            debate_result=None,
        )
        assert result == CONTINUE

    def test_hot_early_terminate_to_continue(self):
        from core.jev_gate import jev_gate, CONTINUE, EARLY_TERMINATE
        result = jev_gate(
            decision=EARLY_TERMINATE,
            match_score=0.7,
            case_density=4,
            rea_confidence=0.7,
            debate_result=None,
        )
        assert result == CONTINUE

    def test_hot_not_triggered_low_density(self):
        """density < 3 → HOT 不触发"""
        from core.jev_gate import jev_gate, REDO
        result = jev_gate(
            decision=REDO,
            match_score=0.8,
            case_density=2,
            rea_confidence=0.8,
            debate_result=None,
        )
        assert result == REDO

    def test_hot_not_triggered_low_match(self):
        """match_score < 0.6 → HOT 不触发"""
        from core.jev_gate import jev_gate, REDO
        result = jev_gate(
            decision=REDO,
            match_score=0.5,
            case_density=5,
            rea_confidence=0.5,
            debate_result=None,
        )
        assert result == REDO

    def test_hot_not_triggered_for_continue(self):
        """HOT 仅对 REDO/EARLY_TERMINATE 生效，不对 CONTINUE"""
        from core.jev_gate import jev_gate, CONTINUE
        # CONTINUE + density=3 + match=0.6 → HOT 不适用
        # rea_confidence=0.6 → error=0 → CONTINUE
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.6,
            case_density=3,
            rea_confidence=0.6,
            debate_result=None,
        )
        assert result == CONTINUE


# ============================================================
# 6. jev_gate — 无信号返回原始
# ============================================================

class TestJevGateNoSignal:
    """无触发条件 → 返回原始决策"""

    def test_no_signal_returns_original(self):
        from core.jev_gate import jev_gate, CONTINUE
        # match=0.6, density=3, rea_conf=0.6
        # error=0 → not > 0.3
        # believability=1.8 → not < 0.5
        # decision=CONTINUE → not REDO/EARLY_TERMINATE → HOT 不适用
        result = jev_gate(
            decision=CONTINUE,
            match_score=0.6,
            case_density=3,
            rea_confidence=0.6,
            debate_result=None,
        )
        assert result == CONTINUE

    def test_jumo_to_unchanged(self):
        from core.jev_gate import jev_gate, JUMP_TO
        result = jev_gate(
            decision=JUMP_TO,
            match_score=0.5,
            case_density=2,
            rea_confidence=0.5,
            debate_result=None,
        )
        assert result == JUMP_TO


# ============================================================
# 7. JevAntiOscillation — 防震荡机制
# ============================================================

class TestJevAntiOscillation:
    """防震荡三重机制测试"""

    def test_no_override_returns_jev_decision(self):
        """未改写 → 返回 jev_decision，重置计数"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        result = ao.check_oscillation("CONTINUE", "CONTINUE")
        assert result == "CONTINUE"
        assert ao._consecutive_overrides == 0

    def test_first_override_returns_jev(self):
        """第 1 次改写 → 返回 jev_decision"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        result = ao.check_oscillation("CONTINUE", "REDO")
        assert result == "REDO"
        assert ao._consecutive_overrides == 1

    def test_second_override_returns_jev(self):
        """第 2 次改写 → 返回 jev_decision（未超上限）"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        ao.check_oscillation("CONTINUE", "REDO")  # 1st
        result = ao.check_oscillation("CONTINUE", "REDO")  # 2nd
        assert result == "REDO"
        assert ao._consecutive_overrides == 2

    def test_third_override_returns_original_and_degrades(self):
        """第 3 次改写 → 返回 original_decision + jev 降级"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        ao.check_oscillation("CONTINUE", "REDO")  # 1st
        ao.check_oscillation("CONTINUE", "REDO")  # 2nd
        result = ao.check_oscillation("CONTINUE", "REDO")  # 3rd
        assert result == "CONTINUE"  # 信任原始
        assert ao._jev_degraded is True
        assert ao._degradation_count == 5

    def test_degraded_always_returns_original(self):
        """降级期间始终返回原始决策"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        # 触发降级
        for _ in range(3):
            ao.check_oscillation("CONTINUE", "REDO")
        assert ao._jev_degraded is True
        # 降级期间 jev 改写 → 仍返回原始
        result = ao.check_oscillation("CONTINUE", "REDO")
        assert result == "CONTINUE"

    def test_recovery_after_non_overrides(self):
        """降级后需 RECOVERY_COUNT 次未改写才能恢复"""
        from core.jev_gate import JevAntiOscillation, RECOVERY_COUNT
        ao = JevAntiOscillation()
        # 触发降级
        for _ in range(3):
            ao.check_oscillation("CONTINUE", "REDO")
        assert ao._jev_degraded is True

        # RECOVERY_COUNT - 1 次未改写 → 仍未恢复
        for _ in range(RECOVERY_COUNT - 1):
            ao.check_oscillation("CONTINUE", "CONTINUE")
        assert ao._jev_degraded is True

        # 第 RECOVERY_COUNT 次未改写 → 恢复
        ao.check_oscillation("CONTINUE", "CONTINUE")
        assert ao._jev_degraded is False
        assert ao._consecutive_overrides == 0

    def test_non_override_resets_consecutive_count(self):
        """未改写 → 重置连续改写计数"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        ao.check_oscillation("CONTINUE", "REDO")  # 1
        ao.check_oscillation("CONTINUE", "REDO")  # 2
        assert ao._consecutive_overrides == 2
        # 未改写 → 重置
        ao.check_oscillation("CONTINUE", "CONTINUE")
        assert ao._consecutive_overrides == 0

    def test_override_history_tracked(self):
        """改写历史被追踪"""
        from core.jev_gate import JevAntiOscillation
        ao = JevAntiOscillation()
        ao.check_oscillation("CONTINUE", "REDO")
        assert len(ao._override_history) == 1
        assert ao._override_history[0] == ("CONTINUE", "REDO")

    def test_recovery_then_override_works(self):
        """恢复后改写重新计数"""
        from core.jev_gate import JevAntiOscillation, RECOVERY_COUNT
        ao = JevAntiOscillation()
        # 触发降级
        for _ in range(3):
            ao.check_oscillation("CONTINUE", "REDO")
        # 恢复
        for _ in range(RECOVERY_COUNT):
            ao.check_oscillation("CONTINUE", "CONTINUE")
        assert ao._jev_degraded is False
        # 新的改写
        result = ao.check_oscillation("CONTINUE", "REDO")
        assert result == "REDO"  # 正常改写
        assert ao._consecutive_overrides == 1


# ============================================================
# 8. 集成 — jev_gate + JevAntiOscillation
# ============================================================

class TestIntegration:
    """jev_gate + JevAntiOscillation 集成测试"""

    def test_gate_then_anti_oscillation(self):
        """先 jev_gate 裁决，再防震荡"""
        from core.jev_gate import jev_gate, JevAntiOscillation, CONTINUE, REDO
        ao = JevAntiOscillation()
        # jev 改写 CONTINUE → REDO
        jev_decision = jev_gate(
            decision=CONTINUE,
            match_score=0.8,
            case_density=3,
            rea_confidence=0.4,
            debate_result=None,
        )
        assert jev_decision == REDO
        # 防震荡
        final = ao.check_oscillation(CONTINUE, jev_decision)
        assert final == REDO  # 第 1 次改写，允许

    def test_repeated_gate_overrides_trigger_anti_oscillation(self):
        """重复 jev 改写触发防震荡 → 信任原始"""
        from core.jev_gate import jev_gate, JevAntiOscillation, CONTINUE, REDO
        ao = JevAntiOscillation()
        # 连续 3 次 jev 改写 CONTINUE → REDO
        for _ in range(3):
            jev_decision = jev_gate(
                decision=CONTINUE,
                match_score=0.8,
                case_density=3,
                rea_confidence=0.4,
                debate_result=None,
            )
            final = ao.check_oscillation(CONTINUE, jev_decision)
        # 第 3 次 → 信任原始
        assert final == CONTINUE
