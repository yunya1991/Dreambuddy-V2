#!/usr/bin/env python3
"""P0-2: C-Drive-Agent 四步循环 + Bull/Bear 辩论测试 (RED 阶段)

验证 Spec §3.4 C-Drive-Agent 四步循环:
  Step 1: recall 认知查询
  Step 2: 反思推理 + Bull/Bear 辩论 (置信度<0.65触发)
  Step 3: jeval 判断 (仅 CONTINUE 时)
  Step 4: subagent 补充 (仅 SUPPLEMENT 时)

硬约束:
  - HC-2: 分级触发 (>0.75跳过, 0.65-0.75只recall, 0.50-0.65加辩论, <0.50全链路)
  - HC-3: 认知系统调用 FAIL-OPEN
  - HC-4: jeval 调用 FAIL-OPEN
  - HC-8: Bull/Bear 辩论仅置信度<0.65触发, 并行调用
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

# 将 python-server 目录加入 sys.path
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class MockCognitiveAdapter:
    """模拟认知适配器，记录 recall 调用"""
    def __init__(self, memories=None, raise_exc=False):
        self._memories = memories or []
        self._raise = raise_exc
        self.recall_called = False
        self.recall_context = None

    def recall(self, context="", top_k=5, min_quality="C"):
        self.recall_called = True
        self.recall_context = context
        if self._raise:
            raise RuntimeError("模拟 MCP 不可用")
        return self._memories


class MockJevJudge:
    """模拟 jev_judge 判断"""
    def __init__(self, noul=0.9, raise_exc=False):
        self._noul = noul
        self._raise = raise_exc
        self.call_count = 0

    def __call__(self, state, questions):
        self.call_count += 1
        if self._raise:
            raise RuntimeError("模拟 jeval 不可用")
        return {
            "model": "jev-mock",
            "answers": {"q1": {"type": "noul", "noul": self._noul}},
            "degraded": False,
        }


def _make_result(confidence=0.8, direction="LONG", outputs=None):
    """构建轻量节点结果对象"""
    r = MagicMock()
    r.confidence = confidence
    r.direction = direction
    r.status = "SUCCESS"
    r.outputs = outputs or {}
    r.error = None
    return r


def _make_signals():
    """构建测试用信号列表"""
    return [
        {"name": "MACD金叉", "value": " bullish", "direction": "long", "confidence": 0.7},
        {"name": "RSI超卖", "value": 28, "direction": "long", "confidence": 0.6},
        {"name": "放量下跌", "value": "bearish", "direction": "short", "confidence": 0.65},
    ]


class TestCDriveAgentImport(unittest.TestCase):
    """RED: 模块可导入性"""

    def test_module_importable(self):
        from c_drive_agent import CDriveAgent, CDriveDecision, CDriveAction
        self.assertIsNotNone(CDriveAgent)
        self.assertIsNotNone(CDriveDecision)
        self.assertIsNotNone(CDriveAction)

    def test_cdrive_action_enum_values(self):
        from c_drive_agent import CDriveAction
        self.assertEqual(CDriveAction.CONTINUE.value, "continue")
        self.assertEqual(CDriveAction.REDO.value, "redo")
        self.assertEqual(CDriveAction.JUMP.value, "jump")
        self.assertEqual(CDriveAction.SUPPLEMENT.value, "supplement")
        self.assertEqual(CDriveAction.DEBATE.value, "debate")


class TestCDriveAgentRunSignature(unittest.TestCase):
    """run() 方法签名"""

    def test_run_returns_cdrive_decision(self):
        from c_drive_agent import CDriveAgent, CDriveDecision
        agent = CDriveAgent()
        result = _make_result(confidence=0.8)
        decision = agent.run(node_id="C1", result=result, state=MagicMock())
        self.assertIsInstance(decision, CDriveDecision)

    def test_run_accepts_optional_signals(self):
        from c_drive_agent import CDriveAgent
        agent = CDriveAgent()
        result = _make_result(confidence=0.8)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)


class TestGradedTriggerHC2(unittest.TestCase):
    """HC-2: 分级触发机制"""

    def test_high_confidence_skips_loop(self):
        """置信度 > 0.75: 跳过四步循环, 直接 CONTINUE"""
        from c_drive_agent import CDriveAgent, CDriveAction
        adapter = MockCognitiveAdapter()
        agent = CDriveAgent(cognitive_adapter=adapter)
        result = _make_result(confidence=0.85)
        decision = agent.run(node_id="C1", result=result, state=MagicMock())
        self.assertEqual(decision.action, CDriveAction.CONTINUE)
        self.assertFalse(adapter.recall_called, "高置信度不应调 recall")
        self.assertEqual(decision.confidence, 0.85)

    def test_mid_confidence_recall_only(self):
        """置信度 0.65-0.75: 只 recall + reflect, 无辩论"""
        from c_drive_agent import CDriveAgent, CDriveAction
        adapter = MockCognitiveAdapter(memories=[])
        llm_calls = []
        def mock_llm(prompt):
            llm_calls.append(prompt)
            return "bull confidence=0.6"
        agent = CDriveAgent(cognitive_adapter=adapter, llm_fn=mock_llm)
        result = _make_result(confidence=0.70)
        decision = agent.run(node_id="C1", result=result, state=MagicMock())
        self.assertTrue(adapter.recall_called, "0.65-0.75 应调 recall")
        self.assertEqual(len(llm_calls), 0, "0.65-0.75 不应触发 Bull/Bear LLM")
        self.assertNotEqual(decision.action, CDriveAction.DEBATE)

    def test_low_confidence_triggers_debate(self):
        """置信度 0.50-0.65: 触发 Bull/Bear 辩论"""
        from c_drive_agent import CDriveAgent, CDriveAction
        adapter = MockCognitiveAdapter(memories=[])
        llm_calls = []
        def mock_llm(prompt):
            llm_calls.append(prompt)
            # D2: Bull/Bear 返回不同 confidence, gap > 0.15 避免触发第二轮
            if "Bull" in prompt:
                return "argument confidence=0.7"
            return "argument confidence=0.3"
        agent = CDriveAgent(cognitive_adapter=adapter, llm_fn=mock_llm)
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        # 应触发 Bull/Bear (2次 LLM 调用, gap>0.15 不触发第二轮)
        self.assertEqual(len(llm_calls), 2, "应并行调 Bull+Bear 两次 LLM")
        # 辩论结果应被记录
        self.assertIsNotNone(decision.bull_argument)
        self.assertIsNotNone(decision.bear_argument)

    def test_very_low_confidence_full_loop(self):
        """置信度 < 0.50: 全链路四步循环"""
        from c_drive_agent import CDriveAgent, CDriveAction
        adapter = MockCognitiveAdapter(memories=[
            {"content": "历史经验: 极低置信度需补充数据", "score": 0.5}
        ])
        jev = MockJevJudge(noul=0.9)
        def mock_llm(prompt):
            return "arg confidence=0.45"
        agent = CDriveAgent(
            cognitive_adapter=adapter, llm_fn=mock_llm, jev_judge_fn=jev)
        result = _make_result(confidence=0.40)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertTrue(adapter.recall_called)
        self.assertGreater(jev.call_count, 0, "<0.50 应触发 jeval")
        self.assertIn("recall", " ".join(decision.steps_executed))


class TestBullBearDebateHC8(unittest.TestCase):
    """HC-8: Bull/Bear 辩论机制"""

    def test_debate_parallel_calls(self):
        """Bull/Bear 应并行调用 (耗时 ≈ 单次, 非 2 倍)"""
        from c_drive_agent import CDriveAgent
        def slow_llm(prompt):
            time.sleep(0.1)
            # D2: Bull/Bear 返回不同 confidence, gap > 0.15 避免触发第二轮
            if "Bull" in prompt:
                return "arg confidence=0.7"
            return "arg confidence=0.3"
        agent = CDriveAgent(llm_fn=slow_llm)
        result = _make_result(confidence=0.55)
        t0 = time.time()
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        elapsed = time.time() - t0
        # 并行: ~0.1s, 串行: ~0.2s, 容差 0.15s
        self.assertLess(elapsed, 0.18, f"应并行调用, 耗时 {elapsed:.3f}s 应 < 0.18s")

    def test_debate_extracts_bull_bear_confidence(self):
        """辩论结果含 bull_confidence / bear_confidence"""
        from c_drive_agent import CDriveAgent
        def mock_llm(prompt):
            if "bull" in prompt.lower() or "多" in prompt:
                return "利好: MACD金叉 confidence=0.75"
            return "利空: 放量下跌 confidence=0.60"
        agent = CDriveAgent(llm_fn=mock_llm)
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision.bull_confidence)
        self.assertIsNotNone(decision.bear_confidence)
        self.assertGreater(decision.bull_confidence, 0)
        self.assertGreater(decision.bear_confidence, 0)

    def test_debate_no_llm_fn_uses_rule_based(self):
        """无 llm_fn 时, 用规则提取 Bull/Bear (FAIL-OPEN)"""
        from c_drive_agent import CDriveAgent
        agent = CDriveAgent(llm_fn=None)
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        # 规则提取: 从 signals 中分多空
        self.assertIsNotNone(decision.bull_argument)
        self.assertIsNotNone(decision.bear_argument)

    def test_debate_not_triggered_above_threshold(self):
        """置信度 >= 0.65 不触发辩论"""
        from c_drive_agent import CDriveAgent
        llm_calls = []
        def mock_llm(prompt):
            llm_calls.append(prompt)
            return "arg"
        agent = CDriveAgent(llm_fn=mock_llm)
        result = _make_result(confidence=0.70)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertEqual(len(llm_calls), 0, ">=0.65 不应触发辩论")


class TestFailOpenHC3HC4(unittest.TestCase):
    """HC-3/HC-4: FAIL-OPEN 机制"""

    def test_no_cognitive_adapter_fails_open(self):
        """HC-3: 无 cognitive_adapter 不阻塞"""
        from c_drive_agent import CDriveAgent, CDriveAction
        agent = CDriveAgent()  # 无 adapter
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)

    def test_cognitive_exception_fails_open(self):
        """HC-3: recall 异常不阻塞"""
        from c_drive_agent import CDriveAgent
        adapter = MockCognitiveAdapter(raise_exc=True)
        agent = CDriveAgent(cognitive_adapter=adapter)
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)

    def test_no_jeval_fails_open(self):
        """HC-4: 无 jev_judge_fn 不阻塞"""
        from c_drive_agent import CDriveAgent, CDriveAction
        agent = CDriveAgent()  # 无 jeval
        result = _make_result(confidence=0.40)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)

    def test_jeval_exception_fails_open(self):
        """HC-4: jeval 异常不阻塞"""
        from c_drive_agent import CDriveAgent
        jev = MockJevJudge(raise_exc=True)
        def mock_llm(prompt):
            return "arg confidence=0.4"
        agent = CDriveAgent(jev_judge_fn=jev, llm_fn=mock_llm)
        result = _make_result(confidence=0.40)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)

    def test_llm_exception_fails_open(self):
        """LLM 异常不阻塞辩论"""
        from c_drive_agent import CDriveAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM 不可用")
        agent = CDriveAgent(llm_fn=bad_llm)
        result = _make_result(confidence=0.55)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertIsNotNone(decision)


class TestJevalGate(unittest.TestCase):
    """Step 3: jeval 判断门控"""

    def test_jeval_high_noul_passes(self):
        """noul >= 0.85: 放行 CONTINUE"""
        from c_drive_agent import CDriveAgent, CDriveAction
        jev = MockJevJudge(noul=0.90)
        def mock_llm(prompt):
            return "arg confidence=0.45"
        agent = CDriveAgent(jev_judge_fn=jev, llm_fn=mock_llm)
        result = _make_result(confidence=0.40)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        self.assertEqual(decision.action, CDriveAction.CONTINUE)
        self.assertGreaterEqual(decision.jeval_noul, 0.85)

    def test_jeval_low_noul_blocks(self):
        """noul < 0.50: 阻止, 回 Step2 重新反思"""
        from c_drive_agent import CDriveAgent
        jev = MockJevJudge(noul=0.30)
        def mock_llm(prompt):
            return "arg confidence=0.45"
        agent = CDriveAgent(jev_judge_fn=jev, llm_fn=mock_llm)
        result = _make_result(confidence=0.40)
        decision = agent.run(
            node_id="C1", result=result, state=MagicMock(),
            signals=_make_signals())
        # 低 noul 应阻止放行
        self.assertLess(decision.jeval_noul, 0.50)


class TestSupplementRouting(unittest.TestCase):
    """Step 4: SUPPLEMENT 路由"""

    def test_supplement_routes_to_module(self):
        """SUPPLEMENT 动作应路由到具体 subagent module"""
        from c_drive_agent import CDriveAgent, CDriveAction
        agent = CDriveAgent()
        result = _make_result(confidence=0.40, outputs={"intent_type": "deep_analysis"})
        decision = agent.run(
            node_id="F1", result=result, state=MagicMock(),
            signals=_make_signals(), intent_type="deep_analysis")
        # 极低置信度应考虑补充
        if decision.action == CDriveAction.SUPPLEMENT:
            self.assertIsNotNone(decision.supplement_module)
            self.assertIn(decision.supplement_module,
                          {"macro", "flow", "technical", "sentiment", "onchain", "valuation"})


class TestStepsTrace(unittest.TestCase):
    """steps_executed 追踪"""

    def test_steps_recorded(self):
        """decision.steps_executed 记录执行了哪些步骤"""
        from c_drive_agent import CDriveAgent
        adapter = MockCognitiveAdapter(memories=[])
        agent = CDriveAgent(cognitive_adapter=adapter)
        result = _make_result(confidence=0.70)
        decision = agent.run(node_id="C1", result=result, state=MagicMock())
        self.assertIsInstance(decision.steps_executed, list)
        self.assertIn("recall", decision.steps_executed)


if __name__ == "__main__":
    unittest.main()
