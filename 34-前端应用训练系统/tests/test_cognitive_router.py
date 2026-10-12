"""P5: 匹配度+案例密度路由测试。

测试 cognitive_router 模块将 recall 结果路由到不同 Tier。
RED 阶段：assert ModuleNotFoundError
GREEN 阶段：实现 cognitive_router.py 使测试通过
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_memory(score=0.5, content="test"):
    """构造 mock memory 对象"""
    return SimpleNamespace(score=score, content=content)


# ============================================================
# 1. 模块导入测试
# ============================================================

class TestModuleImport:
    def test_import_evaluate_match(self):
        from core.cognitive_router import evaluate_match
        assert callable(evaluate_match)

    def test_import_route(self):
        from core.cognitive_router import route
        assert callable(route)

    def test_import_route_result(self):
        from core.cognitive_router import RouteResult
        r = RouteResult(tier="TIER1", description="test")
        assert hasattr(r, "tier")

    def test_import_constants(self):
        from core.cognitive_router import (
            TIER1_MATCH_THRESHOLD, TIER1_DENSITY_THRESHOLD,
            TIER3_MATCH_THRESHOLD, TIER3_DENSITY_THRESHOLD,
        )
        assert TIER1_MATCH_THRESHOLD == 0.7
        assert TIER1_DENSITY_THRESHOLD == 3
        assert TIER3_MATCH_THRESHOLD == 0.4
        assert TIER3_DENSITY_THRESHOLD == 2


# ============================================================
# 2. evaluate_match 测试
# ============================================================

class TestEvaluateMatch:
    """匹配度评估函数"""

    def test_empty_memories_returns_zero(self):
        from core.cognitive_router import evaluate_match
        match_score, density = evaluate_match([])
        assert match_score == 0.0
        assert density == 0

    def test_none_memories_returns_zero(self):
        from core.cognitive_router import evaluate_match
        match_score, density = evaluate_match(None)
        assert match_score == 0.0
        assert density == 0

    def test_single_high_score_memory(self):
        from core.cognitive_router import evaluate_match
        memories = [_make_memory(score=0.9)]
        match_score, density = evaluate_match(memories)
        assert abs(match_score - 0.9) < 0.001
        assert density == 1

    def test_multiple_memories_weighted(self):
        """max*0.6 + avg*0.4 加权"""
        from core.cognitive_router import evaluate_match
        memories = [_make_memory(score=0.8), _make_memory(score=0.6)]
        match_score, density = evaluate_match(memories)
        # max=0.8, avg=(0.8+0.6)/2=0.7
        # match_score = 0.8*0.6 + 0.7*0.4 = 0.48 + 0.28 = 0.76
        assert abs(match_score - 0.76) < 0.001
        assert density == 2

    def test_dict_memories_with_score_key(self):
        """支持 dict 格式（score 键）"""
        from core.cognitive_router import evaluate_match
        memories = [{"score": 0.8}, {"score": 0.6}]
        match_score, density = evaluate_match(memories)
        assert abs(match_score - 0.76) < 0.001
        assert density == 2


# ============================================================
# 3. route — Tier 1 测试（高匹配+高密度）
# ============================================================

class TestRouteTier1:
    """Tier 1: match_score >= 0.7 AND case_density >= 3 → 直接推进"""

    def test_high_match_high_density_tier1(self):
        from core.cognitive_router import route, TIER1
        result = route(match_score=0.8, case_density=5)
        assert result.tier == TIER1

    def test_boundary_tier1(self):
        """match_score=0.7 + density=3 刚好满足 Tier 1"""
        from core.cognitive_router import route, TIER1
        result = route(match_score=0.7, case_density=3)
        assert result.tier == TIER1

    def test_tier1_is_fast_path(self):
        from core.cognitive_router import route, TIER1
        result = route(match_score=0.9, case_density=10)
        assert result.tier == TIER1
        assert "fast" in result.description.lower() or "直接" in result.description


# ============================================================
# 4. route — Tier 2 测试（低匹配+有密度）
# ============================================================

class TestRouteTier2:
    """Tier 2: match_score < 0.7 AND case_density >= 2 → 33-REA 反思"""

    def test_low_match_with_density_tier2(self):
        from core.cognitive_router import route, TIER2
        result = route(match_score=0.5, case_density=3)
        assert result.tier == TIER2

    def test_tier2_is_33rea(self):
        from core.cognitive_router import route, TIER2
        result = route(match_score=0.5, case_density=4)
        assert result.tier == TIER2
        assert "33" in result.description or "REA" in result.description or "反思" in result.description


# ============================================================
# 5. route — Tier 3 测试（低匹配+低密度）
# ============================================================

class TestRouteTier3:
    """Tier 3: match_score < 0.4 AND case_density < 2 → SKILL 调研"""

    def test_low_match_low_density_tier3(self):
        from core.cognitive_router import route, TIER3
        result = route(match_score=0.3, case_density=1)
        assert result.tier == TIER3

    def test_zero_match_zero_density_tier3(self):
        from core.cognitive_router import route, TIER3
        result = route(match_score=0.0, case_density=0)
        assert result.tier == TIER3

    def test_tier3_is_skill_research(self):
        from core.cognitive_router import route, TIER3
        result = route(match_score=0.2, case_density=0)
        assert result.tier == TIER3
        assert "调研" in result.description or "SKILL" in result.description or "research" in result.description.lower()


# ============================================================
# 6. route — Tier 4 测试（多路径）
# ============================================================

class TestRouteTier4:
    """Tier 4: multi_path=True → L4 Debate 选择"""

    def test_multi_path_tier4(self):
        from core.cognitive_router import route, TIER4
        result = route(match_score=0.5, case_density=3, multi_path=True)
        assert result.tier == TIER4

    def test_tier4_is_debate(self):
        from core.cognitive_router import route, TIER4
        result = route(match_score=0.8, case_density=5, multi_path=True)
        assert result.tier == TIER4
        assert "Debate" in result.description or "辩论" in result.description

    def test_multi_path_overrides_tier1(self):
        """多路径优先级最高，覆盖 Tier 1"""
        from core.cognitive_router import route, TIER4
        result = route(match_score=0.9, case_density=10, multi_path=True)
        assert result.tier == TIER4


# ============================================================
# 7. route — 边界和默认
# ============================================================

class TestRouteEdgeCases:
    """边界情况和默认路由"""

    def test_high_match_low_density_tier2(self):
        """match_score >= 0.7 但 density < 3 → 不是 Tier 1"""
        from core.cognitive_router import route, TIER1, TIER2
        result = route(match_score=0.8, case_density=2)
        assert result.tier != TIER1  # 密度不够
        # 应该是 Tier 2（有 2 个案例）
        assert result.tier == TIER2

    def test_medium_match_low_density_tier3(self):
        """match_score 0.4-0.7 + density < 2 → Tier 3（案例太少）"""
        from core.cognitive_router import route, TIER3
        result = route(match_score=0.5, case_density=1)
        # 0.5 不 < 0.4，但 density=1 < 2 → 不满足 Tier 3 的 match 条件
        # 应该是 Tier 2（match < 0.7 且 density >= 1 不满足 Tier 2 的 >= 2... 嗯）
        # 实际上这个情况是边界：match 0.4-0.7, density < 2
        # SPEC 的路由表没有明确覆盖这个区间，应该是 Tier 2 或 Tier 3
        # 按优先级：不满足 Tier 1(0.7+3), 不满足 Tier 3(0.4+2),
        # 所以应该是 Tier 2（安全默认）
        assert result.tier in ["TIER2", "TIER3", "TIER_2", "TIER_3"]


# ============================================================
# 8. FAIL-OPEN 测试
# ============================================================

class TestFailOpen:
    def test_zero_zero_returns_tier3(self):
        """match_score=0 + density=0 → Tier 3（需要调研）"""
        from core.cognitive_router import route, TIER3
        result = route(match_score=0.0, case_density=0)
        assert result.tier == TIER3

    def test_negative_score_treated_as_zero(self):
        from core.cognitive_router import route, TIER3
        result = route(match_score=-0.1, case_density=0)
        assert result.tier == TIER3


# ============================================================
# 9. 集成测试
# ============================================================

class TestIntegration:
    """evaluate_match → route 集成"""

    def test_evaluate_then_route_high_match(self):
        from core.cognitive_router import evaluate_match, route, TIER1
        memories = [_make_memory(score=0.9) for _ in range(5)]
        match_score, density = evaluate_match(memories)
        result = route(match_score, density)
        assert result.tier == TIER1

    def test_evaluate_then_route_low_match(self):
        from core.cognitive_router import evaluate_match, route, TIER2
        memories = [_make_memory(score=0.3) for _ in range(3)]
        match_score, density = evaluate_match(memories)
        result = route(match_score, density)
        assert result.tier == TIER2

    def test_evaluate_then_route_no_memories(self):
        from core.cognitive_router import evaluate_match, route, TIER3
        match_score, density = evaluate_match([])
        result = route(match_score, density)
        assert result.tier == TIER3
