#!/usr/bin/env python3
"""
WorkBuddy OS 图编排引擎核心 (Graph Orchestrator)

位置: experiments/ab-trading/core/graph_orchestrator.py

架构说明:
- S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
- A链: 执行闭环（三大闭环 + 三屏交易），使用SKILL方法论
- C链: 经典量化（经典指标系统）
- F链: 基本面（资金流、情绪、新闻）

核心功能:
1. GraphOrchestrator - 主编排器
2. NodeSelector - 动态节点选择器（基于意图/上下文/置信度）
3. ExecutionGraph - 执行图结构
4. ResultAggregator - 结果聚合器

设计原则:
- 从注册表动态获取节点配置
- 支持顺序/并行/条件执行
- 多模块结果融合与置信度计算
- 降级容错与执行统计
"""

import time
import uuid
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from .modules import (
    get_module_registry,
    get_module_executor,
    ExecutionContext,
    ModuleResult,
    ModuleOutputs,
    create_default_context,
)


# ============================================================
# 枚举类型
# ============================================================

class ExecutionMode(str, Enum):
    """执行模式"""
    SEQUENTIAL = "sequential"      # 顺序执行
    PARALLEL = "parallel"          # 并行执行
    CONDITIONAL = "conditional"    # 条件执行
    PIPELINE = "pipeline"          # 流水线执行


class NodeDependency(str, Enum):
    """节点依赖关系"""
    NONE = "none"                 # 无依赖
    BEFORE = "before"              # 必须在某节点之前
    AFTER = "after"               # 必须在某节点之后
    REQUIRES = "requires"         # 需要某节点结果


# ============================================================
# 执行图结构
# ============================================================

@dataclass
class NodeExecution:
    """节点执行配置"""
    module_id: str
    execution_order: int = 0
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    depends_on: List[str] = field(default_factory=list)
    condition: Optional[str] = None  # 条件表达式
    timeout_ms: int = 30000
    retry_count: int = 2
    required: bool = True  # 是否必须执行


