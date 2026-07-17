"""三屏趋势系统 — 实盘验证模块

Phase 4.4: 实盘验证（纸交易）

提供：
- 纸交易引擎：模拟交易、持仓管理、盈亏计算
- 策略运行器：定时运行策略、执行模拟交易
- 验证报告生成：对比不同策略的实盘表现
"""

from .paper_trading import (
    PaperTradingEngine,
    Order,
    Position,
    Portfolio,
    OrderSide,
    OrderStatus,
)

from .strategy_runner import (
    StrategyRunner,
    create_rule_strategy,
    create_ai_v1_strategy,
    create_ai_v2_strategy,
)

__all__ = [
    # 纸交易引擎
    "PaperTradingEngine",
    "Order",
    "Position",
    "Portfolio",
    "OrderSide",
    "OrderStatus",
    # 策略运行器
    "StrategyRunner",
    "create_rule_strategy",
    "create_ai_v1_strategy",
    "create_ai_v2_strategy",
]