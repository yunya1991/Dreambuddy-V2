"""P6: LLM+SKILL 调研层测试。

测试 skill_research_layer 模块在 Tier 3（案例少+低匹配）场景下的调研链路。
RED 阶段：assert ModuleNotFoundError
GREEN 阶段：实现 skill_research_layer.py 使测试通过
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# 1. 模块导入测试
# ============================================================

class TestModuleImport:
    def test_import_should_research(self):
        from core.skill_research_layer import should_research
        assert callable(should_research)

    def test_import_search_knowledge_base(self):
        from core.skill_research_layer import search_knowledge_base
        assert callable(search_knowledge_base)

    def test_import_invoke_skill_research(self):
        from core.skill_research_layer import invoke_skill_research
        assert callable(invoke_skill_research)

    def test_import_research_and_analyze(self):
        from core.skill_research_layer import research_and_analyze
        assert callable(research_and_analyze)

    def test_import_constants(self):
        from core.skill_research_layer import (
            SKILL_TECHNICAL, SKILL_SCIENTIFIC, SKILL_ARCHITECTURE,
            KB_INSUFFICIENT_THRESHOLD,
        )
        assert SKILL_TECHNICAL == "dream-research-workflow"
        assert SKILL_SCIENTIFIC == "dream-science-orchestrator"
        assert SKILL_ARCHITECTURE == "dream-arch-research-orchestrator"
        assert isinstance(KB_INSUFFICIENT_THRESHOLD, int)


# ============================================================
# 2. should_research — Tier 3 触发判断
# ============================================================

class TestShouldResearch:
    """Tier 3 (match_score < 0.4 AND case_density < 2) 触发调研"""

    def test_tier3_triggers_research(self):
        from core.skill_research_layer import should_research
        assert should_research(match_score=0.3, case_density=1) is True

    def test_tier3_boundary_match(self):
        """match_score = 0.4 不触发（< 0.4 才触发）"""
        from core.skill_research_layer import should_research
        assert should_research(match_score=0.4, case_density=1) is False

    def test_tier3_boundary_density(self):
        """case_density = 2 不触发（< 2 才触发）"""
        from core.skill_research_layer import should_research
        assert should_research(match_score=0.3, case_density=2) is False

    def test_high_match_no_research(self):
        from core.skill_research_layer import should_research
        assert should_research(match_score=0.8, case_density=5) is False

    def test_zero_zero_triggers(self):
        from core.skill_research_layer import should_research
        assert should_research(match_score=0.0, case_density=0) is True


# ============================================================
# 3. search_knowledge_base — 知识库检索（零 token）
# ============================================================

class TestSearchKnowledgeBase:
    """Agentic RAG: 先检索知识库，零 token"""

    def test_returns_results_list(self):
        from core.skill_research_layer import search_knowledge_base
        results = search_knowledge_base("test query", mock_mode=True)
        assert isinstance(results, list)

    def test_empty_query_returns_empty(self):
        from core.skill_research_layer import search_knowledge_base
        results = search_knowledge_base("", mock_mode=True)
        assert results == []

    def test_fail_open_on_error(self):
        """知识库检索失败 → 返回空列表（FAIL-OPEN）"""
        from core.skill_research_layer import search_knowledge_base
        results = search_knowledge_base("test", mock_mode=True, force_error=True)
        assert results == []


# ============================================================
# 4. invoke_skill_research — LLM+SKILL 调研
# ============================================================

class TestInvokeSkillResearch:
    """LLM+SKILL 调研，FAIL-OPEN"""

    def test_technical_skill_routing(self):
        """技术场景 → dream-research-workflow"""
        from core.skill_research_layer import invoke_skill_research, SKILL_TECHNICAL
        result = invoke_skill_research("技术问题", skill_type="technical", mock_mode=True)
        assert result["skill"] == SKILL_TECHNICAL

    def test_scientific_skill_routing(self):
        from core.skill_research_layer import invoke_skill_research, SKILL_SCIENTIFIC
        result = invoke_skill_research("科研问题", skill_type="scientific", mock_mode=True)
        assert result["skill"] == SKILL_SCIENTIFIC

    def test_architecture_skill_routing(self):
        from core.skill_research_layer import invoke_skill_research, SKILL_ARCHITECTURE
        result = invoke_skill_research("架构问题", skill_type="architecture", mock_mode=True)
        assert result["skill"] == SKILL_ARCHITECTURE

    def test_default_skill_routing(self):
        """默认 → technical"""
        from core.skill_research_layer import invoke_skill_research, SKILL_TECHNICAL
        result = invoke_skill_research("unknown", skill_type="unknown", mock_mode=True)
        assert result["skill"] == SKILL_TECHNICAL

    def test_fail_open_on_error(self):
        """SKILL 调研失败 → 返回空结果（FAIL-OPEN）"""
        from core.skill_research_layer import invoke_skill_research
        result = invoke_skill_research("test", mock_mode=True, force_error=True)
        assert result["report"] == ""
        assert result["fail_open"] is True


# ============================================================
# 5. research_and_analyze — 完整调研链路
# ============================================================

class TestResearchAndAnalyze:
    """完整链路: should_research → KB search → SKILL research → 33-REA 分析"""

    def test_kb_sufficient_skips_llm(self):
        """知识库检索结果充足 → 不调用 LLM"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.3, case_density=1,
            query="test query",
            mock_mode=True,
            mock_kb_results=[
                {"content": "result 1", "score": 0.9},
                {"content": "result 2", "score": 0.85},
                {"content": "result 3", "score": 0.8},
            ],
        )
        assert result["kb_searched"] is True
        assert result["llm_invoked"] is False
        assert len(result["knowledge"]) >= 3

    def test_kb_insufficient_invokes_llm(self):
        """知识库检索结果不足 → 调用 LLM+SKILL"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.3, case_density=1,
            query="test query",
            mock_mode=True,
            mock_kb_results=[{"content": "insufficient", "score": 0.2}],
        )
        assert result["kb_searched"] is True
        assert result["llm_invoked"] is True

    def test_no_research_needed_returns_empty(self):
        """非 Tier 3 场景 → 不调研"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.8, case_density=5,
            query="test query",
            mock_mode=True,
        )
        assert result["research_needed"] is False

    def test_multi_path_detection(self):
        """调研后发现多路径 → multi_path=True"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.2, case_density=0,
            query="complex problem",
            mock_mode=True,
            mock_kb_results=[],
            mock_skill_report="路径A: ... 路径B: ...",
        )
        assert result.get("multi_path") is True

    def test_single_path_no_debate(self):
        """调研后单路径 → multi_path=False"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.2, case_density=0,
            query="simple problem",
            mock_mode=True,
            mock_kb_results=[],
            mock_skill_report="唯一路径: ...",
        )
        assert result.get("multi_path") is False


