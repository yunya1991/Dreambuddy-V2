#!/usr/bin/env python3
"""
S层三层递进大模型集成测试

位置: experiments/ab-trading/test_s_layer_llm_integration.py

测试场景：
1. Token预算管理器测试（分级告警/消耗/状态）
2. S层三层递进LLM识别测试
3. 经典指标系统接管测试
4. 接管后剩余Token用途测试
5. 前端启动建议测试
6. 端到端集成测试
7. 压力测试（100轮）
"""

import sys
import os
import time
import unittest
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.intent_engine.s_layer_llm_integration import (
    TokenBudgetManager,
    TokenBudgetStatus,
    HandoverLevel,
    SLayerLLMRecognizer,
    ClassicHandoverManager,
)


class TestTokenBudgetManager(unittest.TestCase):
    """Token预算管理器测试"""

    def setUp(self):
        self.budget = TokenBudgetManager(total_budget=10000)

    def test_initial_status(self):
        """测试初始状态"""
        self.assertEqual(self.budget.total_budget, 10000)
        self.assertEqual(self.budget.used_tokens, 0)
        self.assertEqual(self.budget.remaining_tokens, 10000)
        self.assertEqual(self.budget.status, TokenBudgetStatus.HEALTHY)
        self.assertEqual(self.budget.usage_percentage, 0.0)

    def test_consume_tokens(self):
        """测试Token消耗"""
        status = self.budget.consume_tokens(
            prompt_tokens=500,
            completion_tokens=300,
            module="test",
            layer="S",
            operation="test_op",
        )

        self.assertEqual(self.budget.used_tokens, 800)
        self.assertEqual(self.budget.remaining_tokens, 9200)
        self.assertEqual(len(self.budget.usage_history), 1)

        record = self.budget.usage_history[0]
        self.assertEqual(record.prompt_tokens, 500)
        self.assertEqual(record.completion_tokens, 300)
        self.assertEqual(record.total_tokens, 800)
        self.assertEqual(record.layer, "S")

    def test_status_progression(self):
        """测试状态变化（健康→警告→低→严重→耗尽）"""
        # 初始状态：健康
        self.assertEqual(self.budget.status, TokenBudgetStatus.HEALTHY)

        # 消耗30% → 警告（70%阈值）
        self.budget.consume_tokens(0, 3000)  # 30%
        self.assertEqual(self.budget.status, TokenBudgetStatus.WARNING)

        # 消耗到30%以下 → 低
        self.budget.consume_tokens(0, 5000)  # 80% total
        self.assertEqual(self.budget.status, TokenBudgetStatus.LOW)

        # 消耗到10%以下 → 严重
        self.budget.consume_tokens(0, 1500)  # 95% total
        self.assertEqual(self.budget.status, TokenBudgetStatus.CRITICAL)

        # 消耗完 → 耗尽
        self.budget.consume_tokens(0, 500)  # 100%
        self.assertEqual(self.budget.status, TokenBudgetStatus.EXHAUSTED)

    def test_alerts_generation(self):
        """测试告警生成"""
        # 初始无告警
        self.assertEqual(len(self.budget.alerts), 0)

        # 消耗到警告阈值
        self.budget.consume_tokens(0, 3500)  # 35%
        self.assertEqual(self.budget.status, TokenBudgetStatus.WARNING)
        self.assertGreaterEqual(len(self.budget.alerts), 1)
        self.assertTrue(any(a.level == "warning" for a in self.budget.alerts))

        # 继续消耗到低阈值
        self.budget.consume_tokens(0, 4000)  # 75%
        self.assertEqual(self.budget.status, TokenBudgetStatus.LOW)
        self.assertTrue(any(a.level == "low" for a in self.budget.alerts))

    def test_handover_authorization(self):
        """测试接管授权"""
        self.assertFalse(self.budget.handover_authorized)

        # 授权
        result = self.budget.authorize_handover(HandoverLevel.FULL)
        self.assertTrue(result)
        self.assertTrue(self.budget.handover_authorized)
        self.assertEqual(self.budget.handover_level, HandoverLevel.FULL)
        self.assertEqual(self.budget.status, TokenBudgetStatus.HANDOVER_TRIGGERED)

        # 撤销
        result = self.budget.revoke_handover()
        self.assertTrue(result)
        self.assertFalse(self.budget.handover_authorized)
        self.assertEqual(self.budget.handover_level, HandoverLevel.NONE)

    def test_get_handover_suggestion(self):
        """测试获取接管建议"""
        # 健康状态
        suggestion = self.budget.get_handover_suggestion()
        self.assertEqual(suggestion["current_status"], "healthy")
        self.assertEqual(suggestion["handover_level"], "none")

        # 消耗到低余额
        self.budget.consume_tokens(0, 7500)  # 75%
        suggestion = self.budget.get_handover_suggestion()
        self.assertEqual(suggestion["current_status"], "low")
        self.assertGreater(len(suggestion["suggestions"]), 0)

        # 授权接管
        self.budget.authorize_handover(HandoverLevel.FULL)
        suggestion = self.budget.get_handover_suggestion()
        self.assertTrue(suggestion["handover_authorized"])
        self.assertIn("remaining_token_usage", suggestion)
        self.assertGreater(len(suggestion["remaining_token_usage"]), 0)

    def test_can_use_llm_for_adjustment(self):
        """测试是否可以使用LLM调整策略"""
        # Token充足
        self.assertTrue(self.budget.can_use_llm_for_adjustment())

        # Token不足
        self.budget.consume_tokens(0, 9500)
        self.assertFalse(self.budget.can_use_llm_for_adjustment())

    def test_layer_usage_tracking(self):
        """测试各层Token使用追踪"""
        self.budget.consume_tokens(100, 50, layer="S")
        self.budget.consume_tokens(200, 100, layer="C")
        self.budget.consume_tokens(50, 30, layer="A")

        stats = self.budget.get_stats()
        self.assertIn("layer_usage", stats)
        self.assertGreater(stats["layer_usage"].get("S", 0), 0)
        self.assertGreater(stats["layer_usage"].get("C", 0), 0)


