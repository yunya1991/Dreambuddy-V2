"""P4: 33-REA 零 token 反思驱动测试。

测试 rea_cdrive_adapter 模块将 33-REA 解析结果映射为 C-Drive 反射决策。
RED 阶段：assert ModuleNotFoundError / ImportError
GREEN 阶段：实现 rea_cdrive_adapter.py 使测试通过
"""
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# 确保能导入 core 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interfaces.rea_parser import REAParseResult


# ============================================================
# 辅助函数
# ============================================================

def _make_rea_result(
    known_gaps=None,
    call_chain=None,
    dependency_graph=None,
    confidence=0.8,
    evidence_level="L3",
    observations=None,
):
    """构造 REAParseResult 测试用例"""
    return REAParseResult(
        algorithm_patterns=["test_pattern"],
        call_chain=call_chain or ["func_a -> func_b -> func_c"],
        dependency_graph=dependency_graph or {"a": ["b"], "b": ["c"]},
        known_gaps=known_gaps or [],
        observations=observations or [],
        evidence_level=evidence_level,
        confidence=confidence,
    )


# ============================================================
# 1. 模块导入测试 (RED: ModuleNotFoundError)
# ============================================================

class TestModuleImport:
    """验证 rea_cdrive_adapter 模块可导入"""

    def test_import_derive_decision_from_rea(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        assert callable(derive_decision_from_rea)

    def test_import_load_keyword_map(self):
        from core.rea_cdrive_adapter import _load_keyword_map
        assert callable(_load_keyword_map)

    def test_module_constants(self):
        from core.rea_cdrive_adapter import REA_CONF_THRESHOLD, REA_UNKNOWN_LEVEL
        assert isinstance(REA_CONF_THRESHOLD, float)
        assert REA_UNKNOWN_LEVEL == "UNKNOWN"


# ============================================================
# 2. known_gaps 关键词 → 决策映射
# ============================================================

class TestKnownGapsMapping:
    """known_gaps 关键词 → expected_decision 映射"""

    def test_missing_gap_returns_insert_before(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["missing function handle_debate"])
        assert derive_decision_from_rea(result) == "INSERT_BEFORE"

    def test_missing_gap_chinese(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["缺失未实现的接口"])
        assert derive_decision_from_rea(result) == "INSERT_BEFORE"

    def test_wrong_gap_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["wrong implementation in parser"])
        assert derive_decision_from_rea(result) == "REDO"

    def test_bug_gap_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["bug in circular reference"])
        assert derive_decision_from_rea(result) == "REDO"

    def test_dead_gap_returns_early_terminate(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["dead code path detected"])
        assert derive_decision_from_rea(result) == "EARLY_TERMINATE"

    def test_redundant_gap_returns_early_terminate(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["冗余的无用代码块"])
        assert derive_decision_from_rea(result) == "EARLY_TERMINATE"

    def test_circular_dependency_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["circular dependency in module A"])
        assert derive_decision_from_rea(result) == "REDO"

    def test_circular_dependency_chinese_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["循环依赖 in import chain"])
        assert derive_decision_from_rea(result) == "REDO"

    def test_first_matching_gap_wins(self):
        """多个 gaps 时，第一个匹配的 gap 决定决策"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=[
            "missing interface",   # INSERT_BEFORE
            "wrong logic",         # REDO (不应到达)
        ])
        assert derive_decision_from_rea(result) == "INSERT_BEFORE"

    def test_no_matching_gap_returns_none(self):
        """known_gaps 不匹配任何关键词 → None（降级）"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(known_gaps=["unrelated information"])
        assert derive_decision_from_rea(result) is None


# ============================================================
# 3. call_chain 断裂检测
# ============================================================

