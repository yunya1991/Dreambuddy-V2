"""19-数据访问层 DAL 包：统一数据模型 + Repository 协议层 + 多后端实现（json_legacy/dual_write/sqlite）"""

__version__ = "1.0.0"

# 消费方唯一导入入口：对齐 ENGINEERING_INDEX §2.1 表
from dreambuddy_dal.di import (
    get_config_repo,
    get_kg_repo,
    get_market_macro_repo,
    get_position_repo,
    get_risk_repo,
    get_trade_repo,
)

# 也把协议导出（便于 isinstance 检查）
from dreambuddy_dal.protocols import (
    ConfigRepository,
    KnowledgeGraphRepository,
    MarketMacroRepository,
    PositionRepository,
    RiskRepository,
    TradeRepository,
)

# 数据模型 SSoT 出口（对齐经验 698940）
from dreambuddy_dal.unified_models import (
    CloseInfo,
    DailyStats,
    ExitReason,
    PositionState,
    PositionStyle,
    RiskCaseRecord,
    RiskLevel,
    RiskState,
    TradeDirection,
    TradeRecord,
    TradeStatus,
    TrialStatus,
)

__all__ = [
    "__version__",
    # 对外 6 个工厂函数
    "get_trade_repo", "get_position_repo", "get_market_macro_repo",
    "get_risk_repo", "get_config_repo", "get_kg_repo",
    # 6 个 Repository 协议
    "TradeRepository", "PositionRepository", "MarketMacroRepository",
    "RiskRepository", "ConfigRepository", "KnowledgeGraphRepository",
    # 统一数据模型 SSoT
    "TradeRecord", "PositionState", "DailyStats", "RiskState", "RiskCaseRecord", "CloseInfo",
    "TradeDirection", "TradeStatus", "ExitReason", "RiskLevel", "TrialStatus", "PositionStyle",
]