@dataclass
class ExecutionGraph:
    """执行图"""
    graph_id: str
    nodes: List[NodeExecution] = field(default_factory=list)
    parallel_groups: List[List[str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeExecutionResult:
    """节点执行结果"""
    module_id: str
    success: bool
    outputs: ModuleOutputs
    confidence: float
    latency_ms: int
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    source: Optional[str] = None  # 'skill' / 'local_fallback' / 'api'
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


@dataclass
class GraphExecutionResult:
    """图执行结果"""
    graph_id: str
    success: bool
    final_direction: str
    final_confidence: float
    node_results: List[NodeExecutionResult] = field(default_factory=list)
    execution_time_ms: int = 0
    total_nodes: int = 0
    executed_nodes: int = 0
    skipped_nodes: int = 0
    failed_nodes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 动态节点选择器
# ============================================================

class NodeSelector:
    """
    动态节点选择器
    根据意图、上下文、市场条件选择合适的节点序列
    """

    def __init__(self):
        self.registry = get_module_registry()

    def select(
        self,
        intent: str,
        context: ExecutionContext,
        required_chain: Optional[str] = None,
    ) -> List[str]:
        """
        选择节点序列

        Args:
            intent: 意图类型
            context: 执行上下文
            required_chain: 要求的链类型

        Returns:
            节点ID列表
        """
        # 1. 根据意图和上下文确定节点选择策略
        strategy = self._determine_strategy(intent, context)

        # 2. 根据策略选择节点
        nodes = self._select_by_strategy(strategy, context, required_chain)

        # 3. 应用过滤条件
        nodes = self._apply_filters(nodes, context)

        return nodes

    def _determine_strategy(self, intent: str, context: ExecutionContext) -> str:
        """确定节点选择策略"""
        market_condition = context.market_condition or 'unknown'

        strategy_map = {
            'market_query': 'fast_scan',           # 快速扫描
            'deep_analysis': 'full_analysis',       # 完整分析
            'trading_decision': 'trading',         # 交易决策
            'risk_assessment': 'risk_check',       # 风险评估
            'portfolio_review': 'portfolio',         # 组合回顾
        }

        base_strategy = strategy_map.get(intent, 'fast_scan')

        # 根据市场条件调整
        if market_condition == 'volatile':
            base_strategy += '_volatile'
        elif market_condition == 'trending':
            base_strategy += '_trending'

        return base_strategy

    def _select_by_strategy(
        self,
        strategy: str,
        context: ExecutionContext,
        required_chain: Optional[str] = None,
    ) -> List[str]:
        """根据策略选择节点"""
        # 默认节点序列
        default_nodes = [
            'dream-contradiction-theory',
            'dream-first-principles',
        ]

        strategies = {
            # 快速扫描策略
            'fast_scan': [
                'dream-contradiction-theory',  # A0: 快速矛盾检测
                'classic-indicator-scan',       # C1: 技术扫描
            ],

            # 完整分析策略
            'full_analysis': [
                'dream-contradiction-theory',  # A0: 矛盾检测
                'dream-first-principles',        # A2: 第一性原理
                'dream-strategy-research',       # A1: 策略研究
                'dream-exit-skill-v2',          # A9: 离场评估
            ],

            # 交易决策策略
            'trading': [
                'dream-contradiction-theory',   # A0: 矛盾检测
                'dream-first-principles',       # A2: 第一性原理
                'dream-strategy-designer',       # A3: 策略设计
                'dream-risk-position-sizing',    # 风险仓位
                'dream-gate-keeper',            # A4: 门禁
            ],

            # 风险评估策略
            'risk_check': [
                'classic-regime-detection',     # C2: Regime识别
                'dream-contradiction-theory',   # A0: 矛盾检测
                'dream-risk-assessment',        # 风险评估
            ],

            # 组合回顾策略
            'portfolio': [
                'dream-portfolio-overview',     # 组合概览
                'dream-exit-skill-v2',          # A9: 离场评估
                'dream-performance-review',     # 绩效回顾
            ],

            # A链核心策略 - 三大闭环
            'a_chain_core': [
                'dream-contradiction-theory',   # A0: 执行闭环 - 矛盾检测
                'dream-first-principles',       # A2: 执行闭环 - 第一性原理
                'dream-strategy-designer',     # A3: 执行闭环 - 策略设计
                'dream-gate-keeper',           # A4: 执行闭环 - 门禁
            ],

            # 三屏交易策略
            'three_screen': [
                'dream-screen1-first',          # Screen1: 周线方向
                'dream-screen2-swing',          # Screen2: 日线预设
                'dream-screen3-intra',          # Screen3: 实时执行
            ],

            # C链经典量化策略
            'c_chain_classic': [
                'classic-indicator-scan',       # C1: 技术扫描
                'classic-regime-detection',     # C2: Regime识别
                'classic-trade-signal',        # C3: 交易信号
            ],

            # 标准策略
            'standard': default_nodes,

            # 波动市场变体
            'fast_scan_volatile': [
                'dream-contradiction-theory',   # A0: 矛盾检测
                'classic-regime-detection',      # C2: Regime识别
            ],

            # 趋势市场变体
            'full_analysis_trending': [
                'dream-contradiction-theory',   # A0: 矛盾检测
                'dream-first-principles',       # A2: 第一性原理
                'dream-strategy-designer',     # A3: 策略设计
            ],
        }

        nodes = strategies.get(strategy, default_nodes)

        # 如果指定了链类型，过滤节点
        if required_chain:
            chain_nodes = []
            for node_id in nodes:
                mod = self.registry.get(node_id)
                if mod and mod.chain == required_chain:
                    chain_nodes.append(node_id)
            if chain_nodes:
                nodes = chain_nodes

        return nodes

    def _apply_filters(
        self,
        nodes: List[str],
        context: ExecutionContext,
    ) -> List[str]:
        """应用过滤条件"""
        filtered = []

        for node_id in nodes:
            mod = self.registry.get(node_id)
            if not mod:
                continue

            # 检查模块是否活跃
            if not self.registry.is_active(node_id):
                continue

            # 检查安全等级
            if context.user_role == 'FREE' and mod.security_level in ('R2', 'R3'):
                continue

            # 检查适用意图
            if context.intent not in mod.applicable_intents and mod.applicable_intents:
                # 允许部分匹配
                pass

            # 检查适用市场条件
            if context.market_condition and context.market_condition != 'unknown':
                # 只有在明确指定市场条件时才过滤
                if context.market_condition not in mod.market_conditions and mod.market_conditions:
                    # 市场条件不匹配时跳过
                    continue

            filtered.append(node_id)

        return filtered

    def select_by_chain(self, chain: str) -> List[str]:
        """选择指定链的所有节点"""
        modules = self.registry.get_by_chain(chain)
        return [m.id for m in modules if self.registry.is_active(m.id)]

    def select_by_stage(self, stage: str) -> List[str]:
        """选择适用于指定阶段的节点"""
        modules = self.registry.query(stage=stage)
        return [m.id for m in modules if self.registry.is_active(m.id)]

    def select_by_intent(self, intent: str) -> List[str]:
        """选择适用于指定意图的节点"""
        modules = self.registry.query(intent=intent)
        return [m.id for m in modules if self.registry.is_active(m.id)]

    def select_by_market_condition(self, condition: str) -> List[str]:
        """选择适用于指定市场条件的节点"""
        modules = self.registry.query(market_condition=condition)
        return [m.id for m in modules if self.registry.is_active(m.id)]

    def select_three_screen(self) -> List[str]:
        """选择三屏交易节点"""
        return [
            'dream-screen1-first',   # Screen1: 周线方向
            'dream-screen2-swing',  # Screen2: 日线预设
            'dream-screen3-intra',  # Screen3: 实时执行
        ]

    def select_a_chain_core(self) -> List[str]:
        """选择A链核心节点（三大闭环）"""
        return [
            'dream-contradiction-theory',  # A0: 执行闭环 - 矛盾检测
            'dream-first-principles',       # A2: 执行闭环 - 第一性原理
            'dream-strategy-designer',     # A3: 执行闭环 - 策略设计
            'dream-gate-keeper',           # A4: 执行闭环 - 门禁
        ]

    def select_c_chain_classic(self) -> List[str]:
        """选择C链经典量化节点"""
        return [
            'classic-indicator-scan',      # C1: 技术扫描
            'classic-regime-detection',   # C2: Regime识别
            'classic-trade-signal',      # C3: 交易信号
        ]

    def get_available_nodes(self) -> List[Dict[str, Any]]:
        """获取所有可用节点信息"""
        modules = self.registry.get_all()
        return [
            {
                'id': m.id,
                'name': m.name,
                'chain': m.chain,
                'category': m.category,
                'stage': m.applicable_stages,
                'intent': m.applicable_intents,
                'confidence_range': m.confidence_range,
            }
            for m in modules if self.registry.is_active(m.id)
        ]


# ============================================================
# 结果聚合器
# ============================================================

class ResultAggregator:
    """
    结果聚合器
    将多个节点执行结果融合为最终决策
    """

    def __init__(self, chain_weights: Dict[str, float] = None):
        self.chain_weights = chain_weights or {
            'A': 0.35,
            'C': 0.45,
            'F': 0.20,
        }

    def aggregate(
        self,
        results: List[NodeExecutionResult],
        registry,
    ) -> Tuple[str, float]:
        """
        聚合结果

        Args:
            results: 节点执行结果列表
            registry: 模块注册表

        Returns:
            (最终方向, 最终置信度)
        """
        if not results:
            return 'HOLD', 0.3

        # 按链分组
        by_chain: Dict[str, List[NodeExecutionResult]] = {}
        for r in results:
            if not r.success or r.skipped:
                continue
            mod = registry.get(r.module_id)
            if mod:
                chain = mod.chain
                if chain not in by_chain:
                    by_chain[chain] = []
                by_chain[chain].append(r)

        # 计算各链的加权置信度
        chain_scores: Dict[str, Tuple[str, float]] = {}
        for chain, chain_results in by_chain.items():
            direction, confidence = self._aggregate_chain(chain_results)
            chain_scores[chain] = (direction, confidence)

        # 加权融合
        total_weight = 0.0
        weighted_confidence = 0.0
        direction_votes: Dict[str, float] = {}

        for chain, (direction, confidence) in chain_scores.items():
            weight = self.chain_weights.get(chain, 0.33)
            total_weight += weight
            weighted_confidence += confidence * weight

            # 方向投票
            if direction not in direction_votes:
                direction_votes[direction] = 0.0
            direction_votes[direction] += weight * confidence

        if total_weight > 0:
            weighted_confidence /= total_weight

        # 确定最终方向
        final_direction = max(direction_votes.items(), key=lambda x: x[1])[0]

        # 如果投票分散，降低置信度
        max_vote = max(direction_votes.values()) if direction_votes else 0
        vote_spread = sum(direction_votes.values())
        if vote_spread > 0:
            confidence_ratio = max_vote / vote_spread
            if confidence_ratio < 0.5:
                weighted_confidence *= 0.8  # 方向不一致，降低置信度

        return final_direction, min(weighted_confidence, 0.95)

    def _aggregate_chain(
        self,
        results: List[NodeExecutionResult],
    ) -> Tuple[str, float]:
        """聚合单个链的结果"""
        if not results:
            return 'HOLD', 0.3

        # 同向结果加权平均
        direction_scores: Dict[str, List[float]] = {}
        for r in results:
            direction = r.outputs.direction or 'HOLD'
            if direction not in direction_scores:
                direction_scores[direction] = []
            direction_scores[direction].append(r.confidence)

        if not direction_scores:
            return 'HOLD', 0.3

        # 选择置信度最高的方向
        best_direction = max(
            direction_scores.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0
        )[0]

        # 计算该方向的加权置信度
        confidences = direction_scores[best_direction]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.3

        # 同向节点数加成
        same_dir_count = len(confidences)
        if same_dir_count > 1:
            avg_confidence = min(avg_confidence + 0.02 * (same_dir_count - 1), 0.95)

        return best_direction, avg_confidence


# ============================================================
# 图编排引擎核心
# ============================================================

class GraphOrchestrator:
    """
    图编排引擎核心

    核心功能:
    1. 动态节点选择（基于意图/上下文/置信度）
    2. 执行图构建（顺序/并行/条件）
    3. 图执行（单节点/批量/并行）
    4. 结果聚合（多链融合/置信度计算）
    5. 降级容错与执行统计
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.registry = get_module_registry()
        self.executor = get_module_executor()
        self.node_selector = NodeSelector()
        self.result_aggregator = ResultAggregator()
        self._execution_history: List[GraphExecutionResult] = []

    def execute(
        self,
        context: ExecutionContext,
        intent: Optional[str] = None,
        node_ids: Optional[List[str]] = None,
        execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    ) -> GraphExecutionResult:
        """
        执行图编排

        Args:
            context: 执行上下文
            intent: 意图类型（可选，用于节点选择）
            node_ids: 指定的节点ID列表（可选，优先级高于intent）
            execution_mode: 执行模式

        Returns:
            GraphExecutionResult - 图执行结果
        """
        graph_id = f"graph_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        # 1. 确定要执行的节点
        if node_ids:
            selected_nodes = node_ids
        elif intent:
            selected_nodes = self.node_selector.select(
                intent=intent,
                context=context,
            )
        else:
            # 默认执行A链核心节点
            selected_nodes = [
                'dream-contradiction-theory',
                'dream-first-principles',
            ]

        # 2. 构建执行图
        graph = self._build_graph(graph_id, selected_nodes, execution_mode)

        # 3. 执行图
        node_results = self._execute_graph(graph, context)

        # 4. 聚合结果
        final_direction, final_confidence = self.result_aggregator.aggregate(
            node_results,
            self.registry,
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # 5. 构建结果
        result = GraphExecutionResult(
            graph_id=graph_id,
            success=any(r.success for r in node_results),
            final_direction=final_direction,
            final_confidence=final_confidence,
            node_results=node_results,
            execution_time_ms=execution_time_ms,
            total_nodes=len(graph.nodes),
            executed_nodes=sum(1 for r in node_results if not r.skipped),
            skipped_nodes=sum(1 for r in node_results if r.skipped),
            failed_nodes=sum(1 for r in node_results if not r.success and not r.skipped),
            metadata={
                'intent': intent,
                'execution_mode': execution_mode.value,
                'selected_nodes': selected_nodes,
            },
        )

        self._execution_history.append(result)
        return result

    def _build_graph(
        self,
        graph_id: str,
        node_ids: List[str],
        mode: ExecutionMode,
    ) -> ExecutionGraph:
        """构建执行图（从注册表获取节点配置）"""
        nodes = []
        for i, node_id in enumerate(node_ids):
            # 从注册表获取节点配置
            mod_info = self.registry.get(node_id)
            if not mod_info:
                continue

            # 构建节点执行配置
            node_exec = NodeExecution(
                module_id=node_id,
                execution_order=i,
                mode=mode,
                depends_on=mod_info.dependencies,  # 从注册表获取依赖
            )

            # 根据适配器类型设置超时
            adapter_type = mod_info.adapter.get('type', 'skill')
            if adapter_type == 'api':
                node_exec.timeout_ms = 30000  # API调用超时30秒
            elif adapter_type == 'skill':
                node_exec.timeout_ms = mod_info.estimated_latency_ms or 120000  # SKILL调用超时2分钟
            else:
                node_exec.timeout_ms = 10000  # 本地执行超时10秒

            nodes.append(node_exec)

        # 构建并行组（如果有）
        parallel_groups = []
        if mode == ExecutionMode.PARALLEL:
            parallel_groups.append(node_ids)

        return ExecutionGraph(
            graph_id=graph_id,
            nodes=nodes,
            parallel_groups=parallel_groups,
            metadata={
                'mode': mode.value,
                'nodes_config': [self.registry.get(nid).__dict__ if self.registry.get(nid) else {} for nid in node_ids]
            },
        )

    def _execute_graph(
        self,
        graph: ExecutionGraph,
        context: ExecutionContext,
    ) -> List[NodeExecutionResult]:
        """执行图（支持顺序/并行/条件执行）"""
        results = []

        if graph.metadata.get('mode') == 'parallel':
            # 并行执行所有节点
            return self._execute_parallel(graph, context)
        else:
            # 顺序执行
            return self._execute_sequential(graph, context)

    def _execute_sequential(
        self,
        graph: ExecutionGraph,
        context: ExecutionContext,
    ) -> List[NodeExecutionResult]:
        """顺序执行"""
        results = []
        prior_outputs = {}  # 用于存储前置节点的输出

        for node_exec in graph.nodes:
            # 条件执行：检查前置条件
            if not self._check_execution_condition(node_exec, results, prior_outputs):
                results.append(NodeExecutionResult(
                    module_id=node_exec.module_id,
                    success=True,
                    outputs=ModuleOutputs(),
                    confidence=0.0,
                    latency_ms=0,
                    skipped=True,
                    skip_reason="条件不满足",
                ))
                continue

            # 更新上下文（携带前置节点结果）
            exec_context = self._inject_prior_outputs(context, prior_outputs)

            # 执行节点
            result = self._execute_node(node_exec, exec_context)
            results.append(result)

            # 记录输出用于后续节点
            if result.success and not result.skipped:
                prior_outputs[node_exec.module_id] = result

            # 如果执行失败且节点是必须的，停止执行
            if not result.success and node_exec.required:
                # 记录失败原因
                prior_outputs['_last_error'] = result.error
                # 可选：继续执行或停止
                # return results  # 取消注释以在失败时停止

        return results

    def _execute_parallel(
        self,
        graph: ExecutionGraph,
        context: ExecutionContext,
    ) -> List[NodeExecutionResult]:
        """并行执行所有节点"""
        import concurrent.futures

        results = []
        prior_outputs = {}

        def execute_node_wrapper(node_exec):
            return self._execute_node(node_exec, context)

        # 使用线程池并行执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_node = {
                executor.submit(execute_node_wrapper, node_exec): node_exec
                for node_exec in graph.nodes
            }

            # 按原始顺序收集结果
            node_to_future = {id(f): node for f, node in future_to_node.items()}
            results = [None] * len(graph.nodes)

            for future in concurrent.futures.as_completed(future_to_node):
                node_exec = future_to_node[future]
                idx = next(
                    i for i, n in enumerate(graph.nodes)
                    if n.module_id == node_exec.module_id
                )
                try:
                    result = future.result()
                    results[idx] = result

                    # 记录输出
                    if result.success and not result.skipped:
                        prior_outputs[node_exec.module_id] = result
                except Exception as e:
                    results[idx] = NodeExecutionResult(
                        module_id=node_exec.module_id,
                        success=False,
                        outputs=ModuleOutputs(),
                        confidence=0.0,
                        latency_ms=0,
                        error=str(e),
                    )

        return [r for r in results if r is not None]

    def _check_execution_condition(
        self,
        node_exec: NodeExecution,
        prior_results: List[NodeExecutionResult],
        prior_outputs: Dict[str, Any],
    ) -> bool:
        """检查节点执行条件"""
        # 如果没有依赖条件，默认执行
        if not node_exec.condition:
            return True

        condition = node_exec.condition

        # 解析条件表达式
        # 支持: confidence_above_50, direction_long, has_error 等

        if condition == 'confidence_above_50':
            if prior_outputs:
                last_result = list(prior_outputs.values())[-1]
                if isinstance(last_result, NodeExecutionResult):
                    return last_result.confidence >= 50.0
            return False

        if condition == 'direction_long':
            if prior_outputs:
                for output in prior_outputs.values():
                    if isinstance(output, NodeExecutionResult):
                        if output.outputs.direction == 'long':
                            return True
            return False

        if condition == 'no_error':
            return '_last_error' not in prior_outputs

        if condition == 'has_direction':
            if prior_outputs:
                for output in prior_outputs.values():
                    if isinstance(output, NodeExecutionResult):
                        if output.outputs.direction and output.outputs.direction != 'HOLD':
                            return True
            return False

        return True

    def _inject_prior_outputs(
        self,
        context: ExecutionContext,
        prior_outputs: Dict[str, Any],
    ) -> ExecutionContext:
        """将前置节点输出注入到上下文中"""
        # 构建前置输出摘要
        prior_summary = {}
        for node_id, result in prior_outputs.items():
            if isinstance(result, NodeExecutionResult):
                prior_summary[node_id] = {
                    'direction': result.outputs.direction,
                    'confidence': result.confidence,
                    'analysis': result.outputs.analysis,
                }

        # 更新上下文
        new_context = ExecutionContext(
            session_id=context.session_id,
            intent=context.intent,
            symbol=context.symbol,
            user_role=context.user_role,
            trading_mode=context.trading_mode,
            budget_tokens=context.budget_tokens,
            max_latency_ms=context.max_latency_ms,
            chain_weights=context.chain_weights,
            prior_outputs=prior_summary,
            market_condition=context.market_condition,
            user_preferences=context.user_preferences,
            mkt=context.mkt,
            memory=context.memory,
            extra=context.extra,
        )

        return new_context

    def _execute_node(
        self,
        node_exec: NodeExecution,
        context: ExecutionContext,
    ) -> NodeExecutionResult:
        """执行单个节点"""
        start_time = time.time()
        module_id = node_exec.module_id

        try:
            # 检查节点是否在注册表中
            if not self.registry.has(module_id):
                return NodeExecutionResult(
                    module_id=module_id,
                    success=False,
                    outputs=ModuleOutputs(),
                    confidence=0.0,
                    latency_ms=int((time.time() - start_time) * 1000),
                    skipped=False,
                    error=f"模块 {module_id} 不存在",
                )

            # 检查节点是否活跃
            if not self.registry.is_active(module_id):
                return NodeExecutionResult(
                    module_id=module_id,
                    success=True,
                    outputs=ModuleOutputs(),
                    confidence=0.0,
                    latency_ms=int((time.time() - start_time) * 1000),
                    skipped=True,
                    skip_reason="模块未激活",
                )

            # 执行模块
            result = self.executor.execute(
                module_id=module_id,
                inputs={},
                context=context,
            )

            # 判断来源
            source = 'skill'
            if result.fallback_used:
                source = 'local_fallback'
            elif result.metadata.get('source') == 'local_fallback':
                source = 'local_fallback'

            return NodeExecutionResult(
                module_id=module_id,
                success=result.success,
                outputs=result.outputs,
                confidence=result.confidence,
                latency_ms=int((time.time() - start_time) * 1000),
                source=source,
                fallback_used=result.fallback_used,
                fallback_reason=result.fallback_reason,
            )

        except Exception as e:
            return NodeExecutionResult(
                module_id=module_id,
                success=False,
                outputs=ModuleOutputs(),
                confidence=0.0,
                latency_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    def get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        total = len(self._execution_history)
        if total == 0:
            return {
                'total_executions': 0,
                'success_rate': 0.0,
                'avg_execution_time_ms': 0,
                'avg_nodes_per_execution': 0,
            }

        success_count = sum(1 for r in self._execution_history if r.success)
        total_time = sum(r.execution_time_ms for r in self._execution_history)
        total_nodes = sum(r.total_nodes for r in self._execution_history)

        return {
            'total_executions': total,
            'success_rate': success_count / total,
            'avg_execution_time_ms': total_time / total,
            'avg_nodes_per_execution': total_nodes / total,
            'by_intent': self._aggregate_by_intent(),
        }

    def _aggregate_by_intent(self) -> Dict[str, Dict[str, Any]]:
        """按意图聚合统计"""
        by_intent: Dict[str, List[GraphExecutionResult]] = {}
        for r in self._execution_history:
            intent = r.metadata.get('intent', 'unknown')
            if intent not in by_intent:
                by_intent[intent] = []
            by_intent[intent].append(r)

        result = {}
        for intent, results in by_intent.items():
            success = sum(1 for r in results if r.success)
            result[intent] = {
                'count': len(results),
                'success_rate': success / len(results) if results else 0,
                'avg_confidence': sum(r.final_confidence for r in results) / len(results),
            }

        return result

    def execute_with_config(
        self,
        context: ExecutionContext,
        graph_config: Dict[str, Any],
    ) -> GraphExecutionResult:
        """
        根据注册表配置执行图

        Args:
            context: 执行上下文
            graph_config: 从注册表获取的图配置

        Returns:
            GraphExecutionResult
        """
        # 从配置中提取节点序列
        nodes = graph_config.get('nodes', [])
        if not nodes:
            # 尝试从dependencies构建依赖图
            nodes = self._build_dependency_order(graph_config)

        mode = ExecutionMode(graph_config.get('mode', 'sequential'))

        return self.execute(
            context=context,
            node_ids=nodes,
            execution_mode=mode,
        )

    def _build_dependency_order(self, config: Dict[str, Any]) -> List[str]:
        """根据依赖关系构建节点执行顺序"""
        # 获取所有节点
        all_nodes = set()
        for node_id, node_config in config.items():
            if isinstance(node_config, dict) and 'dependencies' in node_config:
                all_nodes.add(node_id)
                all_nodes.update(node_config.get('dependencies', []))
            elif isinstance(node_config, dict):
                all_nodes.add(node_id)

        # 简单拓扑排序
        result = []
        remaining = set(all_nodes)
        dependencies = {k: v.get('dependencies', []) if isinstance(v, dict) else [] for k, v in config.items()}

        while remaining:
            # 找到没有依赖或依赖已完成的节点
            ready = [
                n for n in remaining
                if not dependencies.get(n) or all(d not in remaining for d in dependencies[n])
            ]
            if not ready:
                # 循环依赖，随机选择一个
                ready = [remaining.pop()]
            else:
                for n in ready:
                    remaining.remove(n)
                    result.append(n)

        return result

    def get_node_info(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取节点信息（从注册表）"""
        mod = self.registry.get(node_id)
        if not mod:
            return None

        return {
            'id': mod.id,
            'name': mod.name,
            'description': mod.description,
            'version': mod.version,
            'chain': mod.chain,
            'category': mod.category,
            'security_level': mod.security_level,
            'estimated_tokens': mod.estimated_tokens,
            'estimated_latency_ms': mod.estimated_latency_ms,
            'confidence_range': mod.confidence_range,
            'applicable_stages': mod.applicable_stages,
            'applicable_intents': mod.applicable_intents,
            'market_conditions': mod.market_conditions,
            'historical_accuracy': mod.historical_accuracy,
            'dependencies': mod.dependencies,
            'adapter': mod.adapter,
            'fallback': mod.fallback,
            'is_active': self.registry.is_active(node_id),
        }

    def validate_execution_plan(
        self,
        node_ids: List[str],
    ) -> Tuple[bool, List[str]]:
        """
        验证执行计划的可行性

        Args:
            node_ids: 节点ID列表

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        for node_id in node_ids:
            mod = self.registry.get(node_id)
            if not mod:
                errors.append(f"节点 {node_id} 不存在")
                continue

            if not self.registry.is_active(node_id):
                errors.append(f"节点 {node_id} 未激活")

            # 检查依赖是否满足
            for dep_id in mod.dependencies:
                if dep_id not in node_ids:
                    errors.append(f"节点 {node_id} 依赖 {dep_id}，但该节点不在执行计划中")
                if not self.registry.is_active(dep_id):
                    errors.append(f"节点 {node_id} 的依赖 {dep_id} 未激活")

        return len(errors) == 0, errors


# ============================================================
# 快捷函数
# ============================================================

def create_orchestrator(config: Dict[str, Any] = None) -> GraphOrchestrator:
    """创建编排器"""
    return GraphOrchestrator(config)


def quick_analyze(
    intent: str,
    mkt: Dict[str, Any],
    symbol: str = 'BTC/USDT',
) -> GraphExecutionResult:
    """
    快速分析（快捷函数）

    Args:
        intent: 意图类型
        mkt: 市场数据
        symbol: 交易对

    Returns:
        GraphExecutionResult
    """
    context = create_default_context(f"quick_{uuid.uuid4().hex[:8]}")
    context.intent = intent
    context.symbol = symbol
    context.mkt = mkt

    orchestrator = GraphOrchestrator()
    return orchestrator.execute(context, intent=intent)


__all__ = [
    'ExecutionMode',
    'NodeDependency',
    'NodeExecution',
    'ExecutionGraph',
    'NodeExecutionResult',
    'GraphExecutionResult',
    'NodeSelector',
    'ResultAggregator',
    'GraphOrchestrator',
    'create_orchestrator',
    'quick_analyze',
]
