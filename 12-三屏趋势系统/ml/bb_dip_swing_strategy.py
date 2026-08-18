"""v3.4 布林带波段抄底策略

核心思路：
- 基础仓位：v2的越跌越买（保证底部有底仓）
- 波段仓位：用一部分仓位在布林带做高抛低吸（下轨买、上轨卖）
- 头肩底确认：形态确认后，波段仓位转为长期持有，不再高抛
- 目标：通过底部波段操作降低持仓成本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class BBDipSwingStrategy(EnhancedMA200Strategy):
    """v3.4 布林带波段抄底"""

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
        # 布林带波段参数
        use_bb_swing: bool = True,
        bb_period: int = 10,
        bb_std: float = 1.5,
        swing_fraction: float = 0.4,  # 用40%的底仓做波段
        bb_upper_sell_pct: float = 0.0,  # 触及上轨卖出波段仓位的比例
        bb_lower_buy_pct: float = 0.0,  # 触及下轨买回波段仓位的比例
        # 头肩底参数
        use_hs_confirmation: bool = True,
        hs_lookback: int = 40,
        hs_min_depth_pct: float = 0.05,
        hs_lock_swing: bool = True,  # 头肩底确认后，波段仓位转为持有
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
        self.name = "bb_dip_swing_v34"

        self.use_bb_swing = use_bb_swing
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.swing_fraction = swing_fraction

        self.use_hs_confirmation = use_hs_confirmation
        self.hs_lookback = hs_lookback
        self.hs_min_depth_pct = hs_min_depth_pct
        self.hs_lock_swing = hs_lock_swing

        self.stats.update({
            "bb_swing_buy_days": 0,
            "bb_swing_sell_days": 0,
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
        """简化版双底检测"""
        if i < self.hs_lookback:
            return False
        window = close[i - self.hs_lookback + 1:i + 1]
        low_idx = np.argmin(window)
        low_price = window[low_idx]
        window_high = np.max(window)
        depth = (window_high - low_price) / window_high
        if depth < self.hs_min_depth_pct:
            return False

        left_half = window[:max(1, low_idx)]
        right_half = window[low_idx + 1:]
        if len(left_half) < 3 or len(right_half) < 3:
            return False

        left_low = np.min(left_half)
        right_low = np.min(right_half)

        lows_diff = abs(left_low - right_low) / max(left_low, right_low)
        if lows_diff > depth * 0.6:
            return False

        right_low_idx = low_idx + 1 + np.argmin(right_half)
        if right_low_idx <= low_idx + 1:
            return False
        mid_seg = window[low_idx + 1:right_low_idx]
        if len(mid_seg) < 2:
            return False
        neckline = np.max(mid_seg)

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

        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close) if self.use_bb_swing else (None, None, None)

        last_state = "init"
        short_entry_price = None

        # 波段状态
        swing_position = 0.0  # 当前波段仓位（正数表示额外持有的波段仓位）
        # swing_position 范围: [-swing_fraction * base_pos, swing_fraction * base_pos]
        # 正值：额外加仓了（下轨买入的）
        # 负值：减仓了（上轨卖出的）
        hs_confirmed = False
        last_bb_action_idx = -10
        bb_min_gap = 2  # 两次波段操作至少间隔2天

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
                    swing_position = 0.0
                    hs_confirmed = False

                elif not price_above:
                    # 价格在MA200下方
                    if base_dip_pos > 0:
                        # === 抄底模式 ===
                        current_state = "dip_buy"
                        short_entry_price = None

                        # 计算波段空间
                        swing_max = base_dip_pos * self.swing_fraction

                        if self.use_bb_swing and bb_upper is not None and not np.isnan(bb_upper[i]):
                            # 头肩底确认后，锁定波段仓位（不再高抛低吸）
                            if self.use_hs_confirmation and not hs_confirmed and self.hs_lock_swing:
                                if self._detect_hs_bottom(close, i):
                                    hs_confirmed = True
                                    swing_position = swing_max  # 转为全仓持有
                                    self.stats["hs_confirmed_days"] += 1

                            if not hs_confirmed or not self.hs_lock_swing:
                                # 触及下轨 → 买回波段仓位
                                if close[i] <= bb_lower[i] and (i - last_bb_action_idx) >= bb_min_gap:
                                    if swing_position < swing_max:
                                        swing_position = min(swing_position + swing_max * 0.5, swing_max)
                                        last_bb_action_idx = i
                                        self.stats["bb_swing_buy_days"] += 1

                                # 触及上轨 → 卖出波段仓位
                                elif close[i] >= bb_upper[i] and (i - last_bb_action_idx) >= bb_min_gap:
                                    if swing_position > -swing_max:
                                        swing_position = max(swing_position - swing_max * 0.5, -swing_max)
                                        last_bb_action_idx = i
                                        self.stats["bb_swing_sell_days"] += 1

                        # 总仓位 = 基础仓位 + 波段仓位
                        target_pos = base_dip_pos + swing_position
                        target_pos = max(0, min(target_pos, self.dip_buy_max_position + swing_max))

                        self.stats["dip_buy_days"] += 1

                    else:
                        # === 做空模式（完全沿用v2）===
                        swing_position = 0.0
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
                    # 价格在MA200上方但斜率不为正
                    if base_dip_pos > 0:
                        current_state = "dip_buy"
                        swing_max = base_dip_pos * self.swing_fraction
                        target_pos = base_dip_pos + swing_position
                        target_pos = max(0, min(target_pos, self.dip_buy_max_position + swing_max))
                        self.stats["dip_buy_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        swing_position = 0.0
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
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v34_v2")
    print(f"  夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")

    print()
    print("v3.4 布林带波段抄底...")
    v34 = BBDipSwingStrategy(is_btc=True, bb_period=10, bb_std=1.5, swing_fraction=0.4)
    v34_r = engine.run_scenario_backtest(prices, v34, "v34", symbol="BTC", experiment_name="v34_swing")
    print(f"  夏普 {v34_r.overall_sharpe:.3f} | 收益 {v34_r.overall_total_return:.1%} | 评分 {v34_r.composite_score:.3f}")

    print()
    print("状态统计:")
    for k, v in sorted(v34.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")

    print()
    print("各目标F1对比:")
    for obj in ["dip_buy", "top_exit", "bear_short", "bear_exit"]:
        v2_f1 = v2_r.objective_metrics[obj].f1_score if obj in v2_r.objective_metrics else 0
        v34_f1 = v34_r.objective_metrics[obj].f1_score if obj in v34_r.objective_metrics else 0
        diff = v34_f1 - v2_f1
        marker = "✅" if diff > 0 else "❌" if diff < 0 else "➖"
        print(f"  {obj}: {v2_f1:.4f} → {v34_f1:.4f} ({diff:+.4f}) {marker}")