class TestCallChainBreak:
    """call_chain 有断裂 → INSERT_BEFORE"""

    def test_empty_call_chain_returns_insert_before(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        # 直接构造 REAParseResult（绕过 helper 的 falsy fallback）
        result = REAParseResult(
            algorithm_patterns=["test"],
            call_chain=[],
            dependency_graph={"a": ["b"]},
            known_gaps=[],
            evidence_level="L3",
            confidence=0.8,
        )
        assert derive_decision_from_rea(result) == "INSERT_BEFORE"

    def test_broken_call_chain_returns_insert_before(self):
        """call_chain 含断裂标记 → INSERT_BEFORE"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(call_chain=["func_a -> ???", "func_b -> func_c"])
        assert derive_decision_from_rea(result) == "INSERT_BEFORE"


# ============================================================
# 4. dependency_graph 循环检测
# ============================================================

class TestDependencyCycle:
    """dependency_graph 有环 → REDO"""

    def test_circular_dependency_graph_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        # A→B→C→A 形成环
        dep_graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
        result = _make_rea_result(dependency_graph=dep_graph)
        assert derive_decision_from_rea(result) == "REDO"

    def test_no_cycle_in_dependency_graph(self):
        """无环的 dependency_graph 不触发 REDO"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        dep_graph = {"A": ["B"], "B": ["C"], "C": []}
        result = _make_rea_result(dependency_graph=dep_graph, known_gaps=[])
        # 无 gap + 无环 + 高 confidence → None
        assert derive_decision_from_rea(result) is None


# ============================================================
# 5. confidence 阈值
# ============================================================

class TestConfidenceThreshold:
    """confidence < 0.3 → REDO（对齐 CDRIVE_CONF_REDO）"""

    def test_low_confidence_returns_redo(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(confidence=0.2, known_gaps=[])
        assert derive_decision_from_rea(result) == "REDO"

    def test_boundary_confidence_03_not_redo(self):
        """confidence = 0.3 不触发 REDO（< 0.3 才触发）"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(confidence=0.3, known_gaps=[])
        assert derive_decision_from_rea(result) is None

    def test_high_confidence_returns_none(self):
        """高 confidence + 无 gap → None"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(confidence=0.9, known_gaps=[])
        assert derive_decision_from_rea(result) is None


# ============================================================
# 6. evidence_level UNKNOWN
# ============================================================

class TestEvidenceLevelUnknown:
    """evidence_level = UNKNOWN → EARLY_TERMINATE"""

    def test_unknown_evidence_returns_early_terminate(self):
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(evidence_level="UNKNOWN", known_gaps=[])
        assert derive_decision_from_rea(result) == "EARLY_TERMINATE"

    def test_normal_evidence_not_terminate(self):
        """非 UNKNOWN evidence_level 不触发 EARLY_TERMINATE"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(evidence_level="L3", known_gaps=[])
        assert derive_decision_from_rea(result) is None


# ============================================================
# 7. FAIL-OPEN 测试
# ============================================================

class TestFailOpen:
    """无信号时返回 None（降级到 P3/P2/P1）"""

    def test_clean_result_returns_none(self):
        """无 gap + 高 confidence + 正常 evidence → None"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        result = _make_rea_result(
            known_gaps=[],
            confidence=0.9,
            evidence_level="L3",
            call_chain=["a -> b -> c"],
            dependency_graph={"a": ["b"], "b": ["c"], "c": []},
        )
        assert derive_decision_from_rea(result) is None

    def test_none_result_returns_none(self):
        """rea_result = None → None"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        assert derive_decision_from_rea(None) is None


# ============================================================
# 8. 关键词配置外部化 (YAML)
# ============================================================

class TestKeywordMapYAML:
    """关键词映射外部化到 YAML 配置"""

    def test_load_keyword_map_returns_dict(self):
        from core.rea_cdrive_adapter import _load_keyword_map
        km = _load_keyword_map()
        assert isinstance(km, dict)
        assert "known_gaps_map" in km

    def test_keyword_map_has_entries(self):
        from core.rea_cdrive_adapter import _load_keyword_map
        km = _load_keyword_map()
        gaps_map = km["known_gaps_map"]
        assert len(gaps_map) >= 4  # missing/wrong/dead/circular

    def test_keyword_map_entries_have_pattern_and_decision(self):
        from core.rea_cdrive_adapter import _load_keyword_map
        km = _load_keyword_map()
        for entry in km["known_gaps_map"]:
            assert "pattern" in entry
            assert "decision" in entry

    def test_keyword_map_fallback_on_missing_file(self, tmp_path):
        """YAML 配置文件不存在时使用内置默认映射"""
        from core.rea_cdrive_adapter import _load_keyword_map
        # 指向不存在的路径
        km = _load_keyword_map(config_path="/nonexistent/rea_keyword_map.yaml")
        assert isinstance(km, dict)
        assert "known_gaps_map" in km
        assert len(km["known_gaps_map"]) >= 4  # 仍有默认映射

    def test_keyword_map_custom_config(self, tmp_path):
        """自定义 YAML 配置可覆盖默认映射"""
        from core.rea_cdrive_adapter import _load_keyword_map, derive_decision_from_rea

        custom_yaml = tmp_path / "custom_map.yaml"
        custom_yaml.write_text(textwrap.dedent("""\
            known_gaps_map:
              - pattern: "custom_pattern"
                decision: "REDO"
        """))
        km = _load_keyword_map(config_path=str(custom_yaml))
        assert len(km["known_gaps_map"]) == 1
        assert km["known_gaps_map"][0]["pattern"] == "custom_pattern"


# ============================================================
# 9. 优先级链测试 (P4 → P2 → P1 降级)
# ============================================================

class TestPriorityChain:
    """P4(33-REA) 优先于 P2(C-Drive) 优先于 P1(语义)"""

    def test_p4_signal_takes_priority_over_p1(self):
        """33-REA 产出 REDO 信号时，不被 P1 的 CONTINUE 覆盖"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        from core.decision_deriver import derive_expected_decision

        rea_result = _make_rea_result(known_gaps=["wrong bug"], confidence=0.9)
        p4_decision = derive_decision_from_rea(rea_result)
        assert p4_decision == "REDO"

        # P1 在 outcome=success 时会返回 CONTINUE，但 P4 优先
        p1_decision = derive_expected_decision(
            intent="test task",
            actions=["完成"],
            outcome="success",
        )
        assert p1_decision == "CONTINUE"

        # P4 优先于 P1
        final = p4_decision if p4_decision is not None else p1_decision
        assert final == "REDO"

    def test_p4_none_degrades_to_p1(self):
        """P4 无信号时降级到 P1"""
        from core.rea_cdrive_adapter import derive_decision_from_rea
        from core.decision_deriver import derive_expected_decision

        rea_result = _make_rea_result(known_gaps=[], confidence=0.9)
        p4_decision = derive_decision_from_rea(rea_result)
        assert p4_decision is None  # P4 无信号

        # 降级到 P1
        p1_decision = derive_expected_decision(
            intent="test task",
            actions=["完成"],
            outcome="success",
        )
        final = p4_decision if p4_decision is not None else p1_decision
        assert final == "CONTINUE"


# ============================================================
# 10. 集成测试
# ============================================================

class TestIntegrationChain:
    """P4 集成到训练数据构造链"""

    def test_p4_enriches_case_with_rea_decision(self):
        """P4 产出的决策写入 case['expected_decision']"""
        from core.rea_cdrive_adapter import derive_decision_from_rea

        rea_result = _make_rea_result(known_gaps=["missing handler"])
        p4_decision = derive_decision_from_rea(rea_result)

        case = {
            "outcome": "success",
            "confidence": 0.9,
            "action_summary": "完成",
            "learned": "",
        }
        # 模拟集成链: P4 优先
        if p4_decision is not None:
            case["expected_decision"] = p4_decision
        else:
            case["expected_decision"] = "CONTINUE"

        assert case["expected_decision"] == "INSERT_BEFORE"

    def test_p4_none_case_falls_through_to_p3_p2_p1(self):
        """P4 无信号时，case 继续走 P3→P2→P1 链"""
        from types import SimpleNamespace
        from core.rea_cdrive_adapter import derive_decision_from_rea
        from core.decision_deriver import derive_expected_decision_with_cdrive

        rea_result = _make_rea_result(known_gaps=[], confidence=0.9)
        p4_decision = derive_decision_from_rea(rea_result)

        # 构造 mock case 对象（对齐 TrainingCase 接口）
        case = SimpleNamespace(
            intent="test task",
            actions=["完成"],
            outcome_text="任务完成",
            learned=[],
            confidence=0.9,
            metadata={"outcome": "success"},
        )
        if p4_decision is not None:
            expected = p4_decision
        else:
            # 降级到 P2（含 C-Drive 反思）
            expected = derive_expected_decision_with_cdrive(case)

        assert expected == "CONTINUE"
