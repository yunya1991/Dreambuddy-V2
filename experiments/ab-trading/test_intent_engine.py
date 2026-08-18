#!/usr/bin/env python3
"""
意图识别引擎 - 单元测试

位置: experiments/ab-trading/test_intent_engine.py

测试三层价值模型：
- Layer 1: 收敛（混沌 → 单点目标）
- Layer 2: 展开（单点 → 线/网 OKR）
- Layer 3: 落地（线/网 → 可执行蓝图）
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core'))

import unittest

from intent_engine import (
    Objective,
    KeyResult,
    OKRSet,
    ExecutionBlueprint,
    IntentRecognitionResult,
    IntentRecognitionEngine,
)
from intent_engine.layer1_intent import (
    ObjectiveExtractor,
    OBJECTIVE_TYPES,
    list_objective_types,
    search_objective_types,
)
from intent_engine.layer2_okr import OKRBuilder
from intent_engine.layer3_blueprint import BlueprintBuilder


class TestObjectiveTypes(unittest.TestCase):
    """测试目标类型体系"""

    def test_objective_types_count(self):
        """测试目标类型数量（9种）"""
        self.assertEqual(len(OBJECTIVE_TYPES), 9)

    def test_list_objective_types(self):
        """测试列出所有目标类型"""
        types = list_objective_types()
        self.assertEqual(len(types), 9)
        self.assertIn('market_query', types)
        self.assertIn('deep_analysis', types)
        self.assertIn('three_screen_trade', types)

    def test_search_objective_types(self):
        """测试按关键词搜索目标类型"""
        results = search_objective_types('行情')
        self.assertIn('market_query', results)

        results = search_objective_types('三屏')
        self.assertIn('three_screen_trade', results)

        results = search_objective_types('深度')
        self.assertIn('deep_analysis', results)

    def test_objective_type_structure(self):
        """测试目标类型结构完整性"""
        for obj_id, obj_def in OBJECTIVE_TYPES.items():
            self.assertIn('name', obj_def)
            self.assertIn('complexity', obj_def)
            self.assertIn('okr_mode', obj_def)
            self.assertIn('domain', obj_def)
            self.assertIn('keywords', obj_def)
            self.assertIn(obj_def['complexity'], ['simple', 'standard', 'deep'])
            self.assertIn(obj_def['okr_mode'], ['single', 'multi'])


class TestLayer1ObjectiveExtractor(unittest.TestCase):
    """测试 Layer 1：目标提取器（收敛）"""

    def setUp(self):
        self.extractor = ObjectiveExtractor()

    def test_simple_query(self):
        """测试简单行情查询"""
        obj = self.extractor.extract(user_message='BTC现在多少钱？')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, 'market_query')
        self.assertGreater(obj.confidence, 0)
        self.assertFalse(obj.clarify_needed)

    def test_trend_analysis(self):
        """测试趋势分析"""
        obj = self.extractor.extract(user_message='分析一下ETH的趋势')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, 'trend_analysis')
        self.assertGreater(obj.confidence, 0)

    def test_deep_analysis(self):
        """测试深度分析"""
        obj = self.extractor.extract(user_message='深度分析一下BTC')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, 'deep_analysis')
        self.assertGreater(obj.confidence, 0)

    def test_three_screen_trade(self):
        """测试三屏交易"""
        obj = self.extractor.extract(user_message='用三屏交易法分析ETH')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, 'three_screen_trade')
        self.assertGreater(obj.confidence, 0)

    def test_trading_decision(self):
        """测试交易决策"""
        obj = self.extractor.extract(user_message='BTC可以买入吗')
        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, 'trading_decision')
        self.assertGreater(obj.confidence, 0)

    def test_extracted_keywords(self):
        """测试关键词提取"""
        obj = self.extractor.extract(user_message='BTC现在价格是多少，行情怎么样？')
        self.assertGreater(len(obj.extracted_keywords), 0)

    def test_market_data_scoring(self):
        """测试市场数据打分"""
        mkt_data = {'price_change_pct': 12, 'volume_change_pct': 60}
        obj = self.extractor.extract(user_message='分析一下', mkt_data=mkt_data)
        self.assertIsNotNone(obj)
        self.assertGreater(obj.confidence, 0)

    def test_source_detection(self):
        """测试来源检测"""
        obj = self.extractor.extract(user_message='test')
        self.assertEqual(obj.source, 'nl')

        obj = self.extractor.extract(mkt_data={'price': 100})
        self.assertEqual(obj.source, 'market')


class TestLayer2OKRBuilder(unittest.TestCase):
    """测试 Layer 2：OKR构建器（展开）"""

    def setUp(self):
        self.builder = OKRBuilder()

    def _make_objective(self, obj_type: str) -> Objective:
        """创建测试用目标"""
        from intent_engine.layer1_intent.objective_types import OBJECTIVE_TYPES
        obj_def = OBJECTIVE_TYPES.get(obj_type, {})
        return Objective(
            type=obj_type,
            title=obj_def.get('name', ''),
            domain=obj_def.get('domain', ''),
            complexity=obj_def.get('complexity', 'standard'),
            confidence=0.8,
        )

    def test_simple_single_line(self):
        """测试简单单线模式（行情查询）"""
        obj = self._make_objective('market_query')
        okr_set = self.builder.build(obj)

        self.assertEqual(okr_set.mode, 'single')
        self.assertEqual(okr_set.complexity, 'simple')
        self.assertEqual(len(okr_set.key_results), 1)
        self.assertAlmostEqual(okr_set.total_weight, 1.0, places=1)

    def test_standard_single_line(self):
        """测试标准单线模式（趋势分析）"""
        obj = self._make_objective('trend_analysis')
        okr_set = self.builder.build(obj)

        self.assertEqual(okr_set.mode, 'single')
        self.assertEqual(okr_set.complexity, 'standard')
        self.assertGreater(len(okr_set.key_results), 1)
        self.assertAlmostEqual(okr_set.total_weight, 1.0, places=1)

    def test_three_screen_single_line(self):
        """测试三屏交易单线模式"""
        obj = self._make_objective('three_screen_trade')
        okr_set = self.builder.build(obj)

        self.assertEqual(okr_set.mode, 'single')
        self.assertEqual(len(okr_set.key_results), 4)

        kr_ids = [kr.id for kr in okr_set.key_results]
        self.assertIn('kr_screen1', kr_ids)
        self.assertIn('kr_screen2', kr_ids)
        self.assertIn('kr_screen3', kr_ids)
        self.assertIn('kr_gate', kr_ids)

    def test_deep_multi_line(self):
        """测试复杂多线模式（深度分析）"""
        obj = self._make_objective('deep_analysis')
        okr_set = self.builder.build(obj)

        self.assertEqual(okr_set.mode, 'multi')
        self.assertEqual(okr_set.complexity, 'deep')
        self.assertGreater(len(okr_set.key_results), 2)
        self.assertGreater(okr_set.parallel_line_count, 1)

    def test_kr_dependencies(self):
        """测试KR依赖关系"""
        obj = self._make_objective('three_screen_trade')
        okr_set = self.builder.build(obj)

        kr_map = {kr.id: kr for kr in okr_set.key_results}
        self.assertIn('kr_screen1', kr_map)
        self.assertIn('kr_screen2', kr_map)
        self.assertIn('kr_screen3', kr_map)

        self.assertEqual(kr_map['kr_screen1'].depends_on, [])
        self.assertIn('kr_screen1', kr_map['kr_screen2'].depends_on)
        self.assertIn('kr_screen2', kr_map['kr_screen3'].depends_on)

    def test_dependency_graph(self):
        """测试依赖图构建"""
        obj = self._make_objective('trend_analysis')
        okr_set = self.builder.build(obj)

        self.assertIsInstance(okr_set.dependency_graph, dict)
        self.assertGreater(len(okr_set.dependency_graph), 0)

    def test_capability_tags(self):
        """测试KR的能力标签"""
        obj = self._make_objective('deep_analysis')
        okr_set = self.builder.build(obj)

        for kr in okr_set.key_results:
            self.assertGreater(len(kr.capability_tags), 0)

    def test_sequential_depth(self):
        """测试顺序深度计算"""
        obj = self._make_objective('trend_analysis')
        okr_set = self.builder.build(obj)

        self.assertGreater(okr_set.sequential_depth, 1)


class TestLayer3BlueprintBuilder(unittest.TestCase):
    """测试 Layer 3：蓝图构建器（落地）"""

    def setUp(self):
        self.builder = BlueprintBuilder(registry=None)

    def _make_simple_okr(self) -> OKRSet:
        """创建简单测试用OKR"""
        obj = Objective(
            id='obj_test',
            type='market_query',
            title='测试查询',
            complexity='simple',
            confidence=0.9,
        )
        kr = KeyResult(
            id='kr_test',
            objective_id='obj_test',
            title='测试KR',
            metric='test_metric',
            weight=1.0,
            capability_tags=['market_data', 'price_query'],
        )
        return OKRSet(
            objective=obj,
            key_results=[kr],
            mode='single',
            complexity='simple',
        )

    def _make_standard_okr(self) -> OKRSet:
        """创建标准测试用OKR"""
        obj = Objective(
            id='obj_test',
            type='three_screen_trade',
            title='三屏交易测试',
            complexity='standard',
            confidence=0.8,
        )
        krs = [
            KeyResult(
                id='kr_screen1',
                objective_id='obj_test',
                title='Screen1',
                metric='trend',
                weight=0.3,
                order_index=0,
                depends_on=[],
                capability_tags=['trend_analysis', 'screen1', 'weekly_timeframe'],
            ),
            KeyResult(
                id='kr_screen2',
                objective_id='obj_test',
                title='Screen2',
                metric='setup',
                weight=0.35,
                order_index=1,
                depends_on=['kr_screen1'],
                capability_tags=['technical_analysis', 'screen2', 'daily_timeframe'],
            ),
            KeyResult(
                id='kr_screen3',
                objective_id='obj_test',
                title='Screen3',
                metric='execution',
                weight=0.2,
                order_index=2,
                depends_on=['kr_screen2'],
                capability_tags=['intraday_execution', 'screen3', 'timing'],
            ),
            KeyResult(
                id='kr_gate',
                objective_id='obj_test',
                title='Gate',
                metric='gate_pass',
                weight=0.15,
                order_index=3,
                depends_on=['kr_screen3'],
                capability_tags=['risk_management', 'gate_keeping'],
            ),
        ]
        return OKRSet(
            objective=obj,
            key_results=krs,
            mode='single',
            complexity='standard',
            lines=[{'id': 'line_main', 'name': '主线', 'kr_ids': [k.id for k in krs]}],
        )

    def _make_deep_okr(self) -> OKRSet:
        """创建复杂多线测试用OKR"""
        obj = Objective(
            id='obj_test',
            type='deep_analysis',
            title='深度分析测试',
            complexity='deep',
            confidence=0.75,
        )
        krs = [
            KeyResult(
                id='kr_tech',
                objective_id='obj_test',
                title='技术面',
                metric='tech_score',
                weight=0.35,
                order_index=0,
                line_id='line_tech',
                depends_on=[],
                is_parallel=True,
                capability_tags=['technical_analysis', 'indicators'],
            ),
            KeyResult(
                id='kr_fund',
                objective_id='obj_test',
                title='资金面',
                metric='fund_score',
                weight=0.25,
                order_index=0,
                line_id='line_fund',
                depends_on=[],
                is_parallel=True,
                capability_tags=['fundamental_analysis', 'fund_flow'],
            ),
            KeyResult(
                id='kr_sent',
                objective_id='obj_test',
                title='情绪面',
                metric='sent_score',
                weight=0.2,
                order_index=0,
                line_id='line_sent',
                depends_on=[],
                is_parallel=True,
                capability_tags=['sentiment_analysis', 'news'],
            ),
            KeyResult(
                id='kr_synth',
                objective_id='obj_test',
                title='综合决策',
                metric='final',
                weight=0.2,
                order_index=1,
                line_id='line_agg',
                depends_on=['kr_tech', 'kr_fund', 'kr_sent'],
                is_parallel=False,
                capability_tags=['synthesis', 'decision_making'],
            ),
        ]
        return OKRSet(
            objective=obj,
            key_results=krs,
            mode='multi',
            complexity='deep',
            lines=[
                {'id': 'line_tech', 'name': '技术面线', 'kr_ids': ['kr_tech']},
                {'id': 'line_fund', 'name': '资金面线', 'kr_ids': ['kr_fund']},
                {'id': 'line_sent', 'name': '情绪面线', 'kr_ids': ['kr_sent']},
                {'id': 'line_agg', 'name': '聚合线', 'kr_ids': ['kr_synth']},
            ],
            parallel_line_count=3,
            sequential_depth=2,
        )

    def test_simple_blueprint(self):
        """测试简单蓝图构建"""
        okr_set = self._make_simple_okr()
        blueprint = self.builder.build(okr_set)

        self.assertIsNotNone(blueprint)
        self.assertEqual(blueprint.complexity, 'simple')
        self.assertEqual(blueprint.okr_mode, 'single')
        self.assertGreater(len(blueprint.node_sequence), 0)

    def test_standard_blueprint(self):
        """测试标准蓝图构建（三屏交易）"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertEqual(blueprint.okr_mode, 'single')
        self.assertEqual(blueprint.execution_mode, 'sequential')
        self.assertGreater(len(blueprint.node_sequence), 0)
        self.assertGreater(len(blueprint.dependencies), 0)

    def test_deep_blueprint(self):
        """测试复杂蓝图构建（多线并行）"""
        okr_set = self._make_deep_okr()
        blueprint = self.builder.build(okr_set)

        self.assertEqual(blueprint.okr_mode, 'multi')
        self.assertIn(blueprint.execution_mode, ['parallel', 'hybrid'])
        self.assertGreater(len(blueprint.parallel_groups), 0)
        self.assertTrue(blueprint.replan_enabled)
        self.assertEqual(blueprint.max_replans, 3)

    def test_kr_to_nodes_mapping(self):
        """测试KR到节点的映射"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertGreater(len(blueprint.kr_to_nodes), 0)
        for kr_id, nodes in blueprint.kr_to_nodes.items():
            self.assertIsInstance(nodes, list)
            self.assertGreater(len(nodes), 0)

    def test_node_to_kr_mapping(self):
        """测试节点到KR的反向映射"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertGreater(len(blueprint.node_to_kr), 0)

    def test_dependency_graph(self):
        """测试节点依赖图"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertIsInstance(blueprint.dependencies, dict)

    def test_engineering_config(self):
        """测试工程配置"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertGreater(blueprint.total_timeout_ms, 0)
        self.assertGreater(len(blueprint.node_timeout_ms), 0)
        self.assertGreater(len(blueprint.retry_policy), 0)

    def test_required_optional_nodes(self):
        """测试必选/可选节点"""
        okr_set = self._make_standard_okr()
        blueprint = self.builder.build(okr_set)

        self.assertIsInstance(blueprint.required_nodes, list)
        self.assertIsInstance(blueprint.optional_nodes, list)


