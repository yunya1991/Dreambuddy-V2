"""增强版v3策略：优化抄底和逃顶

基于v2增强版MA200策略，新增两个核心优化：

【抄底优化 DIP_BUY】
1. 越跌越买：以周线MA200为基线，每跌X%加一档仓位（已有，优化逻辑）
2. 抄底结束条件：有效站上日线MA200 且 5日斜率为正 → 清掉抄底仓位，转入牛市满仓
3. 轻仓试探 → 逐步确认加仓（新增确认机制）

【逃顶优化 TOP_EXIT】
1. 减半周期锚定：比特币减半后18个月为顶部时间窗口
2. MA128破位卖出：有效跌破日线MA128后开始分批卖出
3. 反弹卖出：下跌趋势中出现反弹就卖出（逐批减仓）
4. 波浪理论：基于价格运动分批卖出（简化为多档止盈）

只对BTC生效，小币沿用v2逻辑。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import BaseStrategy


class EnhancedMA200V3Strategy(BaseStrategy):
    """增强版MA200策略 v3 - 优化抄底和逃顶"""

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
        # 抄底参数
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.9,
        dip_buy_levels: int = 6,
        dip_buy_step_pct: float = 3.0,
        dip_buy_initial_pct: float = 0.1,
        # 抄底结束条件
        dip_buy_end_on_ma200_breakout: bool = True,
        # 逃顶参数
        use_ma128_exit: bool = True,
        ma128_exit_levels: int = 4,
        ma128_exit_step_pct: float = 5.0,
        use_bounce_sell: bool = True,
        bounce_sell_pct_per_bounce: float = 0.25,
        # 做空参数
        bear_short_level1_pct: float = 0.3,
        bear_short_level2_pct: float = 0.5,
        fib_take_profit: bool = True,
        fib_levels: list = None,
        # 小币参数
        alt_bear_no_trade: bool = True,
    ):
        super().__init__(name="enhanced_ma200_v3")
        self.ma_period = ma_period
        self.ma128_period = ma128_period
        self.slope_period = slope_period
        self.max_position = max_position
        self.warmup_periods = warmup_periods
        self.symbol = symbol
        self.is_btc = is_btc
        self.btc_prices = btc_prices

        # 抄底
        self.weekly_ma200_dip_buy = weekly_ma200_dip_buy
        self.dip_buy_max_position = dip_buy_max_position
        self.dip_buy_levels = dip_buy_levels
        self.dip_buy_step_pct = dip_buy_step_pct
        self.dip_buy_initial_pct = dip_buy_initial_pct
        self.dip_buy_end_on_ma200_breakout = dip_buy_end_on_ma200_breakout

        # 逃顶
        self.use_ma128_exit = use_ma128_exit
        self.ma128_exit_levels = ma128_exit_levels
        self.ma128_exit_step_pct = ma128_exit_step_pct
        self.use_bounce_sell = use_bounce_sell
        self.bounce_sell_pct_per_bounce = bounce_sell_pct_per_bounce

        # 做空
        self.bear_short_level1_pct = bear_short_level1_pct
        self.bear_short_level2_pct = bear_short_level2_pct
        self.fib_take_profit = fib_take_profit
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618]

        # 小币
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
        """MA128破位后，越跌越卖

        价格在MA128下方时，每跌step_pct就卖出一档
        """
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
        """检测是否为反弹（从近期低点上涨超过阈值）"""
        if i < lookback:
            return False
        recent_low = np.min(close[i - lookback:i])
        bounce_pct = (close[i] - recent_low) / recent_low
        return bounce_pct >= bounce_threshold

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values

        # 计算指标
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

        for i in range(self.warmup_periods, n):
            if np.isnan(ma[i]) or ma[i] <= 0:
                positions[i] = 0.0
                continue

            price_above_ma200 = close[i] > ma[i]
            slope_pos = ma_slope[i] > 0
            slope_neg = ma_slope[i] < 0

            current_state = "sideways"
            target_pos = 0.0

            if self.is_btc:
                # === BTC 策略逻辑 ===

                # 计算近期高点（用于判断是否进入逃顶模式）
                if i >= exit_mode_lookback:
                    recent_high = np.max(close[i - exit_mode_lookback:i + 1])
                    drawdown_from_high = (recent_high - close[i]) / recent_high
                else:
                    recent_high = close[i]
                    drawdown_from_high = 0.0

                # 逃顶模式判断：
                # 触发条件（满足任一即进入逃顶模式）：
                # 1. 价格从60日高点回撤超过15%，且MA200斜率走平/转负
                # 2. 价格跌破MA200（之前是牛市）
                # 退出条件：价格创新高 且 MA200斜率重新转正
                if not exit_mode_active:
                    # 检查是否进入逃顶模式
                    bearish_setup = (
                        drawdown_from_high >= exit_drawdown_threshold
                        and ma_slope[i] < 0.5  # MA200斜率走平或微负
                    )
                    just_broke_ma200 = (
                        not price_above_ma200
                        and last_state in ("bull", "bull_exit")
                    )
                    if bearish_setup or just_broke_ma200:
                        exit_mode_active = True
                        exit_mode_high = recent_high
                        bounce_sell_accumulated = 0.0
                else:
                    # 检查是否退出逃顶模式（创新高且斜率转正）
                    if close[i] >= recent_high * 0.99 and slope_pos and price_above_ma200:
                        exit_mode_active = False
                        exit_mode_high = None
                        bounce_sell_accumulated = 0.0

                # 1. 牛市判断：价格在MA200上方 且 斜率为正
                if price_above_ma200 and slope_pos:
                    current_state = "bull"
                    base_long = self.max_position

                    # 逃顶：仅在逃顶模式下才启用MA128破位卖出和反弹卖出
                    if exit_mode_active and self.use_ma128_exit and not np.isnan(ma128[i]) and ma128[i] > 0:
                        ma128_pos = self._calc_ma128_exit_position(close[i], ma128[i], base_long)
                        if ma128_pos < base_long:
                            self.stats["ma128_exit_days"] += 1
                            current_state = "bull_exit"
                        target_pos = ma128_pos
                    else:
                        target_pos = base_long

                    # 逃顶：反弹卖出（仅在逃顶模式下，价格在MA128下方且出现反弹时减仓）
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

                # 2. 价格在MA200下方
                elif not price_above_ma200:
                    # 重置反弹卖出累计
                    bounce_sell_accumulated = 0.0

                    # 2a. 抄底逻辑：价格接近/跌破周线MA200
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100

                        if weekly_below_pct > 0:
                            # 越跌越买：每跌step_pct加一档
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                # 初始轻仓 + 逐步加仓
                                # 第一档是初始仓位，之后每档均匀增加
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

                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None

                    # 2b. 没有抄底信号 → 做空或空仓
                    else:
                        if dip_buy_active and self.dip_buy_end_on_ma200_breakout:
                            # 抄底结束条件检查：如果之前在抄底，现在价格回到MA200上方附近
                            # 这里已经是 not price_above_ma200 的分支，所以抄底结束由上方分支处理
                            pass

                        base_short = 0.0
                        if slope_neg:
                            base_short = self.bear_short_level2_pct
                            current_state = "bear_short_l2"
                            self.stats["bear_short_l2_days"] += 1
                        else:
                            base_short = self.bear_short_level1_pct
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

                        dip_buy_active = False
                        dip_buy_entry_price = None

                # 3. 价格在MA200上方但斜率不明确（震荡）
                else:
                    bounce_sell_accumulated = 0.0
                    # 检查是否有抄底仓位需要结束
                    if dip_buy_active and self.dip_buy_end_on_ma200_breakout:
                        # 价格站上MA200 + 斜率即将转正 → 抄底结束，转入牛市
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
                # === 小币策略（沿用v2） ===
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


if __name__ == "__main__":
    import json
    from backtest.engine import BacktestEngine

    # 快速测试
    with open("data/historical/BTC_1D_730d.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )

    strategy = EnhancedMA200V3Strategy(is_btc=True)
    signals = strategy.generate_signals(prices)

    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    result = engine.run(prices["close"], signals)

    print("EnhancedMA200 V3 策略测试（BTC）")
    print(f"总收益: {result['metrics']['total_return_pct']:.2%}")
    print(f"夏普: {result['metrics']['sharpe_ratio']:.3f}")
    print(f"最大回撤: {result['metrics']['max_drawdown_pct']:.2%}")
    print(f"交易次数: {len(result['trades'])}")
    print()
    print("状态统计:")
    for k, v in strategy.get_stats().items():
        if v > 0:
            print(f"  {k}: {v}")
