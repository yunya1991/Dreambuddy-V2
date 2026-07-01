#!/usr/bin/env python3
"""
OKR 构建器 (OKR Builder)

位置: experiments/ab-trading/core/intent_engine/layer2_okr/okr_builder.py

Layer 2: 展开 —— 从单点到线/网
将单点目标（Objective）拆解为可衡量的关键结果（KR），形成单线或多线结构。
"""

from typing import Dict, List, Optional

from ..types import Objective, KeyResult, OKRSet
from .templates.single_line import get_single_line_template, has_single_line_template
from .templates.multi_line import get_multi_line_template, has_multi_line_template


class OKRBuilder:
    """
    OKR构建器

    从单点目标展开为OKR结构（单线或多线）：
    - 根据目标类型选择模板
    - 生成KR列表并配置依赖关系
    - 构建依赖图和统计信息
    """

    def __init__(self):
        pass

    def build(self, objective: Objective) -> OKRSet:
        """
        根据目标构建OKR集

        Args:
            objective: 单点目标

        Returns:
            OKRSet（完整的目标结构）
        """
        okr_set = OKRSet(objective=objective)
        okr_set.mode = self._determine_mode(objective)
        okr_set.complexity = objective.complexity if hasattr(objective, 'complexity') else 'standard'

        template = self._get_template(objective.type, okr_set.mode)
        if not template:
            template = self._generate_fallback_template(objective)

        key_results = self._build_key_results(objective, template)
        okr_set.key_results = key_results

        if okr_set.mode == 'multi':
            okr_set.lines = template.get('lines', [])
        else:
            okr_set.lines = [{'id': 'line_main', 'name': '主线', 'kr_ids': [kr.id for kr in key_results]}]

        okr_set.dependency_graph = self._build_dependency_graph(key_results)

        total_weight = sum(kr.weight for kr in key_results)
        okr_set.total_weight = total_weight

        okr_set.parallel_line_count = self._count_parallel_lines(key_results)
        okr_set.sequential_depth = self._calculate_depth(key_results, okr_set.dependency_graph)

        okr_set.confidence = objective.confidence * 0.9
        okr_set.rationale = (
            f'目标「{objective.title}」→ {okr_set.mode}模式, '
            f'{len(key_results)}个KR, {okr_set.complexity}复杂度'
        )

        return okr_set

    def _determine_mode(self, objective: Objective) -> str:
        """
        确定OKR模式（single/multi）

        优先使用目标类型预定义的模式，否则根据复杂度判断
        """
        from ..layer1_intent.objective_types import OBJECTIVE_TYPES

        obj_def = OBJECTIVE_TYPES.get(objective.type, {})
        if 'okr_mode' in obj_def:
            return obj_def['okr_mode']

        complexity = objective.complexity if hasattr(objective, 'complexity') else 'standard'
        if complexity == 'deep':
            return 'multi'
        return 'single'

    def _get_template(self, obj_type: str, mode: str) -> dict:
        """获取对应模式的模板"""
        if mode == 'single' and has_single_line_template(obj_type):
            return get_single_line_template(obj_type)
        elif mode == 'multi' and has_multi_line_template(obj_type):
            return get_multi_line_template(obj_type)
        return {}

    def _generate_fallback_template(self, objective: Objective) -> dict:
        """
        当没有匹配模板时，生成降级模板

        简单模式：1个KR
        标准模式：3个KR（调研→分析→结论）
        复杂模式：4个KR（技术+基本面+情绪 → 综合）
        """
        complexity = objective.complexity if hasattr(objective, 'complexity') else 'standard'

        if complexity == 'simple':
            return {
                'mode': 'single',
                'complexity': 'simple',
                'krs': [
                    {
                        'id': 'kr_query',
                        'title': '查询结果',
                        'description': '获取相关信息',
                        'metric': 'query_result',
                        'target_value': 1.0,
                        'unit': 'complete',
                        'weight': 1.0,
                        'order_index': 0,
                        'depends_on': [],
                        'is_parallel': False,
                        'capability_tags': ['query', 'basic_info'],
                        'complexity_hint': 'simple',
                    },
                ],
            }
        elif complexity == 'deep':
            return {
                'mode': 'multi',
                'complexity': 'deep',
                'lines': [
                    {'id': 'line_1', 'name': '维度1', 'kr_ids': ['kr_dim1']},
                    {'id': 'line_2', 'name': '维度2', 'kr_ids': ['kr_dim2']},
                    {'id': 'line_3', 'name': '维度3', 'kr_ids': ['kr_dim3']},
                    {'id': 'line_agg', 'name': '聚合', 'kr_ids': ['kr_agg']},
                ],
                'krs': [
                    {
                        'id': 'kr_dim1',
                        'title': '维度1分析',
                        'metric': 'dim1_score',
                        'target_value': 0.7,
                        'unit': 'score',
                        'weight': 0.3,
                        'order_index': 0,
                        'line_id': 'line_1',
                        'depends_on': [],
                        'is_parallel': True,
                        'capability_tags': ['analysis'],
                        'complexity_hint': 'deep',
                    },
                    {
                        'id': 'kr_dim2',
                        'title': '维度2分析',
                        'metric': 'dim2_score',
                        'target_value': 0.7,
                        'unit': 'score',
                        'weight': 0.25,
                        'order_index': 0,
                        'line_id': 'line_2',
                        'depends_on': [],
                        'is_parallel': True,
                        'capability_tags': ['analysis'],
                        'complexity_hint': 'deep',
                    },
                    {
                        'id': 'kr_dim3',
                        'title': '维度3分析',
                        'metric': 'dim3_score',
                        'target_value': 0.7,
                        'unit': 'score',
                        'weight': 0.25,
                        'order_index': 0,
                        'line_id': 'line_3',
                        'depends_on': [],
                        'is_parallel': True,
                        'capability_tags': ['analysis'],
                        'complexity_hint': 'deep',
                    },
                    {
                        'id': 'kr_agg',
                        'title': '综合分析',
                        'metric': 'agg_score',
                        'target_value': 0.8,
                        'unit': 'score',
                        'weight': 0.2,
                        'order_index': 1,
                        'line_id': 'line_agg',
                        'depends_on': ['kr_dim1', 'kr_dim2', 'kr_dim3'],
                        'is_parallel': False,
                        'capability_tags': ['synthesis', 'decision_making'],
                        'complexity_hint': 'deep',
                    },
                ],
            }
        else:
            return {
                'mode': 'single',
                'complexity': 'standard',
                'krs': [
                    {
                        'id': 'kr_research',
                        'title': '调研',
                        'metric': 'research_depth',
                        'target_value': 0.7,
                        'unit': 'score',
                        'weight': 0.3,
                        'order_index': 0,
                        'depends_on': [],
                        'is_parallel': False,
                        'capability_tags': ['research', 'information_gathering'],
                        'complexity_hint': 'standard',
                    },
                    {
                        'id': 'kr_analysis',
                        'title': '分析',
                        'metric': 'analysis_depth',
                        'target_value': 0.75,
                        'unit': 'score',
                        'weight': 0.4,
                        'order_index': 1,
                        'depends_on': ['kr_research'],
                        'is_parallel': False,
                        'capability_tags': ['analysis', 'evaluation'],
                        'complexity_hint': 'standard',
                    },
                    {
                        'id': 'kr_conclusion',
                        'title': '结论',
                        'metric': 'conclusion_quality',
                        'target_value': 0.8,
                        'unit': 'score',
                        'weight': 0.3,
                        'order_index': 2,
                        'depends_on': ['kr_analysis'],
                        'is_parallel': False,
                        'capability_tags': ['conclusion', 'recommendation'],
                        'complexity_hint': 'standard',
                    },
                ],
            }

    def _build_key_results(self, objective: Objective, template: dict) -> List[KeyResult]:
        """从模板构建KR列表"""
        kr_list = []
        template_krs = template.get('krs', [])

        for kr_def in template_krs:
            kr = KeyResult(
                id=kr_def.get('id', ''),
                objective_id=objective.id,
                title=kr_def.get('title', ''),
                description=kr_def.get('description', ''),
                metric=kr_def.get('metric', ''),
                target_value=kr_def.get('target_value', 0.0),
                unit=kr_def.get('unit', ''),
                weight=kr_def.get('weight', 0.0),
                order_index=kr_def.get('order_index', 0),
                line_id=kr_def.get('line_id', ''),
                status='pending',
                depends_on=kr_def.get('depends_on', []),
                is_parallel=kr_def.get('is_parallel', False),
                capability_tags=kr_def.get('capability_tags', []),
                complexity_hint=kr_def.get('complexity_hint', 'standard'),
            )
            kr_list.append(kr)

        return kr_list

    def _build_dependency_graph(self, key_results: List[KeyResult]) -> Dict[str, List[str]]:
        """构建KR依赖图（邻接表）"""
        dep_graph = {}

        for kr in key_results:
            if kr.id not in dep_graph:
                dep_graph[kr.id] = []
            for dep_id in kr.depends_on:
                if dep_id not in dep_graph:
                    dep_graph[dep_id] = []

        for kr in key_results:
            for dep_id in kr.depends_on:
                if dep_id in dep_graph and kr.id not in dep_graph[dep_id]:
                    dep_graph[dep_id].append(kr.id)

        return dep_graph

    def _count_parallel_lines(self, key_results: List[KeyResult]) -> int:
        """统计并行线数量"""
        parallel_krs = [kr for kr in key_results if kr.is_parallel]
        order_groups = {}
        for kr in parallel_krs:
            idx = kr.order_index
            if idx not in order_groups:
                order_groups[idx] = 0
            order_groups[idx] += 1
        return max(order_groups.values()) if order_groups else 0

    def _calculate_depth(
        self,
        key_results: List[KeyResult],
        dep_graph: Dict[str, List[str]],
    ) -> int:
        """计算顺序深度（最长路径长度）"""
        kr_ids = [kr.id for kr in key_results]
        depth_map = {}

        def get_depth(kr_id: str) -> int:
            if kr_id in depth_map:
                return depth_map[kr_id]
            kr = next((k for k in key_results if k.id == kr_id), None)
            if not kr or not kr.depends_on:
                depth_map[kr_id] = 1
                return 1
            max_dep_depth = max(get_depth(dep) for dep in kr.depends_on if dep in kr_ids)
            depth_map[kr_id] = max_dep_depth + 1
            return depth_map[kr_id]

        max_depth = 0
        for kr in key_results:
            max_depth = max(max_depth, get_depth(kr.id))

        return max_depth
