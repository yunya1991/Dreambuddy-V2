"""
13-通用风控模块
==============
通用风控引擎 — 为所有交易模块提供统一的风控能力。

三层架构：
    L1 - 事前门禁层 (PreTradeGate)
    L2 - 仓位管理层 (PositionSizer)
    L3 - 事后离场层 (ExitEngine)

增强能力：
    - L1 价值-风险评估 (L1ValueRiskAssessor)
    - ML 风控模型集成 (MLModelRegistry)
    - 飞书告警通知 (RiskAlertNotifier)

使用方式：
    from risk_engine import RiskEngine
    engine = RiskEngine(config)
    result = engine.pre_trade_check(signal, context)
"""

from .core.engine import RiskEngine
from .core.context import RiskContext, PositionState, MarketSnapshot, Signal
from .core.registry import RuleRegistry
from .core.l1_assessor import L1ValueRiskAssessor, ExitFeatureSet, L1Mode, L2HysteresisState
from .core.ml_model import MLRiskModel, CommitteeModel, MLModelRegistry, ModelPrediction
from .core.alert import RiskAlertNotifier, AlertEvent, AlertLevel, AlertCategory

__version__ = "1.1.0"
__all__ = [
    "RiskEngine",
    "RiskContext",
    "PositionState",
    "MarketSnapshot",
    "Signal",
    "RuleRegistry",
    "L1ValueRiskAssessor",
    "ExitFeatureSet",
    "L1Mode",
    "L2HysteresisState",
    "MLRiskModel",
    "CommitteeModel",
    "MLModelRegistry",
    "ModelPrediction",
    "RiskAlertNotifier",
    "AlertEvent",
    "AlertLevel",
    "AlertCategory",
]
