"""v3.3 网格抄底策略

重新设计思路：
- 维持v2的"越跌越买"核心逻辑（保证仓位弹性）
- 叠加布林带网格：每次触及下轨就加一小笔，类似定投/网格
- 头肩底确认：形态确认后停止网格加仓，持有等待
- 核心目标：在v2的基础上，通过布林带网格降低抄底成本

不改变做空逻辑，只优化抄底部分。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class GridDipBuyStrategy(EnhancedMA200Strategy):
    """v3.3 网格抄底策略

    在v2越跌越买的基础上，叠加布林带网格加仓：
    - 基础仓位：沿用v2的越跌越买逻辑（保证仓位弹性）
    - 网格加仓：每次触及布林带下轨，额外加一小笔仓位
    - 头肩底确认：形态确认后，增加到最大抄底仓位
    - 抄底结束：站上MA200且斜率转正
    """

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
        # 抄底基础参数（沿用v2风格）
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.9,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        # 布林带网格参数
        use_bb_grid: bool = True,
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_grid_step: float = 0.05,  # 每次网格加仓5%
        bb_max_extra: float = 0.2,  # 网格最多额外加20%
        # 头肩底参数
        use_hs_confirmation: bool = True,
        hs_lookback: int = 60,
        hs_min_depth_pct: float = 0.05,
        hs_boost_pct: float = 0.1,  # 头肩底确认后再加10%
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
        self.name = "grid_dip_buy_v33"

        self.use_bb_grid = use_bb_grid
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_grid_step = bb_grid_step
        self.bb_max_extra = bb_max_extra

        self.use_hs_confirmation = use_hs_confirmation
        self.hs_lookback = hs_lookback
        self.hs_min_depth_pct = hs_min_depth_pct
        self.hs_boost_pct = hs_boost_pct

        self.stats.update({
            "bb_grid_buy_days": 0,
            "hs_confirmed_days": 0,
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

    def _detect_hs_bottom(self, close: np.ndarray, i: int) -> bool:
        """简化版双底/头肩底检测"""
        if i < self.hs_lookback:
            return False
        window = close[i - self.hs_lookback + 1:i + 1]
        n = len(window)
        low_idx = np.argmin(window)
        low_price = window[low_idx]
        window_high = np.max(window)
        depth = (window_high - low_price) / window_high
        if depth < self.hs_min_depth_pct:
            return False

        # 左右各找一个低点
        left_half = window[:max(1, low_idx)]
        right_half = window[low_idx + 1:]
        if len(left_half) < 3 or len(right_half) < 3:
            return False

        left_low = np.min(left_half)
        right_low = np.min(right_half)

        # 两个低点高度接近
        lows_diff = abs(left_low - right_low) / max(left_low, right_low)
        if lows_diff > depth * 0.6:
            return False

        # 颈线
        right_low_idx = low_idx + 1 + np.argmin(right_half)
        if right_low_idx <= low_idx + 1:
            return False
        mid_seg = window[low_idx + 1:right_low_idx]
        if len(mid_seg) < 2:
            return False
        neckline = np.max(mid_seg)

        # 突破颈线
        return close[i] > neckline * 1.01

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

        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close) if self.use_bb_grid else (None, None, None)

        last_state = "init"
        short_entry_price = None

        # 网格状态
        bb_extra_position = 0.0  # 布林带网格的额外加仓
        last_bb_trigger_idx = -100  # 上次触发网格的索引（避免连续触发）
        bb_min_gap = 3  # 两次网格加仓至少间隔3天

        # 头肩底状态
        hs_confirmed = False

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
                if price_above and slope_pos:
                    # 牛市满仓
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None
                    bb_extra_position = 0.0
                    hs_confirmed = False

                elif not price_above:
                    # 价格在MA200下方 → 抄底或做空
                    dip_buy_pos = 0.0

                    # v2的越跌越买逻辑（基础仓位）
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        if weekly_below_pct > 0:
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                dip_buy_pos = (levels_filled / self.dip_buy_levels) * self.dip_buy_max_position

                    if dip_buy_pos > 0:
                        # === 抄底模式 ===
                        current_state = "dip_buy"
                        short_entry_price = None

                        # 布林带网格加仓
                        if self.use_bb_grid and bb_lower is not None and not np.isnan(bb_lower[i]):
                            # 触及下轨，且间隔足够，加仓
                            if close[i] <= bb_lower[i] and (i - last_bb_trigger_idx) >= bb_min_gap:
                                if bb_extra_position < self.bb_max_extra:
                                    bb_extra_position += self.bb_grid_step
                                    bb_extra_position = min(bb_extra_position, self.bb_max_extra)
                                    last_bb_trigger_idx = i
                                    self.stats["bb_grid_buy_days"] += 1

                        # 头肩底确认后再加仓
                        if self.use_hs_confirmation and not hs_confirmed:
                            if self._detect_hs_bottom(close, i):
                                hs_confirmed = True
                                self.stats["hs_confirmed_days"] += 1

                        # 综合仓位 = 基础仓位 + 网格加仓 + 头肩底加成
                        hs_boost = self.hs_boost_pct if hs_confirmed else 0.0
                        target_pos = min(
                            dip_buy_pos + bb_extra_position + hs_boost,
                            self.dip_buy_max_position + self.bb_max_extra + self.hs_boost_pct
                        )

                        self.stats["dip_buy_days"] += 1

                    else:
                        # === 做空模式（完全沿用v2）===
                        bb_extra_position = 0.0
                        hs_confirmed = False

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
                    # 价格在MA200上方但斜率不为正（震荡）
                    # 沿用v2逻辑：如果有抄底信号则维持，否则空仓
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        if weekly_below_pct > 0:
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                dip_buy_pos = (levels_filled / self.dip_buy_levels) * self.dip_buy_max_position

                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        # 保持网格加仓和头肩底状态
                        hs_boost = self.hs_boost_pct if hs_confirmed else 0.0
                        target_pos = min(
                            dip_buy_pos + bb_extra_position + hs_boost,
                            self.dip_buy_max_position + self.bb_max_extra + self.hs_boost_pct
                        )
                        self.stats["dip_buy_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        bb_extra_position = 0.0
                        hs_confirmed = False

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
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v33_v2")
    print(f"  夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")

    print()
    print("v3.3 网格抄底...")
    v33 = GridDipBuyStrategy(is_btc=True)
    v33_r = engine.run_scenario_backtest(prices, v33, "v33", symbol="BTC", experiment_name="v33_grid")
    print(f"  夏普 {v33_r.overall_sharpe:.3f} | 收益 {v33_r.overall_total_return:.1%} | 评分 {v33_r.composite_score:.3f}")

    print()
    print("DIP_BUY对比：")
    v2_dip = v2_r.objective_metrics["dip_buy"]
    v33_dip = v33_r.objective_metrics["dip_buy"]
    print(f"  胜率: {v2_dip.win_rate:.2%} → {v33_dip.win_rate:.2%} ({v33_dip.win_rate - v2_dip.win_rate:+.2%})")
    print(f"  收益: {v2_dip.avg_return:.2%} → {v33_dip.avg_return:.2%} ({v33_dip.avg_return - v2_dip.avg_return:+.2%})")

    print()
    print("状态统计:")
    for k, v in sorted(v33.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")
