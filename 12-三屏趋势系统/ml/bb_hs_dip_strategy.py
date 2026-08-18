"""v3.2 布林带+头肩底 抄底策略

三层抄底架构：
1. 周线MA200 → 判断抄底大区域
2. 布林带 → 底部震荡高抛低吸，降低持仓成本
3. 头肩底 → 确认最终底部，加满仓位（量变→质变）

只优化抄底模块，其他逻辑完全沿用v2。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class BBSHeadShoulderBottomStrategy(EnhancedMA200Strategy):
    """布林带+头肩底 抄底增强版 v3.2

    基于v2，仅优化抄底模块：
    - 周线MA200作为抄底大区域判断
    - 日线布林带在底部做高抛低吸
    - 头肩底形态确认后加满仓
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
        # 抄底基础参数
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 1.0,
        # 布林带参数
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_buy_position: float = 0.15,
        bb_sell_ratio: float = 0.3,
        # 头肩底参数
        hs_lookback: int = 60,
        hs_min_depth_pct: float = 0.05,
        hs_neckline_break_pct: float = 0.02,
        hs_max_position: float = 1.0,
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
            bear_short_level1_pct=bear_short_level1_pct,
            bear_short_level2_pct=bear_short_level2_pct,
            fib_take_profit=fib_take_profit,
            fib_levels=fib_levels,
            alt_bear_no_trade=alt_bear_no_trade,
        )
        self.name = "bb_hs_dip_v32"

        # 布林带
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_buy_position = bb_buy_position
        self.bb_sell_ratio = bb_sell_ratio

        # 头肩底
        self.hs_lookback = hs_lookback
        self.hs_min_depth_pct = hs_min_depth_pct
        self.hs_neckline_break_pct = hs_neckline_break_pct
        self.hs_max_position = hs_max_position

        self.stats.update({
            "bb_buy_days": 0,
            "bb_sell_days": 0,
            "hs_confirmed_days": 0,
            "dip_bb_days": 0,
        })

    def _compute_bollinger_bands(self, close: np.ndarray) -> tuple:
        """计算布林带"""
        n = len(close)
        mid = np.full(n, np.nan)
        upper = np.full(n, np.nan)
        lower = np.full(n, np.nan)

        for i in range(self.bb_period - 1, n):
            window = close[i - self.bb_period + 1:i + 1]
            m = np.mean(window)
            s = np.std(window)
            mid[i] = m
            upper[i] = m + self.bb_std * s
            lower[i] = m - self.bb_std * s

        return upper, mid, lower

    def _detect_head_shoulder_bottom(
        self, close: np.ndarray, i: int
    ) -> bool:
        """简化版头肩底/双底检测

        简化逻辑：在lookback窗口内，找到两个明显的低点（左右肩/双底），
        且当前价格突破两个低点之间的高点（颈线）。

        返回 True 表示头肩底/双底形态已确认
        """
        if i < self.hs_lookback:
            return False

        window = close[i - self.hs_lookback + 1:i + 1]
        n = len(window)

        # 找最低点（头部）
        low_idx = np.argmin(window)
        low_price = window[low_idx]

        # 深度不够，不算
        window_high = np.max(window)
        depth = (window_high - low_price) / window_high
        if depth < self.hs_min_depth_pct:
            return False

        # 找左半部分的低点（左肩/左底）
        left_half = window[:max(1, low_idx)]
        if len(left_half) < 3:
            return False
        left_low_idx = np.argmin(left_half)
        left_low = left_half[left_low_idx]

        # 找右半部分的低点（右肩/右底）
        right_half = window[low_idx + 1:]
        if len(right_half) < 3:
            return False
        right_low_idx = low_idx + 1 + np.argmin(right_half)
        right_low = window[right_low_idx]

        # 两个低点（左右底）高度接近（相差不超过50%的总深度）
        lows_diff_pct = abs(left_low - right_low) / max(left_low, right_low)
        if lows_diff_pct > depth * 0.5:
            return False

        # 颈线 = 两个低点之间的高点
        if right_low_idx <= low_idx + 1:
            return False
        mid_segment = window[low_idx + 1:right_low_idx]
        if len(mid_segment) < 2:
            return False
        neckline = np.max(mid_segment)

        # 当前价格突破颈线
        current_price = window[-1]
        if current_price > neckline * (1 + self.hs_neckline_break_pct):
            return True

        return False

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values
        high = prices["high"].values
        low = prices["low"].values

        # 计算指标
        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values

        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100

        weekly_ma200 = self._compute_weekly_ma200(prices) if (self.is_btc and self.weekly_ma200_dip_buy) else None
        btc_regime = self._compute_btc_regime() if (not self.is_btc and self.alt_bear_no_trade) else None

        # 布林带
        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close)

        last_state = "init"
        short_entry_price = None

        # 抄底状态
        dip_base_position = 0.0  # 基准抄底仓位
        hs_confirmed = False  # 头肩底是否已确认
        hs_position = 0.0  # 头肩底加仓后的仓位
        bb_position = 0.0  # 布林带动态调整的仓位

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
                # === BTC 策略逻辑 ===

                if price_above and slope_pos:
                    # 牛市：价格在MA200上方且斜率为正 → 满仓
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None

                    # 重置抄底状态
                    dip_base_position = 0.0
                    hs_confirmed = False
                    hs_position = 0.0
                    bb_position = 0.0

                elif not price_above:
                    # 价格在MA200下方 → 可能抄底或做空
                    in_dip_zone = False
                    dip_base_position = 0.0

                    # 第一层：周线MA200判断是否在抄底区域
                    if (self.weekly_ma200_dip_buy
                        and not np.isnan(weekly_ma200[i])
                        and weekly_ma200[i] > 0):

                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100

                        if weekly_below_pct > 0:
                            # 在周线MA200下方 → 抄底区域
                            in_dip_zone = True

                            # 基础抄底仓位：越跌越买（最多到 bb_buy_position）
                            # 这里用较轻的基础仓位，主要靠布林带和头肩底加仓
                            depth_ratio = min(weekly_below_pct / 20.0, 1.0)
                            dip_base_position = self.bb_buy_position * depth_ratio

                    if in_dip_zone:
                        # === 抄底模式 ===
                        current_state = "dip_buy"
                        short_entry_price = None

                        # 第二层：布林带高抛低吸
                        if not np.isnan(bb_upper[i]) and not np.isnan(bb_lower[i]):
                            # 价格触及布林带下轨 → 加仓买入
                            if close[i] <= bb_lower[i]:
                                bb_position = min(
                                    bb_position + self.bb_buy_position,
                                    self.dip_buy_max_position * 0.6
                                )
                                self.stats["bb_buy_days"] += 1

                            # 价格触及布林带上轨 → 减仓卖出
                            elif close[i] >= bb_upper[i] and bb_position > 0:
                                bb_position = bb_position * (1.0 - self.bb_sell_ratio)
                                bb_position = max(bb_position, 0.0)
                                self.stats["bb_sell_days"] += 1

                        # 第三层：头肩底确认 → 加满仓
                        if not hs_confirmed:
                            if self._detect_head_shoulder_bottom(close, i):
                                hs_confirmed = True
                                hs_position = self.hs_max_position
                                self.stats["hs_confirmed_days"] += 1

                        # 综合仓位 = max(基础仓位 + 布林带仓位, 头肩底满仓)
                        if hs_confirmed:
                            target_pos = hs_position
                        else:
                            target_pos = min(
                                dip_base_position + bb_position,
                                self.dip_buy_max_position * 0.7
                            )

                        self.stats["dip_buy_days"] += 1
                        if bb_position > 0 or hs_confirmed:
                            self.stats["dip_bb_days"] += 1

                    else:
                        # === 不在抄底区域 → 做空 ===
                        hs_confirmed = False
                        hs_position = 0.0
                        bb_position = 0.0
                        dip_base_position = 0.0

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
                    # 价格在MA200上方但斜率不明确 → 震荡
                    current_state = "sideways"
                    target_pos = 0.0
                    self.stats["sideways_days"] += 1
                    short_entry_price = None

                    # 保持抄底状态（可能还在确认中）
                    if hs_confirmed:
                        target_pos = hs_position * 0.5  # 减半持有观察

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
    import json
    from backtest.engine import BacktestEngine
    from ml.scenario_backtest_engine import ScenarioBacktestEngine

    with open("data/historical/BTC_1D_730d.json") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("timestamp")
    prices = df[["o", "h", "l", "c", "vol"]].rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
    )

    # 快速测试
    print("⏳ 测试 v3.2 布林带+头肩底 抄底策略...")
    strategy = BBSHeadShoulderBottomStrategy(is_btc=True)
    signals = strategy.generate_signals(prices)

    engine = BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.001)
    result = engine.run(prices["close"], signals)

    print(f"总收益: {result['metrics']['total_return_pct']:.2%}")
    print(f"夏普: {result['metrics']['sharpe_ratio']:.3f}")
    print(f"最大回撤: {result['metrics']['max_drawdown_pct']:.2%}")
    print(f"交易次数: {len(result['trades'])}")
    print()
    print("状态统计:")
    for k, v in sorted(strategy.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")
