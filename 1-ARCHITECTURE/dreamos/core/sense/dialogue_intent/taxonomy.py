"""
对话意图分类体系（6×30：6 大类 × 30 二级意图）

属于 DreamOS 操作系统内核 S 层（core/sense/dialogue_intent/）。
领域无关，可复用于其他能力域。

一级意图（6 大类）:
    query      查询类（low 风险）
    analysis   分析类（medium 风险）
    trade      交易类（high 风险）
    strategy   策略类（medium 风险）
    risk       风控类（medium 风险）
    dialog     对话类（low 风险）
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List


# ============================================================
# 一级意图
# ============================================================

class PrimaryIntent(str, Enum):
    """一级意图（6 大类）"""
    QUERY = "query"
    ANALYSIS = "analysis"
    TRADE = "trade"
    STRATEGY = "strategy"
    RISK = "risk"
    DIALOG = "dialog"


# ============================================================
# 二级意图 — query 查询类
# ============================================================

class QueryIntent(str, Enum):
    MARKET_QUERY = "market_query"           # 行情查询
    HOLDING_QUERY = "holding_query"         # 持仓查询
    ORDER_QUERY = "order_query"             # 订单查询
    ACCOUNT_QUERY = "account_query"         # 账户查询
    MARKET_OVERVIEW = "market_overview"     # 市场概览


# ============================================================
# 二级意图 — analysis 分析类
# ============================================================

class AnalysisIntent(str, Enum):
    TECHNICAL_ANALYSIS = "technical_analysis"     # 技术分析
    HOLDING_ANALYSIS = "holding_analysis"         # 持仓分析
    DEEP_ANALYSIS = "deep_analysis"               # 深度分析
    THREE_SCREEN_ANALYSIS = "three_screen_analysis"  # 三屏分析
    SECTOR_ANALYSIS = "sector_analysis"           # 板块分析


# ============================================================
# 二级意图 — trade 交易类（high 风险）
# ============================================================

class TradeIntent(str, Enum):
    BUY = "buy"                       # 买入
    ADD_POSITION = "add_position"     # 加仓
    SELL = "sell"                     # 卖出
    CLOSE_POSITION = "close_position" # 平仓
    CONDITIONAL_ORDER = "conditional_order"  # 条件单
    ORDER_MANAGE = "order_manage"     # 订单管理


# ============================================================
# 二级意图 — strategy 策略类
# ============================================================

class StrategyIntent(str, Enum):
    STOCK_RECOMMENDATION = "stock_recommendation"  # 股票推荐
    FACTOR_SCREEN = "factor_screen"                # 因子筛选
    STRATEGY_DESIGN = "strategy_design"            # 策略设计
    STRATEGY_OPTIMIZATION = "strategy_optimization"  # 策略优化


# ============================================================
# 二级意图 — risk 风控类
# ============================================================

class RiskIntent(str, Enum):
    RISK_ASSESSMENT = "risk_assessment"    # 风险评估
    RISK_ADVICE = "risk_advice"            # 风控建议
    ALERT_SETUP = "alert_setup"            # 预警设置
    PORTFOLIO_RISK = "portfolio_risk"      # 组合风险


# ============================================================
# 二级意图 — dialog 对话类
# ============================================================

class DialogIntent(str, Enum):
    CONFIRM = "confirm"        # 确认
    CANCEL = "cancel"          # 取消
    MODIFY = "modify"          # 修改
    REPEAT = "repeat"          # 重复
    CLARIFY = "clarify"        # 澄清
    CHITCHAT = "chitchat"      # 闲聊


# ============================================================
# 意图分类体系映射
# ============================================================

# 一级意图 → 二级意图映射
INTENT_TAXONOMY: Dict[str, List[str]] = {
    "query": [e.value for e in QueryIntent],
    "analysis": [e.value for e in AnalysisIntent],
    "trade": [e.value for e in TradeIntent],
    "strategy": [e.value for e in StrategyIntent],
    "risk": [e.value for e in RiskIntent],
    "dialog": [e.value for e in DialogIntent],
}

# 二级意图 → 一级意图反查
_SECONDARY_TO_PRIMARY: Dict[str, str] = {
    secondary: primary
    for primary, secondaries in INTENT_TAXONOMY.items()
    for secondary in secondaries
}


def get_primary_intent(secondary: str) -> str:
    """根据二级意图反查一级意图"""
    return _SECONDARY_TO_PRIMARY.get(secondary, "query")


def is_valid_secondary(secondary: str) -> bool:
    """检查二级意图是否合法"""
    return secondary in _SECONDARY_TO_PRIMARY


def get_all_secondaries() -> List[str]:
    """获取所有合法二级意图"""
    return list(_SECONDARY_TO_PRIMARY.keys())


# ============================================================
# 风险等级映射
# ============================================================

# 一级意图 → 风险等级
PRIMARY_RISK_LEVEL: Dict[str, str] = {
    "query": "low",
    "analysis": "medium",
    "trade": "high",
    "strategy": "medium",
    "risk": "medium",
    "dialog": "low",
}


def get_risk_level(primary: str) -> str:
    """根据一级意图获取风险等级"""
    return PRIMARY_RISK_LEVEL.get(primary, "low")


# ============================================================
# 能力路由映射
# ============================================================

# 一级意图 → 默认能力路由
PRIMARY_CAPABILITY_ROUTE: Dict[str, str] = {
    "query": "database",
    "analysis": "trading_nodes",
    "trade": "trading_nodes",
    "strategy": "trading_nodes",
    "risk": "trading_nodes",
    "dialog": "direct_response",
}


def get_default_capability_route(primary: str) -> str:
    """根据一级意图获取默认能力路由"""
    return PRIMARY_CAPABILITY_ROUTE.get(primary, "harness")