class TestIntentRecognitionEngine(unittest.TestCase):
    """测试完整意图识别引擎（三层贯通）"""

    def setUp(self):
        self.engine = IntentRecognitionEngine()

    def test_simple_query_full_pipeline(self):
        """测试简单查询完整流程"""
        result = self.engine.recognize(user_message='BTC现在多少钱？')

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.objective)
        self.assertIsNotNone(result.okr_set)
        self.assertIsNotNone(result.blueprint)
        self.assertEqual(result.state, 'confirmed')
        self.assertGreater(result.confidence, 0)

        self.assertEqual(result.objective.type, 'market_query')
        self.assertEqual(result.okr_set.mode, 'single')
        self.assertEqual(result.okr_set.complexity, 'simple')

    def test_three_screen_full_pipeline(self):
        """测试三屏交易完整流程"""
        result = self.engine.recognize(user_message='用三屏交易法分析ETH')

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.objective)
        self.assertIsNotNone(result.okr_set)
        self.assertIsNotNone(result.blueprint)
        self.assertEqual(result.state, 'confirmed')

        self.assertEqual(result.objective.type, 'three_screen_trade')
        self.assertEqual(result.okr_set.mode, 'single')
        self.assertEqual(result.blueprint.execution_mode, 'sequential')

    def test_deep_analysis_full_pipeline(self):
        """测试深度分析完整流程（多线模式）"""
        result = self.engine.recognize(user_message='深度分析一下BTC')

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.objective)
        self.assertIsNotNone(result.okr_set)
        self.assertIsNotNone(result.blueprint)
        self.assertEqual(result.state, 'confirmed')

        self.assertEqual(result.objective.type, 'deep_analysis')
        self.assertEqual(result.okr_set.mode, 'multi')
        self.assertEqual(result.okr_set.complexity, 'deep')
        self.assertTrue(result.blueprint.replan_enabled)

    def test_trading_decision_full_pipeline(self):
        """测试交易决策完整流程"""
        result = self.engine.recognize(user_message='现在可以买入BTC吗')

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.objective)
        self.assertIsNotNone(result.okr_set)
        self.assertIsNotNone(result.blueprint)
        self.assertEqual(result.state, 'confirmed')

        self.assertEqual(result.objective.type, 'trading_decision')

    def test_rationale_content(self):
        """测试推理过程描述"""
        result = self.engine.recognize(user_message='深度分析一下BTC')

        self.assertIn('Layer1', result.rationale)
        self.assertIn('Layer2', result.rationale)
        self.assertIn('Layer3', result.rationale)

    def test_supported_objectives(self):
        """测试获取支持的目标类型"""
        objectives = self.engine.get_supported_objectives()
        self.assertEqual(len(objectives), 9)

    def test_session_management(self):
        """测试会话管理"""
        session_id = 'test_session_001'
        result = self.engine.recognize(
            user_message='BTC现在多少钱？',
            session_id=session_id,
        )

        self.assertEqual(result.state, 'confirmed')

        stored = self.engine.get_session_result(session_id)
        self.assertIsNotNone(stored)

        self.engine.clear_session(session_id)
        self.assertIsNone(self.engine.get_session_result(session_id))

    def test_market_data_input(self):
        """测试市场数据输入"""
        result = self.engine.recognize(
            user_message='分析一下',
            mkt_data={'price_change_pct': 8, 'volume_change_pct': 40},
        )

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.objective)

    def test_all_objective_types(self):
        """测试所有9种目标类型都能正常处理"""
        test_cases = [
            ('market_query', 'BTC价格多少'),
            ('trend_analysis', '分析ETH趋势'),
            ('deep_analysis', '深度分析BTC'),
            ('trading_decision', '买入BTC'),
            ('exit_evaluation', '止盈离场'),
            ('strategy_design', '设计交易策略'),
            ('risk_assessment', '风险评估'),
            ('portfolio_review', '组合回顾'),
            ('three_screen_trade', '三屏交易分析'),
        ]

        for obj_type, message in test_cases:
            with self.subTest(obj_type=obj_type):
                result = self.engine.recognize(user_message=message)
                self.assertEqual(result.state, 'confirmed',
                                 f'{obj_type} should be confirmed')
                self.assertIsNotNone(result.objective,
                                     f'{obj_type} should have objective')
                self.assertIsNotNone(result.okr_set,
                                     f'{obj_type} should have okr_set')
                self.assertIsNotNone(result.blueprint,
                                     f'{obj_type} should have blueprint')


if __name__ == '__main__':
    unittest.main(verbosity=2)
