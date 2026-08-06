"""
13-通用风控模块
==============
通用风控引擎 — 为所有交易模块提供统一的风控能力。

三层架构：
    L1 - 事前门禁层 (PreTradeGate)
    L2 - 仓位管理层 (PositionSizer)
    L3 - 事后离场层 (ExitEngine)

三层脑理论映射 (MacLean 三位一体脑 / #3-a)：
    本模块的 L1/L2/L3 按"事前-仓位-事后"流程划分，与 MacLean 三层脑
    （爬行脑/边缘系统/新皮质）并非简单一一对应，而是按"认知层级"交叉映射：

    ┌──────────┬─────────────────────────────────────┬──────────┬─────────┐
    │ 脑层     │ 对应风控组件                         │ 响应速度 │ 可否否决 │
    ├──────────┼─────────────────────────────────────┼──────────┼─────────┤
    │ 爬行脑   │ L1 硬熔断（10%日回撤、杠杆>2x、       │ <1ms 同步│ 不可否决 │
    │ (脑干)   │   Fail-Closed）                      │          │         │
    │          │ L3 P0 安全硬退出（永远一票否决）      │          │         │
    ├──────────┼─────────────────────────────────────┼──────────┼─────────┤
    │ 边缘系统 │ A8 损失厌恶/认知偏差检测层            │ 异步     │ 可上诉   │
    │ (杏仁核) │ （在 11-易经推理系统/A8，通过          │ daily    │ 需记录   │
    │          │  a8_a0_feedback.py 反馈到 A0 矛盾池） │          │         │
    ├──────────┼─────────────────────────────────────┼──────────┼─────────┤
    │ 新皮质   │ L1 评分门禁（战略/评分/执行风险）      │ 分钟级   │ 可被门禁 │
    │ (前额叶) │ L2 仓位管理（风险预算驱动仓位计算）    │          │ 拦截     │
    │          │ L3 P1 价值-风险评估 / P2 三重屏障 /   │          │         │
    │          │   P3 行为约束                         │          │         │
    └──────────┴─────────────────────────────────────┴──────────┴─────────┘

    设计意图：爬行脑负责"不可否决的生存本能"（硬熔断），新皮质负责"可被
    门禁拦截的理性分析"（仓位/评估），边缘系统（A8 偏差检测）介于两者之间
    ——异步检测、可上诉但需记录，偏差通过 a8_a0_feedback 链路写回 A0 矛盾池
    触发重分析（#3-b 已实现）。

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
