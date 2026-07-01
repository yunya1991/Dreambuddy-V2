#!/usr/bin/env python3
"""
WorkBuddy OS 统一类型定义 (Python 侧)

位置: experiments/ab-trading/core/modules/unified_types.py

架构说明:
- S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
- A链: 执行闭环（三大闭环 + 三屏交易），使用SKILL方法论
- C链: 经典量化（经典指标系统）
- F链: 基本面（资金流、情绪、新闻）

功能:
1. 统一 ModuleResult 结构（与 TS 侧对齐）
2. 统一 ExecutionContext 结构
3. 统一 ModuleQuery 结构
4. 置信度维度评分
5. 降级与错误处理

对齐 TS 侧 6-图结构上下文压缩/planner/skill-types.ts
"""

from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


# ============================================================
# 基础枚举类型
# ============================================================

class SkillChain(str, Enum):
    """技能所属链"""
    A = 'A'
    C = 'C'
    F = 'F'
    G = 'G'
    T = 'T'


class ThinkStage(str, Enum):
    """思维阶段"""
    RESEARCH = 'research'
    ANALYSIS = 'analysis'
    DESIGN = 'design'
    VALIDATE = 'validate'
    EXECUTE = 'execute'


class TradeDirection(str, Enum):
    """交易方向"""
    LONG = 'long'
    SHORT = 'short'
    NEUTRAL = 'neutral'
    WAIT = 'wait'


class SecurityLevel(str, Enum):
    """安全等级"""
    R0 = 'R0'  # 公开
    R1 = 'R1'  # 内部
    R2 = 'R2'  # 敏感
    R3 = 'R3'  # 关键


class ModuleStatus(str, Enum):
    """模块状态"""
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    DEPRECATED = 'deprecated'
    EXPERIMENTAL = 'experimental'


class AdapterType(str, Enum):
    """适配器类型"""
    SKILL = 'skill'
    API = 'api'
    LOCAL = 'local'
    EXTERNAL = 'external'
    MCP = 'mcp'


class ExecutionEngine(str, Enum):
    """执行引擎"""
    PYTHON = 'python'
    TYPESCRIPT = 'typescript'
    BOTH = 'both'
    EXTERNAL = 'external'


# ============================================================
# 置信度维度评分
# ============================================================

