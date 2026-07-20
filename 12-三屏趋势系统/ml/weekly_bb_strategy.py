"""v3.9 周线布林带 + 双底确认

最后的尝试：用周线级别布林带，减少日线噪音。
结合双底确认，在周线级别寻找抄底时机。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class WeeklyBBDipStrategy(EnhancedMA200Strategy):
    """v3.9 周线布林带抄底"""

    def __init__(
        self,
        # 基础参数
        ma_period: int = 200,
        slope_period: int = 5,
        max_position: float = 1.0,
        warmup_periods: int = 250,
        symbol: str = "BTC",
        is_btc: bool = True,
        btc_prices: pd.DataFrame = None,
        # 抄底参数
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.8,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        # 周线布林带
        weekly_bb_period: int = 20,
        weekly_bb_std: float = 2.0,
        weekly_bb_lower_add: float = 0.10,  # 周线触及下轨加10%
        # 双底（日线）
        use_db: bool = True,
        db_lookback: int = 60,
        db_swing_window: int = 5,
        db_min_depth_pct: float = 0.08,
        db_max_low_diff_pct: float = 0.05,
        db_neckline_break_pct: float = 0.02,
        db_confirm_days: int = 3,
        db_boost_pct: float = 0.10,  # 双底确认加10%
        # 做空
        bear_short_level1_pct: float = 0.0,
        bear_short_level2_pct: float = 0.6,
        # v2其他
        fib_take_profit: bool = True,
        fib_levels: list = None,
        alt_bear_no_trade: bool = True,
    ):
        super().__init__(
            ma_period=ma_period,
            slope_period=slope_period,
            max_position=max_position,
            warmup_periods=warmup_periods,
            symbol=symbol,
            is_btc=is_btc,
            btc_prices=btc_prices,
            weekly_ma200_dip_buy=weekly_ma200_dip_buy,
            dip_buy_max_position=dip_buy_max_position,
            dip_buy_levels=dip_buy_levels,
            dip_buy_step_pct=dip_buy_step_pct,
            bear_short_level1_pct=bear_short_level1_pct,
            bear_short_level2_pct=bear_short_level2_pct,
            fib_take_profit=fib_take_profit,
            fib_levels=fib_levels,
            alt_bear_no_trade=alt_bear_no_trade,
        )
        self.name = "weekly_bb_v39"

        self.weekly_bb_period = weekly_bb_period
        self.weekly_bb_std = weekly_bb_std
        self.weekly_bb_lower_add = weekly_bb_lower_add

        self.use_db = use_db
        self.db_lookback = db_lookback
        self.db_swing_window = db_swing_window
        self.db_min_depth_pct = db_min_depth_pct
        self.db_max_low_diff_pct = db_max_low_diff_pct
        self.db_neckline_break_pct = db_neckline_break_pct
        self.db_confirm_days = db_confirm_days
        self.db_boost_pct = db_boost_pct

        self.stats.update({
            "weekly_bb_add_days": 0,
            "db_detected_days": 0,
            "db_confirmed_days": 0,
            "db_failed_days": 0,
        })

    def _compute_weekly_bb(self, prices: pd.DataFrame) -> tuple:
        """计算周线布林带"""
        # 转周线
        weekly = prices.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        n = len(weekly)
        upper = np.full(n, np.nan)
        mid = np.full(n, np.nan)
        lower = np.full(n, np.nan)

        close_w = weekly["close"].values
        for i in range(self.weekly_bb_period - 1, n):
            window = close_w[i - self.weekly_bb_period + 1:i + 1]
            m = np.mean(window)
            s = np.std(window)
            mid[i] = m
            upper[i] = m + self.weekly_bb_std * s
            lower[i] = m - self.weekly_bb_std * s

        # 映射回日线
        daily_lower = np.full(len(prices), np.nan)
        weekly_idx = 0
        for i, date in enumerate(prices.index):
            # 找到对应的周线
            while weekly_idx < n - 1 and weekly.index[weekly_idx + 1] <= date:
                weekly_idx += 1
            if weekly_idx < n and not np.isnan(lower[weekly_idx]):
                daily_lower[i] = lower[weekly_idx]

        return daily_lower

    def _find_swing_lows(self, low, start, end):
        w = self.db_swing_window
        swing_lows = []
        for i in range(start + w, end - w + 1):
            left = low[i - w:i]
            right = low[i + 1:i + w + 1]
            if low[i] < left.min() and low[i] <= right.min():
                swing_lows.append((i, low[i]))
        return swing_lows

    def _detect_double_bottom(self, low, close, i, last_breakout):
        if i < self.db_lookback:
            return False, False, 0.0

        start = i - self.db_lookback + 1
        end = i + 1

        swing_lows = self._find_swing_lows(low, start, end)
        if len(swing_lows) < 2:
            return False, False, 0.0

        sorted_by_price = sorted(swing_lows, key=lambda x: x[1])
        idx1, price1 = sorted_by_price[0]

        candidates = [
            (idx, p) for idx, p in swing_lows
            if abs(idx - idx1) >= 20 and abs(p - price1) / price1 < self.db_max_low_diff_pct * 3
        ]
        if not candidates:
            return False, False, 0.0

        idx2, price2 = min(candidates, key=lambda x: x[1])
        if idx1 > idx2:
            idx1, idx2 = idx2, idx1
            price1, price2 = price2, price1

        if idx2 - idx1 < 20:
            return False, False, 0.0

        window_high = low[start:end].max()
        depth = (window_high - min(price1, price2)) / window_high
        if depth < self.db_min_depth_pct:
            return False, False, 0.0

        if abs(price1 - price2) / max(price1, price2) > self.db_max_low_diff_pct:
            return False, False, 0.0

        right_higher = price2 >= price1 * (1 - self.db_max_low_diff_pct * 0.5)

        mid_segment = low[idx1 + 1:idx2]
        if len(mid_segment) < 2:
            return False, False, 0.0
        neckline = mid_segment.max()

        if neckline < min(price1, price2) * (1 + self.db_min_depth_pct * 0.5):
            return False, False, 0.0

        if close[i] <= neckline * (1 + self.db_neckline_break_pct):
            return False, False, 0.0

        if last_breakout >= 0 and (i - last_breakout) < 5:
            if i - last_breakout >= self.db_confirm_days:
                hold_above = True
                for j in range(last_breakout, min(last_breakout + self.db_confirm_days, i + 1)):
                    if close[j] < neckline:
                        hold_above = False
                        break
                if hold_above and right_higher:
                    return False, True, neckline
            return False, False, 0.0

        return True, False, neckline

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values
        low = prices["low"].values

        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values

        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100

        weekly_ma200 = self._compute_weekly_ma200(prices) if (self.is_btc and self.weekly_ma200_dip_buy) else None
        btc_regime = self._compute_btc_regime() if (not self.is_btc and self.alt_bear_no_trade) else None

        weekly_bb_lower = self._compute_weekly_bb(prices)

        last_state = "init"
        short_entry_price = None

        db_confirmed = False
        db_breakout_idx = -1
        db_neckline = 0.0

        last_wbb_idx = -100

        for i in range(self.warmup_periods, n):
            if np.isnan(ma[i]) or ma[i] <= 0:
                positions[i] = 0.0
                continue

            price_above = close[i] > ma[i]
            slope_pos = ma_slope[i] > 0
            slope_neg = ma_slope[i] < 0

            current_state = "sideways"
            target_pos = 0.0

            if self.is_btc:
                base_dip_pos = 0.0
                if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                    weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                    if weekly_below_pct > 0:
                        levels_filled = min(
                            int(weekly_below_pct / self.dip_buy_step_pct),
                            self.dip_buy_levels
                        )
                        if levels_filled > 0:
                            base_dip_pos = (levels_filled / self.dip_buy_levels) * self.dip_buy_max_position

                if price_above and slope_pos:
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None
                    db_confirmed = False
                    db_neckline = 0.0

                elif not price_above:
                    if base_dip_pos > 0:
                        current_state = "dip_buy"
                        short_entry_price = None
                        extra = 0.0

                        # 周线布林带下轨加仓
                        if not np.isnan(weekly_bb_lower[i]) and close[i] <= weekly_bb_lower[i]:
                            if (i - last_wbb_idx) >= 5:  # 至少间隔5天
                                extra += self.weekly_bb_lower_add
                                self.stats["weekly_bb_add_days"] += 1
                                last_wbb_idx = i

                        # 双底检测
                        if self.use_db and not db_confirmed:
                            detected, confirmed, neckline = self._detect_double_bottom(low, close, i, db_breakout_idx)
                            if detected:
                                self.stats["db_detected_days"] += 1
                                db_breakout_idx = i
                                db_neckline = neckline
                            if confirmed:
                                db_confirmed = True
                                self.stats["db_confirmed_days"] += 1

                        if db_confirmed and db_neckline > 0:
                            if close[i] < db_neckline * 0.98:
                                db_confirmed = False
                                db_neckline = 0.0
                                self.stats["db_failed_days"] += 1
                            else:
                                extra += self.db_boost_pct

                        max_pos = self.dip_buy_max_position + self.weekly_bb_lower_add + self.db_boost_pct
                        target_pos = min(base_dip_pos + extra, max_pos)
                        self.stats["dip_buy_days"] += 1

                    else:
                        db_confirmed = False
                        db_neckline = 0.0

                        base_short = 0.0
                        if slope_neg:
                            base_short = self.bear_short_level2_pct
                            current_state = "bear_short_l2"
                            self.stats["bear_short_l2_days"] += 1
                        else:
                            current_state = "bear_short_l1"
                            self.stats["bear_short_l1_days"] += 1

                        if base_short > 0 and short_entry_price is None:
                            short_entry_price = close[i]

                        if base_short > 0 and short_entry_price is not None and self.fib_take_profit:
                            fib_pos = self._calc_fib_tp_position(
                                close[i], short_entry_price, True, base_short
                            )
                            if fib_pos < base_short:
                                self.stats["fib_tp_days"] += 1
                            target_pos = -fib_pos
                        else:
                            target_pos = -base_short

                else:
                    if base_dip_pos > 0:
                        current_state = "dip_buy"
                        extra = 0.0
                        if db_confirmed and db_neckline > 0:
                            if close[i] < db_neckline * 0.98:
                                db_confirmed = False
                                db_neckline = 0.0
                                self.stats["db_failed_days"] += 1
                            else:
                                extra += self.db_boost_pct
                        target_pos = min(base_dip_pos + extra, self.dip_buy_max_position + self.db_boost_pct)
                        self.stats["dip_buy_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        db_confirmed = False
                        db_neckline = 0.0

            else:
                if self.alt_bear_no_trade:
                    btc_in_bull = False
                    if btc_regime is not None and i < len(btc_regime):
                        btc_in_bull = btc_regime[i] == "bull"
                    if price_above and slope_pos and btc_in_bull:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    else:
                        current_state = "bear_flat"
                        target_pos = 0.0
                        self.stats["bear_flat_days"] += 1
                else:
                    if price_above and slope_pos:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    elif not price_above and slope_neg:
                        current_state = "bear_short_l1"
                        target_pos = -self.bear_short_level1_pct
                        self.stats["bear_short_l1_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1

            positions[i] = target_pos
            if current_state != last_state and last_state != "init":
                self.stats["trend_switches"] += 1
            last_state = current_state

        return pd.Series(positions, index=prices.index, name="position")


if __name__ == "__main__":
    import json
    from ml.scenario_backtest_engine import ScenarioBacktestEngine

    with open("data/historical/BTC_1D_730d.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )

    engine = ScenarioBacktestEngine()

    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v39_v2")

    so = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    so_r = engine.run_scenario_backtest(prices, so, "so", symbol="BTC", experiment_name="v39_so")

    configs = [
        ("v3.9默认", {"weekly_bb_period": 20, "weekly_bb_std": 2.0, "weekly_bb_lower_add": 0.10, "db_boost_pct": 0.10}),
        ("周线BB10/1.5", {"weekly_bb_period": 10, "weekly_bb_std": 1.5, "weekly_bb_lower_add": 0.10, "db_boost_pct": 0.10}),
        ("周线BB30/2", {"weekly_bb_period": 30, "weekly_bb_std": 2.0, "weekly_bb_lower_add": 0.10, "db_boost_pct": 0.10}),
        ("加仓20%", {"weekly_bb_period": 20, "weekly_bb_std": 2.0, "weekly_bb_lower_add": 0.20, "db_boost_pct": 0.10}),
        ("无双底", {"weekly_bb_period": 20, "weekly_bb_std": 2.0, "weekly_bb_lower_add": 0.10, "db_boost_pct": 0.0, "use_db": False}),
        ("无周线BB", {"weekly_bb_period": 20, "weekly_bb_std": 2.0, "weekly_bb_lower_add": 0.0, "db_boost_pct": 0.10}),
    ]

    print(f"v2: 收益 {v2_r.overall_total_return:.1%}, 评分 {v2_r.composite_score:.3f}")
    print(f"做空优化: 收益 {so_r.overall_total_return:.1%}, 评分 {so_r.composite_score:.3f}")
    print()
    print(f"{'配置':<18} {'总收益':>10} {'夏普':>8} {'评分':>8} {'周线BB':>6} {'双底':>4} {'失败':>4}")
    print("-" * 65)

    for name, kwargs in configs:
        strategy = WeeklyBBDipStrategy(is_btc=True, **kwargs)
        result = engine.run_scenario_backtest(prices, strategy, name, symbol="BTC", experiment_name=f"v39_{name}")
        stats = strategy.get_stats()
        marker = " ⭐" if result.composite_score > so_r.composite_score else ""
        print(
            f"{name:<18} "
            f"{result.overall_total_return:>10.1%} "
            f"{result.overall_sharpe:>8.3f} "
            f"{result.composite_score:>8.3f}{marker} "
            f"{stats.get('weekly_bb_add_days', 0):>6} "
            f"{stats.get('db_confirmed_days', 0):>4} "
            f"{stats.get('db_failed_days', 0):>4}"
        )
