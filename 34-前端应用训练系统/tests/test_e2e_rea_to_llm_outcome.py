"""E2E 验证: 33-REA 逆向 → TDR 结构化标注 → 5层训练 → LLM outcome 信号闭环

验证 P1 修复后 outcome 信号能从 REA 产出正确流到 LLM 训练循环:

链路:
  1. REAParseResult (33-REA 逆向产出)
  2. rea_to_training_cases() (rea_to_tdr_adapter.py 转换)
  3. derive_outcome + normalize_prompt_pattern (P1 修复: outcome_pattern_deriver.py)
  4. TSHTTPTrainingExecutor._convert_case_to_training_data (转换层)
  5. 输出: {intent, learned, outcome, prompt_pattern} — LLM 层训练数据

关键断言:
  - L1 evidence + observations → LLM case → outcome="success" (核心修复点)
  - known_gaps case → quality=C → outcome="failure" (反思材料)
  - rea_batch_collector case → quality=B → outcome="partial"
  - 同 intent 多 case → 共享 prompt_pattern (可聚类 → 权重可积累)
"""
import os
import sys
import unittest

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingCase
from interfaces.rea_parser import REAParseResult
from interfaces.training_executor import TrainingLayer
from rea_to_tdr_adapter import rea_to_training_cases
from ts_http_training_executor import TSHTTPTrainingExecutor
from core.outcome_pattern_deriver import (
    derive_outcome,
    normalize_prompt_pattern,
    derive_outcome_and_pattern,
)


def _make_wrapup_case(intent="部署BTC策略", quality="B", confidence=0.5):
    """构造收尾案例 dict（rea_to_training_cases 的输入）。"""
    return {
        "intent": intent,
        "actions": ["买入", "止损", "平仓"],
        "outcome_text": "策略部署成功并完成回测验证",
        "learned": ["趋势跟踪有效", "止损位需放宽"],
        "quality": quality,
        "confidence": confidence,
    }


def _make_rea_result(
    evidence_level="L1",
    confidence=0.85,
    algorithm_patterns=None,
    call_chain=None,
    dependency_graph=None,
    known_gaps=None,
    observations=None,
):
    """构造 REAParseResult。"""
    return REAParseResult(
        algorithm_patterns=algorithm_patterns or ["递归", "分治"],
        call_chain=call_chain or ["main", "train", "evaluate"],
        dependency_graph=dependency_graph or {"main": ["train", "evaluate"]},
        known_gaps=known_gaps or [],
        observations=observations or [
            {"result": "训练收敛", "level": "L1"},
            {"result": "验证通过", "level": "L1"},
        ],
        evidence_level=evidence_level,
        confidence=confidence,
    )


# ============================================================
# 1. REA 产出端: rea_to_training_cases 正确生成 quality/confidence
# ============================================================

class TestREAProducedCaseQuality(unittest.TestCase):
    """验证 REA → TrainingCase 转换正确生成 quality/confidence 字段。"""

    def test_l1_evidence_yields_a_quality(self):
        """L1 evidence_level → quality=A (outcome 派生 success 的输入)"""
        rea = _make_rea_result(evidence_level="L1", confidence=0.85)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        # 找 observations 对应的 LLM case
        llm_cases = [c for c in cases if "LLM" in (c.layer_tags or [])]
        self.assertTrue(llm_cases, "应生成至少 1 个 LLM 层 case")
        llm_case = llm_cases[0]
        self.assertEqual(llm_case.quality, "A",
                         "L1 evidence → quality=A → outcome 派生 success")
        self.assertGreaterEqual(llm_case.confidence, 0.7,
                                "confidence >= 0.7 → outcome 派生 success")

    def test_l2_evidence_yields_b_quality(self):
        """L2 evidence_level → quality=B (outcome 派生 partial)"""
        rea = _make_rea_result(evidence_level="L2", confidence=0.5)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        llm_cases = [c for c in cases if "LLM" in (c.layer_tags or [])]
        self.assertTrue(llm_cases)
        self.assertEqual(llm_cases[0].quality, "B")

    def test_known_gaps_case_fixed_c_quality(self):
        """known_gaps → quality=C (反思材料 → outcome=failure)"""
        rea = _make_rea_result(
            evidence_level="L1",  # 即使 L1
            known_gaps=["性能瓶颈未解决", "边界条件未覆盖"],
            observations=[],
        )
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        c_cases = [c for c in cases if "C" in (c.layer_tags or [])]
        # 应有 known_gaps 对应的 C 层 case
        kg_cases = [c for c in c_cases if c.source == "rea_known_gaps"]
        self.assertTrue(kg_cases, "应有 known_gaps → C 层 case")
        self.assertEqual(kg_cases[0].quality, "C",
                         "known_gaps 固定 quality=C → outcome=failure")

    def test_all_five_field_cases_generated(self):
        """完整 REA 结果应生成 5 类 case (algorithm/call_chain/graph/gaps/observations)"""
        rea = _make_rea_result(
            evidence_level="L1",
            algorithm_patterns=["递归", "分治"],
            call_chain=["main", "train"],
            dependency_graph={"main": ["train"]},
            known_gaps=["gap1"],
            observations=[{"result": "obs1"}],
        )
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        sources = {c.source for c in cases}
        self.assertEqual(
            sources,
            {"rea_algorithm", "rea_call_chain", "rea_dependency_graph",
             "rea_known_gaps", "rea_observations"},
            f"应生成全部 5 类 case，实际: {sources}",
        )