@dataclass
class ConfidenceDimensions:
    """置信度分项评分"""
    data_completeness: float = 0.0      # 数据完整性 (0-100)
    logical_consistency: float = 0.0   # 逻辑一致性 (0-100)
    cross_validation: Optional[float] = None  # 跨源印证 (0-100)
    historical_performance: Optional[float] = None  # 历史准确率 (0-100)

    def to_dict(self) -> Dict:
        return {
            'dataCompleteness': self.data_completeness,
            'logicalConsistency': self.logical_consistency,
            'crossValidation': self.cross_validation,
            'historicalPerformance': self.historical_performance,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ConfidenceDimensions':
        return cls(
            data_completeness=data.get('dataCompleteness', 0.0),
            logical_consistency=data.get('logicalConsistency', 0.0),
            cross_validation=data.get('crossValidation'),
            historical_performance=data.get('historicalPerformance'),
        )


# ============================================================
# 模块输出结构
# ============================================================

@dataclass
class ModuleOutputs:
    """模块输出的联合类型"""
    # 基础输出
    direction: Optional[str] = None
    confidence: Optional[float] = None

    # 分析输出
    analysis: Optional[str] = None
    reasoning: Optional[str] = None

    # 数值输出
    value: Optional[float] = None
    values: Optional[Dict[str, float]] = None

    # 信号输出
    signal: Optional[str] = None  # buy / sell / hold
    signals: Optional[List[Dict[str, Any]]] = None

    # 策略输出
    strategy: Optional[str] = None
    strategies: Optional[List[Dict[str, Any]]] = None

    # 回测输出
    backtest: Optional[Dict[str, Any]] = None

    # 风险输出
    risk: Optional[Dict[str, Any]] = None

    # 通用扩展
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        result = {}
        if self.direction is not None:
            result['direction'] = self.direction
        if self.confidence is not None:
            result['confidence'] = self.confidence
        if self.analysis is not None:
            result['analysis'] = self.analysis
        if self.reasoning is not None:
            result['reasoning'] = self.reasoning
        if self.value is not None:
            result['value'] = self.value
        if self.values is not None:
            result['values'] = self.values
        if self.signal is not None:
            result['signal'] = self.signal
        if self.signals is not None:
            result['signals'] = self.signals
        if self.strategy is not None:
            result['strategy'] = self.strategy
        if self.strategies is not None:
            result['strategies'] = self.strategies
        if self.backtest is not None:
            result['backtest'] = self.backtest
        if self.risk is not None:
            result['risk'] = self.risk
        if self.extra:
            result.update(self.extra)
        return result

    @classmethod
    def from_dict(cls, data: Dict) -> 'ModuleOutputs':
        return cls(
            direction=data.get('direction'),
            confidence=data.get('confidence'),
            analysis=data.get('analysis'),
            reasoning=data.get('reasoning'),
            value=data.get('value'),
            values=data.get('values'),
            signal=data.get('signal'),
            signals=data.get('signals'),
            strategy=data.get('strategy'),
            strategies=data.get('strategies'),
            backtest=data.get('backtest'),
            risk=data.get('risk'),
            extra={k: v for k, v in data.items() if k not in [
                'direction', 'confidence', 'analysis', 'reasoning',
                'value', 'values', 'signal', 'signals', 'strategy',
                'strategies', 'backtest', 'risk'
            ]},
        )


# ============================================================
# 执行上下文
# ============================================================

@dataclass
class ChainWeights:
    """链权重配置"""
    a_chain: float = 0.35  # AI 技能权重
    c_chain: float = 0.45  # 经典指标权重
    f_chain: float = 0.20  # 基本面权重

    def to_dict(self) -> Dict:
        return {
            'a_chain': self.a_chain,
            'c_chain': self.c_chain,
            'f_chain': self.f_chain,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ChainWeights':
        return cls(
            a_chain=data.get('a_chain', 0.35),
            c_chain=data.get('c_chain', 0.45),
            f_chain=data.get('f_chain', 0.20),
        )


@dataclass
class ExecutionContext:
    """
    执行上下文
    传递给模块的运行时上下文信息
    """
    session_id: str
    intent: str = 'unknown'
    symbol: Optional[str] = None
    user_role: str = 'FREE'  # FREE / PRO / ADMIN
    trading_mode: str = 'ai_skill'  # ai_skill / classic / hybrid
    budget_tokens: Optional[int] = None
    max_latency_ms: Optional[int] = None
    chain_weights: Optional[ChainWeights] = None
    prior_outputs: Dict[str, Any] = field(default_factory=dict)
    market_condition: str = 'unknown'  # trending / ranging / volatile / unknown
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    mkt: Dict[str, Any] = field(default_factory=dict)
    memory: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'sessionId': self.session_id,
            'intent': self.intent,
            'symbol': self.symbol,
            'userRole': self.user_role,
            'tradingMode': self.trading_mode,
            'budgetTokens': self.budget_tokens,
            'maxLatencyMs': self.max_latency_ms,
            'chainWeights': self.chain_weights.to_dict() if self.chain_weights else None,
            'priorOutputs': self.prior_outputs,
            'marketCondition': self.market_condition,
            'userPreferences': self.user_preferences,
            'mkt': self.mkt,
            'memory': self.memory,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ExecutionContext':
        return cls(
            session_id=data.get('sessionId', ''),
            intent=data.get('intent', 'unknown'),
            symbol=data.get('symbol'),
            user_role=data.get('userRole', 'FREE'),
            trading_mode=data.get('tradingMode', 'ai_skill'),
            budget_tokens=data.get('budgetTokens'),
            max_latency_ms=data.get('maxLatencyMs'),
            chain_weights=ChainWeights.from_dict(data['chainWeights']) if data.get('chainWeights') else None,
            prior_outputs=data.get('priorOutputs', {}),
            market_condition=data.get('marketCondition', 'unknown'),
            user_preferences=data.get('userPreferences', {}),
            mkt=data.get('mkt', {}),
            memory=data.get('memory', {}),
            extra={k: v for k, v in data.items() if k not in [
                'sessionId', 'intent', 'symbol', 'userRole', 'tradingMode',
                'budgetTokens', 'maxLatencyMs', 'chainWeights', 'priorOutputs',
                'marketCondition', 'userPreferences', 'mkt', 'memory'
            ]},
        )


# ============================================================
# 模块执行结果
# ============================================================

@dataclass
class ModuleResult:
    """
    模块执行结果
    所有模块执行后必须返回此格式
    与 TS 侧 SkillResult 对齐
    """
    success: bool
    capability_id: str
    outputs: ModuleOutputs
    confidence: float = 0.0
    confidence_dimensions: Optional[ConfidenceDimensions] = None
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'capabilityId': self.capability_id,
            'outputs': self.outputs.to_dict(),
            'confidence': self.confidence,
            'confidenceDimensions': (
                self.confidence_dimensions.to_dict()
                if self.confidence_dimensions else None
            ),
            'tokensUsed': self.tokens_used,
            'latencyMs': self.latency_ms,
            'error': self.error,
            'warnings': self.warnings,
            'suggestions': self.suggestions,
            'metadata': self.metadata,
            'fallbackUsed': self.fallback_used,
            'fallbackReason': self.fallback_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ModuleResult':
        return cls(
            success=data.get('success', False),
            capability_id=data.get('capabilityId', ''),
            outputs=ModuleOutputs.from_dict(data.get('outputs', {})),
            confidence=data.get('confidence', 0.0),
            confidence_dimensions=(
                ConfidenceDimensions.from_dict(data['confidenceDimensions'])
                if data.get('confidenceDimensions') else None
            ),
            tokens_used=data.get('tokensUsed'),
            latency_ms=data.get('latencyMs'),
            error=data.get('error'),
            warnings=data.get('warnings', []),
            suggestions=data.get('suggestions', []),
            metadata=data.get('metadata', {}),
            fallback_used=data.get('fallbackUsed', False),
            fallback_reason=data.get('fallbackReason'),
        )


# ============================================================
# 快捷构造函数
# ============================================================

def create_success_result(
    capability_id: str,
    outputs: Optional[Dict[str, Any]] = None,
    confidence: float = 75.0,
    confidence_dimensions: Optional[ConfidenceDimensions] = None,
) -> ModuleResult:
    """创建成功结果"""
    if confidence_dimensions is None:
        confidence_dimensions = ConfidenceDimensions(
            data_completeness=confidence,
            logical_consistency=confidence,
        )
    return ModuleResult(
        success=True,
        capability_id=capability_id,
        outputs=ModuleOutputs.from_dict(outputs or {}),
        confidence=confidence,
        confidence_dimensions=confidence_dimensions,
    )


def create_failure_result(
    capability_id: str,
    error: str,
) -> ModuleResult:
    """创建失败结果"""
    return ModuleResult(
        success=False,
        capability_id=capability_id,
        outputs=ModuleOutputs(),
        confidence=0.0,
        error=error,
    )


def create_fallback_result(
    capability_id: str,
    reason: str,
    outputs: Optional[Dict[str, Any]] = None,
    confidence: float = 30.0,
) -> ModuleResult:
    """创建降级结果"""
    return ModuleResult(
        success=False,
        capability_id=capability_id,
        outputs=ModuleOutputs.from_dict(outputs or {}),
        confidence=confidence,
        error=f'降级: {reason}',
        warnings=['此为降级结果，置信度较低，建议人工确认'],
        fallback_used=True,
        fallback_reason=reason,
    )


def create_default_context(session_id: str) -> ExecutionContext:
    """创建默认的执行上下文"""
    return ExecutionContext(
        session_id=session_id,
        intent='unknown',
        user_role='FREE',
        trading_mode='ai_skill',
        chain_weights=ChainWeights(),
    )


# ============================================================
# 模块查询参数
# ============================================================

@dataclass
class ModuleQueryParams:
    """模块查询参数"""
    chain: Optional[Union[str, List[str]]] = None
    category: Optional[Union[str, List[str]]] = None
    domain: Optional[Union[str, List[str]]] = None
    stage: Optional[Union[str, List[str]]] = None
    tag: Optional[Union[str, List[str]]] = None
    security_level: Optional[str] = None
    min_accuracy: Optional[float] = None
    max_tokens: Optional[int] = None
    intent: Optional[str] = None
    market_condition: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'chain': self.chain,
            'category': self.category,
            'domain': self.domain,
            'stage': self.stage,
            'tag': self.tag,
            'security_level': self.security_level,
            'min_accuracy': self.min_accuracy,
            'max_tokens': self.max_tokens,
            'intent': self.intent,
            'market_condition': self.market_condition,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ModuleQueryParams':
        return cls(
            chain=data.get('chain'),
            category=data.get('category'),
            domain=data.get('domain'),
            stage=data.get('stage'),
            tag=data.get('tag'),
            security_level=data.get('security_level'),
            min_accuracy=data.get('min_accuracy'),
            max_tokens=data.get('max_tokens'),
            intent=data.get('intent'),
            market_condition=data.get('market_condition'),
        )


__all__ = [
    # 枚举
    'SkillChain',
    'ThinkStage',
    'TradeDirection',
    'SecurityLevel',
    'ModuleStatus',
    'AdapterType',
    'ExecutionEngine',
    # 数据类
    'ConfidenceDimensions',
    'ModuleOutputs',
    'ChainWeights',
    'ExecutionContext',
    'ModuleResult',
    'ModuleQueryParams',
    # 工具函数
    'create_success_result',
    'create_failure_result',
    'create_fallback_result',
    'create_default_context',
]
