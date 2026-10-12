"""P1 修复: outcome + prompt_pattern 派生器测试

RED 阶段：assert ModuleNotFoundError
GREEN 阶段：实现 outcome_pattern_deriver.py 使测试通过

修复目标:
  1. outcome 信号: 从 quality/confidence 派生 (S/A→success, B→partial, C/D→failure)
  2. prompt_pattern 归一化: 用 intent 或前 N 字符替代完整唯一内容，使模板可聚类
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_case(quality="C", confidence=0.3, outcome_text="", intent="",
               metadata=None, learned=None):
    """构造 mock TrainingCase"""
    return type("C", (), {
        "intent": intent,
        "actions": [],
        "outcome_text": outcome_text,
        "learned": learned or [],
        "layer_tags": [],
        "quality": quality,
        "confidence": confidence,
        "source": "test",
        "metadata": metadata or {},
    })()


# ============================================================
# 1. 模块导入 (RED)
# ============================================================

class TestModuleImport:
    def test_import_deriver(self):
        from core.outcome_pattern_deriver import derive_outcome
        assert callable(derive_outcome)

    def test_import_pattern(self):
        from core.outcome_pattern_deriver import normalize_prompt_pattern
        assert callable(normalize_prompt_pattern)

    def test_import_combined(self):
        from core.outcome_pattern_deriver import derive_outcome_and_pattern
        assert callable(derive_outcome_and_pattern)


# ============================================================
# 2. outcome 派生 — quality 映射
# ============================================================

class TestOutcomeFromQuality:
    """从 quality 派生 outcome (核心修复: success 信号)"""

    def test_s_quality_success(self):
        """quality=S → success"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="S", confidence=0.9)
        assert derive_outcome(case) == "success"

    def test_a_quality_success(self):
        """quality=A → success"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="A", confidence=0.7)
        assert derive_outcome(case) == "success"

    def test_b_quality_partial(self):
        """quality=B → partial"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="B", confidence=0.5)
        assert derive_outcome(case) == "partial"

    def test_c_quality_failure(self):
        """quality=C → failure"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="C", confidence=0.2)
        assert derive_outcome(case) == "failure"

    def test_d_quality_failure(self):
        """quality=D → failure"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="D", confidence=0.1)
        assert derive_outcome(case) == "failure"

    def test_explicit_outcome_overrides_quality(self):
        """metadata.outcome 显式设置时优先使用"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="C", confidence=0.2,
                          metadata={"outcome": "success"})
        assert derive_outcome(case) == "success"


# ============================================================
# 3. outcome 派生 — confidence 兜底
# ============================================================

class TestOutcomeFromConfidence:
    """无 quality 时从 confidence 派生"""

    def test_high_confidence_success(self):
        """confidence >= 0.7 → success"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="", confidence=0.8)
        assert derive_outcome(case) == "success"

    def test_mid_confidence_partial(self):
        """0.4 <= confidence < 0.7 → partial"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="", confidence=0.5)
        assert derive_outcome(case) == "partial"

    def test_low_confidence_failure(self):
        """confidence < 0.4 → failure"""
        from core.outcome_pattern_deriver import derive_outcome
        case = _make_case(quality="", confidence=0.2)
        assert derive_outcome(case) == "failure"


# ============================================================
# 4. prompt_pattern 归一化
# ============================================================

class TestPromptPatternNormalization:
    """归一化 prompt_pattern 使模板可聚类 (核心修复: 避免唯一内容)"""

    def test_uses_intent_when_available(self):
        """有 intent 时用 intent 作为 pattern 键"""
        from core.outcome_pattern_deriver import normalize_prompt_pattern
        case = _make_case(intent="查询BTC价格", outcome_text="完整的执行结果内容...")
        pattern = normalize_prompt_pattern(case)
        assert pattern == "查询BTC价格"

    def test_fallback_to_outcome_text_prefix(self):
        """无 intent 时用 outcome_text 前 N 字符"""
        from core.outcome_pattern_deriver import normalize_prompt_pattern
        long_text = "这是一段很长的执行结果描述，包含很多细节信息"
        case = _make_case(intent="", outcome_text=long_text)
        pattern = normalize_prompt_pattern(case)
        assert len(pattern) <= 80
        assert pattern == long_text[:80]

    def test_empty_fallback(self):
        """intent 和 outcome_text 都空 → 返回默认 pattern"""
        from core.outcome_pattern_deriver import normalize_prompt_pattern
        case = _make_case(intent="", outcome_text="")
        pattern = normalize_prompt_pattern(case)
        assert pattern == "unknown_pattern"

    def test_similar_cases_share_pattern(self):
        """相似 case (同 intent) 共享 pattern → 模板可聚类"""
        from core.outcome_pattern_deriver import normalize_prompt_pattern
        case1 = _make_case(intent="查询BTC价格", outcome_text="结果A")
        case2 = _make_case(intent="查询BTC价格", outcome_text="结果B不同")
        assert normalize_prompt_pattern(case1) == normalize_prompt_pattern(case2)


# ============================================================
# 5. 组合派生
# ============================================================

class TestDeriveCombined:
    """derive_outcome_and_pattern 一次性返回 (outcome, pattern)"""

    def test_combined_success(self):
        """S级 + intent → success + intent pattern"""
        from core.outcome_pattern_deriver import derive_outcome_and_pattern
        case = _make_case(quality="S", confidence=0.9,
                          intent="部署策略", outcome_text="完整结果")
        outcome, pattern = derive_outcome_and_pattern(case)
        assert outcome == "success"
        assert pattern == "部署策略"

    def test_combined_failure(self):
        """C级 → failure"""
        from core.outcome_pattern_deriver import derive_outcome_and_pattern
        case = _make_case(quality="C", confidence=0.2, intent="测试")
        outcome, pattern = derive_outcome_and_pattern(case)
        assert outcome == "failure"

    def test_combined_has_success_signal(self):
        """至少有一个场景产出 success (回归 success_count=0 的 bug)"""
        from core.outcome_pattern_deriver import derive_outcome_and_pattern
        cases = [
            _make_case(quality="S", intent="A"),
            _make_case(quality="A", confidence=0.8, intent="B"),
            _make_case(quality="B", intent="C"),
            _make_case(quality="C", intent="D"),
        ]
        outcomes = [derive_outcome_and_pattern(c)[0] for c in cases]
        assert "success" in outcomes  # 必须有 success 信号
        assert len(set(outcomes)) >= 2  # 多样化
