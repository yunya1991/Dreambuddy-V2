"""
通用风控引擎 - 核心模块

三层脑理论映射见上层 13-通用风控模块/__init__.py (#3-a)：
    爬行脑  → PreTradeGate 硬熔断 + ExitEngine P0 安全硬退出
    边缘系统 → A8 偏差检测（11-易经推理系统，通过 a8_a0_feedback 反馈 A0）
    新皮质  → PreTradeGate 评分门禁 + PositionSizer + ExitEngine P1/P2/P3
"""

from .alert import AlertCategory, AlertEvent, AlertLevel, RiskAlertNotifier
from .context import MarketSnapshot, PositionState, RiskContext, Signal
from .engine import RiskEngine
from .exit_engine import ExitEngine
from .l1_assessor import ExitFeatureSet, L1Mode, L1ValueRiskAssessor, L2HysteresisState
from .ml_model import CommitteeModel, MLModelRegistry, MLRiskModel, ModelPrediction
from .position_sizer import PositionSizer
from .pre_trade_gate import PreTradeGate
from .registry import RuleRegistry

__all__ = [
    "RiskEngine",
    "RiskContext",
    "PositionState",
    "MarketSnapshot",
    "Signal",
    "RuleRegistry",
    "PreTradeGate",
    "PositionSizer",
    "ExitEngine",
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
