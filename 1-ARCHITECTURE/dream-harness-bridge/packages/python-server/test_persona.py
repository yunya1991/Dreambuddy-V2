#!/usr/bin/env python3
"""test_persona.py — Persona 系统单元测试 (TDD RED→GREEN)

测试 SPEC v2.0-rc3 第三节定义的 Persona 系统：
- Persona dataclass 字段完整性
- build_system_prompt 生成逻辑（角色定位/人格特质/话术/禁止/对方论点/背景/记忆/输出约束）
- 7 预设 Persona 库
- 动态话题匹配（Crypto/AI/通用）
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestPersonaDataclass(unittest.TestCase):
    """Persona dataclass 字段完整性。"""

    def test_importable(self):
        """RED: persona 模块尚未创建，import 应失败。"""
        from persona import Persona  # noqa: F401

    def test_create_basic(self):
        """Persona 基本字段创建。"""
        from persona import Persona
        p = Persona(
            name="乐观分析师",
            side="bull",
            traits=["幽默", "数据驱动", "爱用比喻"],
            speech_style="轻松诙谐但不失逻辑",
            backstory="前对冲基金分析师",
            expertise=["宏观经济学", "链上分析"],
            forbidden=["人身攻击", "使用未经验证的数据", "情绪化表述"],
        )
        self.assertEqual(p.name, "乐观分析师")
        self.assertEqual(p.side, "bull")
        self.assertEqual(len(p.traits), 3)
        self.assertEqual(len(p.forbidden), 3)


class TestBuildSystemPrompt(unittest.TestCase):
    """build_system_prompt 生成逻辑。"""

    def test_basic_prompt_contains_role(self):
        """prompt 包含角色定位。"""
        from persona import Persona
        p = Persona(
            name="乐观分析师", side="bull",
            traits=["幽默"], speech_style="轻松",
            backstory="分析师", expertise=["宏观"],
            forbidden=["人身攻击"],
        )
        prompt = p.build_system_prompt(topic="BTC 是数字黄金")
        self.assertIn("乐观分析师", prompt)
        self.assertIn("正方", prompt)
        self.assertIn("支持", prompt)
        self.assertIn("BTC 是数字黄金", prompt)

    def test_bear_side(self):
        """bear 方立场为反对。"""
        from persona import Persona
        p = Persona(
            name="谨慎风控师", side="bear",
            traits=["犀利"], speech_style="严谨",
            backstory="风控", expertise=["风险"],
            forbidden=["情绪化表述"],
        )
        prompt = p.build_system_prompt(topic="BTC 是数字黄金")
        self.assertIn("反方", prompt)
        self.assertIn("反对", prompt)

    def test_prompt_contains_traits_and_style(self):
        """prompt 包含人格特质和话术风格。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bull",
            traits=["幽默", "数据驱动"],
            speech_style="轻松诙谐",
            backstory="", expertise=["宏观"],
            forbidden=[],
        )
        prompt = p.build_system_prompt(topic="测试话题")
        self.assertIn("幽默", prompt)
        self.assertIn("数据驱动", prompt)
        self.assertIn("轻松诙谐", prompt)

    def test_prompt_contains_forbidden(self):
        """prompt 包含禁止行为。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bull",
            traits=[], speech_style="",
            backstory="", expertise=[],
            forbidden=["人身攻击", "情绪化表述"],
        )
        prompt = p.build_system_prompt(topic="测试")
        self.assertIn("绝对禁止", prompt)
        self.assertIn("人身攻击", prompt)
        self.assertIn("情绪化表述", prompt)

    def test_prompt_with_opponent_thesis(self):
        """prompt 包含对方论点。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bear",
            traits=[], speech_style="",
            backstory="", expertise=[],
            forbidden=[],
        )
        prompt = p.build_system_prompt(
            topic="测试", opponent_thesis="BTC 稀缺性决定长期价值")
        self.assertIn("对方上一轮核心论点", prompt)
        self.assertIn("BTC 稀缺性决定长期价值", prompt)

    def test_prompt_with_background(self):
        """prompt 包含背景材料。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bull",
            traits=[], speech_style="",
            backstory="", expertise=[],
            forbidden=[],
        )
        prompt = p.build_system_prompt(topic="测试", background="BTC 当前 65000 美元")
        self.assertIn("背景信息", prompt)
        self.assertIn("65000", prompt)

    def test_prompt_with_memories(self):
        """prompt 包含历史记忆。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bull",
            traits=[], speech_style="",
            backstory="", expertise=[],
            forbidden=[],
        )
        memories = ["2024 年 BTC 减半后上涨 300%", "机构采用率持续攀升"]
        prompt = p.build_system_prompt(topic="测试", memories=memories)
        self.assertIn("历史辩论中的有效论据", prompt)
        self.assertIn("2024 年 BTC 减半后上涨 300%", prompt)

    def test_prompt_contains_json_output_constraint(self):
        """prompt 包含 JSON 输出约束。"""
        from persona import Persona
        p = Persona(
            name="测试", side="bull",
            traits=[], speech_style="",
            backstory="", expertise=[],
            forbidden=[],
        )
        prompt = p.build_system_prompt(topic="测试")
        self.assertIn("JSON", prompt)
        self.assertIn("thesis", prompt)
        self.assertIn("arguments", prompt)
        self.assertIn("confidence", prompt)