# ============================================================
# 2. outcome 派生端: P1 修复后的 derive_outcome 对 REA case 正确工作
# ============================================================

class TestOutcomeDerivationForREACases(unittest.TestCase):
    """验证 P1 修复后的 outcome_pattern_deriver 对 REA 产出的 case 正确派生。"""

    def test_l1_observations_case_success(self):
        """L1 evidence + observations → outcome=success (核心修复点)"""
        rea = _make_rea_result(evidence_level="L1", confidence=0.85)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        llm_case = next(c for c in cases if c.source == "rea_observations")
        outcome = derive_outcome(llm_case)
        self.assertEqual(outcome, "success",
                         "L1+observations → quality=A → success (P1 核心修复)")

    def test_known_gaps_case_failure(self):
        """known_gaps case → outcome=failure"""
        rea = _make_rea_result(
            evidence_level="L1",
            known_gaps=["未解决"],
            observations=[],
        )
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        kg_case = next(c for c in cases if c.source == "rea_known_gaps")
        outcome = derive_outcome(kg_case)
        self.assertEqual(outcome, "failure",
                         "known_gaps quality=C → failure")

    def test_l2_algorithm_case_partial(self):
        """L2 evidence + algorithm_patterns → outcome=partial"""
        rea = _make_rea_result(evidence_level="L2", confidence=0.5)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        algo_case = next(c for c in cases if c.source == "rea_algorithm")
        outcome = derive_outcome(algo_case)
        self.assertEqual(outcome, "partial",
                         "L2 → quality=B → partial")

    def test_rea_batch_collector_case_partial(self):
        """rea_batch_collector.py 固定 quality=B → outcome=partial"""
        # 模拟 rea_batch_collector._analyze_file 的产出
        batch_case = TrainingCase(
            intent="algorithm_reducer.py",
            actions=["递归", "分治"],
            outcome_text="Algorithm patterns: 递归, 分治",
            learned=["递归", "分治"],
            layer_tags=["DSH", "G"],
            quality="B",
            confidence=0.4,
            source="rea",
            metadata={"file_path": "/tmp/test.py"},
        )
        outcome = derive_outcome(batch_case)
        self.assertEqual(outcome, "partial")


# ============================================================
# 3. prompt_pattern 归一化: 同 intent 共享 pattern (可聚类)
# ============================================================

class TestPromptPatternClustering(unittest.TestCase):
    """验证 P1 修复: 同 intent 的 REA case 共享 prompt_pattern → 可聚类"""

    def test_same_intent_shared_pattern(self):
        """同 intent 不同 observations → 共享 prompt_pattern"""
        intent = "部署BTC趋势策略"
        wrapup = _make_wrapup_case(intent=intent)
        rea1 = _make_rea_result(
            observations=[{"result": "训练收敛v1"}])
        rea2 = _make_rea_result(
            observations=[{"result": "训练收敛v2 不同结果"}])
        cases1 = rea_to_training_cases(wrapup, rea1)
        cases2 = rea_to_training_cases(wrapup, rea2)
        llm1 = next(c for c in cases1 if c.source == "rea_observations")
        llm2 = next(c for c in cases2 if c.source == "rea_observations")
        p1 = normalize_prompt_pattern(llm1)
        p2 = normalize_prompt_pattern(llm2)
        self.assertEqual(p1, p2,
                         "同 intent → 共享 pattern → 模板可聚类 → 权重可积累")
        self.assertEqual(p1, intent)

    def test_pattern_not_full_outcome_text(self):
        """prompt_pattern 不应是完整 outcome_text (避免唯一性)"""
        rea = _make_rea_result(evidence_level="L1", confidence=0.85)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        llm_case = next(c for c in cases if c.source == "rea_observations")
        pattern = normalize_prompt_pattern(llm_case)
        # 不等于完整 outcome_text
        self.assertNotEqual(pattern, llm_case.outcome_text)
        # 等于 intent (短)
        self.assertEqual(pattern, llm_case.intent)


