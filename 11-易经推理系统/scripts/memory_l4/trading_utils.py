#!/usr/bin/env python3
"""
交易工具集：风险控制、绩效统计、Case 生成、动态仓位
"""
import json
import os
import time
import uuid
import fcntl
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

from scripts.memory_l4.paths import memory_l4_stats_dir, memory_l4_cases_dir, memory_l4_dir
from scripts.memory_l4.trade_event import TradeEvent
from scripts.memory_l4.case_registry import UnifiedCaseRegistry


# ── 数据结构 ──────────────────────────────────────────

@dataclass
class TradeRecord:
    """单笔交易记录"""
    trade_id: str = ""
    coin: str = ""
    inst_id: str = ""
    direction: str = ""       # long / short
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""     # signal_reverse / stop_loss / take_profit / manual
    confidence: float = 0.0
    hexagram: str = ""
    liangyi_state: Dict = field(default_factory=dict)
    scale_params: Dict = field(default_factory=dict)
    market_snapshot: Dict = field(default_factory=dict)
    contradiction_list: List[Dict] = field(default_factory=list)
    strategy_source: str = ""  # bcrm / external (马丁等其他策略)
    enhance_info: Dict = field(default_factory=dict)  # 震荡市增强器信息（regime, bollinger, sl_mult等）
    reduce_count: int = 0  # E项优化：累计减仓次数，用于max_reduce_count限制
    # ATR 基线 SL/TP 收益率（开仓时记录，供易经离场系统调制使用）
    base_sl_roi: float = 0.0   # 开仓时 ATR 基线止损收益率（如 0.12 = 12%）
    base_tp_roi: float = 0.0   # 开仓时 ATR 基线止盈收益率（如 0.60 = 60%）


@dataclass
class DailyStats:
    """每日绩效统计"""
    date: str = ""
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    current_consecutive_wins: int = 0
    current_consecutive_losses: int = 0
    peak_equity: float = 0.0
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    trades: List[Dict] = field(default_factory=list)


@dataclass
class RiskState:
    """风控状态"""
    daily_pnl: float = 0.0
    daily_loss_limit: float = -100.0       # 日最大亏损（USDT，兜底固定值）
    loss_limit_pct: float = 0.20           # 日最大亏损比例（相对当前权益，0.20=20%）
    max_consecutive_losses: int = 999      # 最大连续亏损次数（已禁用，设极大值不再触发）
    current_consecutive_losses: int = 0
    trading_halted: bool = False
    halt_reason: str = ""
    position_size_pct: float = 0.10        # 默认单笔仓位 10%
    min_position_size_pct: float = 0.02
    max_position_size_pct: float = 0.20
    min_position_usdt: float = 20.0       # 最低名义仓位价值（USDT，传给OKX的下单金额）


# ── 绩效统计器 ────────────────────────────────────────

