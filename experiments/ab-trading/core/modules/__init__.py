"""
Dreambuddy OS 模块适配器层
统一封装外部系统（经典指标/基本面分析）和 SKILL 的调用接口

设计原则:
- 调用的不重复建设：已有能力通过适配器调用，不重新实现
- 统一接口协议：所有模块遵循相同的调用规范
- 降级容错：外部服务不可用时自动降级到本地规则
- 可扩展：新模块只需添加适配器，无需修改调度层
"""

from .classic_indicators import ClassicIndicatorsClient
from .fundamental_api import FundamentalAPIClient
from .skill_loader import SkillLoader, execute_skill
from .module_registry import (
    ModuleInfo,
    ModuleRegistry,
    get_module_registry,
    reload_registry,
)
from .unified_types import (
    ModuleResult,
    ExecutionContext,
    ModuleOutputs,
    ConfidenceDimensions,
    ChainWeights,
    ModuleQueryParams,
    create_success_result,
    create_failure_result,
    create_fallback_result,
    create_default_context,
    SkillChain,
    ThinkStage,
    TradeDirection,
    SecurityLevel,
    ModuleStatus,
    AdapterType,
    ExecutionEngine,
)
from .adapter_framework import (
    BaseModuleAdapter,
    SkillAdapter,
    APIAdapter,
    LocalAdapter,
    NodeAdapter,
    ModuleExecutor,
    get_module_executor,
)

__all__ = [
    "ClassicIndicatorsClient",
    "FundamentalAPIClient",
    "SkillLoader",
    "execute_skill",
    "ModuleInfo",
    "ModuleRegistry",
    "get_module_registry",
    "reload_registry",
    # 统一类型
    "ModuleResult",
    "ExecutionContext",
    "ModuleOutputs",
    "ConfidenceDimensions",
    "ChainWeights",
    "ModuleQueryParams",
    "create_success_result",
    "create_failure_result",
    "create_fallback_result",
    "create_default_context",
    "SkillChain",
    "ThinkStage",
    "TradeDirection",
    "SecurityLevel",
    "ModuleStatus",
    "AdapterType",
    "ExecutionEngine",
    # 适配器框架
    "BaseModuleAdapter",
    "SkillAdapter",
    "APIAdapter",
    "LocalAdapter",
    "NodeAdapter",
    "ModuleExecutor",
    "get_module_executor",
]