# ============================================================
# 4. 转换层: TSHTTPTrainingExecutor LLM 层转换
# ============================================================

class TestLLMLayerConversion(unittest.TestCase):
    """验证 TSHTTPTrainingExecutor 对 LLM 层 REA case 的转换正确。"""

    def test_l1_case_converts_to_success(self):
        """L1+observations → 转换层输出 outcome=success, prompt_pattern=intent"""
        rea = _make_rea_result(evidence_level="L1", confidence=0.85)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        llm_case = next(c for c in cases if c.source == "rea_observations")
        executor = TSHTTPTrainingExecutor(TrainingLayer.LLM)
        data = executor._convert_case_to_training_data(llm_case)
        self.assertEqual(data["outcome"], "success",
                         "LLM 层 outcome=success (P1 核心修复)")
        self.assertEqual(data["prompt_pattern"], llm_case.intent,
                         "prompt_pattern=intent (可聚类)")
        self.assertEqual(data["intent"], llm_case.intent)
        self.assertEqual(data["learned"], llm_case.learned)

    def test_known_gaps_case_converts_to_failure(self):
        """known_gaps → 转换层 C 层 outcome=failure"""
        rea = _make_rea_result(
            evidence_level="L1",
            known_gaps=["未解决"],
            observations=[],
        )
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        kg_case = next(c for c in cases if c.source == "rea_known_gaps")
        executor = TSHTTPTrainingExecutor(TrainingLayer.C)
        data = executor._convert_case_to_training_data(kg_case)
        self.assertEqual(data["outcome"], "failure",
                         "known_gaps → C 层 outcome=failure")

    def test_algorithm_case_converts_to_partial(self):
        """L2 algorithm → DSH 层 outcome=partial"""
        rea = _make_rea_result(evidence_level="L2", confidence=0.5)
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        algo_case = next(c for c in cases if c.source == "rea_algorithm")
        executor = TSHTTPTrainingExecutor(TrainingLayer.DSH)
        data = executor._convert_case_to_training_data(algo_case)
        self.assertEqual(data["outcome"], "partial",
                         "L2 algorithm → DSH 层 outcome=partial")


# ============================================================
# 5. 端到端: 模拟多个 REA 工程的 LLM 训练数据流
# ============================================================

