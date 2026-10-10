#!/usr/bin/env python3
"""test_persona_ext.py — persona.py Elo+策略推荐扩展测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §5.6 参数消费闭环:
- §5.6.1: build_system_prompt 接受 strategy_weights, 注入策略推荐
- §5.6.2: match_personas 接受 elo_registry, ε-贪心选择
- §5.7: 冷启动期策略推荐标注 "[低置信度]"
- HC3: 向后兼容 — 不传新参数时行为不变
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestMatchPersonasElo(unittest.TestCase):
    """§5.6.2: match_personas 接受 elo_registry。"""

    def test_without_elo_backward_compatible(self):
        """不传 elo_registry 时行为不变 (HC3)。"""
        from persona import match_personas
        bull, bear = match_personas("BTC是数字黄金")
        self.assertIsNotNone(bull)
        self.assertIsNotNone(bear)

    def test_with_elo_registry(self):
        """传 elo_registry 时不报错。"""
        from persona import match_personas
        elo = {"乐观分析师": 1250, "加密老兵": 1300, "谨慎风控师": 1180, "传统金融人": 1220}
        bull, bear = match_personas("BTC是数字黄金", elo_registry=elo)
        self.assertIsNotNone(bull)
        self.assertIsNotNone(bear)

    def test_elo_prefers_higher(self):
        """ε=0 时应选 Elo 最高的 Persona。"""
        from persona import match_personas
        # BTC 话题匹配: 加密老兵(bull) vs 传统金融人(bear)
        elo = {"加密老兵": 1400, "传统金融人": 1100,
               "乐观分析师": 1200, "谨慎风控师": 1200}
        # 多次调用验证确定性选择 (ε=0)
        for _ in range(10):
            bull, bear = match_personas("BTC", elo_registry=elo, epsilon=0.0)
            self.assertEqual(bull.name, "加密老兵")

    def test_elo_random_exploration(self):
        """ε=1.0 时完全随机 (探索模式)。"""
        from persona import match_personas
        elo = {"加密老兵": 1400, "传统金融人": 1100,
               "乐观分析师": 1200, "谨慎风控师": 1200}
        # 多次调用，至少有一次选不同的 (随机探索)
        names = set()
        for _ in range(20):
            bull, _ = match_personas("BTC", elo_registry=elo, epsilon=1.0)
            names.add(bull.name)
        # ε=1.0 应有探索性
        self.assertGreater(len(names), 1)


class TestBuildSystemPromptStrategy(unittest.TestCase):
    """§5.6.1: build_system_prompt 接受 strategy_weights。"""

    def test_without_strategy_weights_backward_compatible(self):
        """不传 strategy_weights 时 prompt 不变 (HC3)。"""
        from persona import DEFAULT_BULL
        prompt = DEFAULT_BULL.build_system_prompt("BTC是数字黄金")
        self.assertIn("正方", prompt)
        self.assertIn("BTC", prompt)

    def test_with_strategy_weights(self):
        """传 strategy_weights 时注入策略推荐。"""
        from persona import DEFAULT_BULL
        weights = {"evidence-heavy": 0.72, "definition-lock": 0.58,
                   "counterplan": 0.33}
        prompt = DEFAULT_BULL.build_system_prompt(
            "BTC是数字黄金", strategy_weights=weights)
        # 应包含策略推荐
        self.assertIn("evidence-heavy", prompt)
        self.assertIn("推荐策略", prompt)

    def test_strategy_weights_top2(self):
        """策略推荐只显示 Top-2。"""
        from persona import DEFAULT_BULL
        weights = {"evidence-heavy": 0.72, "definition-lock": 0.58,
                   "counterplan": 0.33}
        prompt = DEFAULT_BULL.build_system_prompt(
            "BTC是数字黄金", strategy_weights=weights)
        # Top-2: evidence-heavy + definition-lock
        self.assertIn("evidence-heavy", prompt)
        self.assertIn("definition-lock", prompt)
        # counterplan 不应出现 (排第3)
        self.assertNotIn("counterplan", prompt)

    def test_cold_start_annotation(self):
        """§5.7 冷启动期策略推荐标注低置信度。"""
        from persona import DEFAULT_BULL
        weights = {"evidence-heavy": 0.50}  # Beta(1,1) = 0.5
        prompt = DEFAULT_BULL.build_system_prompt(
            "BTC是数字黄金",
            strategy_weights=weights,
            cold_start=True,
        )
        self.assertIn("低置信度", prompt)


class TestJudgePersonaUnchanged(unittest.TestCase):
    """裁判 Persona 不受策略推荐影响。"""

    def test_judge_no_strategy_weights(self):
        """裁判 prompt 不注入策略推荐。"""
        from persona import DEFAULT_JUDGE
        weights = {"evidence-heavy": 0.72}
        prompt = DEFAULT_JUDGE.build_system_prompt(
            "BTC", strategy_weights=weights)
        # 裁判 prompt 不应包含策略推荐
        self.assertNotIn("推荐策略", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
