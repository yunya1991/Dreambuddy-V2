"""v3.6 综合优化策略

结合两大优化方向：
1. 做空优化：去掉L1做空，只在斜率明确为负时做空（已验证提升10%）
2. 抄底优化：在v2越跌越买基础上，叠加布林带加速+底部确认

这是一个综合版本，验证两个优化能否叠加。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class V36ComboStrategy(EnhancedMA200Strategy):
    """v3.6 综合优化：做空优化 + 抄底增强"""

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
        # 布林带加速抄底
        bb_accel_pct: float = 0.15,  # 布林带下轨额外加仓
        bb_period: int = 20,
        bb_std: float = 2.0,
        # 底部确认加仓
        bottom_confirm_pct: float = 0.15,  # 底部确认后再加仓
        confirm_days: int = 5,  # 站稳中轨N天确认
        # 做空参数（优化版：无L1）
        bear_short_level1_pct: float = 0.0,
        bear_short_level2_pct: float = 0.6,
        # v2其他参数
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
        self.name = "v36_combo"

        self.bb_accel_pct = bb_accel_pct
        self.bb_period = bb_period
        self.bb_std = bb_std

        self.bottom_confirm_pct = bottom_confirm_pct
        self.confirm_days = confirm_days

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

        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close)

        last_state = "init"
        short_entry_price = None

        bottom_confirmed = False
        above_mid_count = 0

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

                        # 布林带下轨加速
                        if not np.isnan(bb_lower[i]) and close[i] <= bb_lower[i]:
                            extra_pos += self.bb_accel_pct
                            self.stats["bb_accel_days"] += 1

                        # 底部确认：站稳中轨
                        if not np.isnan(bb_mid[i]):
                            if close[i] > bb_mid[i]:
                                above_mid_count += 1
                                if above_mid_count >= self.confirm_days:
                                    bottom_confirmed = True
                            else:
                                above_mid_count = max(0, above_mid_count - 1)

                            if bottom_confirmed:
                                extra_pos += self.bottom_confirm_pct
                                self.stats["bottom_confirmed_days"] += 1

                        max_dip = self.dip_buy_max_position + self.bb_accel_pct + self.bottom_confirm_pct
                        target_pos = min(base_dip_pos + extra_pos, max_dip)

                        self.stats["dip_buy_days"] += 1

                    else:
                        # === 做空模式（优化版：只有L2，没有L1）===
                        bottom_confirmed = False
                        above_mid_count = 0

                        base_short = 0.0
                        if slope_neg:
                            base_short = self.bear_short_level2_pct
                            current_state = "bear_short_l2"
                            self.stats["bear_short_l2_days"] += 1
                        else:
                            # 斜率不为负 → 空仓观望（不做L1做空）
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
                        extra_pos = self.bottom_confirm_pct if bottom_confirmed else 0.0
                        target_pos = min(base_dip_pos + extra_pos, self.dip_buy_max_position + self.bottom_confirm_pct)
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
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v36_v2")
    print(f"  夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")

    print()
    print("只优化做空（L1=0, L2=0.6）...")
    short_opt = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    so_r = engine.run_scenario_backtest(prices, short_opt, "short_opt", symbol="BTC", experiment_name="v36_short_opt")
    print(f"  夏普 {so_r.overall_sharpe:.3f} | 收益 {so_r.overall_total_return:.1%} | 评分 {so_r.composite_score:.3f}")

    print()
    print("v3.6 综合优化（做空优化+抄底增强）...")
    v36 = V36ComboStrategy(is_btc=True)
    v36_r = engine.run_scenario_backtest(prices, v36, "v36_combo", symbol="BTC", experiment_name="v36_combo")
    print(f"  夏普 {v36_r.overall_sharpe:.3f} | 收益 {v36_r.overall_total_return:.1%} | 评分 {v36_r.composite_score:.3f}")

    print()
    print("状态统计:")
    for k, v in sorted(v36.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")

    # 详细对比
    print()
    print("=" * 70)
    print("📊 详细对比：")
    print(f"{'指标':<18} {'v2':>12} {'做空优化':>12} {'v3.6综合':>12}")
    print("-" * 70)
    metrics = [
        ("总收益", v2_r.overall_total_return, so_r.overall_total_return, v36_r.overall_total_return, ".1%"),
        ("夏普比率", v2_r.overall_sharpe, so_r.overall_sharpe, v36_r.overall_sharpe, ".3f"),
        ("卡玛比率", v2_r.overall_calmar, so_r.overall_calmar, v36_r.overall_calmar, ".3f"),
        ("最大回撤", v2_r.overall_max_drawdown, so_r.overall_max_drawdown, v36_r.overall_max_drawdown, ".1%"),
        ("胜率", v2_r.overall_win_rate, so_r.overall_win_rate, v36_r.overall_win_rate, ".2%"),
        ("综合评分", v2_r.composite_score, so_r.composite_score, v36_r.composite_score, ".3f"),
    ]
    for name, v2_val, so_val, v36_val, fmt in metrics:
        print(f"{name:<18} {v2_val:>12{fmt}} {so_val:>12{fmt}} {v36_val:>12{fmt}}")

    # 各目标对比
    print()
    print("🎯 各目标F1对比:")
    for obj in ["dip_buy", "top_exit", "bear_short", "bear_exit"]:
        v2_m = v2_r.objective_metrics.get(obj)
        so_m = so_r.objective_metrics.get(obj)
        v36_m = v36_r.objective_metrics.get(obj)
        if v2_m and so_m and v36_m:
            print(f"  {obj}:")
            print(f"    胜率: {v2_m.win_rate:.2%} → {so_m.win_rate:.2%} → {v36_m.win_rate:.2%}")
            print(f"    收益: {v2_m.avg_return:.2%} → {so_m.avg_return:.2%} → {v36_m.avg_return:.2%}")
            print(f"    标签F1: {v2_m.label_f1:.3f} → {so_m.label_f1:.3f} → {v36_m.label_f1:.3f}")
