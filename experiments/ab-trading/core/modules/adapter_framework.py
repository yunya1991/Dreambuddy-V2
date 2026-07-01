#!/usr/bin/env python3
"""
WorkBuddy OS 模块适配器框架 (Python 侧)

位置: experiments/ab-trading/core/modules/adapter_framework.py

架构说明:
- S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
- A链: 执行闭环（三大闭环 + 三屏交易）
- C链: 经典量化（经典指标系统）
- F链: 基本面（资金流、情绪、新闻）
- G域: 治理域
- T域: 任务域

功能:
1. 统一的模块适配器基类 (BaseModuleAdapter)
2. SkillAdapter - 调用 SKILL.md 方法论（A链/C链/F链）
3. APIAdapter - 调用外部 API 服务（C链指标系统）
4. LocalAdapter - 本地规则实现（降级用）
5. NodeAdapter - 封装现有节点实现
6. ModuleExecutor - 统一模块执行器，支持降级容错

设计原则:
- 统一接口：所有适配器都遵循相同的 execute 协议
- 降级容错：主执行失败时自动尝试降级
- 成本核算：Token 消耗、延迟统计
- 置信度评估：多维度置信度评分
"""

import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

from .unified_types import (
    ModuleResult,
    ExecutionContext,
    ModuleOutputs,
    ConfidenceDimensions,
    create_success_result,
    create_failure_result,
    create_fallback_result,
)
from .module_registry import get_module_registry, ModuleInfo


# ============================================================
# 适配器基类
# ============================================================

