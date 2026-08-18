#!/usr/bin/env python3
"""
动态意图识别器测试 (Dynamic Intent Recognizer Test)

位置: experiments/ab-trading/test_dynamic_intent_recognizer.py

测试场景：
1. 本地规则识别测试（20+金融意图类型）
2. S思维链LLM降级测试
3. 自定义意图注册测试
4. 从LLM结果学习测试
5. 多轮对话意图识别测试
6. 压力测试（200轮）
"""

import sys
import os
import time
import unittest
import json
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.intent_engine.dynamic_intent_recognizer import (
    DynamicIntentRecognizer,
    DynamicIntentResult,
    DynamicIntentType,
    SChainLLMRecognizer,
    FINANCE_INTENT_KNOWLEDGE_BASE,
)


class TestDynamicIntentRecognizer(unittest.TestCase):
    """动态意图识别器测试套件"""

    def setUp(self):
        """初始化测试环境"""
        self.recognizer = DynamicIntentRecognizer()

    # ============================================================
    # 场景1: 本地规则识别测试（20+金融意图类型）
    # ============================================================

    def test_local_recognition_trading_intents(self):
        """测试交易类意图本地识别"""
        test_cases = [
            ("我想买入BTC现货", "spot_trade", "现货交易"),
            ("帮我开一个ETH合约做多", "futures_trade", "合约交易"),
            ("取消我的订单", "order_management", "订单管理"),
            ("查看我的持仓仓位", "position_management", "仓位管理"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    def test_local_recognition_analysis_intents(self):
        """测试分析类意图本地识别"""
        test_cases = [
            ("帮我做技术分析", "technical_analysis", "技术分析"),
            ("ETH基本面分析", "fundamental_analysis", "基本面分析"),
            ("市场情绪分析", "sentiment_analysis", "情绪分析"),
            ("成交量分析", "volume_analysis", "成交量分析"),
            ("巨鲸追踪", "whale_tracking", "巨鲸追踪"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    def test_local_recognition_risk_intents(self):
        """测试风险类意图本地识别"""
        test_cases = [
            ("风险评估", "risk_assessment", "风险评估"),
            ("爆仓检查", "liquidation_check", "爆仓检查"),
            ("再平衡建议", "rebalance_suggestion", "再平衡建议"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    def test_local_recognition_portfolio_intents(self):
        """测试投资组合类意图本地识别"""
        test_cases = [
            ("组合回顾", "portfolio_review", "组合回顾"),
            ("资产配置", "asset_allocation", "资产配置"),
            ("分散化检查", "diversification_check", "分散化检查"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    def test_local_recognition_education_intents(self):
        """测试教育类意图本地识别"""
        test_cases = [
            ("什么是MACD", "concept_explanation", "概念解释"),
            ("如何交易", "strategy_learning", "策略学习"),
            ("指标使用方法", "indicator_usage", "指标使用"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    def test_local_recognition_research_intents(self):
        """测试研究类意图本地识别"""
        test_cases = [
            ("市场调研", "market_research", "市场调研"),
            ("项目调研", "project_research", "项目调研"),
            ("对比分析", "comparative_analysis", "对比分析"),
        ]

        for user_msg, expected_type, expected_name in test_cases:
            result = self.recognizer.recognize(user_msg)

            self.assertEqual(result.intent_type, expected_type,
                f"输入: {user_msg}, 期望: {expected_type}, 实际: {result.intent_type}")
            self.assertEqual(result.intent_name, expected_name,
                f"输入: {user_msg}, 期望: {expected_name}, 实际: {result.intent_name}")
            self.assertGreater(result.confidence, 0.4,
                f"输入: {user_msg}, 置信度过低: {result.confidence}")
            self.assertEqual(result.recognition_source, 'local',
                f"输入: {user_msg}, 应为本地识别")

    # ============================================================
    # 场景2: S思维链LLM降级测试
    # ============================================================

    def test_llm_fallback_threshold(self):
        """测试LLM降级阈值"""
        # 创建一个低阈值配置的识别器
        recognizer = DynamicIntentRecognizer(config={
            'llm_fallback_threshold': 0.6,  # 设置较高阈值
            'enable_learning': True,
            'enable_cache': False,
        })

        # 输入一个模糊的意图，触发LLM降级
        result = recognizer.recognize("今天天气怎么样")  # 非金融意图

        self.assertLess(result.confidence, 0.6,
            f"低置信度输入应触发LLM降级，置信度: {result.confidence}")
        # 由于是模拟LLM，会返回llm_s_chain来源
        self.assertIn(result.recognition_source, ['llm_s_chain', 'local_no_match'],
            f"识别来源应为LLM降级或无匹配")

    def test_force_llm_recognition(self):
        """测试强制使用LLM识别"""
        result = self.recognizer.recognize(
            "分析一下BTC",
            force_llm=True,
        )

        self.assertEqual(result.recognition_source, 'llm_s_chain',
            f"强制LLM识别，来源应为llm_s_chain")
        self.assertGreater(result.llm_tokens_used, 0,
            f"LLM识别应有Token消耗")
        self.assertGreater(result.latency_ms, 0,
            f"LLM识别应有耗时")

    def test_llm_s_chain_prompt_structure(self):
        """测试S思维链Prompt结构"""
        llm_recognizer = SChainLLMRecognizer()
        prompt = llm_recognizer._build_s_chain_prompt(
            "我想买入BTC",
            context={'symbol': 'BTC'},
            fallback_local_result=None,
        )

        # 验证Prompt包含S链三层结构
        self.assertIn('Layer 1', prompt, "Prompt应包含Layer 1: 收敛")
        self.assertIn('Layer 2', prompt, "Prompt应包含Layer 2: 展开")
        self.assertIn('Layer 3', prompt, "Prompt应包含Layer 3: 落地")
        self.assertIn('Objective', prompt, "Prompt应包含Objective关键词")
        self.assertIn('OKR', prompt, "Prompt应包含OKR关键词")
        self.assertIn('Blueprint', prompt, "Prompt应包含Blueprint关键词")

    # ============================================================
    # 场景3: 自定义意图注册测试
    # ============================================================

    def test_custom_intent_registration(self):
        """测试自定义意图注册"""
        custom_intent_def = {
            'intent_id': 'nft_trade',
            'name': 'NFT交易',
            'category': 'trading',
            'description': 'NFT买卖交易',
            'keywords': ['NFT', 'nft', '数字藏品'],
            'patterns': [r'nft.*交易', r'数字藏品'],
            'domain_tags': ['trading', 'nft'],
            'confidence_base': 0.7,
            'recommended_chain': 'S+F',
            'priority': 7,
        }

        success = self.recognizer.register_custom_intent(custom_intent_def)
        self.assertTrue(success, "自定义意图注册应成功")

        # 测试识别自定义意图
        result = self.recognizer.recognize("NFT交易")
        self.assertEqual(result.intent_type, 'nft_trade',
            f"应识别为自定义意图nft_trade，实际: {result.intent_type}")
        self.assertEqual(result.intent_name, 'NFT交易',
            f"意图名称应为NFT交易，实际: {result.intent_name}")

    def test_invalid_custom_intent_registration(self):
        """测试无效自定义意图注册"""
        invalid_def = {
            'name': '无效意图',  # 缺少intent_id
            'keywords': ['test'],
        }

        success = self.recognizer.register_custom_intent(invalid_def)
        self.assertFalse(success, "无效自定义意图注册应失败")

    # ============================================================
    # 场景4: 从LLM结果学习测试
    # ============================================================

    def test_learning_from_llm_result(self):
        """测试从LLM结果学习"""
        # 创建启用学习的识别器
        recognizer = DynamicIntentRecognizer(config={
            'llm_fallback_threshold': 0.3,
            'enable_learning': True,
            'enable_cache': False,
        })

        # 强制LLM识别一个新意图
        result = recognizer.recognize(
            "帮我分析一下DeFi项目的流动性挖矿收益",
            force_llm=True,
        )

        # 检查学习结果
        learned_intents = recognizer.llm_recognizer.get_learned_intents()
        if result.confidence >= 0.6:
            self.assertIn(result.intent_type, learned_intents,
                f"高置信度LLM结果应被学习: {result.intent_type}")
            learned_intent = learned_intents[result.intent_type]
            self.assertEqual(learned_intent.learned_count, 1,
                f"学习计数应为1")

    def test_learning_count_increment(self):
        """测试学习计数递增"""
        recognizer = DynamicIntentRecognizer(config={
            'enable_learning': True,
            'enable_cache': False,
        })

        # 多次识别同一意图
        for _ in range(3):
            result = recognizer.recognize("新的交易模式xyz", force_llm=True)

        learned_intents = recognizer.llm_recognizer.get_learned_intents()
        if result.intent_type in learned_intents:
            self.assertGreater(learned_intents[result.intent_type].learned_count, 1,
                f"多次识别同一意图应递增学习计数")

    # ============================================================
    # 场景5: 多轮对话意图识别测试
    # ============================================================

    def test_multi_turn_intent_recognition(self):
        """测试多轮对话意图识别"""
        # 第一轮：简单查询
        result1 = self.recognizer.recognize("现货买卖")
        self.assertEqual(result1.intent_type, 'spot_trade',
            f"第一轮应识别为现货交易")

        # 第二轮：深入分析
        result2 = self.recognizer.recognize("技术分析")
        self.assertEqual(result2.intent_type, 'technical_analysis',
            f"第二轮应识别为技术分析")

        # 第三轮：交易决策
        result3 = self.recognizer.recognize("合约做多")
        self.assertIn(result3.intent_type, ['futures_trade', 'spot_trade'],
            f"第三轮应识别为交易相关意图")

    def test_context_aware_recognition(self):
        """测试上下文感知识别"""
        context = {
            'symbol': 'ETH',
            'last_intent': 'technical_analysis',
            'market_regime': 'TREND_UP',
        }

        result = self.recognizer.recognize(
            "技术分析",
            context=context,
        )

        # 应能识别为延续上一轮意图
        self.assertIn(result.intent_type, ['technical_analysis'],
            f"上下文感知识别应为技术分析")

    # ============================================================
    # 场景6: 压力测试（200轮）
    # ============================================================

    def test_stress_200_rounds(self):
        """测试200轮压力"""
        test_messages = [
            "买入BTC", "卖出ETH", "分析趋势", "技术指标",
            "风险评估", "仓位管理", "组合回顾", "基本面分析",
            "情绪分析", "成交量分析", "巨鲸追踪", "爆仓检查",
            "资产配置", "概念解释", "策略学习", "市场调研",
            "项目调研", "对比分析", "NFT交易", "DeFi研究",
        ]

        total_rounds = 200
        success_count = 0
        total_latency = 0.0

        for i in range(total_rounds):
            msg = test_messages[i % len(test_messages)]
            start = time.time()
            result = self.recognizer.recognize(msg)
            latency = (time.time() - start) * 1000
            total_latency += latency

            if result.confidence > 0.3:
                success_count += 1

        avg_latency = total_latency / total_rounds
        success_rate = success_count / total_rounds

        self.assertGreater(success_rate, 0.8,
            f"200轮压力测试成功率应>80%, 实际: {success_rate:.2%}")
        self.assertLess(avg_latency, 5.0,
            f"200轮平均延迟应<5ms, 实际: {avg_latency:.2f}ms")

        # 打印统计
        stats = self.recognizer.get_stats()
        print(f"\n  压力测试统计:")
        print(f"    总调用: {stats['total_calls']}")
        print(f"    本地成功: {stats['local_success']}")
        print(f"    LLM降级: {stats['llm_fallback']}")
        print(f"    成功率: {success_rate:.2%}")
        print(f"    平均延迟: {avg_latency:.2f}ms")

    # ============================================================
    # 场景7: 意图类型统计测试
    # ============================================================

    def test_intent_type_count(self):
        """测试意图类型数量"""
        all_intents = self.recognizer.get_all_intent_types()

        # 应包含20+意图类型
        self.assertGreater(len(all_intents), 20,
            f"意图类型数量应>20, 实际: {len(all_intents)}")

        # 应包含6大分类
        categories = set(intent.category for intent in all_intents.values())
        expected_categories = {'trading', 'analysis', 'risk', 'portfolio', 'education', 'research'}
        self.assertTrue(expected_categories.issubset(categories),
            f"应包含6大分类, 实际: {categories}")

    def test_intent_type_structure(self):
        """测试意图类型结构"""
        all_intents = self.recognizer.get_all_intent_types()

        for intent_id, intent_type in all_intents.items():
            # 验证每个意图类型包含必要字段
            self.assertIsNotNone(intent_type.intent_id, "intent_id不能为空")
            self.assertIsNotNone(intent_type.name, "name不能为空")
            self.assertIsNotNone(intent_type.category, "category不能为空")
            self.assertGreater(len(intent_type.keywords), 0, "keywords不能为空")
            self.assertGreater(intent_type.confidence_base, 0, "confidence_base应>0")
            self.assertGreater(intent_type.priority, 0, "priority应>0")


class TestSChainLLMRecognizer(unittest.TestCase):
    """S思维链LLM识别器测试"""

    def setUp(self):
        self.llm_recognizer = SChainLLMRecognizer()

    def test_mock_llm_response(self):
        """测试模拟LLM响应"""
        prompt = self.llm_recognizer._build_s_chain_prompt(
            "我想买入BTC",
            context=None,
            fallback_local_result=None,
        )

        response = self.llm_recognizer._mock_llm_response(prompt)

        self.assertIn('content', response, "响应应包含content")
        self.assertIn('tokens_used', response, "响应应包含tokens_used")

        # 解析content
        content = json.loads(response['content'])
        self.assertIn('final_result', content, "响应应包含final_result")
        self.assertIn('layer1_objective', content, "响应应包含layer1_objective")
        self.assertIn('layer2_okr', content, "响应应包含layer2_okr")
        self.assertIn('layer3_blueprint', content, "响应应包含layer3_blueprint")

    def test_parse_llm_response(self):
        """测试解析LLM响应"""
        mock_response = {
            'content': json.dumps({
                'final_result': {
                    'intent_type': 'spot_trade',
                    'intent_name': '现货交易',
                    'confidence': 0.75,
                    'rationale': '识别到买入关键词',
                    'clarify_needed': False,
                },
                'layer1_objective': {
                    'title': '现货交易',
                    'type': 'spot_trade',
                    'confidence': 0.75,
                    'keywords_matched': ['买入'],
                },
                'layer2_okr': {
                    'mode': 'single',
                    'complexity': 'standard',
                },
                'layer3_blueprint': {
                    'recommended_chain': 'S',
                    'suggested_nodes': ['spot-trade-executor'],
                    'execution_mode': 'sequential',
                },
            }),
            'tokens_used': 300,
        }

        result = self.llm_recognizer._parse_llm_response(mock_response, "买入BTC")

        self.assertEqual(result.intent_type, 'spot_trade')
        self.assertEqual(result.intent_name, '现货交易')
        self.assertEqual(result.confidence, 0.75)
        self.assertEqual(result.llm_tokens_used, 300)
        self.assertEqual(result.recommended_chain, 'S')


if __name__ == '__main__':
    unittest.main(verbosity=2)