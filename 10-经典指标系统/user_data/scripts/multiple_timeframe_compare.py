"""
多周期回测对比脚本
将 5m 数据聚合为 30m 和 1h，然后与 5m 一起跑完整对比

运行方式:
    source .venv/bin/activate
    python user_data/scripts/multiple_timeframe_compare.py
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import talib.abstract as ta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA_DIR = os.path.join(ROOT, "user_data", "data", "hyperliquid", "futures")
OUT_DIR = os.path.join(ROOT, "user_data", "data", "aggregated")
AGG_DIR = os.path.join(OUT_DIR, "futures")

INITIAL_CAPITAL = 1000.0
FEE_RATE = 0.0004
SLIPPAGE = 0.0005
MAX_POSITION_PER_TRADE = 150.0
COOLDOWN_BARS = 3

# ===========================================================================
# 数据加载 & 聚合
# ===========================================================================

def load_bars(symbol: str, tf: str = "5m") -> pd.DataFrame:
    """加载指定周期的数据"""
    if tf == "5m":
        path = os.path.join(DATA_DIR, f"{symbol}-5m-futures.json")
    else:
        path = os.path.join(AGG_DIR, f"{symbol}-{tf}-futures.json")

    if not os.path.exists(path):
        raise FileNotFoundError(f"数据不存在: {path}")

    with open(path, "r") as f:
        raw = json.load(f)
    df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], unit="ms", utc=True)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def aggregate_bars(df_5m: pd.DataFrame, tf: str) -> pd.DataFrame:
    """将 5m 数据聚合为指定周期"""
    if tf.endswith("m"):
        minutes = int(tf.replace("m", ""))
        rule = f"{minutes}min"
    elif tf.endswith("h"):
        minutes = int(tf.replace("h", "")) * 60
        rule = f"{minutes}min"
    else:
        raise ValueError(f"Unsupported timeframe: {tf}")

    agg = df_5m.set_index("date").resample(rule, origin="start").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg


def ensure_aggregated_data(symbols: List[str], timeframes: List[str] = ["30m", "1h"]):
    """确保聚合数据存在"""
    os.makedirs(AGG_DIR, exist_ok=True)

    for symbol in symbols:
        df_5m = load_bars(symbol, "5m")
        for tf in timeframes:
            out_path = os.path.join(AGG_DIR, f"{symbol}-{tf}-futures.json")
            if os.path.exists(out_path):
                continue
            df_agg = aggregate_bars(df_5m, tf)
            # 转为毫秒时间戳 (freqtrade 格式)
            records = [
                [int(row["date"].timestamp() * 1000),
                 float(row["open"]), float(row["high"]),
                 float(row["low"]), float(row["close"]), float(row["volume"])]
                for _, row in df_agg.iterrows()
            ]
            with open(out_path, "w") as f:
                json.dump(records, f)
            print(f"  [生成] {symbol} {tf}: {len(records)} bars")


# ===========================================================================
# 指标 & 信号生成
# ===========================================================================

def add_indicators(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = ta.RSI(df, timeperiod=14)

    # EMA 参数随周期调整
    if tf == "5m":
        ema_fast_p, ema_slow_p, ema_trend_p = 10, 30, 50
    elif tf == "30m":
        ema_fast_p, ema_slow_p, ema_trend_p = 8, 20, 40
    else:  # 1h
        ema_fast_p, ema_slow_p, ema_trend_p = 6, 15, 30

    df["ema_fast"] = ta.EMA(df, timeperiod=ema_fast_p)
    df["ema_slow"] = ta.EMA(df, timeperiod=ema_slow_p)
    df["ema_trend"] = ta.EMA(df, timeperiod=ema_trend_p)
    df["adx"] = ta.ADX(df, timeperiod=14)
    df["atr"] = ta.ATR(df, timeperiod=14)

    bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
    df["bb_upper"] = bb["upperband"]
    df["bb_middle"] = bb["middleband"]
    df["bb_lower"] = bb["lowerband"]
    df["bb_percent"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    df["volume_mean"] = df["volume"].rolling(20).mean()
    df["tema"] = ta.TEMA(df, timeperiod=9)
    df["sar"] = ta.SAR(df)

    # 4h 波动率（用当前周期聚合近似，1h: 4 bars, 30m: 8 bars）
    if tf == "1h":
        roll = 4
    elif tf == "30m":
        roll = 8
    else:
        roll = 48
    high_r = df["high"].rolling(roll).max()
    low_r = df["low"].rolling(roll).min()
    df["btc_volatility_4h"] = (high_r - low_r) / df["close"]

    return df


@dataclass
class Signal:
    bar_idx: int
    direction: str
    reason: str
    stop_loss: float
    take_profit: Optional[float] = None
    trail_atr: Optional[float] = None


def gen_bot2(df: pd.DataFrame, cfg: Dict) -> List[Signal]:
    """Bot2StrategyTrend 信号"""
    signals = []
    n = len(df)
    warm = 200 if len(df) > 1000 else len(df) // 5

    for i in range(warm, n):
        row = df.iloc[i]
        price = float(row["close"])

        regime = 1 if (pd.notna(row["btc_volatility_4h"]) and
                       row["btc_volatility_4h"] >= cfg["vol_threshold"]) else 0

        lookback = cfg["lookback"]
        max_high = float(df["high"].iloc[max(0, i - lookback):i].max())
        recent_pump = (price / max_high) - 1 if max_high > 0 else 0
        adx_slope = float(row["adx"] - df["adx"].iloc[i - 3]) if i >= 3 else 0

        chase = (
            price > row["ema_trend"] * (1 + cfg["anti_dev"]) or
            float(row["rsi"]) >= cfg["anti_rsi"] or
            (pd.notna(row["bb_percent"]) and float(row["bb_percent"]) >= cfg["anti_bb"]) or
            adx_slope < cfg["anti_adx_slope"] or
            recent_pump >= cfg["anti_pump"]
        )

        mr1 = price < row["bb_lower"]
        mr2 = float(row["rsi"]) < cfg["rsi_range"]
        mr3 = price < row["ema_fast"] * (1 - cfg["mr_dev"])
        mr_score = int(mr1) + int(mr2) + int(mr3)

        t1 = (price > row["ema_fast"] and
              float(row["ema_fast"]) > float(row["ema_slow"]) > float(row["ema_trend"]))
        t2 = float(row["adx"]) > cfg["adx_trend"]
        t3 = float(row["volume"]) > float(row["volume_mean"]) * cfg["vol_factor"] if pd.notna(row["volume_mean"]) else False
        trend_score = int(t1) + int(t2) + int(t3)

        entry = False
        if regime == 0 and mr_score >= 2 and float(row["volume"]) > 0:
            entry, reason = True, f"mr={mr_score}"
        elif regime == 1 and trend_score >= 2 and float(row["volume"]) > 0:
            entry, reason = True, f"tr={trend_score}"

        if entry and not chase:
            sl = price * (1 + cfg["stoploss"])
            tp = price * (1 + cfg["tp_ratio"])
            signals.append(Signal(i, "long", reason, sl, tp))
    return signals


def gen_simple(df: pd.DataFrame, cfg: Dict) -> List[Signal]:
    """SimpleStrategy RSI+TEMA 均值回归信号"""
    signals = []
    n = len(df)
    warm = 100

    for i in range(warm, n):
        row = df.iloc[i]
        price = float(row["close"])
        rsi = float(row["rsi"]) if pd.notna(row["rsi"]) else 50
        tema = float(row["tema"]) if pd.notna(row["tema"]) else price
        bb_mid = float(row["bb_middle"]) if pd.notna(row["bb_middle"]) else price
        tema_prev = float(df["tema"].iloc[i - 1]) if i >= 1 and pd.notna(df["tema"].iloc[i - 1]) else tema
        atr = float(row["atr"]) if pd.notna(row["atr"]) and float(row["atr"]) > 0 else price * 0.01
        vol = float(row["volume"])
        vol_mean = float(row["volume_mean"]) if pd.notna(row["volume_mean"]) else 0

        loose_buy = min(cfg["buy_rsi"] + 4, 35)
        loose_sell = max(cfg["sell_rsi"] - 4, 65)

        # Long
        deep = (rsi < cfg["buy_rsi"] and tema <= bb_mid and tema > tema_prev and vol > vol_mean)
        mild = (rsi < loose_buy and tema <= bb_mid and vol > vol_mean * 0.5)
        if deep or mild:
            sl = price - atr * cfg["atr_mult"]
            tp = price + atr * cfg["atr_mult"] * 1.5
            signals.append(Signal(i, "long", f"rsi={rsi:.0f}", sl, tp, atr * cfg["trail_mult"]))
            continue

        # Short
        if cfg.get("allow_short", True):
            deep_s = (rsi > cfg["sell_rsi"] and tema >= bb_mid and tema < tema_prev and vol > vol_mean)
            mild_s = (rsi > loose_sell and tema >= bb_mid and vol > vol_mean * 0.5)
            if deep_s or mild_s:
                sl = price + atr * cfg["atr_mult"]
                tp = price - atr * cfg["atr_mult"] * 1.5
                signals.append(Signal(i, "short", f"rsi={rsi:.0f}", sl, tp, atr * cfg["trail_mult"]))
    return signals


def gen_ott(df: pd.DataFrame, cfg: Dict) -> List[Signal]:
    """OTT 趋势信号"""
    signals = []
    n = len(df)
    warm = 100

    for i in range(warm, n):
        row = df.iloc[i]
        price = float(row["close"])
        ema_s = float(row["ema_slow"]) if pd.notna(row["ema_slow"]) else price
        ema_t = float(row["ema_trend"]) if pd.notna(row["ema_trend"]) else price
        adx = float(row["adx"]) if pd.notna(row["adx"]) else 0
        atr = float(row["atr"]) if pd.notna(row["atr"]) and float(row["atr"]) > 0 else price * 0.01
        prev_p = float(df["close"].iloc[i - 1])
        prev_s = float(df["ema_slow"].iloc[i - 1]) if pd.notna(df["ema_slow"].iloc[i - 1]) else price

        long_cond = (price > ema_s and ema_s > ema_t and adx > cfg["adx_min"] and prev_p <= prev_s)
        short_cond = (cfg.get("allow_short", True) and price < ema_s and
                      ema_s < ema_t and adx > cfg["adx_min"] and prev_p >= prev_s)

        if long_cond:
            sl = price * (1 + cfg["stoploss"])
            tp = price * (1 + cfg["tp_0"])
            signals.append(Signal(i, "long", f"adx={adx:.0f}", sl, tp, atr))
        elif short_cond:
            sl = price * (1 - cfg["stoploss"])
            tp = price * (1 - cfg["tp_60"])
            signals.append(Signal(i, "short", f"adx={adx:.0f}", sl, tp, atr))
    return signals


# ===========================================================================
# 回测引擎
# ===========================================================================

@dataclass
class Trade:
    direction: str
    entry_price: float
    entry_idx: int
    exit_price: float
    exit_idx: int
    exit_reason: str
    pnl: float
    pnl_pct: float


@dataclass
class Result:
    trades: List[Trade]
    equity_curve: List[float]
    equity_dates: List[str]

    @property
    def total(self): return len(self.trades)
    @property
    def wins(self): return sum(1 for t in self.trades if t.pnl > 0)
    @property
    def losses(self): return sum(1 for t in self.trades if t.pnl <= 0)
    @property
    def win_rate(self): return self.wins / self.total if self.total > 0 else 0
    @property
    def total_pnl(self): return sum(t.pnl for t in self.trades)
    @property
    def avg_win(self):
        w = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(w)/len(w) if w else 0
    @property
    def avg_loss(self):
        l = [t.pnl for t in self.trades if t.pnl <= 0]
        return sum(l)/len(l) if l else 0
    @property
    def pf(self):
        g = sum(t.pnl for t in self.trades if t.pnl > 0)
        l = -sum(t.pnl for t in self.trades if t.pnl <= 0)
        return g/l if l > 0 else float("inf")
    @property
    def max_dd(self):
        if not self.equity_curve: return 0
        peak = np.maximum.accumulate(np.array(self.equity_curve))
        return float(((peak - np.array(self.equity_curve)) / peak).max()) * 100
    @property
    def ret(self):
        if not self.equity_curve: return 0
        return (self.equity_curve[-1] / self.equity_curve[0] - 1) * 100


class Engine:
    def __init__(self, df, initial=INITIAL_CAPITAL, max_cap=MAX_POSITION_PER_TRADE,
                 fee=FEE_RATE, slip=SLIPPAGE, cooldown=COOLDOWN_BARS):
        self.df = df
        self.initial = initial
        self.cap = initial
        self.max_cap = max_cap
        self.fee = fee
        self.slip = slip
        self.cooldown = cooldown
        self.pos = None
        self.trades = []
        self.last_entry = -9999
        self.equity = [initial]
        self.dates = []

    def _check_exit(self, pos, high, low, close):
        if pos.direction == "long":
            if low <= pos.sl: return pos.sl * (1 - self.slip), "sl"
            if high >= pos.tp: return pos.tp * (1 - self.slip), "tp"
        else:
            if high >= pos.sl: return pos.sl * (1 + self.slip), "sl"
            if low <= pos.tp: return pos.tp * (1 + self.slip), "tp"
        return None, None

    def _unreal(self, close):
        if not self.pos: return 0
        if self.pos.direction == "long":
            return (close - self.pos.ep) * self.pos.sz
        return (self.pos.ep - close) * self.pos.sz

    def run(self, signals):
        self.pos = None
        self.trades = []
        self.cap = self.initial
        self.last_entry = -9999
        self.equity = [self.initial]
        self.dates = []

        n = len(self.df)
        sig_idx = 0
        next_sig = signals[sig_idx] if signals else None

        for i in range(1, n):
            bar = self.df.iloc[i]
            hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])
            date_str = str(bar["date"])[:19]

            # 平仓检查
            if self.pos:
                xp, xr = self._check_exit(self.pos, hi, lo, cl)
                if xp is not None:
                    gross = self._unreal(xp)
                    fee = self.pos.ep * self.pos.sz * self.fee + xp * self.pos.sz * self.fee
                    net = gross - fee
                    pct = net / self.pos.cap
                    self.trades.append(Trade(self.pos.direction, self.pos.ep, self.pos.ei,
                                           xp, i, xr, net, pct))
                    self.cap += net
                    self.pos = None

            # 入场
            if not self.pos and next_sig and i >= next_sig.bar_idx:
                if i - self.last_entry >= self.cooldown:
                    ei = min(i + 1, n - 1)
                    eb = self.df.iloc[ei]
                    ep = float(eb["open"]) * (1 + (self.slip if next_sig.direction == "long" else -self.slip))
                    cap = min(self.max_cap, self.cap * 0.5)
                    sz = cap / ep
                    atr = float(self.df["atr"].iloc[ei]) if pd.notna(self.df["atr"].iloc[ei]) else ep * 0.01

                    if next_sig.direction == "long":
                        sl = min(next_sig.stop_loss, ep - atr * 2)
                    else:
                        sl = max(next_sig.stop_loss, ep + atr * 2)
                    tp = next_sig.take_profit if next_sig.take_profit else (
                        ep * (1 + 0.05) if next_sig.direction == "long" else ep * (1 - 0.05))

                    self.pos = type("Pos", (), {
                        "direction": next_sig.direction, "ep": ep, "ei": ei, "sz": sz,
                        "cap": cap, "sl": sl, "tp": tp, "atr": next_sig.trail_atr or atr,
                        "best": ep
                    })()
                    self.last_entry = ei

                sig_idx += 1
                next_sig = signals[sig_idx] if sig_idx < len(signals) else None

            self.equity.append(self.cap + (self._unreal(cl) if self.pos else 0))
            self.dates.append(date_str)

        if self.pos:
            lc = float(self.df["close"].iloc[-1])
            gross = self._unreal(lc)
            fee = self.pos.ep * self.pos.sz * self.fee + lc * self.pos.sz * self.fee
            self.trades.append(Trade(self.pos.direction, self.pos.ep, self.pos.ei,
                                    lc, n - 1, "eod", gross - fee, (gross - fee) / self.pos.cap))

        return Result(self.trades, self.equity, self.dates)


# ===========================================================================
# 策略配置组（每周期可能有不同参数）
# ===========================================================================

def get_configs(tf: str) -> Dict[str, Tuple[str, Dict]]:
    """获取各策略的配置，参数随周期调整"""
    if tf == "5m":
        return {
            "Bot2原始":      ("bot2", dict(stoploss=-0.028, tp_ratio=0.05, vol_threshold=0.02,
                                          rsi_range=35, adx_trend=25, vol_factor=1.2,
                                          mr_dev=0.015, lookback=20,
                                          anti_dev=0.08, anti_rsi=78, anti_bb=0.95,
                                          anti_adx_slope=-0.5, anti_pump=0.05)),
            "Bot2优化(-8%SL)":("bot2", dict(stoploss=-0.08, tp_ratio=0.15, vol_threshold=0.025,
                                            rsi_range=32, adx_trend=28, vol_factor=1.3,
                                            mr_dev=0.02, lookback=20,
                                            anti_dev=0.10, anti_rsi=82, anti_bb=0.98,
                                            anti_adx_slope=-0.3, anti_pump=0.04)),
            "Simple多空":    ("simple", dict(buy_rsi=27, sell_rsi=72, atr_mult=2.0,
                                             trail_mult=1.5, allow_short=True)),
            "Simple仅做多":  ("simple", dict(buy_rsi=27, sell_rsi=72, atr_mult=2.5,
                                             trail_mult=2.0, allow_short=False)),
            "Simple收紧RSI": ("simple", dict(buy_rsi=22, sell_rsi=75, atr_mult=2.0,
                                             trail_mult=1.8, allow_short=True)),
            "OTT原始":       ("ott", dict(stoploss=-0.15, tp_0=0.20, tp_60=0.12,
                                          adx_min=20, allow_short=True)),
            "OTT收紧SL":     ("ott", dict(stoploss=-0.08, tp_0=0.12, tp_60=0.06,
                                          adx_min=25, allow_short=True)),
            "OTT仅做多":     ("ott", dict(stoploss=-0.10, tp_0=0.15, tp_60=0.08,
                                          adx_min=22, allow_short=False)),
        }
    elif tf == "30m":
        # 30m: 波动加大，止损适当放宽，止盈提高
        return {
            "Bot2原始":      ("bot2", dict(stoploss=-0.05, tp_ratio=0.08, vol_threshold=0.015,
                                          rsi_range=35, adx_trend=25, vol_factor=1.2,
                                          mr_dev=0.015, lookback=20,
                                          anti_dev=0.08, anti_rsi=78, anti_bb=0.95,
                                          anti_adx_slope=-0.5, anti_pump=0.05)),
            "Bot2优化(-10%SL)":("bot2", dict(stoploss=-0.10, tp_ratio=0.18, vol_threshold=0.02,
                                             rsi_range=30, adx_trend=28, vol_factor=1.3,
                                             mr_dev=0.02, lookback=20,
                                             anti_dev=0.10, anti_rsi=82, anti_bb=0.98,
                                             anti_adx_slope=-0.3, anti_pump=0.04)),
            "Simple多空":    ("simple", dict(buy_rsi=28, sell_rsi=72, atr_mult=2.0,
                                             trail_mult=1.5, allow_short=True)),
            "Simple仅做多":  ("simple", dict(buy_rsi=28, sell_rsi=72, atr_mult=2.5,
                                             trail_mult=2.0, allow_short=False)),
            "Simple收紧RSI": ("simple", dict(buy_rsi=25, sell_rsi=74, atr_mult=2.0,
                                             trail_mult=1.8, allow_short=True)),
            "OTT原始":       ("ott", dict(stoploss=-0.12, tp_0=0.18, tp_60=0.10,
                                          adx_min=20, allow_short=True)),
            "OTT收紧SL":     ("ott", dict(stoploss=-0.08, tp_0=0.12, tp_60=0.06,
                                          adx_min=25, allow_short=True)),
            "OTT仅做多":     ("ott", dict(stoploss=-0.10, tp_0=0.15, tp_60=0.08,
                                          adx_min=22, allow_short=False)),
        }
    else:  # 1h
        # 1h: 止损进一步放宽，信号更少但质量更高
        return {
            "Bot2原始":      ("bot2", dict(stoploss=-0.08, tp_ratio=0.12, vol_threshold=0.01,
                                          rsi_range=35, adx_trend=22, vol_factor=1.1,
                                          mr_dev=0.015, lookback=12,
                                          anti_dev=0.08, anti_rsi=76, anti_bb=0.95,
                                          anti_adx_slope=-0.5, anti_pump=0.05)),
            "Bot2优化(-15%SL)":("bot2", dict(stoploss=-0.15, tp_ratio=0.20, vol_threshold=0.015,
                                             rsi_range=30, adx_trend=25, vol_factor=1.2,
                                             mr_dev=0.02, lookback=12,
                                             anti_dev=0.10, anti_rsi=80, anti_bb=0.98,
                                             anti_adx_slope=-0.3, anti_pump=0.04)),
            "Simple多空":    ("simple", dict(buy_rsi=30, sell_rsi=70, atr_mult=2.0,
                                             trail_mult=1.5, allow_short=True)),
            "Simple仅做多":  ("simple", dict(buy_rsi=30, sell_rsi=70, atr_mult=2.5,
                                             trail_mult=2.0, allow_short=False)),
            "Simple收紧RSI": ("simple", dict(buy_rsi=28, sell_rsi=72, atr_mult=2.0,
                                             trail_mult=1.8, allow_short=True)),
            "OTT原始":       ("ott", dict(stoploss=-0.10, tp_0=0.15, tp_60=0.08,
                                          adx_min=18, allow_short=True)),
            "OTT收紧SL":     ("ott", dict(stoploss=-0.06, tp_0=0.10, tp_60=0.05,
                                          adx_min=22, allow_short=True)),
            "OTT仅做多":     ("ott", dict(stoploss=-0.08, tp_0=0.12, tp_60=0.06,
                                          adx_min=20, allow_short=False)),
        }


# ===========================================================================
# 主流程
# ===========================================================================

def run_comparison(symbol: str, tf: str, configs: Dict):
    df = load_bars(symbol, tf)
    df = add_indicators(df, tf)
    results = {}
    for name, (typ, cfg) in configs.items():
        if typ == "bot2":
            signals = gen_bot2(df, cfg)
        elif typ == "simple":
            signals = gen_simple(df, cfg)
        else:
            signals = gen_ott(df, cfg)

        engine = Engine(df)
        r = engine.run(signals)
        results[name] = r
    return results


def print_summary_table(all_results: Dict[str, Dict[str, Result]]):
    """跨周期汇总表"""
    print("\n" + "="*120)
    print("  跨周期汇总对比（BTC/ETH/SOL 三币种平均）")
    print("="*120)

    # 按策略分组
    by_strat: Dict[str, dict] = {}
    for tf_key, tf_results in all_results.items():
        for name, r in tf_results.items():
            if name not in by_strat:
                by_strat[name] = {"trades": 0, "pnl": 0.0, "wr": 0.0,
                                  "pf": 0.0, "dd": 0.0, "ret": 0.0, "n": 0}
            agg = by_strat[name]
            agg["trades"] += r.total
            agg["pnl"] += r.total_pnl
            agg["wr"] += r.win_rate * 100
            pf_val = min(r.pf, 10.0) if r.pf != float("inf") else 10.0
            agg["pf"] += pf_val
            agg["dd"] += r.max_dd
            agg["ret"] += r.ret
            agg["n"] += 1

    rows = []
    for name, agg in by_strat.items():
        if agg["n"] == 0:
            continue
        n = agg["n"]
        rows.append({
            "策略": name,
            "总交易": str(agg["trades"]),
            "平均胜率%": f"{agg['wr']/n:.1f}",
            "总盈亏$": f"{agg['pnl']/n:+.1f}",
            "平均PF": f"{agg['pf']/n:.2f}",
            "平均回撤%": f"{agg['dd']/n:.1f}",
            "平均收益%": f"{agg['ret']/n:+.1f}",
        })

    rows.sort(key=lambda r: float(r["总盈亏$"]), reverse=True)
    if not rows:
        return

    keys = list(rows[0].keys())
    widths = {k: max(len(k), max(len(r[k]) for r in rows)) for k in keys}
    sep = "-+-".join("-" * widths[k] for k in keys)
    print(f"\n  {' | '.join(k.ljust(widths[k]) for k in keys)}")
    print(f"  {sep}")
    for row in rows:
        print(f"  {' | '.join(row[k].ljust(widths[k]) for k in keys)}")


def print_tf_detail(tf_results: Dict[str, Result], tf: str, symbol: str):
    """打印单个周期+币种的详细结果"""
    print(f"\n{'─'*100}")
    print(f"  [{tf}] {symbol}")
    print(f"{'─'*100}")

    # 打印一行汇总
    for name, r in tf_results.items():
        if r.total == 0:
            print(f"  {name:<25} 交易=0")
            continue
        pf = f"{r.pf:.2f}" if r.pf != float("inf") else "inf"
        dd = f"{r.max_dd:.1f}"
        ret = f"{r.ret:+.1f}"
        wr = f"{r.win_rate*100:.0f}%"
        pnl = f"{r.total_pnl:+.1f}"
        trade_info = f"#{r.total} {wr} {pnl} PF={pf} DD={dd}% ret={ret}%"
        print(f"  {name:<25} {trade_info}")


def main():
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    timeframes = ["5m", "30m", "1h"]

    print("\n" + "="*100)
    print("  多周期策略对比回测 (5m vs 30m vs 1h)")
    print(f"  初始资金: ${INITIAL_CAPITAL} | 单笔最大保证金: ${MAX_POSITION_PER_TRADE}")
    print("="*100)

    # 1. 确保聚合数据存在
    print("\n[准备数据]")
    ensure_aggregated_data(symbols, ["30m", "1h"])

    all_results: Dict[str, Dict[str, Result]] = {}

    for tf in timeframes:
        for symbol in symbols:
            print(f"\n[处理] {tf} - {symbol}")
            try:
                configs = get_configs(tf)
                results = run_comparison(symbol, tf, configs)
                print_tf_detail(results, tf, symbol)
                if tf not in all_results:
                    all_results[tf] = {}
                for name, r in results.items():
                    key = f"{symbol}_{name}"
                    if key not in all_results[tf]:
                        all_results[tf][key] = r
            except FileNotFoundError as e:
                print(f"  [跳过] {e}")

    # 2. 跨周期汇总
    print_summary_table(all_results)

    # 3. 周期对比表格
    print("\n\n" + "="*120)
    print("  周期 vs 策略 交叉对比（BTC 平均）")
    print("="*120)

    # 收集 BTC 各周期各策略的关键指标
    period_summary: Dict[str, Dict[str, dict]] = {}
    for tf in timeframes:
        for symbol in symbols:
            if symbol != "BTC_USDT":
                continue
            try:
                configs = get_configs(tf)
                results = run_comparison(symbol, tf, configs)
                period_summary[tf] = {}
                for name, r in results.items():
                    period_summary[tf][name] = {
                        "total": r.total,
                        "wr": r.win_rate * 100,
                        "pnl": r.total_pnl,
                        "pf": r.pf if r.pf != float("inf") else 99,
                        "dd": r.max_dd,
                        "ret": r.ret,
                    }
            except FileNotFoundError:
                pass

    if period_summary:
        tf_list = [k for k in period_summary if k in ["5m", "30m", "1h"]]
        strat_names = list(next(iter(period_summary.values())).keys())

        header = ["策略"] + [f"{tf}胜率" for tf in tf_list] + [f"{tf}盈亏" for tf in tf_list] + [f"{tf}PF" for tf in tf_list]
        widths = [max(len(h), max(len(str(
            period_summary.get(tf, {}).get(s, {}).get(k.replace(f"{tf}胜率", "wr").replace(f"{tf}盈亏", "pnl").replace(f"{tf}PF", "pf"), ""))) or ""
            for tf in tf_list
        )) for h, k in zip(header, ["策略"] + ["wr"] * len(tf_list) + ["pnl"] * len(tf_list) + ["pf"] * len(tf_list))]

        print(f"\n  {' | '.join(h.ljust(20) for h in header)}")
        print(f"  {'-+-'.join('-' * 20 for _ in header)}")
        for sname in strat_names:
            cells = [sname]
            for tf in tf_list:
                d = period_summary.get(tf, {}).get(sname, {})
                cells.append(f"{d.get('wr', 0):.0f}%" if d else "N/A")
            for tf in tf_list:
                d = period_summary.get(tf, {}).get(sname, {})
                cells.append(f"{d.get('pnl', 0):+.1f}" if d else "N/A")
            for tf in tf_list:
                d = period_summary.get(tf, {}).get(sname, {})
                cells.append(f"{d.get('pf', 0):.2f}" if d else "N/A")
            print(f"  {' | '.join(c.ljust(20) for c in cells)}")

    print("\n")


if __name__ == "__main__":
    main()