class TestE2EMultiProjectLLMFlow(unittest.TestCase):
    """模拟多个 REA 工程产出 → LLM 训练数据列表 → 验证 success 信号比例。"""

    def test_three_projects_yield_mixed_outcomes(self):
        """3 个 REA 工程 → LLM 训练数据列表 → 应包含 success 信号"""
        wrapup = _make_wrapup_case()

        # 工程1: L1 evidence (高质量) → success
        rea1 = _make_rea_result(evidence_level="L1", confidence=0.9)
        # 工程2: L2 evidence (中等) → partial
        rea2 = _make_rea_result(evidence_level="L2", confidence=0.5)
        # 工程3: L1 evidence 但只有 known_gaps (低质量) → failure
        rea3 = _make_rea_result(
            evidence_level="L1",
            known_gaps=["gap1"],
            observations=[],  # 无 observations → 无 LLM case
            algorithm_patterns=[],
            call_chain=[],
            dependency_graph={},
        )

        all_llm_data = []
        for rea in [rea1, rea2, rea3]:
            cases = rea_to_training_cases(wrapup, rea)
            llm_cases = [c for c in cases if "LLM" in (c.layer_tags or [])]
            executor = TSHTTPTrainingExecutor(TrainingLayer.LLM)
            for c in llm_cases:
                all_llm_data.append(
                    executor._convert_case_to_training_data(c))

        # 至少有 1 条 LLM 训练数据
        self.assertGreater(len(all_llm_data), 0)
        outcomes = [d["outcome"] for d in all_llm_data]
        # 关键断言: P1 修复前 success_count=0, 修复后应有 success
        self.assertIn("success", outcomes,
                      "P1 修复后 REA→LLM 链路应有 success 信号")
        # 应有多种 outcome
        self.assertGreaterEqual(len(set(outcomes)), 2,
                                "应有多样化 outcome")

    def test_success_signal_reaches_llm_training_input(self):
        """验证 success 信号能进入 LLM 训练循环的输入数据形态

        llm-prompt-training-loop.ts addTrainingData 接收:
          {intent, learned, outcome, prompt_pattern}
        success 信号路径: REA L1 → case.quality=A →
          derive_outcome → "success" → 转换层 → LLM 训练数据
        """
        rea = _make_rea_result(evidence_level="L1", confidence=0.9)
        wrapup = _make_wrapup_case(intent="部署策略")
        cases = rea_to_training_cases(wrapup, rea)
        llm_case = next(c for c in cases if c.source == "rea_observations")
        executor = TSHTTPTrainingExecutor(TrainingLayer.LLM)
        data = executor._convert_case_to_training_data(llm_case)

        # 完整字段集 (匹配 TS 层 addTrainingData 输入)
        required_keys = {"intent", "learned", "outcome", "prompt_pattern"}
        self.assertTrue(required_keys.issubset(set(data.keys())),
                        f"LLM 训练数据应包含 {required_keys}")
        # outcome 必须是 success (P1 修复前为 partial)
        self.assertEqual(data["outcome"], "success")
        # prompt_pattern 必须是 intent (可聚类)
        self.assertEqual(data["prompt_pattern"], "部署策略")

    def test_pattern_clustering_for_weight_accumulation(self):
        """验证多个相似 REA 工程的 prompt_pattern 相同 → 权重可积累

        场景: 3 个不同工程对同一类问题（intent="优化训练循环"）做逆向
        P1 修复前: prompt_pattern=完整 outcome_text → 3 个不同模板 → 各衰减一次后归零
        P1 修复后: prompt_pattern=intent → 1 个聚类模板 → 3 次 success 累积
        """
        shared_intent = "优化训练循环"
        wrapup = _make_wrapup_case(intent=shared_intent)
        # 3 个不同 REA 工程的产出（不同的 observations 但同 intent）
        rea_results = [
            _make_rea_result(
                evidence_level="L1",
                confidence=0.85,
                observations=[{"result": f"工程{i}优化点A"}],
            )
            for i in range(3)
        ]

        patterns = []
        for rea in rea_results:
            cases = rea_to_training_cases(wrapup, rea)
            llm_case = next(c for c in cases if c.source == "rea_observations")
            _, pattern = derive_outcome_and_pattern(llm_case)
            patterns.append(pattern)

        # 3 个 case 应共享同一 pattern
        self.assertEqual(len(set(patterns)), 1,
                         "3 个 REA 工程同 intent → 共享 1 个 pattern")
        self.assertEqual(patterns[0], shared_intent)


# ============================================================
# 6. 降级路径: REA 不可用时
# ============================================================

class TestDegradedPath(unittest.TestCase):
    """REA 不可用时降级为纯文本四元组。"""

    def test_none_rea_yields_text_case(self):
        """rea_result=None → 降级为全层覆盖的文本 case"""
        cases = rea_to_training_cases(_make_wrapup_case(), None)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(set(case.layer_tags),
                         {"S", "DSH", "C", "G", "LLM"})
        # 降级 case 用 wrapup 的 quality (默认 B)
        self.assertEqual(case.quality, "B")
        outcome = derive_outcome(case)
        self.assertEqual(outcome, "partial",
                         "降级 case quality=B → partial")

    def test_empty_rea_yields_text_case(self):
        """所有字段都空的 REAParseResult → 降级"""
        rea = REAParseResult()  # 全部默认空
        cases = rea_to_training_cases(_make_wrapup_case(), rea)
        self.assertEqual(len(cases), 1)
        self.assertEqual(set(cases[0].layer_tags),
                         {"S", "DSH", "C", "G", "LLM"})


if __name__ == "__main__":
    unittest.main()
