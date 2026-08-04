"""比特币减半周期逃顶策略 v4

基于V3基线（做空优化），新增减半周期顶部逃顶机制：

【顶部逃顶优化 TOP_EXIT】
1. 减半周期锚定：比特币减半后12-18个月为顶部时间窗口
   - 减半后12个月开始进入顶部预警区，逐步减仓
   - 减半后15个月进入顶部高危区，加速减仓
   - 减半后18个月为顶部目标时间，清仓或极低仓位
2. 越高越卖：在顶部区域内，价格每创新高就卖出一部分
3. MA128破位卖出：有效跌破日线MA128后开始分批卖出
4. 反弹卖出：下跌趋势中出现反弹就卖出（逐批减仓）

比特币减半历史时间点：
- 2016-07-09 第2次减半
- 2020-05-11 第3次减半
- 2024-04-20 第4次减半
"""

import numpy as np
import pandas as pd


BTC_HALVING_DATES = [
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-20"),
]


class HalvingTopExitStrategy:
    """减半周期逃顶策略 - 基于V3基线优化顶部离场"""

    def __init__(
        self,
        ma_period: int = 200,
        ma128_period: int = 128,
        slope_period: int = 5,
        max_position: float = 1.0,
        warmup_periods: int = 250,
        symbol: str = "BTC",
        is_btc: bool = True,
        btc_prices: pd.DataFrame = None,
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.9,
        dip_buy_levels: int = 6,
        dip_buy_step_pct: float = 3.0,
        dip_buy_initial_pct: float = 0.1,
        dip_buy_end_on_ma200_breakout: bool = True,
        weekly_ma200_support_zone_pct: float = 5.0,
        use_halving_timing: bool = True,
        halving_warn_months: int = 12,
        halving_danger_months: int = 15,
        halving_peak_months: int = 18,
        halving_end_months: int = 24,
        halving_warn_min_position: float = 0.7,
        halving_danger_min_position: float = 0.3,
        halving_peak_min_position: float = 0.0,
        use_high_to_sell: bool = True,
        high_to_sell_step_pct: float = 5.0,
        high_to_sell_portion: float = 0.15,
        use_ma128_exit: bool = True,
        ma128_exit_levels: int = 4,
        ma128_exit_step_pct: float = 5.0,
        use_bounce_sell: bool = True,
        bounce_sell_pct_per_bounce: float = 0.25,
        bear_short_level1_pct: float = 0.0,
        bear_short_level2_pct: float = 0.6,
        fib_take_profit: bool = True,
        fib_levels: list = None,
        alt_bear_no_trade: bool = True,
    ):
        self.name = "halving_top_exit_v4"
        self.ma_period = ma_period
        self.ma128_period = ma128_period
        self.slope_period = slope_period
        self.max_position = max_position
        self.warmup_periods = warmup_periods
        self.symbol = symbol
        self.is_btc = is_btc
        self.btc_prices = btc_prices

        self.weekly_ma200_dip_buy = weekly_ma200_dip_buy
        self.dip_buy_max_position = dip_buy_max_position
        self.dip_buy_levels = dip_buy_levels
        self.dip_buy_step_pct = dip_buy_step_pct
        self.dip_buy_initial_pct = dip_buy_initial_pct
        self.dip_buy_end_on_ma200_breakout = dip_buy_end_on_ma200_breakout
        self.weekly_ma200_support_zone_pct = weekly_ma200_support_zone_pct

        self.use_halving_timing = use_halving_timing
        self.halving_warn_months = halving_warn_months
        self.halving_danger_months = halving_danger_months
        self.halving_peak_months = halving_peak_months
        self.halving_end_months = halving_end_months
        self.halving_warn_min_position = halving_warn_min_position
        self.halving_danger_min_position = halving_danger_min_position
        self.halving_peak_min_position = halving_peak_min_position

        self.use_high_to_sell = use_high_to_sell
        self.high_to_sell_step_pct = high_to_sell_step_pct
        self.high_to_sell_portion = high_to_sell_portion

        self.use_ma128_exit = use_ma128_exit
        self.ma128_exit_levels = ma128_exit_levels
        self.ma128_exit_step_pct = ma128_exit_step_pct

        self.use_bounce_sell = use_bounce_sell
        self.bounce_sell_pct_per_bounce = bounce_sell_pct_per_bounce

        self.bear_short_level1_pct = bear_short_level1_pct
        self.bear_short_level2_pct = bear_short_level2_pct
        self.fib_take_profit = fib_take_profit
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618]

        self.alt_bear_no_trade = alt_bear_no_trade

        self.stats = {
            "bull_days": 0,
            "bull_exit_days": 0,
            "bear_short_l1_days": 0,
            "bear_short_l2_days": 0,
            "bear_flat_days": 0,
            "sideways_days": 0,
            "dip_buy_days": 0,
            "dip_buy_end_days": 0,
            "fib_tp_days": 0,
            "ma128_exit_days": 0,
            "bounce_sell_days": 0,
            "halving_warn_days": 0,
            "halving_danger_days": 0,
            "halving_peak_days": 0,
            "high_to_sell_days": 0,
            "trend_switches": 0,
        }

    def _resample_to_weekly(self, prices: pd.DataFrame) -> pd.DataFrame:
        df = prices.copy()
        if "date" in df.columns:
            df = df.set_index("date")
        else:
            df.index = pd.to_datetime(df.index)
        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        return weekly

    def _compute_weekly_ma200(self, prices: pd.DataFrame) -> np.ndarray:
        weekly = self._resample_to_weekly(prices)
        weekly_close = weekly["close"].values
        if len(weekly_close) < 200:
            return np.full(len(prices), np.nan)
        weekly_ma200 = pd.Series(weekly_close).rolling(window=200, min_periods=200).mean().values
        daily_ma200 = np.full(len(prices), np.nan)
        weekly_idx = 0
        for i in range(len(prices)):
            current_date = prices.index[i]
            while weekly_idx < len(weekly) and weekly.index[weekly_idx] <= current_date:
                weekly_idx += 1
            if weekly_idx >= 200:
                daily_ma200[i] = weekly_ma200[weekly_idx - 1]
        return daily_ma200

    def _compute_btc_regime(self) -> np.ndarray:
        if self.btc_prices is None or self.is_btc:
            return None
        btc_close = self.btc_prices["close"].values
        n_btc = len(btc_close)
        btc_ma = pd.Series(btc_close).rolling(window=self.ma_period, min_periods=self.ma_period).mean().values
        btc_slope = np.zeros(n_btc)
        for i in range(self.warmup_periods, n_btc):
            if not np.isnan(btc_ma[i]) and not np.isnan(btc_ma[i - self.slope_period]):
                btc_slope[i] = (btc_ma[i] / btc_ma[i - self.slope_period] - 1) * 100
        btc_regime = np.full(n_btc, "sideways", dtype=object)
        for i in range(self.warmup_periods, n_btc):
            if np.isnan(btc_ma[i]):
                continue
            price_above = btc_close[i] > btc_ma[i]
            slope_pos = btc_slope[i] > 0
            if price_above and slope_pos:
                btc_regime[i] = "bull"
            elif not price_above:
                btc_regime[i] = "bear"
            else:
                btc_regime[i] = "sideways"
        return btc_regime

    def _get_halving_phase(self, current_date: pd.Timestamp) -> str:
        if not self.use_halving_timing:
            return "normal"

        last_halving = None
        for halving_date in BTC_HALVING_DATES:
            if halving_date <= current_date:
                last_halving = halving_date
            else:
                break

        if last_halving is None:
            return "normal"

        months_after = (current_date.year - last_halving.year) * 12 + (current_date.month - last_halving.month)
        if months_after < self.halving_warn_months:
            return "normal"
        elif months_after < self.halving_danger_months:
            return "warn"
        elif months_after < self.halving_peak_months:
            return "danger"
        elif months_after < self.halving_end_months:
            return "peak"
        else:
            return "normal"

    def _calc_halving_position(self, current_date: pd.Timestamp, base_long: float) -> float:
        phase = self._get_halving_phase(current_date)

        if phase == "normal":
            return base_long
        elif phase == "warn":
            self.stats["halving_warn_days"] += 1
            return max(base_long * self.halving_warn_min_position, 0.0)
        elif phase == "danger":
            self.stats["halving_danger_days"] += 1
            return max(base_long * self.halving_danger_min_position, 0.0)
        elif phase == "peak":
            self.stats["halving_peak_days"] += 1
            return max(base_long * self.halving_peak_min_position, 0.0)

        return base_long

    def _calc_high_to_sell_position(
        self,
        close: np.ndarray,
        i: int,
        current_pos: float,
        base_long: float,
        ath_price: float,
    ) -> tuple:
        if not self.use_high_to_sell or ath_price <= 0:
            return current_pos, ath_price

        current_price = close[i]

        if current_price > ath_price:
            new_ath = current_price
            gain_pct = (current_price - ath_price) / ath_price * 100

            steps = int(gain_pct / self.high_to_sell_step_pct)
            if steps > 0:
                sell_ratio = steps * self.high_to_sell_portion
                sell_ratio = min(sell_ratio, 0.8)
                new_pos = base_long * (1.0 - sell_ratio)
                new_pos = max(new_pos, 0.0)
                if new_pos < current_pos:
                    self.stats["high_to_sell_days"] += 1
                    return new_pos, new_ath

            return current_pos, new_ath

        return current_pos, ath_price

    def _calc_fib_tp_position(
        self,
        current_price: float,
        entry_price: float,
        is_short: bool,
        current_short_pos: float,
    ) -> float:
        if not self.fib_take_profit or not is_short or entry_price <= 0:
            return current_short_pos
        profit_pct = (entry_price - current_price) / entry_price
        if profit_pct <= 0:
            return current_short_pos
        remaining_ratio = 1.0
        n_levels = len(self.fib_levels)
        portion_per_level = 1.0 / n_levels
        for level in self.fib_levels:
            if profit_pct >= level:
                remaining_ratio -= portion_per_level
        remaining_ratio = max(remaining_ratio, 0.0)
        return current_short_pos * remaining_ratio

    def _calc_ma128_exit_position(
        self,
        current_price: float,
        ma128: float,
        current_long_pos: float,
    ) -> float:
        if not self.use_ma128_exit or ma128 <= 0 or current_price >= ma128:
            return current_long_pos

        below_pct = (ma128 - current_price) / ma128 * 100
        if below_pct <= 0:
            return current_long_pos

        levels_filled = min(
            int(below_pct / self.ma128_exit_step_pct),
            self.ma128_exit_levels
        )
        if levels_filled <= 0:
            return current_long_pos

        sell_ratio = levels_filled / self.ma128_exit_levels
        remaining_pos = current_long_pos * (1.0 - sell_ratio)
        return max(remaining_pos, 0.0)

    def _detect_bounce(
        self,
        close: np.ndarray,
        i: int,
        lookback: int = 5,
        bounce_threshold: float = 0.03,
    ) -> bool:
        if i < lookback:
            return False
        recent_low = np.min(close[i - lookback:i])
        bounce_pct = (close[i] - recent_low) / recent_low
        return bounce_pct >= bounce_threshold

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values

        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values

        ma128_series = pd.Series(close).rolling(window=self.ma128_period, min_periods=self.ma128_period).mean()
        ma128 = ma128_series.values

        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100

        weekly_ma200 = self._compute_weekly_ma200(prices) if (self.is_btc and self.weekly_ma200_dip_buy) else None
        btc_regime = self._compute_btc_regime() if (not self.is_btc and self.alt_bear_no_trade) else None

        last_state = "init"
        short_entry_price = None
        dip_buy_active = False
        dip_buy_entry_price = None
        bounce_sell_accumulated = 0.0
        exit_mode_active = False
        exit_mode_high = None
        exit_mode_lookback = 60
        exit_drawdown_threshold = 0.15

        ath_price = 0.0
        halving_ath_price = 0.0

        for i in range(self.warmup_periods, n):
            if np.isnan(ma[i]) or ma[i] <= 0:
                positions[i] = 0.0
                continue

            price_above_ma200 = close[i] > ma[i]
            slope_pos = ma_slope[i] > 0
            slope_neg = ma_slope[i] < 0
            current_date = prices.index[i]

            current_state = "sideways"
            target_pos = 0.0

            if self.is_btc:
                halving_phase = self._get_halving_phase(current_date)

                if i >= exit_mode_lookback:
                    recent_high = np.max(close[i - exit_mode_lookback:i + 1])
                    drawdown_from_high = (recent_high - close[i]) / recent_high
                else:
                    recent_high = close[i]
                    drawdown_from_high = 0.0

                if close[i] > ath_price:
                    ath_price = close[i]

                if not exit_mode_active:
                    bearish_setup = (
                        drawdown_from_high >= exit_drawdown_threshold
                        and ma_slope[i] < 0.5
                    )
                    just_broke_ma200 = (
                        not price_above_ma200
                        and last_state in ("bull", "bull_exit")
                    )
                    halving_exit = (
                        halving_phase in ("danger", "peak")
                        and price_above_ma200
                    )
                    if bearish_setup or just_broke_ma200 or halving_exit:
                        exit_mode_active = True
                        exit_mode_high = recent_high
                        bounce_sell_accumulated = 0.0
                        halving_ath_price = ath_price
                else:
                    if close[i] >= recent_high * 0.99 and slope_pos and price_above_ma200 and halving_phase == "normal":
                        exit_mode_active = False
                        exit_mode_high = None
                        bounce_sell_accumulated = 0.0
                        halving_ath_price = 0.0

                if price_above_ma200 and slope_pos:
                    current_state = "bull"
                    base_long = self.max_position

                    target_pos = base_long

                    if halving_phase != "normal":
                        halving_pos = self._calc_halving_position(current_date, base_long)
                        if halving_pos < target_pos:
                            target_pos = halving_pos
                            current_state = "bull_exit"

                    if exit_mode_active and self.use_high_to_sell and halving_phase != "normal":
                        high_sell_pos, new_ath = self._calc_high_to_sell_position(
                            close, i, target_pos, base_long, halving_ath_price
                        )
                        halving_ath_price = new_ath
                        if high_sell_pos < target_pos:
                            target_pos = high_sell_pos
                            current_state = "bull_exit"

                    if exit_mode_active and self.use_ma128_exit and not np.isnan(ma128[i]) and ma128[i] > 0:
                        ma128_pos = self._calc_ma128_exit_position(close[i], ma128[i], target_pos)
                        if ma128_pos < target_pos:
                            self.stats["ma128_exit_days"] += 1
                            target_pos = ma128_pos
                            current_state = "bull_exit"

                    if exit_mode_active and self.use_bounce_sell and target_pos > 0:
                        below_ma128 = not np.isnan(ma128[i]) and close[i] < ma128[i]
                        if below_ma128 and self._detect_bounce(close, i):
                            self.stats["bounce_sell_days"] += 1
                            bounce_sell_accumulated += self.bounce_sell_pct_per_bounce
                            bounce_sell_accumulated = min(bounce_sell_accumulated, 0.8)
                            target_pos = target_pos * (1.0 - bounce_sell_accumulated)
                            target_pos = max(target_pos, 0.0)
                            current_state = "bull_exit"
                    elif not exit_mode_active:
                        bounce_sell_accumulated = 0.0

                    if current_state == "bull":
                        self.stats["bull_days"] += 1
                    else:
                        self.stats["bull_exit_days"] += 1

                    short_entry_price = None
                    dip_buy_active = False
                    dip_buy_entry_price = None

                elif not price_above_ma200:
                    bounce_sell_accumulated = 0.0

                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100

                        weekly_above_pct = -weekly_below_pct
                        in_support_zone = weekly_above_pct <= self.weekly_ma200_support_zone_pct

                        if weekly_below_pct > 0:
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                if levels_filled == 1:
                                    dip_buy_pos = self.dip_buy_initial_pct * self.dip_buy_max_position
                                else:
                                    remaining_levels = levels_filled - 1
                                    remaining_pct = self.dip_buy_max_position - self.dip_buy_initial_pct * self.dip_buy_max_position
                                    add_per_level = remaining_pct / (self.dip_buy_levels - 1)
                                    dip_buy_pos = self.dip_buy_initial_pct * self.dip_buy_max_position + remaining_levels * add_per_level

                                dip_buy_pos = min(dip_buy_pos, self.dip_buy_max_position)

                                if not dip_buy_active:
                                    dip_buy_active = True
                                    dip_buy_entry_price = close[i]

                        elif in_support_zone and dip_buy_active:
                            protection_factor = max(1.0 - weekly_above_pct / self.weekly_ma200_support_zone_pct, 0.0)
                            dip_buy_pos = self.dip_buy_initial_pct * self.dip_buy_max_position * protection_factor
                            if dip_buy_pos < 0.01:
                                dip_buy_pos = 0.0

                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None

                    else:
                        if dip_buy_active and self.dip_buy_end_on_ma200_breakout:
                            pass

                        base_short = 0.0
                        if slope_neg:
                            base_short = self.bear_short_level2_pct
                            current_state = "bear_short_l2"
                            self.stats["bear_short_l2_days"] += 1
                        else:
                            base_short = self.bear_short_level1_pct
                            if base_short > 0:
                                current_state = "bear_short_l1"
                                self.stats["bear_short_l1_days"] += 1
                            else:
                                current_state = "bear_flat"
                                self.stats["bear_flat_days"] += 1

                        if base_short > 0 and weekly_ma200 is not None and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                            weekly_distance_pct = abs(close[i] - weekly_ma200[i]) / weekly_ma200[i] * 100
                            if weekly_distance_pct <= self.weekly_ma200_support_zone_pct:
                                protection_factor = weekly_distance_pct / self.weekly_ma200_support_zone_pct
                                base_short = base_short * protection_factor
                                if base_short < 0.05:
                                    base_short = 0.0
                                current_state = "bear_short_l2" if base_short > 0 else "bear_flat"

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

                        dip_buy_active = False
                        dip_buy_entry_price = None

                        if weekly_ma200 is not None and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                            weekly_dist = abs(close[i] - weekly_ma200[i]) / weekly_ma200[i] * 100
                            if weekly_dist <= self.weekly_ma200_support_zone_pct:
                                dip_buy_active = True

                else:
                    bounce_sell_accumulated = 0.0
                    if dip_buy_active and self.dip_buy_end_on_ma200_breakout:
                        if slope_pos or ma_slope[i] >= -0.1:
                            current_state = "dip_buy_end"
                            target_pos = self.max_position
                            self.stats["dip_buy_end_days"] += 1
                            dip_buy_active = False
                            short_entry_price = None
                        else:
                            current_state = "sideways"
                            target_pos = 0.0
                            self.stats["sideways_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None

            else:
                if self.alt_bear_no_trade:
                    btc_in_bull = False
                    if btc_regime is not None and i < len(btc_regime):
                        btc_in_bull = btc_regime[i] == "bull"
                    if price_above_ma200 and slope_pos and btc_in_bull:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    else:
                        current_state = "bear_flat"
                        target_pos = 0.0
                        self.stats["bear_flat_days"] += 1
                else:
                    if price_above_ma200 and slope_pos:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    elif not price_above_ma200 and slope_neg:
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

    def get_stats(self) -> dict:
        return self.stats.copy()
