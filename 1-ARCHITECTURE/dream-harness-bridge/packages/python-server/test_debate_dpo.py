#!/usr/bin/env python3
"""test_debate_dpo.py — T-DPO 偏好学习层单元测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §9.2.2 (T-DPO, BIT 2025) + §9.3 Phase 3 + §5.5
- PreferenceNode: 逐轮 (response, feedback) 树节点
- PreferencePair: (chosen, rejected, margin) 偏好对
- PreferenceTreeBuilder: 辩论日志 → 偏好树 → 偏好对
- DebateDPOTrainer: 累积100+场触发 + 概率奖励margin + 策略权重微调
- §9.2.1 Self-Play DPO: reward = log(P_win / P_lose) 概率奖励 (非离散 win/loss)
- FAIL-OPEN: 无数据/异常时不崩溃
"""
from __future__ import annotations
import json, math, os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_adjudication_result():
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[
            {"turn": 1, "clarity": 4, "fact_authenticity": 4, "logical_validity": 4},
            {"turn": 2, "clarity": 3, "fact_authenticity": 3, "logical_validity": 3},
        ],
        bear_turn_scores=[
            {"turn": 1, "clarity": 3, "fact_authenticity": 3, "logical_validity": 3},
            {"turn": 2, "clarity": 4, "fact_authenticity": 4, "logical_validity": 4},
        ],
        bull_total=23.0,
        bear_total=19.0,
        dimension_comparison={
            "clarity": {"bull": 4.0, "bear": 3.5},
            "fact_authenticity": {"bull": 4.0, "bear": 3.5},
        },
        winner="bull",
        rfd="正方领先",
        key_clash_points=["稀缺性vs波动性"],
        rebuttal_strength={"bull": 4, "bear": 3},
        evidence_depth={"bull": 4, "bear": 3},
        timestamp="2026-01-01T00:00:00",
    )


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {
            "thesis": "BTC稀缺性", "arguments": ["2100万上限"],
            "quote": "数字黄金", "confidence": 0.8, "strategy": "evidence-heavy",
        }, "persona": "乐观分析师"},
        {"speaker": "bear", "round": 1, "content": {
            "thesis": "BTC波动性", "arguments": ["单日20%"],
            "quote": "不是黄金", "confidence": 0.7, "strategy": "counter-example",
        }, "persona": "谨慎风控师"},
        {"speaker": "bull", "round": 2, "content": {
            "thesis": "机构采用", "arguments": ["ETF流入"],
            "quote": "趋势不可逆", "confidence": 0.75, "strategy": "definition-lock",
        }, "persona": "乐观分析师"},
        {"speaker": "bear", "round": 2, "content": {
            "thesis": "监管风险", "arguments": ["SEC诉讼"],
            "quote": "监管是达摩克利斯之剑", "confidence": 0.8, "strategy": "kritik",
        }, "persona": "谨慎风控师"},
    ]


# ── Tests ─────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    def test_import_classes(self):
        from debate_dpo import (  # noqa: F401
            PreferenceNode, PreferencePair,
            PreferenceTreeBuilder, DebateDPOTrainer,
        )

    def test_import_margin_fn(self):
        from debate_dpo import compute_reward_margin  # noqa: F401


class TestRewardMargin(unittest.TestCase):
    """§9.2.1 Self-Play DPO: 概率奖励 = log(P_win / P_lose)。"""

    def test_positive_margin_when_chosen_better(self):
        from debate_dpo import compute_reward_margin
        margin = compute_reward_margin(chosen_score=5.0, rejected_score=3.0)
        self.assertGreater(margin, 0)

    def test_margin_logistic_form(self):
        """margin = log(chosen / rejected)。"""
        from debate_dpo import compute_reward_margin
        margin = compute_reward_margin(5.0, 2.5)
        self.assertAlmostEqual(margin, math.log(5.0 / 2.5), places=4)

    def test_zero_margin_when_equal(self):
        from debate_dpo import compute_reward_margin
        margin = compute_reward_margin(3.0, 3.0)
        self.assertAlmostEqual(margin, 0.0, places=4)

    def test_handles_zero_rejected(self):
        """rejected=0 时不除零崩溃。"""
        from debate_dpo import compute_reward_margin
        margin = compute_reward_margin(3.0, 0.0)
        self.assertGreaterEqual(margin, 0)


class TestPreferenceTreeBuilder(unittest.TestCase):
    """§9.2.2: 辩论日志 → 偏好树。"""

    def test_build_tree(self):
        from debate_dpo import PreferenceTreeBuilder
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree(
            _make_transcript(), _make_adjudication_result())
        self.assertIsInstance(tree, list)
        self.assertGreater(len(tree), 0)

    def test_nodes_have_chosen_flag(self):
        """每个节点含 chosen 标记 (胜出分支 True)。"""
        from debate_dpo import PreferenceTreeBuilder, PreferenceNode
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree(
            _make_transcript(), _make_adjudication_result())
        for node in tree:
            self.assertIsInstance(node, PreferenceNode)
            self.assertIsInstance(node.chosen, bool)

    def test_node_has_strategies(self):
        """节点携带该轮策略标签 (Layer A 生成时标签)。"""
        from debate_dpo import PreferenceTreeBuilder
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree(
            _make_transcript(), _make_adjudication_result())
        strategies = [n.strategies for n in tree if n.strategies]
        self.assertGreater(len(strategies), 0)

    def test_extract_pairs(self):
        """从偏好树提取偏好对。"""
        from debate_dpo import PreferenceTreeBuilder, PreferencePair
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree(
            _make_transcript(), _make_adjudication_result())
        pairs = builder.extract_preference_pairs(tree)
        self.assertIsInstance(pairs, list)
        self.assertGreater(len(pairs), 0)
        self.assertIsInstance(pairs[0], PreferencePair)

    def test_pair_has_margin(self):
        """偏好对含 margin (评分差)。"""
        from debate_dpo import PreferenceTreeBuilder
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree(
            _make_transcript(), _make_adjudication_result())
        pairs = builder.extract_preference_pairs(tree)
        for p in pairs:
            self.assertIsInstance(p.margin, float)

    def test_empty_input(self):
        from debate_dpo import PreferenceTreeBuilder
        builder = PreferenceTreeBuilder()
        tree = builder.build_preference_tree([], _make_adjudication_result())
        self.assertEqual(tree, [])


