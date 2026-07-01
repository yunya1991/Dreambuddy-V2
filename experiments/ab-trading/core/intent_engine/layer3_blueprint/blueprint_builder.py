#!/usr/bin/env python3
"""
蓝图构建器 (Blueprint Builder)

位置: experiments/ab-trading/core/intent_engine/layer3_blueprint/blueprint_builder.py

Layer 3: 落地 —— 从线/网到可执行图
将OKR层的目标结构，映射为可执行的工程蓝图。

5步工程化：
1. 节点展开：KR → 具体模块节点
2. 依赖映射：KR依赖 → 节点依赖（DAG）
3. 拓扑排序：DAG → 可执行序列
4. 并行识别：识别可并行执行的节点组
5. 工程配置：超时、重试、降级等工程参数
"""

from typing import Dict, List, Optional, Set
from collections import deque

from ..types import OKRSet, ExecutionBlueprint

try:
    from ...modules import get_module_registry, ModuleInfo
    _HAS_REGISTRY = True
except (ImportError, ValueError):
    _HAS_REGISTRY = False
    ModuleInfo = None


class BlueprintBuilder:
    """
    执行蓝图构建器 - 将OKR映射为执行图

    5步工程化过程：
    1. 节点展开：KR → 具体模块节点
    2. 依赖映射：KR依赖 → 节点依赖（DAG）
    3. 拓扑排序：DAG → 可执行序列
    4. 并行识别：识别可并行执行的节点组
    5. 工程配置：超时、重试、降级等工程参数
    """

    def __init__(self, registry=None):
        if registry is not None:
            self.registry = registry
        elif _HAS_REGISTRY:
            try:
                self.registry = get_module_registry()
            except Exception:
                self.registry = None
        else:
            self.registry = None

    def build(self, okr_set: OKRSet) -> ExecutionBlueprint:
        """
        根据OKR集构建执行蓝图

        Args:
            okr_set: OKR集（目标结构）

        Returns:
            ExecutionBlueprint（执行蓝图）
        """
        blueprint = ExecutionBlueprint()
        blueprint.objective_id = okr_set.objective.id
        blueprint.complexity = okr_set.complexity
        blueprint.okr_mode = okr_set.mode

        kr_node_map = self._expand_krs_to_nodes(okr_set)
        blueprint.kr_to_nodes = kr_node_map

        blueprint.node_to_kr = self._build_reverse_map(kr_node_map)

        dep_graph = self._build_dependency_graph(okr_set, kr_node_map)
        blueprint.dependencies = dep_graph

        sorted_nodes = self._topological_sort(dep_graph, kr_node_map)
        blueprint.node_sequence = sorted_nodes

        parallel_groups = self._identify_parallel_groups(
            okr_set, kr_node_map, dep_graph, sorted_nodes
        )
        blueprint.parallel_groups = parallel_groups

        blueprint.execution_mode = self._determine_execution_mode(
            parallel_groups, okr_set.mode
        )

        engineering_config = self._configure_engineering(
            okr_set, sorted_nodes, kr_node_map
        )

        blueprint.total_timeout_ms = engineering_config['total_timeout_ms']
        blueprint.node_timeout_ms = engineering_config['node_timeout_ms']
        blueprint.retry_policy = engineering_config['retry_policy']
        blueprint.fallback_policy = engineering_config['fallback_policy']
        blueprint.required_nodes = engineering_config['required_nodes']
        blueprint.optional_nodes = engineering_config['optional_nodes']

        if okr_set.complexity == 'deep':
            blueprint.replan_enabled = True
            blueprint.max_replans = 3
            blueprint.replan_triggers = [
                'low_confidence',
                'module_failure',
                'market_shock',
            ]
        else:
            blueprint.replan_enabled = False
            blueprint.max_replans = 0

        blueprint.confidence = okr_set.confidence * 0.85
        blueprint.rationale = (
            f'OKR({okr_set.mode}, {okr_set.complexity}) → '
            f'蓝图({blueprint.execution_mode}, {len(sorted_nodes)}节点)'
        )

        return blueprint

    def _expand_krs_to_nodes(self, okr_set: OKRSet) -> Dict[str, List[str]]:
        """
        Step 1: 节点展开（KR → 具体模块节点）

        匹配策略：
        1. 如果有注册表，按 capability_tags 搜索匹配
        2. 如果没有注册表，使用映射规则生成默认节点
        3. 考虑模块依赖和可用性
        """
        kr_node_map = {}

        for kr in okr_set.key_results:
            nodes = self._match_modules_for_kr(kr)
            kr_node_map[kr.id] = nodes

        return kr_node_map

    def _match_modules_for_kr(self, kr) -> List[str]:
        """
        为单个KR匹配模块节点

        优先使用注册表搜索，否则使用降级映射
        """
        if self.registry is not None and hasattr(self.registry, 'query'):
            try:
                return self._match_via_registry(kr)
            except Exception:
                pass

        return self._match_via_fallback(kr)

    def _match_via_registry(self, kr) -> List[str]:
        """通过注册表按标签匹配模块"""
        matched_modules = []
        best_score = 0

        all_modules = self.registry.get_all() if hasattr(self.registry, 'get_all') else []

        for mod in all_modules:
            if mod.lifecycle and mod.lifecycle.get('status') != 'active':
                continue

            tags = set(mod.tags) if hasattr(mod, 'tags') else set()
            kr_tags = set(kr.capability_tags)

            if not kr_tags or not tags:
                continue

            overlap = tags & kr_tags
            if not overlap:
                continue

            score = len(overlap) / len(kr_tags)

            if score > 0.3:
                matched_modules.append((mod.id, score))
                best_score = max(best_score, score)

        matched_modules.sort(key=lambda x: x[1], reverse=True)

        result = []
        for mod_id, score in matched_modules[:3]:
            if mod_id not in result:
                result.append(mod_id)

        if result:
            return result

        return self._match_via_fallback(kr)

    def _match_via_fallback(self, kr) -> List[str]:
        """
        降级映射：当注册表不可用时，基于能力标签的规则映射

        这是一个简化的映射，确保在没有注册表时也能工作
        """
        tag_to_module = {
            'technical_analysis': ['dream-first-principles'],
            'trend_analysis': ['dream-first-principles'],
            'indicators': ['classic-indicator-scan'],
            'pattern': ['classic-indicator-scan'],
            'fundamental_analysis': ['dream-fundamental-analyzer'],
            'fund_flow': ['dream-fundamental-analyzer'],
            'sentiment_analysis': ['dream-sentiment-analyzer'],
            'news': ['dream-sentiment-analyzer'],
            'contradiction_analysis': ['dream-contradiction-theory'],
            'strategy_design': ['dream-strategy-designer'],
            'strategy_research': ['dream-strategy-research'],
            'risk_management': ['dream-gate-keeper'],
            'gate_keeping': ['dream-gate-keeper'],
            'synthesis': ['dream-strategy-research'],
            'decision_making': ['dream-strategy-research'],
            'research': ['dream-strategy-research'],
            'market_data': ['classic-indicator-scan'],
            'price_query': ['classic-indicator-scan'],
            'screen1': ['dream-screen1-first'],
            'screen2': ['dream-screen2-second'],
            'screen3': ['dream-screen3-third'],
            'weekly_timeframe': ['dream-screen1-first'],
            'daily_timeframe': ['dream-screen2-second'],
            'intraday_execution': ['dream-screen3-third'],
            'entry_setup': ['dream-screen2-second'],
            'timing': ['dream-screen3-third'],
            'execution': ['dream-screen3-third'],
            'position_management': ['dream-exit-skill-v2'],
            'exit_strategy': ['dream-exit-skill-v2'],
            'regime_detection': ['dream-regime-detector'],
            'support_resistance': ['classic-indicator-scan'],
            'key_levels': ['classic-indicator-scan'],
            'backtesting': ['dream-strategy-designer'],
            'performance_analysis': ['dream-strategy-research'],
            'summary': ['dream-strategy-research'],
            'recommendation': ['dream-strategy-research'],
        }

        result = []
        for tag in kr.capability_tags:
            if tag in tag_to_module:
                for mod_id in tag_to_module[tag]:
                    if mod_id not in result:
                        result.append(mod_id)

        if not result:
            default_map = {
                'simple': ['classic-indicator-scan'],
                'standard': ['dream-first-principles', 'classic-indicator-scan'],
                'deep': [
                    'dream-contradiction-theory',
                    'dream-first-principles',
                    'dream-strategy-research',
                ],
            }
            result = default_map.get(kr.complexity_hint, ['classic-indicator-scan'])

        return result[:3]

    def _build_dependency_graph(
        self,
        okr_set: OKRSet,
        kr_node_map: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        """
        Step 2: 依赖映射（KR依赖 → 节点依赖）

        依赖来源：
        1. KR内部的节点顺序依赖（第一个依赖第二个...）
        2. KR之间的依赖（当前KR的第一个节点依赖上游KR的最后一个节点）
        """
        dep_graph = {}

        all_nodes = set()
        for nodes in kr_node_map.values():
            all_nodes.update(nodes)

        for node in all_nodes:
            if node not in dep_graph:
                dep_graph[node] = []

        for kr_id, nodes in kr_node_map.items():
            for i in range(1, len(nodes)):
                if nodes[i] in dep_graph and nodes[i-1] not in dep_graph[nodes[i]]:
                    dep_graph[nodes[i]].append(nodes[i-1])

        for kr in okr_set.key_results:
            if not kr.depends_on:
                continue

            current_nodes = kr_node_map.get(kr.id, [])
            if not current_nodes:
                continue

            first_node = current_nodes[0]

            for dep_kr_id in kr.depends_on:
                dep_nodes = kr_node_map.get(dep_kr_id, [])
                if dep_nodes:
                    last_dep_node = dep_nodes[-1]
                    if last_dep_node not in dep_graph.get(first_node, []):
                        if first_node in dep_graph:
                            dep_graph[first_node].append(last_dep_node)

        return dep_graph

    def _topological_sort(
        self,
        dep_graph: Dict[str, List[str]],
        kr_node_map: Dict[str, List[str]],
    ) -> List[str]:
        """
        Step 3: 拓扑排序（DAG → 可执行序列）

        使用 Kahn 算法进行拓扑排序
        """
        all_nodes = set(dep_graph.keys())
        for deps in dep_graph.values():
            all_nodes.update(deps)

        in_degree = {node: 0 for node in all_nodes}

        reverse_graph = {node: [] for node in all_nodes}
        for node, deps in dep_graph.items():
            for dep in deps:
                reverse_graph[dep].append(node)
                in_degree[node] = in_degree.get(node, 0) + 1

        for node in all_nodes:
            if node not in in_degree:
                in_degree[node] = 0

        queue = deque()
        for node in all_nodes:
            if in_degree.get(node, 0) == 0:
                queue.append(node)

        result = []
        while queue:
            node = queue.popleft()
            result.append(node)

            for next_node in reverse_graph.get(node, []):
                in_degree[next_node] -= 1
                if in_degree[next_node] == 0:
                    queue.append(next_node)

        remaining = [n for n in all_nodes if n not in result]
        if remaining:
            result.extend(remaining)

        return result

    def _identify_parallel_groups(
        self,
        okr_set: OKRSet,
        kr_node_map: Dict[str, List[str]],
        dep_graph: Dict[str, List[str]],
        sorted_nodes: List[str],
    ) -> List[List[str]]:
        """
        Step 4: 并行组识别

        识别可以并行执行的节点组
        """
        parallel_groups = []

        if okr_set.mode == 'multi':
            parallel_krs = [kr for kr in okr_set.key_results if kr.is_parallel]

            if parallel_krs:
                parallel_group = []
                for kr in parallel_krs:
                    kr_nodes = kr_node_map.get(kr.id, [])
                    if kr_nodes:
                        parallel_group.append(kr_nodes)
                if parallel_group:
                    parallel_groups.append(parallel_group)

            sequential_krs = [kr for kr in okr_set.key_results if not kr.is_parallel]
            for kr in sequential_krs:
                kr_nodes = kr_node_map.get(kr.id, [])
                if kr_nodes:
                    parallel_groups.append(kr_nodes)
        else:
            current_group = []
            for node in sorted_nodes:
                deps = dep_graph.get(node, [])
                if not deps and not current_group:
                    current_group.append(node)
                elif deps and all(d in current_group for d in deps):
                    current_group.append(node)
                else:
                    if current_group:
                        parallel_groups.append(current_group)
                    current_group = [node]

            if current_group:
                parallel_groups.append(current_group)

        return parallel_groups

    def _determine_execution_mode(
        self,
        parallel_groups: List[List[str]],
        okr_mode: str,
    ) -> str:
        """
        确定执行模式

        - sequential: 完全顺序执行（单线下，只有一个顺序链）
        - parallel: 完全并行执行（多线下，只有一个并行阶段）
        - hybrid: 混合模式（多阶段，有并行也有顺序）
        """
        if not parallel_groups:
            return 'sequential'

        if okr_mode == 'single':
            return 'sequential'

        has_nested = any(isinstance(g, list) and any(isinstance(x, list) for x in g)
                        for g in parallel_groups)

        if has_nested:
            return 'hybrid'

        if len(parallel_groups) == 1:
            group = parallel_groups[0]
            if isinstance(group, list) and len(group) > 1:
                if all(isinstance(x, list) for x in group):
                    return 'parallel'
                return 'parallel'
            return 'sequential'

        if len(parallel_groups) > 1:
            return 'hybrid'

        return 'sequential'

    def _configure_engineering(
        self,
        okr_set: OKRSet,
        sorted_nodes: List[str],
        kr_node_map: Dict[str, List[str]],
    ) -> dict:
        """
        Step 5: 工程配置

        配置项：
        - 超时时间
        - 重试策略
        - 降级策略
        - 必选/可选节点
        """
        node_timeout_ms = {}
        retry_policy = {}
        fallback_policy = {}
        required_nodes = []
        optional_nodes = []

        default_latency = {
            'simple': 5000,
            'standard': 30000,
            'deep': 60000,
        }
        default_timeout = default_latency.get(okr_set.complexity, 30000)

        kr_weights = {kr.id: kr.weight for kr in okr_set.key_results}

        for node in sorted_nodes:
            node_timeout_ms[node] = default_timeout
            retry_policy[node] = {'count': 1, 'delay_ms': 1000}

            if self.registry is not None and hasattr(self.registry, 'get'):
                try:
                    mod_info = self.registry.get(node)
                    if mod_info:
                        if hasattr(mod_info, 'estimated_latency_ms'):
                            node_timeout_ms[node] = mod_info.estimated_latency_ms * 2

                        if hasattr(mod_info, 'security_level'):
                            sec_level = mod_info.security_level
                            retry_count = {'R1': 2, 'R2': 1, 'R3': 0}.get(sec_level, 1)
                            retry_policy[node] = {
                                'count': retry_count,
                                'delay_ms': 1000,
                            }

                        if hasattr(mod_info, 'fallback'):
                            fb = mod_info.fallback
                            if fb and fb.get('enabled'):
                                fallback_policy[node] = fb.get('fallback_module', '')
                except Exception:
                    pass

            kr_id = None
            for kid, nodes in kr_node_map.items():
                if node in nodes:
                    kr_id = kid
                    break

            if kr_id and kr_weights.get(kr_id, 0) >= 0.2:
                required_nodes.append(node)
            else:
                optional_nodes.append(node)

        total_timeout = sum(node_timeout_ms.values())

        return {
            'total_timeout_ms': total_timeout,
            'node_timeout_ms': node_timeout_ms,
            'retry_policy': retry_policy,
            'fallback_policy': fallback_policy,
            'required_nodes': list(set(required_nodes)),
            'optional_nodes': list(set(optional_nodes)),
        }

    def _build_reverse_map(
        self,
        kr_node_map: Dict[str, List[str]],
    ) -> Dict[str, str]:
        """构建反向映射：节点ID → KR ID"""
        reverse = {}
        for kr_id, nodes in kr_node_map.items():
            for node in nodes:
                reverse[node] = kr_id
        return reverse
