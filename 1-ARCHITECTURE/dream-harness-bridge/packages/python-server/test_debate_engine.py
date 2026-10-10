#!/usr/bin/env python3
"""test_debate_engine.py — DebateEngine 单元测试 (TDD RED→GREEN)

SPEC v2.0-rc3 第六节：C-Drive 内部辩论引擎。
- run_fast: 1轮并行 Bull/Bear，无 Persona，<10s
- run_deep: 2轮+Judge+Persona+认知闭环，20-40s
- _recall_debate_memories: 检索历史辩论记忆
- _record_debate: 存储辩论经验
- _inject_debate_memories: B+级过滤 + prompt 注入格式
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock, AsyncMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


# ── mock LLM ──────────────────────────────────────────────────

def _make_llm(bull_resp=None, bear_resp=None, judge_resp=None):
    """创建 mock LLM 函数，按 prompt 内容返回不同响应。"""
    bull_json = bull_resp or json.dumps({
        "thesis": "BTC 稀缺性决定长期价值",
        "arguments": ["2100万枚上限", "减半周期", "机构采用"],
        "quote": "数字黄金不是投机",
        "confidence": 0.85,
    })
    bear_json = bear_resp or json.dumps({
        "thesis": "BTC 波动性远超黄金",
        "arguments": ["单日波动可达20%", "与风险资产高相关"],
        "quote": "黄金一天跌20%就不是黄金了",
        "confidence": 0.72,
    })
    judge_json = judge_resp or json.dumps({
        "summary": "正方论据更充分",
        "winner": "bull",
        "key_insights": ["稀缺性是核心", "波动性需时间验证"],
        "topic_angle": "数字黄金的进化论",
    })

    def llm_fn(prompt, max_tokens=600):
        pl = prompt.lower()
        if "bull" in pl or "正方" in prompt or "支持" in prompt:
            return bull_json
        if "bear" in pl or "反方" in prompt or "反对" in prompt:
            return bear_json
        if "裁判" in prompt or "judge" in pl or "中立" in prompt:
            return judge_json
        return bull_json  # 默认
    return llm_fn


# ── mock cognitive adapter ────────────────────────────────────

def _make_cognitive(memories=None):
    """创建 mock 认知适配器。"""
    cog = MagicMock()
    cog.recall = MagicMock(return_value=memories or [])
    cog.record = MagicMock(return_value="VM-test-001")
    cog.verify = MagicMock(return_value=True)
    return cog


class TestImport(unittest.TestCase):
    def test_importable(self):
        from debate_engine import DebateEngine  # noqa: F401


class TestRunFast(unittest.TestCase):
    """run_fast: 1轮并行，无 Persona，无 Judge。"""

    def test_returns_expected_keys(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(llm_fn=_make_llm(), config={})
        import asyncio
        result = asyncio.run(engine.run_fast("BTC 是数字黄金"))
        self.assertIn("bull_thesis", result)
        self.assertIn("bull_confidence", result)
        self.assertIn("bear_thesis", result)
        self.assertIn("bear_confidence", result)

    def test_confidence_values(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(llm_fn=_make_llm(), config={})
        import asyncio
        result = asyncio.run(engine.run_fast("BTC 是数字黄金"))
        self.assertAlmostEqual(result["bull_confidence"], 0.85)
        self.assertAlmostEqual(result["bear_confidence"], 0.72)

    def test_thesis_not_empty(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(llm_fn=_make_llm(), config={})
        import asyncio
        result = asyncio.run(engine.run_fast("BTC 是数字黄金"))
        self.assertTrue(len(result["bull_thesis"]) > 0)
        self.assertTrue(len(result["bear_thesis"]) > 0)

    def test_llm_failure_fallback(self):
        """LLM 返回无效 JSON 时 fallback。"""
        from debate_engine import DebateEngine
        bad_llm = lambda p, m=600: "这不是JSON"
        engine = DebateEngine(llm_fn=bad_llm, config={})
        import asyncio
        result = asyncio.run(engine.run_fast("测试"))
        # fallback confidence = 0.0
        self.assertEqual(result["bull_confidence"], 0.0)
        self.assertEqual(result["bear_confidence"], 0.0)


class TestRunDeep(unittest.TestCase):
    """run_deep: 2轮+Judge+Persona+认知闭环。"""

    def test_returns_dict_with_transcript(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(
            llm_fn=_make_llm(),
            config={},
            cognitive_adapter=_make_cognitive(),
        )
        import asyncio
        result = asyncio.run(engine.run_deep("BTC 是数字黄金"))
        self.assertIn("topic", result)
        self.assertIn("transcript", result)
        self.assertIn("verdict", result)
        self.assertIsInstance(result["transcript"], list)

    def test_transcript_has_multiple_turns(self):
        """2轮辩论 → transcript 至少 4 条（bull+bear × 2轮）。"""
        from debate_engine import DebateEngine
        engine = DebateEngine(
            llm_fn=_make_llm(),
            config={},
            cognitive_adapter=_make_cognitive(),
        )
        import asyncio
        result = asyncio.run(engine.run_deep("BTC 是数字黄金"))
        self.assertGreaterEqual(len(result["transcript"]), 4)

    def test_verdict_present(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(
            llm_fn=_make_llm(),
            config={},
            cognitive_adapter=_make_cognitive(),
        )
        import asyncio
        result = asyncio.run(engine.run_deep("BTC 是数字黄金"))
        self.assertIsNotNone(result["verdict"])
        self.assertIn("winner", result["verdict"])

    def test_cognitive_record_called(self):
        """run_deep 后应调用 cognitive.record。"""
        from debate_engine import DebateEngine
        cog = _make_cognitive()
        engine = DebateEngine(
            llm_fn=_make_llm(), config={}, cognitive_adapter=cog,
        )
        import asyncio
        asyncio.run(engine.run_deep("BTC 是数字黄金"))
        self.assertTrue(cog.record.called)

    def test_cognitive_recall_called(self):
        """run_deep 前应调用 cognitive.recall。"""
        from debate_engine import DebateEngine
        cog = _make_cognitive()
        engine = DebateEngine(
            llm_fn=_make_llm(), config={}, cognitive_adapter=cog,
        )
        import asyncio
        asyncio.run(engine.run_deep("BTC 是数字黄金"))
        self.assertTrue(cog.recall.called)

    def test_fail_open_without_cognitive(self):
        """无 cognitive_adapter 时 FAIL-OPEN，不崩溃。"""
        from debate_engine import DebateEngine
        engine = DebateEngine(llm_fn=_make_llm(), config={})
        import asyncio
        result = asyncio.run(engine.run_deep("测试话题"))
        self.assertIn("transcript", result)


class TestInjectMemories(unittest.TestCase):
    """_inject_debate_memories: B+级过滤 + prompt 注入格式。"""

    def test_empty_memories(self):
        from debate_engine import DebateEngine
        engine = DebateEngine(llm_fn=lambda p, m=600: "{}", config={})
        result = engine._inject_debate_memories("BTC", [])
        self.assertEqual(result, "")

    def test_filter_below_b_quality(self):
        """C 级（<0.40）记忆不注入。"""
        from debate_engine import DebateEngine
        memories = [
            {"content": json.dumps({"thesis": "弱论点", "side": "bull", "confidence": 0.3}),
             "quality": "C", "quality_score": 0.2, "verified": False},
        ]
        engine = DebateEngine(llm_fn=lambda p, m=600: "{}", config={})
        result = engine._inject_debate_memories("BTC", memories)
        self.assertEqual(result, "")

    def test_b_quality_injected(self):
        """B 级（≥0.40）记忆注入。"""
        from debate_engine import DebateEngine
        memories = [
            {"content": json.dumps({"thesis": "BTC稀缺性", "side": "bull", "confidence": 0.85}),
             "quality": "B", "quality_score": 0.45, "verified": True},
        ]
        engine = DebateEngine(llm_fn=lambda p, m=600: "{}", config={})
        result = engine._inject_debate_memories("BTC", memories)
        self.assertIn("[历史辩论经验]", result)
        self.assertIn("BTC稀缺性", result)
        self.assertIn("正方", result)
        self.assertIn("0.85", result)

    def test_verified_label(self):
        """已验证记忆标注"已验证"。"""
        from debate_engine import DebateEngine
        memories = [
            {"content": json.dumps({"thesis": "测试", "side": "bull", "confidence": 0.8}),
             "quality": "B", "quality_score": 0.5, "verified": True},
        ]
        engine = DebateEngine(llm_fn=lambda p, m=600: "{}", config={})
        result = engine._inject_debate_memories("BTC", memories)
        self.assertIn("已验证", result)

    def test_max_5_memories(self):
        """最多注入 5 条记忆。"""
        from debate_engine import DebateEngine
        memories = [
            {"content": json.dumps({"thesis": f"论点{i}", "side": "bull", "confidence": 0.8}),
             "quality": "B", "quality_score": 0.5, "verified": True}
            for i in range(10)
        ]
        engine = DebateEngine(llm_fn=lambda p, m=600: "{}", config={})
        result = engine._inject_debate_memories("BTC", memories)
        # 统计注入的论点数
        count = result.count("正方论点")
        self.assertLessEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
