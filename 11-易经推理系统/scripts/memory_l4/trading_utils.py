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
    # P2-07: 形态预测器 regime + 参数乘数快照（开仓时记录，事后审计用）
    regime_pred: str = None
    regime_multipliers: Dict = None
    # Phase C (Spec §4.3.2): B 档排队止盈计划
    # {"type": "ranked_tp", "wait_cycles": 2, "trigger_rank": float, "set_at_cycle": int}
    reduce_plan: Optional[Dict] = None


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

    # ===== P3: 波动率自适应 =====

    @staticmethod
    def volatility_regime(volatility: float) -> str:
        """波动率分层（3-tier）。

        - LOW: vol < 0.02（平静市场，适合紧止损+大仓位）
        - NORMAL: 0.02 ≤ vol < 0.05（正常波动）
        - HIGH: vol ≥ 0.05（剧烈波动，宽止损+小仓位+高门槛）
        """
        if volatility < 0.02:
            return "LOW"
        elif volatility < 0.05:
            return "NORMAL"
        return "HIGH"

    @staticmethod
    def volatility_adaptive_atr_mult(volatility: float,
                                     base_sl: float = 2.5,
                                     base_tp_ratio: float = 2.0) -> tuple:
        """波动率自适应 ATR 止损/止盈倍率（连续插值，非离散跳变）。

        核心思路：
        - vol=0.01（低波）→ SL=2.0×ATR（紧），TP=4.0×ATR
        - vol=0.03（正常）→ SL=2.5×ATR（基准），TP=5.0×ATR
        - vol=0.06（高波）→ SL=3.5×ATR（宽），TP=7.0×ATR
        - vol=0.10+（极端）→ SL=4.0×ATR（很宽），TP=8.0×ATR

        公式：sl_mult = base_sl + max(0, (vol - 0.02)) × 25，clamp [2.0, 4.0]
              tp_mult = sl_mult × base_tp_ratio（保持盈亏比）
        """
        # 连续插值：以 vol=0.02 为基准点
        vol_excess = max(0.0, volatility - 0.02)
        sl_mult = base_sl + vol_excess * 25.0  # vol=0.06 → +1.0 → 3.5
        sl_mult = max(2.0, min(sl_mult, 4.0))  # clamp [2.0, 4.0]

        # 低波时收紧密止损
        if volatility < 0.02:
            sl_mult = max(2.0, base_sl - (0.02 - volatility) * 25.0)  # vol=0.01 → 2.25

        tp_mult = sl_mult * base_tp_ratio  # 盈亏比保持 2:1
        return round(sl_mult, 2), round(tp_mult, 2)

    @staticmethod
    def volatility_position_factor(volatility: float,
                                   f_min: float = 0.55,
                                   f_max: float = 1.00) -> float:
        """波动率仓位调整因子（叠加在 P2 base_multiplier 上）。

        分段函数：低/正常波动不惩罚，仅高波动缩仓。
        - vol < 0.04（低/正常）→ 1.00（不变化，不误伤正常波动）
        - vol = 0.05（高波边界）→ ~0.89（轻微缩仓）
        - vol = 0.06 → ~0.77
        - vol = 0.08+（极端）→ ~0.58（大幅缩仓）

        公式：vol < 0.04 时 factor=1.0；否则 sigmoid 衰减
              factor = f_max - (f_max - f_min) × sigmoid((vol - 0.04) × 30)
        """
        import math
        if volatility < 0.04:
            return 1.0
        sigmoid = 1.0 / (1.0 + math.exp(-(volatility - 0.04) * 30.0))
        factor = f_max - (f_max - f_min) * sigmoid
        return round(factor, 4)

    @staticmethod
    def kelly_half_factor(win_rate: float, avg_win: float, avg_loss: float,
                          kelly_shrink: float = 0.5,
                          min_factor: float = 0.25, max_factor: float = 1.25) -> float:
        """半凯利仓位系数。

        Kelly 公式: f = (p·b − q) / b，其中 p=胜率, q=1-p, b=盈亏比=avg_win/avg_loss
        保守取 kelly_shrink × f（默认半凯利），避免过拟合与过激进。
        当样本不足或 b <= 0 时返回 1.0（保持默认仓位）。
        """
        if win_rate <= 0.0 or avg_loss <= 0.0 or avg_win <= 0.0:
            return 1.0
        b = avg_win / avg_loss
        if b <= 0:
            return 1.0
        f = (win_rate * b - (1.0 - win_rate)) / b
        f_shrunk = max(0.0, f) * kelly_shrink  # 半凯利 / 收缩
        factor = 1.0 + (f_shrunk - 0.10)  # 以 f=10% 为基准线
        factor = max(min_factor, min(factor, max_factor))
        return factor

    @staticmethod
    def consecutive_loss_factor(loss_streak: int,
                                factor_map: Optional[Dict[int, float]] = None) -> float:
        """连续亏损缩仓系数：连亏越多，仓位越小，防止情绪失控与极端段放大回撤。

        默认映射：连亏0→1.0；连亏1→0.85；连亏2→0.65；连亏3→0.45；连亏≥4→0.30
        """
        if loss_streak <= 0:
            return 1.0
        if factor_map is None:
            factor_map = {0: 1.0, 1: 0.85, 2: 0.65, 3: 0.45}
        return factor_map.get(loss_streak, 0.30)

    @staticmethod
    def hexagram_class_factor(hexagram: str,
                              bullish_hexagrams: Optional[set] = None,
                              bearish_hexagrams: Optional[set] = None) -> Tuple[float, str]:
        """卦象类型仓位系数（复用 review_engine 中 BULLISH/BEARISH/NEUTRAL 分类）。

        - BULLISH（吉卦，做多有利）×1.20  放大仓位
        - BEARISH（凶卦，做空有利）×0.70  降低做多仓位
        - NEUTRAL ×1.00  中性
        返回 (factor, class_name)。
        """
        h = (hexagram or "").strip()
        if not h:
            return 1.0, "neutral"
        if bullish_hexagrams and h in bullish_hexagrams:
            return 1.20, "bullish"
        if bearish_hexagrams and h in bearish_hexagrams:
            return 0.70, "bearish"
        return 1.0, "neutral"

    # ===== Phase B: EV 风险价值雷达 =====

    @staticmethod
    def calc_position_ev(subscores: Dict[str, float],
                         weights: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
        """EV 风险-价值合成（Spec §4）。

        数学：base_score = Σ(w_i * s_i)，其中 s_i ∈ [0,1] 归一化子分
              EV = base_score - 0.2（正偏置：全中值 0.5 → EV=0.3）

        返回 (ev, subscores) — 同时返回子分便于日志/调试。
        """
        if not subscores:
            return 0.0, {}
        base_score = sum(
            float(weights.get(k, 0.0)) * float(v)
            for k, v in subscores.items()
        )
        ev = base_score - 0.2  # 正偏置，使 Σ(w*0.5)=0.5 → EV=0.3
        return round(ev, 4), dict(subscores)

    # ===== Phase C: 多 horizon 预测（S3）=====

    @staticmethod
    def predict_multi_horizon(inference: Dict,
                              k_candidates: List[int]) -> Dict:
        """多 horizon K 线预测（Phase C 占位实现，Spec §4.2）。

        基于当前推理的 confidence / direction / 五角得分，为每个候选 K 线数
        估算"在该 K 线后止盈离场"的置信度和预期 ROI。

        实现思路（占位，后续接入真实 BCRM 逐 horizon 回测）：
        - 短 horizon（5~10）：以 bagua + trend 为主，衰减快，置信度快速降
        - 中 horizon（20~30）：以 regime + 五角一致性为主，置信度先升后降
        - 长 horizon（45~60）：需 macro + cross 维度一致，否则衰减

        返回 {"horizons": [{k_bar, confidence, direction, expected_roi_pct}],
                 "recommended_action": "HOLD"|"PREP_EXIT"|"EXTEND_TRACK"|"NOOP"}
        """
        base_conf = max(0.10, min(0.99, float(inference.get("confidence", 0.5))))
        base_dir = str(inference.get("direction", "UP"))
        pentagon = inference.get("pentagon_scores") or {}
        pentagon_avg = (sum(float(v) for v in pentagon.values()) / len(pentagon)) \
            if pentagon else base_conf

        # 为每个 k 生成 horizon 条目（以中=30 为置信度顶峰，高斯衰减）
        import math
        peak_k = 30  # 占位：默认最佳 K 线 ~30h（五角越强 → peak 越右移）
        # 用 pentagon_avg 右移 peak：五角高 → 支持更长持有
        peak_k = int(peak_k + (pentagon_avg - 0.5) * 80)  # ±40 偏移
        peak_k = max(5, min(60, peak_k))

        sigma = 20.0  # 高斯宽度
        max_roi_pct = 0.02 + (base_conf - 0.5) * 0.10  # 2%~7% 预期 ROI

        horizons = []
        for k in k_candidates:
            decay = math.exp(-((k - peak_k) ** 2) / (2 * sigma * sigma))
            c = base_conf * (0.35 + 0.65 * decay)
            # 方向：如果 base=UP，短期跟随；过久后可能反转
            if k <= peak_k:
                direction = base_dir
            else:
                # 超过 peak 后，若置信度已跌落 < 0.45 → 反向
                direction = base_dir if c >= 0.45 else \
                    ("DOWN" if base_dir == "UP" else "UP")
            roi = max_roi_pct * decay
            horizons.append({
                "k_bar": int(k),
                "confidence": round(c, 4),
                "direction": direction,
                "expected_roi_pct": round(roi, 6),
            })

        # 简单 recommended_action 占位（具体 HOLD/PREP_EXIT 判定在 _recommend_exit_bars）
        # 这里选最高置信度的 horizon 作为参考点
        best_h = max(horizons, key=lambda x: x["confidence"]) if horizons else None
        if best_h and best_h["confidence"] >= 0.6:
            action = "HOLD" if best_h["direction"] == base_dir else "PREP_EXIT"
        elif best_h and best_h["confidence"] < 0.45:
            action = "PREP_EXIT"
        else:
            action = "EXTEND_TRACK"

        return {"horizons": horizons, "recommended_action": action}

    # ===== Phase C (Spec §4.3.1): 多 horizon 合成曲线 =====

    @staticmethod
    def synthesize_horizon_curves(
        multi_horizon_probs: Dict[int, Dict[str, float]],
        pos_sign: int = 1,  # +1=LONG, -1=SHORT
        tau: float = 15.0,  # L(k) 饱和时间常数
    ) -> Dict:
        """从多 horizon 概率对合成 S(k)/L(k)/HORIZON_K_STAR 等曲线指标。

        Spec §4.3.1 数学：
          S(k) = Σ_{h=1..k} (P_correct(h) - 0.5)   短期延续曲线
          HORIZON_K_STAR = 使 S(k+1) - S(k) ≤ 0 的最小 k（边际收益转负点）
          L(k) = P_correct(k) * (1 - exp(-k / τ))   远期饱和曲线
          CONTINUATION_SCORE = L_norm(6)  （L(6) 归一化到 [0,1]）
          SHORT_TERM_REVERSAL_RISK = 1 - (S(3) + 1.5) / 3  clip to [0,1]

        Args:
            multi_horizon_probs: {h: {"P_up": float, "P_down": float}}, h 为 horizon K 线数
            pos_sign: +1 做多（correct=P_up），-1 做空（correct=P_down）
            tau: L(k) 饱和时间常数，默认 15

        Returns:
            {
                "S_curve": {k: float},          # 短期延续累积曲线
                "L_curve": {k: float},          # 远期饱和曲线
                "HORIZON_K_STAR": int,          # 最佳离场 K 线数
                "CONTINUATION_SCORE": float,    # L(6) 归一化 [0,1]
                "SHORT_TERM_REVERSAL_RISK": float,  # [0,1]
            }
        """
        import math

        if not multi_horizon_probs:
            return {
                "S_curve": {}, "L_curve": {},
                "HORIZON_K_STAR": 0,
                "CONTINUATION_SCORE": 0.0,
                "SHORT_TERM_REVERSAL_RISK": 0.5,
            }

        # 按 horizon 排序
        sorted_horizons = sorted(multi_horizon_probs.keys())

        # 1. S(k): 累积 (P_correct - 0.5)
        S_curve = {}
        cumulative = 0.0
        for h in sorted_horizons:
            probs = multi_horizon_probs[h]
            p_correct = float(probs.get("P_up", 0.5)) if pos_sign >= 0 \
                else float(probs.get("P_down", 0.5))
            cumulative += (p_correct - 0.5)
            S_curve[h] = cumulative

        # 2. HORIZON_K_STAR: 第一个 S(k+1) - S(k) ≤ 0 的 k
        k_star = sorted_horizons[-1]  # 默认取最大 horizon（一直延续）
        for i in range(len(sorted_horizons) - 1):
            k_curr = sorted_horizons[i]
            k_next = sorted_horizons[i + 1]
            if S_curve[k_next] - S_curve[k_curr] <= 0:
                k_star = k_curr
                break

        # 3. L(k): P_correct(k) * (1 - exp(-k / τ))
        L_curve = {}
        for h in sorted_horizons:
            probs = multi_horizon_probs[h]
            p_correct = float(probs.get("P_up", 0.5)) if pos_sign >= 0 \
                else float(probs.get("P_down", 0.5))
            L_curve[h] = p_correct * (1.0 - math.exp(-h / tau))

        # 4. CONTINUATION_SCORE = L_norm(6)
        # 取 h=6 的 L 值（或最近的 horizon），归一化到 [0,1]
        # L(k) 最大值 ≈ 1.0 * (1 - exp(-60/15)) ≈ 0.98，所以直接 clip 即可
        h6 = min(sorted_horizons, key=lambda h: abs(h - 6))
        cont_score = max(0.0, min(1.0, L_curve.get(h6, 0.0)))

        # 5. SHORT_TERM_REVERSAL_RISK = 1 - (S(3) + 1.5) / 3
        h3 = min(sorted_horizons, key=lambda h: abs(h - 3))
        s3 = S_curve.get(h3, 0.0)
        reversal_risk = max(0.0, min(1.0, 1.0 - (s3 + 1.5) / 3.0))

        return {
            "S_curve": S_curve,
            "L_curve": L_curve,
            "HORIZON_K_STAR": k_star,
            "CONTINUATION_SCORE": round(cont_score, 4),
            "SHORT_TERM_REVERSAL_RISK": round(reversal_risk, 4),
        }

    # ===== Phase C: 排名止盈落差（S4）=====

    @staticmethod
    def calc_ranked_tp_gap(ranked_positions: List[Dict],
                           min_profit_usdt: float = 5.0) -> Dict:
        """排名止盈落差计算（Spec §4.3）。

        数学（Top1 > 0）：
          gap_ratio = (Top1_upl − Top2_upl) / Top1_upl
          trigger = (gap_ratio >= GAP_THRESHOLD 默认 0.70)
                     AND (Top1_upl >= min_profit_usdt)
                     AND (len(ranked) >= 2)

        边界保护：
          - 持仓 < 2 → 无法比落差 → trigger=False
          - Top1_upl <= 0 → 亏损或持平 → trigger=False（别把亏损单止盈）
          - Top1_upl < min_profit_usdt → 小盈利噪声 → trigger=False
        """
        if not ranked_positions or len(ranked_positions) < 2:
            return {"top1_idx": -1, "gap_ratio": 0.0, "trigger": False}

        # 按 upl 降序排序（必须是浮点数；不接受字符串等异常类型）
        def _upl(x):
            try:
                return float(x.get("upl", 0.0))
            except Exception:
                return 0.0

        sorted_pos = sorted(enumerate(ranked_positions),
                            key=lambda iv: _upl(iv[1]), reverse=True)
        top1_idx, top1 = sorted_pos[0]
        _, top2 = sorted_pos[1]
        upl1 = _upl(top1)
        upl2 = _upl(top2)

        if upl1 <= 0 or upl1 < min_profit_usdt:
            return {"top1_idx": top1_idx, "gap_ratio": 0.0, "trigger": False}

        gap_ratio = (upl1 - upl2) / upl1  # ∈ (-∞, 1]
        gap_ratio = round(gap_ratio, 6)

        # trigger 默认 0.70 阈值；具体门槛在调用方传入（此处只算 ratio）
        # 但测试 C-5 直接断言 trigger=True 当 gap=0.70 时，所以这里也用 ≥0.70
        trigger = (gap_ratio >= 0.70)
        return {"top1_idx": top1_idx, "gap_ratio": gap_ratio, "trigger": trigger}

    def calc_position_size(self,
                           confidence: float,
                           volatility: float,
                           current_equity: float,
                           base_pct: float = None,
                           leverage: float = None,
                           kelly_factor: float = 1.0,
                           consecutive_loss_factor: float = 1.0,
                           hexagram_factor: float = 1.0,
                           vol_regime_factor: float = 1.0) -> Dict:
        """根据置信度和波动率动态计算仓位大小

        Args:
            confidence: 置信度 0~1
            volatility: 波动率 0~1
            current_equity: 当前权益
            base_pct: 基础仓位比例（默认用 state 中的值）
            leverage: 杠杆倍数（默认从环境变量读取）
            kelly_factor: P2 凯利系数（半凯利动态仓位），范围 [0.25,1.25]
            consecutive_loss_factor: P2 连亏缩仓系数，范围 [0.30,1.00]
            hexagram_factor: P2 卦象类型系数，范围 [0.70,1.20]
            vol_regime_factor: P3 波动率仓位因子，范围 [0.50,1.15]

        Returns:
            {position_usdt: float, margin_usdt: float, position_pct: float, reason: str}
        """
        if leverage is None:
            leverage = float(os.environ.get("DEFAULT_LEVERAGE", 10))

        base = base_pct or self.state.position_size_pct

        # P2+P3 动态仓位基础倍率：凯利 × 连亏 × 卦象 × 波动率 共同作用于 base
        p2_base_multiplier = max(0.15, min(kelly_factor, 1.50)) \
            * max(0.25, min(consecutive_loss_factor, 1.20)) \
            * max(0.50, min(hexagram_factor, 1.50)) \
            * max(0.40, min(vol_regime_factor, 1.30))
        p2_base_multiplier = max(0.15, min(p2_base_multiplier, 1.80))  # 全局限制避免因子乘积爆炸
        base = base * p2_base_multiplier

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
            "kelly_factor": round(kelly_factor, 4),
            "consecutive_loss_factor": round(consecutive_loss_factor, 4),
            "hexagram_factor": round(hexagram_factor, 4),
            "vol_regime_factor": round(vol_regime_factor, 4),
            "p2_base_multiplier": round(p2_base_multiplier, 4),
            "reason": (
                f"P3[Kelly={kelly_factor:.2f}×ConLoss={consecutive_loss_factor:.2f}"
                f"×Hex={hexagram_factor:.2f}×VolRF={vol_regime_factor:.2f}"
                f"=×{p2_base_multiplier:.2f}] "
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
                      base_tp_roi: float = 0.0,
                      regime_pred: str = None,
                      regime_multipliers: Dict = None) -> TradeRecord:
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
            regime_pred=regime_pred,
            regime_multipliers=regime_multipliers,
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