class TestTriggerGate(unittest.TestCase):
    """§5.5: 累积 100+场后触发。"""

    def test_should_trigger_below_threshold(self):
        from debate_dpo import DebateDPOTrainer
        trainer = DebateDPOTrainer()
        self.assertFalse(trainer.should_trigger(99))

    def test_should_trigger_at_threshold(self):
        from debate_dpo import DebateDPOTrainer
        trainer = DebateDPOTrainer()
        self.assertTrue(trainer.should_trigger(100))

    def test_min_debates_constant(self):
        from debate_dpo import DebateDPOTrainer
        self.assertEqual(DebateDPOTrainer.MIN_DEBATES, 100)


class TestDPOTrain(unittest.TestCase):
    """DPO 偏好学习 → 微调策略权重 (§9.3 Phase 3)。"""

    def test_train_before_trigger_skips(self):
        """<100 场时跳过训练。"""
        from debate_dpo import DebateDPOTrainer
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        trainer = DebateDPOTrainer()
        result = trainer.train(
            adjudication_result=_make_adjudication_result(),
            transcript=_make_transcript(),
            bayesian=bsw,
            topic_type="crypto",
            debate_count=50,
        )
        self.assertFalse(result["trained"])

    def test_train_at_trigger_updates_weights(self):
        """>=100 场时更新策略权重。"""
        from debate_dpo import DebateDPOTrainer
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        trainer = DebateDPOTrainer()
        result = trainer.train(
            adjudication_result=_make_adjudication_result(),
            transcript=_make_transcript(),
            bayesian=bsw,
            topic_type="crypto",
            debate_count=100,
        )
        self.assertTrue(result["trained"])
        self.assertGreater(result["pairs"], 0)

    def test_chosen_strategy_alpha_increases(self):
        """胜出策略 α 增加 (偏好微调)。"""
        from debate_dpo import DebateDPOTrainer
        from debate_trainer import BayesianStrategyWeights
        bsw = BayesianStrategyWeights()
        before = bsw.get_win_prob("evidence-heavy", "crypto")
        trainer = DebateDPOTrainer()
        trainer.train(
            adjudication_result=_make_adjudication_result(),
            transcript=_make_transcript(),
            bayesian=bsw,
            topic_type="crypto",
            debate_count=100,
        )
        after = bsw.get_win_prob("evidence-heavy", "crypto")
        self.assertGreater(after, before)

    def test_margin_weighted_updates(self):
        """margin 越大，权重更新越强 (§9.2.1 概率奖励)。"""
        from debate_dpo import DebateDPOTrainer
        from debate_trainer import BayesianStrategyWeights

        bsw_small = BayesianStrategyWeights()
        bsw_large = BayesianStrategyWeights()
        trainer = DebateDPOTrainer()

        # 小 margin
        adj_small = _make_adjudication_result()
        adj_small.bull_turn_scores = [
            {"turn": 1, "clarity": 3.2, "fact_authenticity": 3.2, "logical_validity": 3.2}]
        adj_small.bear_turn_scores = [
            {"turn": 1, "clarity": 3.0, "fact_authenticity": 3.0, "logical_validity": 3.0}]
        trainer.train(adj_small, _make_transcript(), bsw_small, "crypto", 100)

        # 大 margin
        adj_large = _make_adjudication_result()
        adj_large.bull_turn_scores = [
            {"turn": 1, "clarity": 5.0, "fact_authenticity": 5.0, "logical_validity": 5.0}]
        adj_large.bear_turn_scores = [
            {"turn": 1, "clarity": 1.0, "fact_authenticity": 1.0, "logical_validity": 1.0}]
        trainer.train(adj_large, _make_transcript(), bsw_large, "crypto", 100)

        prob_small = bsw_small.get_win_prob("evidence-heavy", "crypto")
        prob_large = bsw_large.get_win_prob("evidence-heavy", "crypto")
        self.assertGreater(prob_large, prob_small)


class TestFailOpen(unittest.TestCase):
    """FAIL-OPEN。"""

    def test_train_none_args(self):
        from debate_dpo import DebateDPOTrainer
        trainer = DebateDPOTrainer()
        result = trainer.train(None, None, None, "crypto", 100)
        self.assertFalse(result["trained"])

    def test_train_none_bayesian(self):
        from debate_dpo import DebateDPOTrainer
        trainer = DebateDPOTrainer()
        result = trainer.train(
            _make_adjudication_result(), _make_transcript(),
            None, "crypto", 100)
        self.assertFalse(result["trained"])


if __name__ == "__main__":
    unittest.main(verbosity=2)