class TestPresetPersonas(unittest.TestCase):
    """7 预设 Persona 库。"""

    def test_presets_exist(self):
        """7 个预设 Persona 全部存在。"""
        from persona import PRESET_PERSONAS
        self.assertIsInstance(PRESET_PERSONAS, dict)
        expected_names = {
            "乐观分析师", "谨慎风控师", "中立裁判",
            "技术乐观派", "伦理审慎派", "加密老兵", "传统金融人",
        }
        self.assertEqual(set(PRESET_PERSONAS.keys()), expected_names)

    def test_preset_sides(self):
        """预设 Persona 的 side 正确。"""
        from persona import PRESET_PERSONAS
        self.assertEqual(PRESET_PERSONAS["乐观分析师"].side, "bull")
        self.assertEqual(PRESET_PERSONAS["谨慎风控师"].side, "bear")
        self.assertEqual(PRESET_PERSONAS["中立裁判"].side, "judge")
        self.assertEqual(PRESET_PERSONAS["技术乐观派"].side, "bull")
        self.assertEqual(PRESET_PERSONAS["伦理审慎派"].side, "bear")
        self.assertEqual(PRESET_PERSONAS["加密老兵"].side, "bull")
        self.assertEqual(PRESET_PERSONAS["传统金融人"].side, "bear")

    def test_preset_has_forbidden(self):
        """每个预设 Persona 都有禁止行为。"""
        from persona import PRESET_PERSONAS
        for name, p in PRESET_PERSONAS.items():
            self.assertTrue(len(p.forbidden) > 0,
                            f"{name} 缺少 forbidden 字段")

    def test_judge_prompt_differs_from_bull_bear(self):
        """裁判的 prompt 不含正方/反方立场。"""
        from persona import PRESET_PERSONAS
        judge = PRESET_PERSONAS["中立裁判"]
        prompt = judge.build_system_prompt(topic="测试")
        # judge 不应该是正方或反方
        self.assertNotIn("正方辩手", prompt)
        self.assertNotIn("反方辩手", prompt)


class TestDynamicMatch(unittest.TestCase):
    """动态话题匹配。"""

    def test_match_crypto(self):
        """Crypto 关键词匹配加密老兵 vs 传统金融人。"""
        from persona import match_personas
        bull, bear = match_personas("BTC 是数字黄金吗")
        self.assertEqual(bull.name, "加密老兵")
        self.assertEqual(bear.name, "传统金融人")

    def test_match_crypto_keywords(self):
        """多种 Crypto 关键词都能匹配。"""
        from persona import match_personas
        for kw in ["BTC", "Crypto", "加密", "比特币", "以太坊", "ETH"]:
            bull, bear = match_personas(f"{kw} 话题")
            self.assertEqual(bull.name, "加密老兵", f"关键词 {kw} 未匹配加密老兵")
            self.assertEqual(bear.name, "传统金融人")

    def test_match_ai(self):
        """AI 关键词匹配技术乐观派 vs 伦理审慎派。"""
        from persona import match_personas
        bull, bear = match_personas("AI 人工智能会取代人类吗")
        self.assertEqual(bull.name, "技术乐观派")
        self.assertEqual(bear.name, "伦理审慎派")

    def test_match_ai_keywords(self):
        """多种 AI 关键词都能匹配。"""
        from persona import match_personas
        for kw in ["AI", "人工智能", "大模型", "LLM", "AGI"]:
            bull, bear = match_personas(f"{kw} 话题")
            self.assertEqual(bull.name, "技术乐观派", f"关键词 {kw} 未匹配技术乐观派")

    def test_match_default(self):
        """通用话题匹配乐观分析师 vs 谨慎风控师。"""
        from persona import match_personas
        bull, bear = match_personas("远程办公是否应成为常态")
        self.assertEqual(bull.name, "乐观分析师")
        self.assertEqual(bear.name, "谨慎风控师")

    def test_match_returns_persona_instances(self):
        """match_personas 返回 Persona 实例。"""
        from persona import match_personas, Persona
        bull, bear = match_personas("通用话题")
        self.assertIsInstance(bull, Persona)
        self.assertIsInstance(bear, Persona)


if __name__ == "__main__":
    unittest.main()