# ============================================================
# 6. FAIL-OPEN 测试
# ============================================================

class TestFailOpen:
    def test_kb_fail_open_still_invokes_llm(self):
        """知识库失败 → 仍调用 LLM"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.2, case_density=0,
            query="test",
            mock_mode=True,
            mock_kb_results=None,  # 模拟 KB 失败
        )
        assert result["kb_searched"] is True
        assert result["llm_invoked"] is True

    def test_all_fail_returns_degraded(self):
        """全部失败 → 降级返回"""
        from core.skill_research_layer import research_and_analyze
        result = research_and_analyze(
            match_score=0.2, case_density=0,
            query="test",
            mock_mode=True,
            mock_kb_results=None,
            force_skill_error=True,
        )
        assert result["fail_open"] is True
        assert result["multi_path"] is False


# ============================================================
# 7. 集成测试 — P5 route → P6 research
# ============================================================

class TestIntegrationP5P6:
    """P5 路由 → P6 调研集成"""

    def test_tier3_triggers_research_chain(self):
        from core.cognitive_router import evaluate_match, route, TIER3
        from core.skill_research_layer import should_research, research_and_analyze

        # P5: 评估 + 路由
        memories = []  # 无记忆
        match_score, density = evaluate_match(memories)
        result = route(match_score, density)
        assert result.tier == TIER3

        # P6: Tier 3 → 调研
        assert should_research(match_score, density) is True

        # P6: 执行调研
        research = research_and_analyze(
            match_score, density, "test query", mock_mode=True
        )
        assert research["research_needed"] is True

    def test_tier1_skips_research(self):
        from core.cognitive_router import evaluate_match, route, TIER1
        from core.skill_research_layer import should_research

        memories = [SimpleNamespace(score=0.9) for _ in range(5)]
        match_score, density = evaluate_match(memories)
        result = route(match_score, density)
        assert result.tier == TIER1

        # Tier 1 不需要调研
        assert should_research(match_score, density) is False