class TestSLayerLLMRecognizer(unittest.TestCase):
    """S层三层递进LLM识别器测试"""

    def setUp(self):
        self.recognizer = SLayerLLMRecognizer(config={'token_budget': 20000})

    def test_recognize_simple_query(self):
        """测试简单查询识别"""
        result = self.recognizer.recognize("BTC行情怎么样")

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["objective"])
        self.assertIsNotNone(result["okr_set"])
        self.assertIsNotNone(result["blueprint"])
        self.assertIn(result["recognition_mode"], ["llm_full", "local_fallback"])
        self.assertGreater(result["token_used"], 0)

    def test_recognize_deep_analysis(self):
        """测试深度分析识别"""
        result = self.recognizer.recognize("深度分析ETH的技术面和基本面")

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["objective"])
        self.assertEqual(result["objective"]["complexity"], "deep")
        self.assertEqual(result["okr_set"]["mode"], "multi")
        self.assertGreater(len(result["blueprint"]["node_sequence"]), 3)

    def test_recognize_trading_decision(self):
        """测试交易决策识别"""
        result = self.recognizer.recognize("现在可以买入BTC吗")

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["objective"])
        self.assertIn("交易", result["objective"]["title"])

    def test_recognize_risk_assessment(self):
        """测试风险评估识别"""
        result = self.recognizer.recognize("评估我的交易风险")

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["objective"])
        self.assertIn("风险", result["objective"]["title"])

    def test_recognize_concept_explanation(self):
        """测试概念解释识别"""
        result = self.recognizer.recognize("什么是MACD指标")

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["objective"])
        self.assertEqual(result["objective"]["complexity"], "simple")

    def test_token_consumption_during_recognition(self):
        """测试识别过程中的Token消耗"""
        initial_remaining = self.recognizer.token_budget.remaining_tokens

        result = self.recognizer.recognize("分析BTC趋势")

        final_remaining = self.recognizer.token_budget.remaining_tokens
        self.assertLess(final_remaining, initial_remaining)
        self.assertEqual(result["token_used"], initial_remaining - final_remaining)

    def test_force_local_recognition(self):
        """测试强制本地识别"""
        result = self.recognizer.recognize("BTC价格多少", force_local=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["recognition_mode"], "local_fallback")
        self.assertEqual(result["token_used"], 0)

    def test_low_token_fallback_to_local(self):
        """测试Token不足时降级到本地"""
        # 设置很低的预算
        recognizer = SLayerLLMRecognizer(config={'token_budget': 500})

        # 第一次可能用LLM（如果Token还够）
        result1 = recognizer.recognize("分析BTC")
        self.assertTrue(result1["success"])

        # 消耗大部分Token
        recognizer.token_budget.consume_tokens(0, 400)

        # 再次识别，应该降级到本地
        result2 = recognizer.recognize("分析ETH")
        self.assertTrue(result2["success"])
        # Token不足时应降级
        if recognizer.token_budget.status == TokenBudgetStatus.CRITICAL:
            self.assertEqual(result2["recognition_mode"], "local_fallback")

    def test_adjust_strategy_params(self):
        """测试策略参数调整"""
        current_params = {
            "position_size": 1.0,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 10.0,
        }

        result = self.recognizer.adjust_strategy_params(
            strategy_id="BreakoutStrategy",
            user_request="降低风险，更保守一点",
            current_params=current_params,
        )

        self.assertTrue(result["success"])
        self.assertIn("suggested_params", result)
        self.assertLess(
            result["suggested_params"]["position_size"],
            current_params["position_size"]
        )
        self.assertGreater(result["remaining_tokens"], 0)

    def test_explain_classic_result(self):
        """测试经典指标结果解释"""
        result_data = {
            "signal": "LONG",
            "confidence": 0.75,
            "rsi": 35.2,
            "macd": "golden_cross",
        }

        result = self.recognizer.explain_classic_result(result_data)

        self.assertTrue(result["success"])
        self.assertIn("explanation", result)
        self.assertIn("original_result", result)
        self.assertGreater(len(result["explanation"]), 0)

    def test_suggest_frontend_start(self):
        """测试前端启动建议"""
        # 先消耗到严重不足
        self.recognizer.token_budget.consume_tokens(0, 19000)

        suggestion = self.recognizer.suggest_frontend_start()

        self.assertEqual(suggestion["type"], "frontend_takeover_suggestion")
        self.assertIn("benefits", suggestion)
        self.assertIn("actions", suggestion)
        self.assertGreater(len(suggestion["benefits"]), 0)
        self.assertGreater(len(suggestion["actions"]), 0)


