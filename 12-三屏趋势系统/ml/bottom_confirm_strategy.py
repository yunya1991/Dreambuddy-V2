"""v3.5 底部确认抄底策略

重新设计：
1. 周线MA200定底部区域（沿用v2越跌越买）
2. 布林带辅助买点：价格接近/跌破布林带下轨时，加速加仓
3. 底部确认信号：当价格从底部区域放量突破布林带中轨，且维持N天 → 确认底部，加满仓
   （用"突破中轨"替代"头肩底"，更简单可靠）

核心原则：底部只加不减，方向向上。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class BottomConfirmStrategy(EnhancedMA200Strategy):
    """v3.5 底部确认抄底"""

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
        # 抄底基础参数
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.8,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        # 布林带参数
        use_bb_accel: bool = True,
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_lower_accel_pct: float = 0.1,  # 触及下轨时额外加仓10%
        # 底部确认参数
        use_bottom_confirm: bool = True,
        confirm_above_mid_days: int = 5,  # 站稳中轨N天确认底部
        confirm_boost_pct: float = 0.2,  # 确认后再加20%
        # v2其他参数
        bear_short_level1_pct: float = 0.3,
        bear_short_level2_pct: float = 0.5,
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
        self.name = "bottom_confirm_v35"

        self.use_bb_accel = use_bb_accel
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_lower_accel_pct = bb_lower_accel_pct

        self.use_bottom_confirm = use_bottom_confirm
        self.confirm_above_mid_days = confirm_above_mid_days
        self.confirm_boost_pct = confirm_boost_pct

        self.stats.update({
            "bb_accel_days": 0,
            "bottom_confirmed_days": 0,
        })

    def _compute_bollinger_bands(self, close: np.ndarray) -> tuple:
        n = len(close)
        upper = np.full(n, np.nan)
        mid = np.full(n, np.nan)
        lower = np.full(n, np.nan)
        for i in range(self.bb_period - 1, n):
            window = close[i - self.bb_period + 1:i + 1]
            m = np.mean(window)
            s = np.std(window)
            mid[i] = m
            upper[i] = m + self.bb_std * s
            lower[i] = m - self.bb_std * s
        return upper, mid, lower

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values

        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values

        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100

        weekly_ma200 = self._compute_weekly_ma200(prices) if (self.is_btc and self.weekly_ma200_dip_buy) else None
        btc_regime = self._compute_btc_regime() if (not self.is_btc and self.alt_bear_no_trade) else None

        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close) if (self.use_bb_accel or self.use_bottom_confirm) else (None, None, None)

        last_state = "init"
        short_entry_price = None

        # 底部状态
        bottom_confirmed = False
        above_mid_count = 0  # 连续在中轨上方的天数

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
                # 计算基础抄底仓位
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
                    # 牛市满仓
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None
                    bottom_confirmed = False
                    above_mid_count = 0

                elif not price_above:
                    # 价格在MA200下方
                    if base_dip_pos > 0:
                        # === 抄底模式 ===
                        current_state = "dip_buy"
                        short_entry_price = None
                        extra_pos = 0.0

                        # 布林带下轨加速加仓
                        if self.use_bb_accel and bb_lower is not None and not np.isnan(bb_lower[i]):
                            if close[i] <= bb_lower[i]:
                                extra_pos += self.bb_lower_accel_pct
                                self.stats["bb_accel_days"] += 1

                        # 底部确认：站稳布林带中轨N天
                        if self.use_bottom_confirm and bb_mid is not None and not np.isnan(bb_mid[i]):
                            if close[i] > bb_mid[i]:
                                above_mid_count += 1
                                if above_mid_count >= self.confirm_above_mid_days:
                                    bottom_confirmed = True
                            else:
                                above_mid_count = max(0, above_mid_count - 1)

                            if bottom_confirmed:
                                extra_pos += self.confirm_boost_pct
                                self.stats["bottom_confirmed_days"] += 1

                        target_pos = min(
                            base_dip_pos + extra_pos,
                            self.dip_buy_max_position + self.bb_lower_accel_pct + self.confirm_boost_pct
                        )

                        self.stats["dip_buy_days"] += 1

                    else:
                        # === 做空模式（完全沿用v2）===
                        bottom_confirmed = False
                        above_mid_count = 0

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

                else:
                    # 价格在MA200上方但斜率不为正
                    if base_dip_pos > 0:
                        current_state = "dip_buy"
                        extra_pos = 0.0
                        if bottom_confirmed:
                            extra_pos += self.confirm_boost_pct
                        target_pos = min(
                            base_dip_pos + extra_pos,
                            self.dip_buy_max_position + self.confirm_boost_pct
                        )
                        self.stats["dip_buy_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        bottom_confirmed = False
                        above_mid_count = 0

            else:
                # 小币沿用v2
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

    print("v2 基线...")
    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v35_v2")
    print(f"  夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")

    print()
    print("v3.5 底部确认抄底...")
    v35 = BottomConfirmStrategy(
        is_btc=True,
        bb_period=20,
        bb_std=2.0,
        bb_lower_accel_pct=0.1,
        confirm_above_mid_days=5,
        confirm_boost_pct=0.2,
    )
    v35_r = engine.run_scenario_backtest(prices, v35, "v35", symbol="BTC", experiment_name="v35_bottom_confirm")
    print(f"  夏普 {v35_r.overall_sharpe:.3f} | 收益 {v35_r.overall_total_return:.1%} | 评分 {v35_r.composite_score:.3f}")

    print()
    print("状态统计:")
    for k, v in sorted(v35.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")

    # 详细对比
    print()
    print("=" * 60)
    print("详细对比：")
    print(f"{'指标':<20} {'v2':>12} {'v3.5':>12} {'差异':>12}")
    print("-" * 60)
    metrics = [
        ("总收益", v2_r.overall_total_return, v35_r.overall_total_return, ".1%"),
        ("夏普比率", v2_r.overall_sharpe, v35_r.overall_sharpe, ".3f"),
        ("卡玛比率", v2_r.overall_calmar, v35_r.overall_calmar, ".3f"),
        ("最大回撤", v2_r.overall_max_drawdown, v35_r.overall_max_drawdown, ".1%"),
        ("胜率", v2_r.overall_win_rate, v35_r.overall_win_rate, ".2%"),
        ("盈亏比", v2_r.overall_profit_factor, v35_r.overall_profit_factor, ".2f"),
    ]
    for name, v2_val, v35_val, fmt in metrics:
        diff = v35_val - v2_val
        print(f"{name:<20} {v2_val:>12{fmt}} {v35_val:>12{fmt}} {diff:>+12{fmt}}")
