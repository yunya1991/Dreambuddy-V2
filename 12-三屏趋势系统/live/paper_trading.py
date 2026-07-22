"""三屏趋势系统 — 纸交易引擎

纸交易（模拟交易）引擎，用于策略实盘验证。
支持多策略并行对比，记录交易日志，计算盈亏。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import os
import sys
from pathlib import Path

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[2] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.trade_event import TradeEvent
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class Order:
    """订单"""
    order_id: str
    strategy_name: str
    inst_id: str
    side: OrderSide
    pos_side: str  # long/short/net
    sz: float
    px: float  # 成交价格
    timestamp: datetime
    status: OrderStatus = OrderStatus.FILLED
    fee: float = 0.0  # 手续费
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "order_id": self.order_id,
            "strategy_name": self.strategy_name,
            "inst_id": self.inst_id,
            "side": self.side.value,
            "pos_side": self.pos_side,
            "sz": self.sz,
            "px": self.px,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "fee": self.fee,
            "notes": self.notes,
        }


@dataclass
class Position:
    """持仓"""
    inst_id: str
    side: str  # long/short
    sz: float = 0.0
    avg_px: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "inst_id": self.inst_id,
            "side": self.side,
            "sz": self.sz,
            "avg_px": self.avg_px,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
        }


@dataclass
class Portfolio:
    """策略组合"""
    strategy_name: str
    initial_capital: float
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    orders: List[Order] = field(default_factory=list)
    total_fee: float = 0.0

    @property
    def equity(self) -> float:
        """总权益"""
        pos_value = 0.0
        for p in self.positions.values():
            if p.side == "long":
                pos_value += p.sz * p.avg_px
            else:
                pos_value -= p.sz * p.avg_px
        return self.cash + pos_value

    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.equity - self.initial_capital

    @property
    def return_pct(self) -> float:
        """收益率"""
        return (self.equity / self.initial_capital - 1) * 100 if self.initial_capital > 0 else 0

    def to_dict(self) -> Dict:
        return {
            "strategy_name": self.strategy_name,
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "equity": self.equity,
            "total_pnl": self.total_pnl,
            "return_pct": self.return_pct,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "total_fee": self.total_fee,
            "order_count": len(self.orders),
        }


class PaperTradingEngine:
    """纸交易引擎

    支持多策略并行模拟交易，用于对比不同策略的实盘表现。

    特性：
    - 模拟市价单成交（滑点可选）
    - 手续费扣除
    - 持仓管理（支持多空双向）
    - 盈亏计算
    - 交易日志记录
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_rate: float = 0.001,  # 0.1%
        slippage_rate: float = 0.0005,  # 0.05%
        data_dir: Optional[str] = None,
    ):
        """
        参数:
            initial_capital: 初始资金
            commission_rate: 手续费率
            slippage_rate: 滑点率
            data_dir: 数据存储目录
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

        # 多策略组合
        self.portfolios: Dict[str, Portfolio] = {}

        # 数据目录
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def register_strategy(self, strategy_name: str) -> None:
        """注册策略"""
        if strategy_name not in self.portfolios:
            self.portfolios[strategy_name] = Portfolio(
                strategy_name=strategy_name,
                initial_capital=self.initial_capital,
                cash=self.initial_capital,
            )

    def execute_signal(
        self,
        strategy_name: str,
        inst_id: str,
        signal: float,  # -1~1
        current_price: float,
        timestamp: Optional[datetime] = None,
        notes: str = "",
    ) -> Optional[Order]:
        """执行信号

        参数:
            strategy_name: 策略名
            inst_id: 交易对
            signal: 信号强度 (-1~1)，负数做空，正数做多，0 平仓
            current_price: 当前价格
            timestamp: 时间戳
            notes: 备注

        返回:
            订单对象（如果产生交易）
        """
        if strategy_name not in self.portfolios:
            self.register_strategy(strategy_name)

        portfolio = self.portfolios[strategy_name]
        ts = timestamp or datetime.now()

        # 计算目标仓位
        target_sz = abs(signal) * (portfolio.cash / current_price) * 0.95  # 留5%现金
        target_side = "long" if signal > 0 else "short" if signal < 0 else None

        # 滑点调整：做多时买价略高，做空时卖价略低
        slippage_adjust = self.slippage_rate if signal > 0 else -self.slippage_rate
        exec_px = current_price * (1 + slippage_adjust)

        order = None
        pos_key = f"{inst_id}_{target_side}" if target_side else None

        # 获取当前持仓
        current_pos = portfolio.positions.get(pos_key) if pos_key else None

        if signal == 0:
            # 平仓信号 - 平掉所有持仓（无论多空）
            for side in ["long", "short"]:
                pos_key = f"{inst_id}_{side}"
                if pos_key in portfolio.positions:
                    pos = portfolio.positions[pos_key]
                    if pos.sz > 0:
                        order = self._close_position(
                            portfolio, pos, exec_px, ts, notes
                        )
        elif signal > 0:
            # 做多
            if current_pos:
                # 已有多头仓位，调整
                if current_pos.sz < target_sz:
                    # 加仓
                    order = self._open_position(
                        portfolio, inst_id, "long", target_sz - current_pos.sz,
                        exec_px, ts, notes
                    )
                elif current_pos.sz > target_sz:
                    # 减仓
                    order = self._close_position(
                        portfolio, current_pos, exec_px, ts, notes,
                        close_sz=current_pos.sz - target_sz
                    )
            else:
                # 开多头
                order = self._open_position(
                    portfolio, inst_id, "long", target_sz, exec_px, ts, notes
                )

            # 如果有空头仓位，先平空
            short_key = f"{inst_id}_short"
            if short_key in portfolio.positions:
                short_pos = portfolio.positions[short_key]
                if short_pos.sz > 0:
                    self._close_position(portfolio, short_pos, exec_px, ts, "平空反多")

        elif signal < 0:
            # 做空
            if current_pos:
                # 已有空头仓位，调整
                if current_pos.sz < target_sz:
                    # 加仓
                    order = self._open_position(
                        portfolio, inst_id, "short", target_sz - current_pos.sz,
                        exec_px, ts, notes
                    )
                elif current_pos.sz > target_sz:
                    # 减仓
                    order = self._close_position(
                        portfolio, current_pos, exec_px, ts, notes,
                        close_sz=current_pos.sz - target_sz
                    )
            else:
                # 开空头
                order = self._open_position(
                    portfolio, inst_id, "short", target_sz, exec_px, ts, notes
                )

            # 如果有多头仓位，先平多
            long_key = f"{inst_id}_long"
            if long_key in portfolio.positions:
                long_pos = portfolio.positions[long_key]
                if long_pos.sz > 0:
                    self._close_position(portfolio, long_pos, exec_px, ts, "平多反空")

        return order

    def _open_position(
        self,
        portfolio: Portfolio,
        inst_id: str,
        side: str,
        sz: float,
        px: float,
        ts: datetime,
        notes: str,
    ) -> Order:
        """开仓"""
        # 计算手续费
        fee = sz * px * self.commission_rate

        # 检查资金（只对多头检查）
        if side == "long":
            required = sz * px + fee
            if portfolio.cash < required:
                sz = (portfolio.cash - fee) / px * 0.99

        if sz <= 0:
            return None

        # 资金处理：多头扣除，空头收到
        if side == "long":
            portfolio.cash -= sz * px + fee
        else:
            portfolio.cash += sz * px - fee

        portfolio.total_fee += fee

        # 更新持仓
        pos_key = f"{inst_id}_{side}"
        if pos_key not in portfolio.positions:
            portfolio.positions[pos_key] = Position(
                inst_id=inst_id, side=side, sz=sz, avg_px=px
            )
        else:
            pos = portfolio.positions[pos_key]
            total_sz = pos.sz + sz
            pos.avg_px = (pos.avg_px * pos.sz + px * sz) / total_sz if total_sz > 0 else px
            pos.sz = total_sz

        # 记录订单
        order = Order(
            order_id=f"{portfolio.strategy_name}_{ts.strftime('%Y%m%d%H%M%S')}_{len(portfolio.orders)}",
            strategy_name=portfolio.strategy_name,
            inst_id=inst_id,
            side=OrderSide.BUY if side == "long" else OrderSide.SELL,
            pos_side=side,
            sz=sz,
            px=px,
            timestamp=ts,
            fee=fee,
            notes=notes,
        )
        portfolio.orders.append(order)

        return order

    def _close_position(
        self,
        portfolio: Portfolio,
        position: Position,
        px: float,
        ts: datetime,
        notes: str,
        close_sz: Optional[float] = None,
    ) -> Order:
        """平仓"""
        sz = close_sz if close_sz else position.sz
        if sz <= 0 or position.sz <= 0:
            return None

        sz = min(sz, position.sz)

        # 计算手续费和盈亏
        fee = sz * px * self.commission_rate
        pnl = (px - position.avg_px) * sz * (1 if position.side == "long" else -1)

        # 资金处理：平多头收到资金，平空头付出资金
        if position.side == "long":
            portfolio.cash += sz * px - fee
        else:
            portfolio.cash -= sz * px + fee

        portfolio.total_fee += fee

        # 更新持仓
        position.sz -= sz
        position.realized_pnl += pnl

        if position.sz <= 0:
            # 完全平仓
            pos_key = f"{position.inst_id}_{position.side}"
            if pos_key in portfolio.positions:
                del portfolio.positions[pos_key]

        # 记录订单
        order = Order(
            order_id=f"{portfolio.strategy_name}_{ts.strftime('%Y%m%d%H%M%S')}_{len(portfolio.orders)}",
            strategy_name=portfolio.strategy_name,
            inst_id=position.inst_id,
            side=OrderSide.SELL if position.side == "long" else OrderSide.BUY,
            pos_side=position.side,
            sz=sz,
            px=px,
            timestamp=ts,
            fee=fee,
            notes=f"平仓(pnl={pnl:.2f}) {notes}",
        )
        portfolio.orders.append(order)

        # 注册到 L4
        if _L4_ENABLED and position.sz <= 0:
            try:
                trade_id = f"three_screen_paper_{int(datetime.now(timezone.utc).timestamp())}_{position.inst_id.replace('-', '_')}"
                event = TradeEvent(
                    event_id=TradeEvent.generate_event_id(),
                    system_source="three_screen",
                    trade_id=trade_id,
                    ts_entry=ts.isoformat(),
                    ts_exit=ts.isoformat(),
                    symbol=position.inst_id,
                    direction=position.side,
                    entry_price=position.avg_px,
                    exit_price=px,
                    position_size=sz,
                    pnl=pnl,
                    pnl_pct=(pnl / (position.avg_px * sz) * 100) if position.avg_px > 0 and sz > 0 else 0,
                    exit_reason=f"paper_close_{notes}",
                    decision_context={
                        "strategy_name": portfolio.strategy_name,
                        "strategy_type": "three_screen_trend",
                        "paper_trading": True,
                    },
                )
                registry = UnifiedCaseRegistry()
                case_id, success = registry.register_trade_event(event)
                if success:
                    print(f"[L4] 纸交易案例已注册: {case_id}")
            except Exception as e:
                print(f"[L4] 纸交易注册异常: {e}")

        return order

    def update_prices(self, prices: Dict[str, float]) -> None:
        """更新持仓价格，计算未实现盈亏"""
        for portfolio in self.portfolios.values():
            for pos_key, pos in portfolio.positions.items():
                inst_id = pos.inst_id
                if inst_id in prices:
                    current_px = prices[inst_id]
                    pos.unrealized_pnl = (current_px - pos.avg_px) * pos.sz * (
                        1 if pos.side == "long" else -1
                    )

    def get_summary(self) -> Dict[str, Any]:
        """获取汇总报告"""
        return {
            "timestamp": datetime.now().isoformat(),
            "initial_capital": self.initial_capital,
            "strategies": {
                name: portfolio.to_dict()
                for name, portfolio in self.portfolios.items()
            },
        }

    def save_trading_log(self, filename: Optional[str] = None) -> str:
        """保存交易日志"""
        fname = filename or f"trading_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.data_dir / fname

        log_data = self.get_summary()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        return str(filepath)

    def load_trading_log(self, filepath: str) -> None:
        """加载交易日志"""
        with open(filepath, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        self.initial_capital = log_data.get("initial_capital", 10000)

        for name, data in log_data.get("strategies", {}).items():
            portfolio = Portfolio(
                strategy_name=name,
                initial_capital=data.get("initial_capital", self.initial_capital),
                cash=data.get("cash", self.initial_capital),
            )
            portfolio.total_fee = data.get("total_fee", 0)

            # 恢复持仓
            for pos_key, pos_data in data.get("positions", {}).items():
                portfolio.positions[pos_key] = Position(
                    inst_id=pos_data["inst_id"],
                    side=pos_data["side"],
                    sz=pos_data["sz"],
                    avg_px=pos_data["avg_px"],
                    unrealized_pnl=pos_data.get("unrealized_pnl", 0),
                    realized_pnl=pos_data.get("realized_pnl", 0),
                )

            self.portfolios[name] = portfolio