class TestClassicHandoverManager(unittest.TestCase):
    """经典指标系统接管管理器测试"""

    def setUp(self):
        self.recognizer = SLayerLLMRecognizer(config={'token_budget': 10000})
        self.manager = ClassicHandoverManager(
            s_layer_recognizer=self.recognizer,
            classic_api_url="http://127.0.0.1:8092",
        )

    def test_request_handover(self):
        """测试请求接管"""
        request = self.manager.request_handover(
            level="full",
            reason="Token不足",
        )

        self.assertIn("request_id", request)
        self.assertEqual(request["status"], "pending_authorization")
        self.assertTrue(request["requires_user_action"])
        self.assertIn("authorization_action", request)
        self.assertIn("what_happens_next", request)
        self.assertGreater(len(request["what_happens_next"]), 0)

    def test_authorize_handover(self):
        """测试授权接管"""
        result = self.manager.authorize_handover(level="full")

        self.assertTrue(result["success"])
        self.assertTrue(result["handover_active"])
        self.assertEqual(result["handover_level"], "full")
        self.assertIn("remaining_token_purpose", result)
        self.assertGreater(len(result["remaining_token_purpose"]), 0)
        self.assertIn("classic_system_info", result)
        self.assertIn("frontend_suggestion", result)

    def test_authorize_partial_handover(self):
        """测试部分接管授权"""
        result = self.manager.authorize_handover(level="partial")

        self.assertTrue(result["success"])
        self.assertTrue(result["handover_active"])
        self.assertEqual(result["handover_level"], "partial")
        # 部分接管不建议启动前端
        self.assertNotIn("frontend_suggestion", result)

    def test_revoke_handover(self):
        """测试撤销接管"""
        # 先授权
        self.manager.authorize_handover(level="full")
        self.assertTrue(self.recognizer.token_budget.handover_authorized)

        # 再撤销
        result = self.manager.revoke_handover()
        self.assertTrue(result["success"])
        self.assertFalse(result["handover_active"])
        self.assertFalse(self.recognizer.token_budget.handover_authorized)

    def test_start_frontend(self):
        """测试启动前端"""
        result = self.manager.start_frontend()

        self.assertTrue(result["success"])
        self.assertTrue(result["frontend_started"])
        self.assertIn("frontend_url", result)
        self.assertIn("features", result)
        self.assertGreater(len(result["features"]), 0)

    def test_adjust_strategy_after_handover(self):
        """测试接管后调整策略"""
        # 先授权接管
        self.manager.authorize_handover(level="full")

        current_params = {
            "position_size": 1.0,
            "timeframe": "4h",
        }

        result = self.manager.adjust_strategy(
            strategy_id="RegimeHybridStrategy",
            user_request="增加收益，更激进一些",
            current_params=current_params,
        )

        self.assertTrue(result["success"])
        self.assertIn("suggested_params", result)

    def test_explain_result_after_handover(self):
        """测试接管后解释结果"""
        # 先授权接管
        self.manager.authorize_handover(level="full")

        result_data = {"signal": "SHORT", "confidence": 0.7}
        result = self.manager.explain_result(result_data)

        self.assertTrue(result["success"])
        self.assertIn("explanation", result)

    def test_get_stats(self):
        """测试获取统计"""
        stats = self.manager.get_stats()

        self.assertIn("handover_active", stats)
        self.assertIn("handover_level", stats)
        self.assertIn("token_stats", stats)
        self.assertIn("classic_api_url", stats)