class BaseModuleAdapter(ABC):
    """
    模块适配器基类
    所有适配器必须实现此接口
    """

    def __init__(self, module_id: str):
        self.module_id = module_id
        self._registry = get_module_registry()
        self._module_info: Optional[ModuleInfo] = None

    @property
    def module_info(self) -> Optional[ModuleInfo]:
        """获取模块元信息"""
        if self._module_info is None:
            self._module_info = self._registry.get(self.module_id)
        return self._module_info

    def is_available(self) -> bool:
        """检查适配器是否可用"""
        return True

    @abstractmethod
    def execute(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        """
        执行模块

        Args:
            inputs: 输入参数
            context: 执行上下文

        Returns:
            ModuleResult - 执行结果
        """
        pass

    def validate_inputs(self, inputs: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        验证输入合法性

        Returns:
            (is_valid, errors)
        """
        return True, []

    def get_fallback(self, inputs: Dict[str, Any], context: ExecutionContext) -> Optional[ModuleResult]:
        """
        获取降级实现
        默认返回 None，子类可覆盖
        """
        return None


# ============================================================
# Skill 适配器
# ============================================================

class SkillAdapter(BaseModuleAdapter):
    """
    SKILL 适配器
    封装对 SKILL.md 方法论的调用
    """

    def __init__(self, module_id: str, skill_name: str):
        super().__init__(module_id)
        self.skill_name = skill_name

    def is_available(self) -> bool:
        from .skill_loader import SkillLoader
        loader = SkillLoader()
        return loader.is_skill_available(self.skill_name)

    def execute(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        start_time = time.time()
        try:
            from .skill_loader import execute_skill

            is_valid, errors = self.validate_inputs(inputs)
            if not is_valid:
                return create_failure_result(
                    self.module_id,
                    f"输入验证失败: {', '.join(errors)}"
                )

            skill_inputs = {
                'mkt': context.mkt,
                'memory': context.memory,
                'data': inputs.get('data', {}),
                'a0': inputs.get('a0', {}),
                **inputs,
            }

            skill_result = execute_skill(self.skill_name, skill_inputs)
            latency_ms = int((time.time() - start_time) * 1000)

            outputs = ModuleOutputs(
                direction=skill_result.direction.lower() if skill_result.direction else None,
                analysis='\n'.join(skill_result.rationale),
                reasoning='\n'.join(skill_result.rationale),
                extra=skill_result.data,
            )

            # skill_result.confidence 已经是 0-1 范围，直接使用
            confidence = skill_result.confidence * 100
            confidence_dimensions = ConfidenceDimensions(
                data_completeness=min(confidence + 5, 100) if skill_result.used_skill else 40,
                logical_consistency=confidence,
                historical_performance=(
                    self.module_info.historical_accuracy
                    if self.module_info else 70.0
                ),
            )

            result = ModuleResult(
                success=True,
                capability_id=self.module_id,
                outputs=outputs,
                confidence=confidence,
                confidence_dimensions=confidence_dimensions,
                tokens_used=(
                    self.module_info.estimated_tokens
                    if self.module_info else 1000
                ),
                latency_ms=latency_ms,
                warnings=[] if skill_result.used_skill else ['使用降级实现'],
                metadata={
                    'skill_name': skill_result.skill_name,
                    'skill_version': skill_result.version,
                    'phases_executed': skill_result.phases_executed,
                    'used_skill': skill_result.used_skill,
                    'rationale': skill_result.rationale,
                },
                fallback_used=not skill_result.used_skill,
                fallback_reason=skill_result.fallback_reason,
            )

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            result = create_failure_result(self.module_id, str(e))
            result.latency_ms = latency_ms
            return result


# ============================================================
# API 适配器
# ============================================================

class APIAdapter(BaseModuleAdapter):
    """
    API 适配器
    封装对外部 API 服务的调用
    """

    def __init__(self, module_id: str, base_url: str, endpoint: str,
                 method: str = 'POST', timeout: int = 10):
        super().__init__(module_id)
        self.base_url = base_url.rstrip('/')
        self.endpoint = endpoint.lstrip('/')
        self.method = method.upper()
        self.timeout = timeout
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def is_available(self) -> bool:
        try:
            import requests
            resp = requests.get(f"{self.base_url}", timeout=2)
            return resp.status_code < 500
        except Exception:
            return False

    def execute(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        start_time = time.time()
        url = f"{self.base_url}/{self.endpoint}"

        try:
            import requests
            session = self._get_session()

            if self.method == 'GET':
                resp = session.get(url, params=inputs, timeout=self.timeout)
            else:
                resp = session.post(url, json=inputs, timeout=self.timeout)

            resp.raise_for_status()
            data = resp.json()
            latency_ms = int((time.time() - start_time) * 1000)

            outputs = ModuleOutputs.from_dict(data.get('outputs', data))
            confidence = data.get('confidence', 60.0)

            return ModuleResult(
                success=data.get('success', True),
                capability_id=self.module_id,
                outputs=outputs,
                confidence=confidence,
                confidence_dimensions=ConfidenceDimensions(
                    data_completeness=min(confidence + 10, 100),
                    logical_consistency=confidence,
                ),
                tokens_used=data.get('tokensUsed', 500),
                latency_ms=latency_ms,
                warnings=data.get('warnings', []),
                suggestions=data.get('suggestions', []),
                metadata=data.get('metadata', {}),
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            result = create_failure_result(self.module_id, f"API调用失败: {e}")
            result.latency_ms = latency_ms
            return result

    def get_fallback(self, inputs: Dict[str, Any], context: ExecutionContext) -> Optional[ModuleResult]:
        """
        API适配器降级：使用本地规则替代API调用

        针对API不可用的情况，提供本地简化实现作为降级方案
        """
        # 定义本地降级规则
        fallback_rules = {
            'classic-indicator-scan': self._local_c1_scan,
            'classic-regime-detection': self._local_regime_detection,
        }

        if self.module_id in fallback_rules:
            try:
                return fallback_rules[self.module_id](inputs, context)
            except Exception:
                return None

        return None

    def _local_c1_scan(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        """C1技术扫描本地降级实现"""
        mkt = context.mkt or {}

        # 简化的技术分析
        rsi = mkt.get('rsi14', 50)
        price = mkt.get('price', 0)
        ema20 = mkt.get('ema20', price)
        ema50 = mkt.get('ema50', price)
        ema200 = mkt.get('ema200', price)
        change24h = mkt.get('change_24h', 0)

        # 简单趋势判断
        direction = 'HOLD'
        if price > ema20 > ema50 > ema200 and change24h > 0:
            direction = 'long'
        elif price < ema20 < ema50 < ema200 and change24h < 0:
            direction = 'short'

        # RSI超买超卖判断
        confidence = 50.0
        if rsi > 70:
            confidence = 40.0  # 超买，降低置信度
        elif rsi < 30:
            confidence = 40.0  # 超卖，降低置信度

        return ModuleResult(
            success=True,
            capability_id=self.module_id,
            outputs=ModuleOutputs(
                direction=direction.lower() if direction else 'hold',
                analysis=f'本地简化分析: RSI={rsi:.1f}, 24H变化={change24h:.1f}%',
            ),
            confidence=confidence,
            confidence_dimensions=ConfidenceDimensions(
                data_completeness=50.0,
                logical_consistency=confidence,
            ),
            latency_ms=5,
            warnings=['API不可用，使用本地降级实现'],
            metadata={'source': 'local_fallback'},
            fallback_used=True,
            fallback_reason='API服务不可用',
        )

    def _local_regime_detection(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        """Regime检测本地降级实现"""
        mkt = context.mkt or {}

        price = mkt.get('price', 0)
        ema20 = mkt.get('ema20', price)
        ema50 = mkt.get('ema50', price)
        atr14 = mkt.get('atr14', price * 0.02)
        vol_ratio = mkt.get('vol_ratio', 1.0)

        # 简单Regime判断
        regime = 'unknown'
        if price > ema20 > ema50:
            regime = 'trending_up'
        elif price < ema20 < ema50:
            regime = 'trending_down'
        else:
            regime = 'ranging'

        volatility = 'normal'
        if vol_ratio > 1.5:
            volatility = 'high'
        elif vol_ratio < 0.7:
            volatility = 'low'

        return ModuleResult(
            success=True,
            capability_id=self.module_id,
            outputs=ModuleOutputs(
                direction=regime,
                analysis=f'Regime={regime}, Volatility={volatility}',
                extra={
                    'regime': regime,
                    'volatility': volatility,
                }
            ),
            confidence=45.0,
            confidence_dimensions=ConfidenceDimensions(
                data_completeness=40.0,
                logical_consistency=45.0,
            ),
            latency_ms=5,
            warnings=['API不可用，使用本地降级实现'],
            metadata={'source': 'local_fallback'},
            fallback_used=True,
            fallback_reason='API服务不可用',
        )


# ============================================================
# Local 适配器（本地规则降级）
# ============================================================

class LocalAdapter(BaseModuleAdapter):
    """
    本地规则适配器
    使用本地实现作为降级方案
    """

    def __init__(self, module_id: str, handler: Callable[[Dict, ExecutionContext], ModuleResult]):
        super().__init__(module_id)
        self.handler = handler

    def is_available(self) -> bool:
        return True

    def execute(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        start_time = time.time()
        try:
            result = self.handler(inputs, context)
            latency_ms = int((time.time() - start_time) * 1000)
            result.latency_ms = latency_ms
            result.fallback_used = True
            if not result.warnings:
                result.warnings = ['使用本地降级实现']
            return result
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            result = create_failure_result(self.module_id, f"本地执行失败: {e}")
            result.latency_ms = latency_ms
            return result


# ============================================================
# 节点适配器（从现有的 nodes/ 模块创建）
# ============================================================

class NodeAdapter(BaseModuleAdapter):
    """
    节点适配器
    封装现有 core/nodes/ 下的节点实现
    """

    def __init__(self, module_id: str, node_id: str):
        super().__init__(module_id)
        self.node_id = node_id

    def is_available(self) -> bool:
        try:
            from core.nodes import get_node_handler
            return get_node_handler(self.node_id) is not None
        except Exception:
            return False

    def execute(self, inputs: Dict[str, Any], context: ExecutionContext) -> ModuleResult:
        start_time = time.time()
        try:
            from core.nodes import get_node_handler

            handler = get_node_handler(self.node_id)
            if handler is None:
                return create_failure_result(
                    self.module_id,
                    f"节点 {self.node_id} 未找到"
                )

            mkt = context.mkt or inputs.get('mkt', {})
            memory = context.memory or inputs.get('memory', {})
            data = inputs.get('data', {})

            node_result = handler(mkt, memory, data)
            latency_ms = int((time.time() - start_time) * 1000)

            direction = node_result.get('direction', 'HOLD')
            confidence = node_result.get('confidence', 0.5) * 100
            rationale = node_result.get('rationale', [])
            result_data = node_result.get('data', {})

            outputs = ModuleOutputs(
                direction=direction.lower() if direction else None,
                analysis='\n'.join(rationale) if rationale else None,
                reasoning='\n'.join(rationale) if rationale else None,
                extra=result_data,
            )

            return ModuleResult(
                success=True,
                capability_id=self.module_id,
                outputs=outputs,
                confidence=confidence,
                confidence_dimensions=ConfidenceDimensions(
                    data_completeness=min(confidence + 5, 100),
                    logical_consistency=confidence,
                    historical_performance=(
                        self.module_info.historical_accuracy
                        if self.module_info else 65.0
                    ),
                ),
                tokens_used=(
                    self.module_info.estimated_tokens
                    if self.module_info else 0
                ),
                latency_ms=latency_ms,
                warnings=['本地节点实现，零Token消耗'],
                metadata={
                    'node_id': self.node_id,
                    'rationale': rationale,
                },
                fallback_used=True,
                fallback_reason='local_node',
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            result = create_failure_result(self.module_id, f"节点执行失败: {e}")
            result.latency_ms = latency_ms
            return result


# ============================================================
# 模块执行器（统一调度 + 降级容错）
# ============================================================

class ModuleExecutor:
    """
    模块执行器
    统一调度模块执行，支持降级容错、成本控制、置信度评估
    """

    def __init__(self):
        self._adapters: Dict[str, BaseModuleAdapter] = {}
        self._registry = get_module_registry()
        self._execution_count: Dict[str, int] = {}
        self._total_latency: Dict[str, float] = {}

    def register_adapter(self, module_id: str, adapter: BaseModuleAdapter) -> None:
        """注册模块适配器"""
        self._adapters[module_id] = adapter

    def get_adapter(self, module_id: str) -> Optional[BaseModuleAdapter]:
        """获取模块适配器"""
        if module_id in self._adapters:
            return self._adapters[module_id]

        adapter = self._auto_create_adapter(module_id)
        if adapter:
            self._adapters[module_id] = adapter
        return adapter

    def _auto_create_adapter(self, module_id: str) -> Optional[BaseModuleAdapter]:
        """根据注册表自动创建适配器"""
        module_info = self._registry.get(module_id)
        if not module_info:
            return None

        adapter_type = module_info.adapter.get('type', 'local')

        if adapter_type == 'skill':
            skill_md = module_info.adapter.get('skill_md', '')
            skill_name = module_id
            return SkillAdapter(module_id, skill_name)

        elif adapter_type == 'api':
            base_url = module_info.adapter.get('base_url', '')
            endpoint = module_info.adapter.get('endpoint', '')
            if base_url and endpoint:
                return APIAdapter(module_id, base_url, endpoint)

        elif adapter_type == 'local':
            node_map = {
                'dream-contradiction-theory': 'A0_矛盾论',
                'dream-first-principles': 'A2_分析(含A0)',
                'dream-exit-skill-v2': 'A9_离场评估',
                'classic-indicator-scan': 'C1_技术扫描',
                'dream-oneirology': '做梦部',
            }
            node_id = node_map.get(module_id)
            if node_id:
                return NodeAdapter(module_id, node_id)

        return None

    def execute(self, module_id: str, inputs: Dict[str, Any],
                context: ExecutionContext) -> ModuleResult:
        """
        执行模块（含降级容错）

        Args:
            module_id: 模块ID
            inputs: 输入参数
            context: 执行上下文

        Returns:
            ModuleResult - 执行结果
        """
        adapter = self.get_adapter(module_id)

        if adapter is None:
            return create_fallback_result(
                module_id,
                f"模块 {module_id} 未注册适配器",
                confidence=20.0,
            )

        try:
            result = adapter.execute(inputs, context)

            self._execution_count[module_id] = (
                self._execution_count.get(module_id, 0) + 1
            )
            if result.latency_ms:
                self._total_latency[module_id] = (
                    self._total_latency.get(module_id, 0) + result.latency_ms
                )

            if result.success:
                return result

            if not result.fallback_used:
                fallback_result = self._try_fallback(module_id, inputs, context, adapter)
                if fallback_result:
                    return fallback_result

            return result

        except Exception as e:
            fallback_result = self._try_fallback(module_id, inputs, context, adapter)
            if fallback_result:
                return fallback_result

            return create_failure_result(module_id, f"执行异常: {e}")

    def _try_fallback(self, module_id: str, inputs: Dict[str, Any],
                      context: ExecutionContext,
                      adapter: BaseModuleAdapter) -> Optional[ModuleResult]:
        """尝试降级执行"""
        try:
            fallback_result = adapter.get_fallback(inputs, context)
            if fallback_result:
                return fallback_result
        except Exception:
            pass

        module_info = self._registry.get(module_id)
        if module_info and module_info.fallback.get('enabled'):
            fallback_module_id = module_info.fallback.get('fallback_module')
            if fallback_module_id and fallback_module_id != module_id:
                try:
                    fallback_result = self.execute(fallback_module_id, inputs, context)
                    fallback_result.fallback_used = True
                    fallback_result.fallback_reason = (
                        module_info.fallback.get('fallback_reason', '模块降级')
                    )
                    if not fallback_result.warnings:
                        fallback_result.warnings = [
                            f"从 {module_id} 降级到 {fallback_module_id}"
                        ]
                    return fallback_result
                except Exception:
                    pass

        return None

    def execute_batch(self, calls: List[Dict[str, Any]],
                      context: ExecutionContext) -> List[ModuleResult]:
        """批量执行模块"""
        results = []
        for call in calls:
            module_id = call.get('module_id', call.get('skillId', ''))
            inputs = call.get('inputs', {})
            result = self.execute(module_id, inputs, context)
            results.append(result)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        stats = {}
        for module_id, count in self._execution_count.items():
            total_latency = self._total_latency.get(module_id, 0)
            avg_latency = total_latency / count if count > 0 else 0
            stats[module_id] = {
                'execution_count': count,
                'total_latency_ms': total_latency,
                'avg_latency_ms': avg_latency,
            }
        return stats

    def reset_stats(self) -> None:
        """重置统计"""
        self._execution_count.clear()
        self._total_latency.clear()


# ============================================================
# 全局执行器单例
# ============================================================

_global_executor: Optional[ModuleExecutor] = None


def get_module_executor() -> ModuleExecutor:
    """获取全局模块执行器"""
    global _global_executor
    if _global_executor is None:
        _global_executor = ModuleExecutor()
    return _global_executor


__all__ = [
    'BaseModuleAdapter',
    'SkillAdapter',
    'APIAdapter',
    'LocalAdapter',
    'NodeAdapter',
    'ModuleExecutor',
    'get_module_executor',
]