class PerformanceTracker:
    """交易绩效跟踪器"""

    def __init__(self, initial_equity: float = 10000.0):
        self.stats_dir = memory_l4_stats_dir()
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.stats_dir / "all_trades.jsonl"
        self.daily_stats_file = self.stats_dir / "daily_stats.json"

        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.peak_equity = initial_equity
        self.max_drawdown = 0.0

        self.trades: List[TradeRecord] = []
        self.daily_stats: Dict[str, DailyStats] = {}

        self._load_state()

    def _load_state(self):
        """加载历史统计数据"""
        if self.trades_file.exists():
            try:
                with open(self.trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            rec = TradeRecord(**{k: v for k, v in data.items()
                                               if k in TradeRecord.__dataclass_fields__})
                            self.trades.append(rec)
            except Exception:
                pass

        if self.daily_stats_file.exists():
            try:
                with open(self.daily_stats_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for date_str, stats_data in data.items():
                    ds = DailyStats(**{k: v for k, v in stats_data.items()
                                     if k in DailyStats.__dataclass_fields__})
                    self.daily_stats[date_str] = ds
            except Exception:
                pass

        if self.trades:
            running_equity = self.initial_equity
            self.peak_equity = self.initial_equity
            for t in self.trades:
                running_equity += t.pnl
                if running_equity > self.peak_equity:
                    self.peak_equity = running_equity
                dd = (self.peak_equity - running_equity) / self.peak_equity if self.peak_equity else 0
                if dd > self.max_drawdown:
                    self.max_drawdown = dd
            self.current_equity = running_equity

    def _save_trade(self, trade: TradeRecord):
        """保存单笔交易到日志"""
        try:
            with open(self.trades_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(trade), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _save_daily_stats(self):
        """保存每日统计"""
        try:
            data = {date: asdict(stats) for date, stats in self.daily_stats.items()}
            with open(self.daily_stats_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def record_trade(self, trade: TradeRecord) -> Dict:
        """记录一笔已平仓交易并更新统计

        Returns:
            交易摘要 dict
        """
        self.trades.append(trade)
        self._save_trade(trade)

        self.current_equity += trade.pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        dd = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity else 0
        if dd > self.max_drawdown:
            self.max_drawdown = dd

        date_str = trade.exit_time[:10] if trade.exit_time else datetime.now().strftime("%Y-%m-%d")
        if date_str not in self.daily_stats:
            self.daily_stats[date_str] = DailyStats(
                date=date_str,
                starting_equity=self.current_equity - trade.pnl,
                peak_equity=self.peak_equity,
            )
        ds = self.daily_stats[date_str]
        ds.total_trades += 1
        ds.total_pnl += trade.pnl
        ds.ending_equity = self.current_equity
        ds.trades.append(asdict(trade))

        if trade.pnl >= 0:
            ds.win_trades += 1
            ds.current_consecutive_wins += 1
            ds.current_consecutive_losses = 0
            ds.max_consecutive_wins = max(ds.max_consecutive_wins,
                                          ds.current_consecutive_wins)
        else:
            ds.loss_trades += 1
            ds.current_consecutive_losses += 1
            ds.current_consecutive_wins = 0
            ds.max_consecutive_losses = max(ds.max_consecutive_losses,
                                            ds.current_consecutive_losses)

        ds.win_rate = ds.win_trades / ds.total_trades if ds.total_trades else 0

        wins = [t["pnl"] for t in ds.trades if t["pnl"] >= 0]
        losses = [abs(t["pnl"]) for t in ds.trades if t["pnl"] < 0]
        ds.avg_win = sum(wins) / len(wins) if wins else 0
        ds.avg_loss = sum(losses) / len(losses) if losses else 0
        ds.profit_factor = ds.avg_win / ds.avg_loss if ds.avg_loss else 0

        peak = ds.starting_equity
        running = ds.starting_equity
        for t in ds.trades:
            running += t["pnl"]
            if running > peak:
                peak = running
            dd = (peak - running) / peak if peak else 0
            if dd > ds.max_drawdown:
                ds.max_drawdown = dd

        self._save_daily_stats()

        return {
            "trade_id": trade.trade_id,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "win": trade.pnl >= 0,
            "daily_total_pnl": ds.total_pnl,
            "daily_win_rate": ds.win_rate,
            "daily_trades": ds.total_trades,
            "current_equity": self.current_equity,
            "max_drawdown": self.max_drawdown,
            "consecutive_losses": ds.current_consecutive_losses,
        }

    def get_today_stats(self) -> Dict:
        """获取今日统计"""
        today = datetime.now().strftime("%Y-%m-%d")
        ds = self.daily_stats.get(today)
        if not ds:
            return {
                "date": today,
                "total_trades": 0,
                "win_trades": 0,
                "loss_trades": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "current_consecutive_losses": 0,
            }
        return asdict(ds)

    def get_overall_stats(self) -> Dict:
        """获取整体统计（P2修正：补夏普比率和日收益率序列）"""
        total_trades = len(self.trades)
        win_trades = sum(1 for t in self.trades if t.pnl >= 0)
        loss_trades = total_trades - win_trades
        total_pnl = sum(t.pnl for t in self.trades)
        win_rate = win_trades / total_trades if total_trades else 0

        wins = [t.pnl for t in self.trades if t.pnl >= 0]
        losses = [abs(t.pnl) for t in self.trades if t.pnl < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = avg_win / avg_loss if avg_loss else 0

        # P2修正：计算日收益率序列和夏普比率
        daily_returns = {}
        for t in self.trades:
            day = (t.exit_time or "")[:10]
            if not day:
                day = "unknown"
            daily_returns[day] = daily_returns.get(day, 0.0) + t.pnl

        daily_pnls = list(daily_returns.values())
        sharpe_ratio = 0.0
        if len(daily_pnls) > 1:
            import numpy as _np
            std = _np.std(daily_pnls)
            if std > 0:
                sharpe_ratio = _np.mean(daily_pnls) / std * (252 ** 0.5)

        return {
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": self.max_drawdown,
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "initial_equity": self.initial_equity,
            "sharpe_ratio": sharpe_ratio,  # P2新增
            "daily_returns": daily_pnls,   # P2新增
            "trading_days": len(daily_pnls),  # P2新增
        }


# ── 风险控制器 ────────────────────────────────────────

class RiskManager:
    """风险控制器：动态仓位 + 日亏损限制 + 连续亏损熔断"""

    def __init__(self,
                 daily_loss_limit_usdt: float = -30.0,
                 max_consecutive_losses: int = 999,
                 default_position_pct: float = 0.10,
                 min_position_pct: float = 0.02,
                 max_position_pct: float = 0.20,
                 min_position_usdt: float = 20.0,
                 loss_limit_pct: float = 0.20):
        self.state = RiskState(
            daily_loss_limit=daily_loss_limit_usdt,
            loss_limit_pct=loss_limit_pct,
            max_consecutive_losses=max_consecutive_losses,
            position_size_pct=default_position_pct,
            min_position_size_pct=min_position_pct,
            max_position_size_pct=max_position_pct,
            min_position_usdt=min_position_usdt,
        )

        self.risk_dir = memory_l4_dir() / "risk"
        self.risk_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.risk_dir / "risk_state.json"
        self._save_failed = False
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                today = datetime.now().strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self.state.daily_pnl = data.get("daily_pnl", 0.0)
                    self.state.current_consecutive_losses = data.get("consecutive_losses", 0)
                    self.state.trading_halted = data.get("trading_halted", False)
                    self.state.halt_reason = data.get("halt_reason", "")
                # 配置字段：跨日保留（可能被 config.json 热覆盖）
                if "daily_loss_limit" in data:
                    self.state.daily_loss_limit = data["daily_loss_limit"]
                if "loss_limit_pct" in data:
                    self.state.loss_limit_pct = data["loss_limit_pct"]
                if "max_consecutive_losses" in data:
                    self.state.max_consecutive_losses = data["max_consecutive_losses"]
                if "position_size_pct" in data:
                    self.state.position_size_pct = data["position_size_pct"]
                if "min_position_size_pct" in data:
                    self.state.min_position_size_pct = data["min_position_size_pct"]
                if "max_position_size_pct" in data:
                    self.state.max_position_size_pct = data["max_position_size_pct"]
                if "min_position_usdt" in data:
                    self.state.min_position_usdt = data["min_position_usdt"]
            except Exception:
                logger.exception("加载风控状态失败，使用默认状态（可能保守）")

    def _save_state(self):
        try:
            data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "daily_pnl": self.state.daily_pnl,
                "consecutive_losses": self.state.current_consecutive_losses,
                "trading_halted": self.state.trading_halted,
                "halt_reason": self.state.halt_reason,
                "daily_loss_limit": self.state.daily_loss_limit,
                "loss_limit_pct": self.state.loss_limit_pct,
                "max_consecutive_losses": self.state.max_consecutive_losses,
                "position_size_pct": self.state.position_size_pct,
                "min_position_size_pct": self.state.min_position_size_pct,
                "max_position_size_pct": self.state.max_position_size_pct,
                "min_position_usdt": self.state.min_position_usdt,
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            self._save_failed = False
        except Exception:
            logger.exception("保存风控状态失败，后续开仓将被拒绝直到恢复")
            self._save_failed = True

    def can_trade(self, current_equity: float = 0) -> Dict:
        """检查是否允许开仓

        风控规则：亏损金额超过可用金额的 loss_limit_pct（默认20%）则触发拦截。
        不再以连续亏损笔数为准，避免小幅连续亏损反复触发风控。

        Args:
            current_equity: 当前账户权益（USDT），用于动态计算亏损阈值

        Returns:
            {allowed: bool, reason: str}
        """
        if self._save_failed:
            return {"allowed": False, "reason": "风控状态持久化失败，拒绝开仓 until 恢复"}

        if self.state.trading_halted:
            return {"allowed": False, "reason": f"交易已暂停: {self.state.halt_reason}"}

        # 动态亏损阈值：亏损超过当前权益的 loss_limit_pct（默认20%）则拦截
        # 兜底固定值 daily_loss_limit（默认-30U，即150U可用金的20%）
        dynamic_limit = -(current_equity * self.state.loss_limit_pct) if current_equity > 0 else self.state.daily_loss_limit
        effective_limit = max(dynamic_limit, self.state.daily_loss_limit)  # 取更严格的阈值

        if self.state.daily_pnl <= effective_limit:
            return {"allowed": False,
                    "reason": f"日亏损达上限: {self.state.daily_pnl:.2f} <= {effective_limit:.2f} (权益{current_equity:.2f}的{self.state.loss_limit_pct:.0%})"}

        return {"allowed": True, "reason": ""}

    def calc_position_size(self,
                           confidence: float,
                           volatility: float,
                           current_equity: float,
                           base_pct: float = None,
                           leverage: float = None) -> Dict:
        """根据置信度和波动率动态计算仓位大小

        Args:
            confidence: 置信度 0~1
            volatility: 波动率 0~1
            current_equity: 当前权益
            base_pct: 基础仓位比例（默认用 state 中的值）
            leverage: 杠杆倍数（默认从环境变量读取）

        Returns:
            {position_usdt: float, margin_usdt: float, position_pct: float, reason: str}
        """
        if leverage is None:
            leverage = float(os.environ.get("DEFAULT_LEVERAGE", 10))

        base = base_pct or self.state.position_size_pct

        # 置信度系数：分段线性动态缩放
        # 以 0.70 为基准点，低于基准减仓，高于基准加仓
        # 置信度 0.00 → 系数 0.40（最低）
        # 置信度 0.55 → 系数 0.75（低置信度减仓）
        # 置信度 0.70 → 系数 1.00（基准）
        # 置信度 0.80 → 系数 1.17（明显加仓）
        # 置信度 0.90 → 系数 1.33（高置信度大幅加仓）
        # 置信度 0.95+ → 系数 1.50（极高置信度满仓）
        conf_normalized = max(0.0, min(1.0, confidence))
        if conf_normalized <= 0.70:
            # 低置信度区间：0.40 → 1.00（线性插值）
            conf_factor = 0.40 + (conf_normalized / 0.70) * 0.60
        else:
            # 高置信度区间：1.00 → 1.50（线性插值）
            conf_factor = 1.00 + ((conf_normalized - 0.70) / 0.30) * 0.50
        # 限制在 [0.40, 1.50] 区间
        conf_factor = max(0.40, min(1.50, conf_factor))

        if volatility > 0:
            vol_factor = 0.02 / volatility  # 波动率越高，仓位越小（反比）
            vol_factor = max(0.3, min(vol_factor, 1.8))
        else:
            vol_factor = 1.0

        position_pct = base * conf_factor * vol_factor
        position_pct = max(self.state.min_position_size_pct,
                           min(position_pct, self.state.max_position_size_pct))

        margin_usdt = current_equity * position_pct  # 保证金金额
        position_usdt = margin_usdt * leverage  # 名义仓位价值（传给OKX下单）
        position_usdt = max(position_usdt, self.state.min_position_usdt)  # 不低于最低名义仓位价值
        margin_usdt = position_usdt / leverage  # 反推保证金

        return {
            "position_usdt": round(position_usdt, 2),
            "margin_usdt": round(margin_usdt, 2),
            "position_pct": round(position_pct, 4),
            "confidence_factor": round(conf_factor, 4),
            "volatility_factor": round(vol_factor, 4),
            "reason": (
                f"conf={confidence:.2f}(factor={conf_factor:.2f}) "
                f"vol={volatility:.4f}(factor={vol_factor:.2f}) "
                f"-> pos={position_usdt:.2f}USDT ({position_pct:.1%})"
            ),
        }

    def update_after_trade(self, pnl: float, is_win: bool, current_equity: float = 0):
        """交易平仓后更新风控状态

        Args:
            pnl: 本笔盈亏（USDT）
            is_win: 是否盈利
            current_equity: 当前权益（用于动态亏损阈值判断）
        """
        self.state.daily_pnl += pnl

        if is_win:
            self.state.current_consecutive_losses = 0
        else:
            self.state.current_consecutive_losses += 1

        # 仅以亏损金额触发halt，不以连续亏损笔数触发
        dynamic_limit = -(current_equity * self.state.loss_limit_pct) if current_equity > 0 else self.state.daily_loss_limit
        effective_limit = max(dynamic_limit, self.state.daily_loss_limit)

        if self.state.daily_pnl <= effective_limit:
            self.state.trading_halted = True
            self.state.halt_reason = (
                f"日亏损达到上限 {effective_limit:.2f} USDT "
                f"(权益{current_equity:.2f}的{self.state.loss_limit_pct:.0%})"
            )

        self._save_state()

    def reset_daily(self):
        """重置每日风控（新的一天调用）"""
        today = datetime.now().strftime("%Y-%m-%d")
        self.state.daily_pnl = 0.0
        self.state.trading_halted = False
        self.state.halt_reason = ""
        self._save_state()

    def get_state(self) -> Dict:
        return {
            "daily_pnl": round(self.state.daily_pnl, 2),
            "daily_loss_limit": self.state.daily_loss_limit,
            "consecutive_losses": self.state.current_consecutive_losses,
            "max_consecutive_losses": self.state.max_consecutive_losses,
            "trading_halted": self.state.trading_halted,
            "halt_reason": self.state.halt_reason,
            "position_size_pct": self.state.position_size_pct,
            "min_position_usdt": self.state.min_position_usdt,
        }


# ── Case 生成器（统一接口）──────────────────────────────

def generate_case_from_trade(trade: TradeRecord) -> Dict:
    """从平仓交易生成 L4 case（旧接口，保留兼容性）

    调用新的 UnifiedCaseRegistry 创建标准 TradeCase v0.3
    """
    event = TradeEvent.from_trade_record(trade)
    registry = UnifiedCaseRegistry()
    case = registry.build_trade_case(event)
    return case


def save_case_to_l4(case: Dict) -> bool:
    """保存 case 到 L4 案例库（旧接口，保留兼容性）"""
    registry = UnifiedCaseRegistry()
    return registry.save_case(case)


def register_trade_to_l4(trade: TradeRecord) -> Tuple[str, bool]:
    """
    新统一接口：将交易记录注册到 L4

    使用 TradeEvent + UnifiedCaseRegistry 生成标准 TradeCase v0.3

    Returns:
        (case_id, success)
    """
    event = TradeEvent.from_trade_record(trade)
    registry = UnifiedCaseRegistry()
    return registry.register_trade_event(event)


# ── 持仓跟踪器 ────────────────────────────────────────

class PositionTracker:
    """持仓跟踪器：记录开仓信息，平仓时生成完整交易记录"""

    def __init__(self):
        self.positions_dir = memory_l4_dir() / "open_positions"
        self.positions_dir.mkdir(parents=True, exist_ok=True)
        self.open_positions: Dict[str, TradeRecord] = {}
        # 统一冷静期：{inst_id: {pos_side, close_ts, exit_reason}}
        self.last_close_info: Dict[str, dict] = {}
        self._load_open_positions()
        self._load_last_close_info()

    # ── 统一冷静期：持久化 ────────────────────────────────────────────────
    def _last_close_file(self):
        return self.positions_dir / "last_close_info.json"

    def _load_last_close_info(self):
        """从磁盘加载最后平仓记录（用于跨重启保留冷却期）"""
        f = self._last_close_file()
        if f.exists():
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    self.last_close_info = json.load(fp)
            except Exception:
                self.last_close_info = {}

    def _save_last_close_info(self):
        """保存最后平仓记录到磁盘"""
        f = self._last_close_file()
        try:
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(self.last_close_info, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def is_in_cooldown(self, inst_id: str, direction: str,
                       cooldown_sec: float) -> Tuple[bool, str]:
        """检查统一冷静期（全方向拦截）

        平仓后 cooldown_sec 内禁止该币种任何方向的新开仓（含反手）。
        防止"平仓→立即反手→又亏→再反手"的频繁来回割肉循环。

        Args:
            inst_id: 合约ID
            direction: 欲开仓方向 (long/short) — 保留参数兼容，但不再区分方向
            cooldown_sec: 冷静期秒数

        Returns:
            (in_cooldown, reason) — in_cooldown=True 表示应跳过开仓
        """
        info = self.last_close_info.get(inst_id)
        if not info:
            return False, ""
        elapsed = time.time() - info.get("close_ts", 0)
        if elapsed < cooldown_sec:
            remaining = cooldown_sec - elapsed
            return True, (f"统一冷静期: 剩余{remaining/3600:.1f}h "
                          f"(上次{info.get('pos_side')}平仓于{elapsed/60:.1f}分钟前, "
                          f"reason={info.get('exit_reason')})")
        return False, ""

    def _load_open_positions(self):
        """从磁盘加载未平仓记录"""
        for f in self.positions_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                rec = TradeRecord(**{k: v for k, v in data.items()
                                   if k in TradeRecord.__dataclass_fields__})
                if rec.inst_id:
                    self.open_positions[rec.inst_id] = rec
            except Exception:
                pass

    def _save_open_position(self, inst_id: str):
        """保存未平仓记录到磁盘"""
        if inst_id in self.open_positions:
            filepath = self.positions_dir / f"{inst_id.replace('/', '_')}.json"
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(asdict(self.open_positions[inst_id]), f,
                              indent=2, ensure_ascii=False, default=str)
            except Exception:
                pass

    def _remove_open_position(self, inst_id: str):
        """删除未平仓记录"""
        self.open_positions.pop(inst_id, None)
        filepath = self.positions_dir / f"{inst_id.replace('/', '_')}.json"
        if filepath.exists():
            try:
                filepath.unlink()
            except Exception:
                pass

    def open_position(self,
                      coin: str,
                      inst_id: str,
                      direction: str,
                      entry_price: float,
                      confidence: float,
                      hexagram: str,
                      liangyi_state: Dict = None,
                      scale_params: Dict = None,
                      market_snapshot: Dict = None,
                      contradiction_list: List[Dict] = None,
                      strategy_source: str = "bcrm",
                      enhance_info: Dict = None,
                      base_sl_roi: float = 0.0,
                      base_tp_roi: float = 0.0) -> TradeRecord:
        """记录开仓"""
        trade_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        rec = TradeRecord(
            trade_id=trade_id,
            coin=coin,
            inst_id=inst_id,
            direction=direction,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc).isoformat(),
            confidence=confidence,
            hexagram=hexagram,
            liangyi_state=liangyi_state or {},
            scale_params=scale_params or {},
            market_snapshot=market_snapshot or {},
            contradiction_list=contradiction_list or [],
            strategy_source=strategy_source,
            enhance_info=enhance_info or {},
            base_sl_roi=base_sl_roi,
            base_tp_roi=base_tp_roi,
        )
        self.open_positions[inst_id] = rec
        self._save_open_position(inst_id)
        return rec

    def close_position(self,
                       inst_id: str,
                       exit_price: float,
                       exit_reason: str,
                       pnl: float = None,
                       pnl_pct: float = None) -> Optional[TradeRecord]:
        """记录平仓，返回完整交易记录

        Returns:
            TradeRecord 或 None（如果没有对应开仓记录）
        """
        if inst_id not in self.open_positions:
            return None

        rec = self.open_positions[inst_id]
        rec.exit_price = exit_price
        rec.exit_time = datetime.now(timezone.utc).isoformat()
        rec.exit_reason = exit_reason

        if pnl is None:
            if rec.direction == "long":
                rec.pnl = (exit_price - rec.entry_price) / rec.entry_price * 100
            else:
                rec.pnl = (rec.entry_price - exit_price) / rec.entry_price * 100
        else:
            rec.pnl = pnl

        if pnl_pct is None:
            rec.pnl_pct = rec.pnl / 100 if rec.entry_price else 0
        else:
            rec.pnl_pct = pnl_pct

        # 记录统一冷静期信息（所有平仓路径都经过此处）
        self.last_close_info[inst_id] = {
            "pos_side": rec.direction,
            "close_ts": time.time(),
            "exit_reason": exit_reason,
        }
        self._save_last_close_info()

        self._remove_open_position(inst_id)
        return rec

    def get_open_position(self, inst_id: str) -> Optional[TradeRecord]:
        return self.open_positions.get(inst_id)

    def has_open_position(self, inst_id: str) -> bool:
        return inst_id in self.open_positions

    def all_open_positions(self) -> List[TradeRecord]:
        return list(self.open_positions.values())