class TestEndToEndIntegration(unittest.TestCase):
    """端到端集成测试"""

    def test_full_user_journey(self):
        """测试完整用户旅程：正常使用→Token不足→接管→策略调整"""
        # Step 1: 初始正常使用
        recognizer = SLayerLLMRecognizer(config={'token_budget': 20000})
        manager = ClassicHandoverManager(s_layer_recognizer=recognizer)

        result1 = recognizer.recognize("分析BTC趋势")
        self.assertTrue(result1["success"])
        self.assertIn(result1["token_status"], ["healthy", "warning"])

        # Step 2: 消耗到警告/低状态
        recognizer.token_budget.consume_tokens(0, 5000)
        result2 = recognizer.recognize("分析ETH")
        self.assertTrue(result2["success"])
        self.assertIn(result2["token_status"], ["warning", "low"])

        # Step 3: 消耗到低状态（但还能调整策略）
        recognizer.token_budget.consume_tokens(0, 8000)
        result3 = recognizer.recognize("分析SOL")
        self.assertTrue(result3["success"])
        self.assertIn(result3["token_status"], ["low", "critical", "warning"])

        # Step 4: 用户授权接管
        handover_result = manager.authorize_handover(level="full")
        self.assertTrue(handover_result["success"])

        # Step 5: 接管后调整策略
        adjust_result = manager.adjust_strategy(
            strategy_id="BreakoutStrategy",
            user_request="降低风险",
            current_params={"position_size": 1.0},
        )
        self.assertTrue(adjust_result["success"])

        # Step 6: 解释经典指标结果
        explain_result = manager.explain_result({"signal": "LONG", "confidence": 0.8})
        self.assertTrue(explain_result["success"])

        # Step 7: 启动前端
        frontend_result = manager.start_frontend()
        self.assertTrue(frontend_result["success"])
        self.assertTrue(frontend_result["frontend_started"])

    def test_multiple_intent_types(self):
        """测试多种意图类型的三层识别"""
        recognizer = SLayerLLMRecognizer(config={'token_budget': 20000})

        test_cases = [
            "BTC趋势分析",
            "ETH基本面分析",
            "现在可以买入吗",
            "评估风险",
            "什么是RSI",
            "深度分析SOL",
            "查看持仓",
            "市场情绪怎么样",
        ]

        for query in test_cases:
            result = recognizer.recognize(query)
            self.assertTrue(result["success"], f"Failed for: {query}")
            self.assertIsNotNone(result["objective"])
            self.assertIsNotNone(result["okr_set"])
            self.assertIsNotNone(result["blueprint"])


class TestStress100Rounds(unittest.TestCase):
    """100轮压力测试"""

    def test_100_rounds_recognition(self):
        """100轮识别压力测试"""
        recognizer = SLayerLLMRecognizer(config={'token_budget': 50000})

        test_queries = [
            "BTC趋势分析",
            "ETH可以买入吗",
            "什么是MACD",
            "风险评估",
            "深度分析SOL",
            "持仓回顾",
            "市场情绪",
            "技术分析",
            "基本面分析",
            "策略调整",
        ]

        total_rounds = 100
        success_count = 0
        total_latency = 0.0

        for i in range(total_rounds):
            query = test_queries[i % len(test_queries)]
            start = time.time()
            result = recognizer.recognize(query)
            latency = (time.time() - start) * 1000
            total_latency += latency

            if result["success"]:
                success_count += 1

        success_rate = success_count / total_rounds
        avg_latency = total_latency / total_rounds

        # 打印统计
        stats = recognizer.token_budget.get_stats()
        print(f"\n  100轮压力测试统计:")
        print(f"    成功率: {success_rate:.2%}")
        print(f"    平均延迟: {avg_latency:.2f}ms")
        print(f"    总Token消耗: {stats['used_tokens']}")
        print(f"    剩余Token: {stats['remaining_tokens']}")

        # 验证
        self.assertGreater(success_rate, 0.9, f"成功率应>90%, 实际: {success_rate:.2%}")
        self.assertGreater(stats["used_tokens"], 0, "应有Token消耗")


if __name__ == '__main__':
    unittest.main(verbosity=2)