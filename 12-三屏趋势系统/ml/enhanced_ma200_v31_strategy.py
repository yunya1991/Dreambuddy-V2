"""v3.1 策略：精准抄底优化

思路：保持v2的主体逻辑不变（牛市满仓、熊市分级做空、斐波那契止盈），
仅对抄底模块做精细化优化：

1. 抄底入场：保留周线MA200越跌越买的核心逻辑
2. 抄底加仓节奏：优化档位和步长
3. 抄底离场：新增"站上日线MA200且斜率转正"作为抄底结束信号
4. 其他模块完全沿用v2（不引入逃顶新逻辑）

目标：验证"抄底优化"本身能否带来整体收益提升。
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class EnhancedMA200V31Strategy(EnhancedMA200Strategy):
    """v3.1 精准抄底优化版

    基于v2，仅优化抄底模块：
    - 更细的抄底档位（6档，每3%一档）
    - 初始轻仓试探（10%起步）
    - 站上MA200且斜率转正 → 抄底结束，转入牛市满仓
    - 其他完全沿用v2
    """

    def __init__(
        self,
        # 沿用v2参数
        ma_period: int = 200,
        slope_period: int = 5,
        max_position: float = 1.0,
        warmup_periods: int = 210,
        symbol: str = "BTC",
        is_btc: bool = True,
        btc_prices: pd.DataFrame = None,
        # 抄底优化参数
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.9,
        dip_buy_levels: int = 6,
        dip_buy_step_pct: float = 3.0,
        dip_buy_initial_ratio: float = 0.15,
        dip_buy_end_on_breakout: bool = True,
        # 沿用v2其他参数
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
        self.name = "enhanced_ma200_v31"
        self.dip_buy_initial_ratio = dip_buy_initial_ratio
        self.dip_buy_end_on_breakout = dip_buy_end_on_breakout
        self.stats["dip_buy_end_days"] = 0

    def _calc_dip_position(self, weekly_below_pct: float) -> float:
        """计算抄底仓位

        初始轻仓 + 越跌越买的线性加仓
        """
        if weekly_below_pct <= 0:
            return 0.0

        levels_filled = min(
            int(weekly_below_pct / self.dip_buy_step_pct),
            self.dip_buy_levels
        )
        if levels_filled <= 0:
            return 0.0

        # 第1档：初始仓位（dip_buy_initial_ratio * max_position）
        # 第2~N档：均匀分配剩余仓位
        initial_pos = self.dip_buy_initial_ratio * self.dip_buy_max_position
        if levels_filled == 1:
            return initial_pos

        remaining_levels = levels_filled - 1
        total_levels = self.dip_buy_levels - 1
        remaining_pct = self.dip_buy_max_position - initial_pos
        add_pos = (remaining_levels / total_levels) * remaining_pct

        return min(initial_pos + add_pos, self.dip_buy_max_position)

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

        last_state = "init"
        short_entry_price = None
        in_dip_buy = False  # 是否处于抄底状态

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
                    # 牛市：价格在MA200上方且斜率为正
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None

                    # 如果之前在抄底，这里算作"抄底结束"
                    if in_dip_buy:
                        self.stats["dip_buy_end_days"] += 1
                        in_dip_buy = False

                elif not price_above:
                    # 价格在MA200下方
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        dip_buy_pos = self._calc_dip_position(weekly_below_pct)

                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None
                        in_dip_buy = True
                    else:
                        # 没有抄底信号 → 做空
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

                        in_dip_buy = False
                else:
                    # 价格在MA200上方但斜率不为正（震荡）
                    # v2逻辑：如果有抄底信号则抄底，否则空仓
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        dip_buy_pos = self._calc_dip_position(weekly_below_pct)

                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None
                        in_dip_buy = True
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        in_dip_buy = False
            else:
                # 小币沿用v2逻辑
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
    from backtest.engine import BacktestEngine

    with open("data/historical/BTC_1D_730d.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )

    # v2
    v2 = EnhancedMA200Strategy(is_btc=True)
    v2_signals = v2.generate_signals(prices)
    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    v2_result = engine.run(prices["close"], v2_signals)

    # v3.1
    v31 = EnhancedMA200V31Strategy(is_btc=True)
    v31_signals = v31.generate_signals(prices)
    v31_result = engine.run(prices["close"], v31_signals)

    print("v2 vs v3.1 对比（BTC日线）")
    print("=" * 60)
    print(f"{'指标':<15} {'v2':>12} {'v3.1':>12}")
    print("-" * 60)
    print(f"{'总收益':<15} {v2_result['metrics']['total_return_pct']:>12.2%} {v31_result['metrics']['total_return_pct']:>12.2%}")
    print(f"{'夏普':<15} {v2_result['metrics']['sharpe_ratio']:>12.3f} {v31_result['metrics']['sharpe_ratio']:>12.3f}")
    print(f"{'最大回撤':<15} {v2_result['metrics']['max_drawdown_pct']:>12.2%} {v31_result['metrics']['max_drawdown_pct']:>12.2%}")
    print(f"{'交易次数':<15} {len(v2_result['trades']):>12} {len(v31_result['trades']):>12}")
    print()
    print("v3.1 状态统计:")
    for k, v in sorted(v31.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")
