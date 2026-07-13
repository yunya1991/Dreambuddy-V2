"""
风控上下文与状态管理
====================
定义所有风控相关的数据结构和上下文对象。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from datetime import datetime, timezone


class Direction(str, Enum):
    """交易方向"""
    LONG = "long"
    SHORT = "short"


class ExitAction(str, Enum):
    """离场动作"""
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 提高止盈价（强反弹时让利润奔跑）


class ExitPriority(str, Enum):
    """离场优先级"""
    P0_L0_HARD = "p0_l0"
    P1_VALUE_RISK = "p1"
    P2_TRIPLE_BARRIER = "p2"
    P3_BEHAVIORAL = "p3"


class RiskLevel(str, Enum):
    """风险等级"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NORMAL = "normal"


class ReasonCode(str, Enum):
    """理由码体系 - 与知识库风控体系.md对齐"""
    PASS = "PASS"

    HARD_FAIL_MISSING_CORE_DATA = "HARD_FAIL_MISSING_CORE_DATA"
    HARD_FAIL_LEVERAGE_EXCEEDS_CAP = "HARD_FAIL_LEVERAGE_EXCEEDS_CAP"
    HARD_FAIL_STRATEGY_EXCLUDED = "HARD_FAIL_STRATEGY_EXCLUDED"
    HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER = "HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER"
    HARD_FAIL_DIRECTION_MISMATCH = "HARD_FAIL_DIRECTION_MISMATCH"
    HARD_FAIL_NO_STRATEGY = "HARD_FAIL_NO_STRATEGY"
    HARD_FAIL_SLIPPAGE = "HARD_FAIL_SLIPPAGE"
    HARD_FAIL_NEGATIVE_EDGE = "HARD_FAIL_NEGATIVE_EDGE"
    HARD_FAIL_BLACKOUT = "HARD_FAIL_BLACKOUT"
    HARD_FAIL_CONCURRENT_LIMIT = "HARD_FAIL_CONCURRENT_LIMIT"
    HARD_FAIL_CONSECUTIVE_LOSSES = "HARD_FAIL_CONSECUTIVE_LOSSES"

    FAIL_LOW_DIM = "FAIL_LOW_DIM"
    FAIL_LOW_TOTAL = "FAIL_LOW_TOTAL"

    DEGRADE_DREAM_MODE = "DEGRADE_DREAM_MODE"
    DEGRADE_STRATEGY_REDUCED_RISK = "DEGRADE_STRATEGY_REDUCED_RISK"
    DEGRADE_DRAWDOWN_WARNING = "DEGRADE_DRAWDOWN_WARNING"

    SOFT_WARN_STRATEGY_DIRECTS_WAIT = "SOFT_WARN_STRATEGY_DIRECTS_WAIT"
    SOFT_WARN_LOW_CONFIDENCE = "SOFT_WARN_LOW_CONFIDENCE"


@dataclass
class Signal:
    """交易信号"""
    coin: str
    direction: Direction
    confidence: float = 0.5
    strategy: str = ""
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionState:
    """持仓状态"""
    coin: str
    side: Direction
    entry_price: float = 0.0
    current_price: float = 0.0
    position_size: float = 0.0
    position_age_sec: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    entry_ts: int = 0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0
    addon_count: int = 0
    max_addons: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def pnl_eff(self) -> float:
        """含杠杆的有效收益率"""
        return self.unrealized_pnl_pct * self.leverage

    @property
    def is_long(self) -> bool:
        return self.side == Direction.LONG


@dataclass
class MarketSnapshot:
    """市场快照"""
    coin: str
    price: float = 0.0
    rsi: float = 50.0
    macd_hist: float = 0.0
    atr_pct: float = 0.02
    volume_24h: float = 0.0
    trend: str = "neutral"
    volatility: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    passed: bool
    reason_code: ReasonCode = ReasonCode.PASS
    risk_level: RiskLevel = RiskLevel.NORMAL
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    position_modifier: float = 1.0

    @classmethod
    def pass_result(cls, message: str = "") -> "RiskCheckResult":
        return cls(passed=True, message=message or "风控通过")

    @classmethod
    def fail_result(cls, reason_code: ReasonCode, message: str = "") -> "RiskCheckResult":
        return cls(
            passed=False,
            reason_code=reason_code,
            risk_level=RiskLevel.HIGH,
            message=message or reason_code.value
        )

    @classmethod
    def degrade_result(cls, reason_code: ReasonCode, modifier: float, message: str = "") -> "RiskCheckResult":
        return cls(
            passed=True,
            reason_code=reason_code,
            risk_level=RiskLevel.MEDIUM,
            message=message or reason_code.value,
            position_modifier=modifier
        )


@dataclass
class PositionSizeResult:
    """仓位计算结果"""
    base_size_usdt: float = 0.0
    base_size_coins: float = 0.0
    risk_per_trade_usdt: float = 0.0
    max_addons: int = 0
    addon_sizes: List[float] = field(default_factory=list)
    position_tier: str = "trial"
    leverage: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExitResult:
    """离场决策结果"""
    action: ExitAction = ExitAction.HOLD
    priority: ExitPriority = ExitPriority.P3_BEHAVIORAL
    reason: str = ""
    reduce_frac: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class RiskContext:
    """风控上下文 - 全局风控状态的单一真相源

    负责维护：
    - 账户状态（权益、可用余额、保证金）
    - 日盈亏/回撤记录
    - 连续亏损计数
    - 当前持仓列表
    - 交易历史
    """

    def __init__(
        self,
        total_equity: float = 0.0,
        available_balance: float = 0.0,
        used_margin: float = 0.0,
        daily_pnl: float = 0.0,
        daily_start_equity: Optional[float] = None,
        max_daily_equity: Optional[float] = None,
        consecutive_losses: int = 0,
        total_trades: int = 0,
        total_wins: int = 0,
        positions: Optional[Dict[str, PositionState]] = None,
        trade_history: Optional[List[Dict[str, Any]]] = None,
    ):
        self.total_equity = total_equity
        self.available_balance = available_balance or total_equity
        self.used_margin = used_margin

        self.daily_pnl = daily_pnl
        self.daily_start_equity = daily_start_equity or total_equity
        self.max_daily_equity = max_daily_equity or total_equity

        self.consecutive_losses = consecutive_losses
        self.total_trades = total_trades
        self.total_wins = total_wins

        self.positions = positions or {}
        self.trade_history = trade_history or []

        self.last_update_ts = int(datetime.now(timezone.utc).timestamp())

    @property
    def daily_drawdown_pct(self) -> float:
        """当日回撤百分比（相对于日最高权益）"""
        if self.max_daily_equity <= 0:
            return 0.0
        return (self.max_daily_equity - self.total_equity) / self.max_daily_equity

    @property
    def daily_return_pct(self) -> float:
        """当日收益率（相对于日初权益）"""
        if self.daily_start_equity <= 0:
            return 0.0
        return self.daily_pnl / self.daily_start_equity

    @property
    def win_rate(self) -> float:
        """胜率"""
        if self.total_trades == 0:
            return 0.0
        return self.total_wins / self.total_trades

    @property
    def active_positions_count(self) -> int:
        """活跃持仓数量"""
        return len(self.positions)

    def update_equity(self, total_equity: float, available_balance: Optional[float] = None):
        """更新账户权益"""
        self.total_equity = total_equity
        if available_balance is not None:
            self.available_balance = available_balance

        if total_equity > self.max_daily_equity:
            self.max_daily_equity = total_equity

        self.daily_pnl = total_equity - self.daily_start_equity
        self.last_update_ts = int(datetime.now(timezone.utc).timestamp())

    def add_position(self, position: PositionState):
        """添加持仓"""
        self.positions[position.coin] = position

    def remove_position(self, coin: str):
        """移除持仓"""
        if coin in self.positions:
            del self.positions[coin]

    def record_trade(self, trade: Dict[str, Any]):
        """记录交易"""
        self.trade_history.append(trade)
        self.total_trades += 1

        if trade.get("pnl", 0) > 0:
            self.total_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

    def reset_daily(self, new_start_equity: Optional[float] = None):
        """重置日度数据"""
        if new_start_equity is not None:
            self.total_equity = new_start_equity
        self.daily_start_equity = self.total_equity
        self.max_daily_equity = self.total_equity
        self.daily_pnl = 0.0
        self.consecutive_losses = 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化"""
        return {
            "total_equity": self.total_equity,
            "available_balance": self.available_balance,
            "used_margin": self.used_margin,
            "daily_pnl": self.daily_pnl,
            "daily_start_equity": self.daily_start_equity,
            "max_daily_equity": self.max_daily_equity,
            "consecutive_losses": self.consecutive_losses,
            "total_trades": self.total_trades,
            "total_wins": self.total_wins,
            "positions": {k: v.__dict__ for k, v in self.positions.items()},
            "last_update_ts": self.last_update_ts,
        }
