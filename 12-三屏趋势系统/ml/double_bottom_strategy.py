"""v3.7 优化双底检测 + 布林带只加仓策略

核心改进：
1. 双底检测升级：
   - 用swing low（局部低点）替代简单argmin
   - 要求右底 >= 左底（底部抬升，确认趋势转好）
   - 颈线突破需要站稳N天
   - 加入成交量放大确认（可选）

2. 布林带只加仓：
   - 触及下轨 → 加仓（底部只加不减）
   - 不在上轨卖出（避免卖飞）

3. 结合做空优化（L1=0, L2=0.6）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from backtest.strategy import EnhancedMA200Strategy


class DoubleBottomDipStrategy(EnhancedMA200Strategy):
    """v3.7 优化双底检测 + 布林带只加仓"""

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
        # 布林带只加仓参数
        use_bb_add: bool = True,
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_lower_add_pct: float = 0.10,  # 触及下轨额外加10%
        bb_lower_deep_add_pct: float = 0.15,  # 跌破下轨2%额外再加15%
        # 双底检测参数
        use_double_bottom: bool = True,
        db_lookback: int = 60,  # 回看窗口
        db_swing_window: int = 5,  # 局部低点窗口（左右各5天）
        db_min_depth_pct: float = 0.08,  # 最小深度8%
        db_max_low_diff_pct: float = 0.05,  # 两低点高度差不超过5%
        db_neckline_break_pct: float = 0.02,  # 突破颈线2%
        db_confirm_days: int = 3,  # 突破后站稳N天确认
        db_boost_pct: float = 0.15,  # 双底确认后加仓15%
        # 做空参数（优化版）
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
        self.name = "double_bottom_v37"

        self.use_bb_add = use_bb_add
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_lower_add_pct = bb_lower_add_pct
        self.bb_lower_deep_add_pct = bb_lower_deep_add_pct

        self.use_double_bottom = use_double_bottom
        self.db_lookback = db_lookback
        self.db_swing_window = db_swing_window
        self.db_min_depth_pct = db_min_depth_pct
        self.db_max_low_diff_pct = db_max_low_diff_pct
        self.db_neckline_break_pct = db_neckline_break_pct
        self.db_confirm_days = db_confirm_days
        self.db_boost_pct = db_boost_pct

        self.stats.update({
            "bb_lower_add_days": 0,
            "bb_lower_deep_add_days": 0,
            "bb_rebound_add_days": 0,
            "double_bottom_detected_days": 0,
            "double_bottom_confirmed_days": 0,
            "double_bottom_failed_days": 0,
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

    def _find_swing_lows(self, low: np.ndarray, start: int, end: int) -> list:
        """寻找局部低点（swing lows）

        一个swing low是指：某点的low值比左右各swing_window天的low都低。
        返回 [(idx_in_window, price), ...] 按时间顺序
        """
        w = self.db_swing_window
        swing_lows = []
        for i in range(start + w, end - w + 1):
            left = low[i - w:i]
            right = low[i + 1:i + w + 1]
            if low[i] < left.min() and low[i] <= right.min():
                swing_lows.append((i, low[i]))
        return swing_lows

    def _detect_double_bottom(
        self,
        low: np.ndarray,
        close: np.ndarray,
        i: int,
        last_db_breakout_idx: int,
    ) -> tuple:
        """检测双底形态（严格版）

        只在首次突破颈线时返回detected=True。

        Args:
            last_db_breakout_idx: 上次双底突破的索引，用于判断是否为"首次突破"

        Returns:
            (detected: bool, confirmed: bool)
            - detected: 首次突破颈线
            - confirmed: 突破后站稳N天
        """
        if i < self.db_lookback:
            return False, False

        start = i - self.db_lookback + 1
        end = i + 1

        # 找swing lows
        swing_lows = self._find_swing_lows(low, start, end)
        if len(swing_lows) < 2:
            return False, False

        # 取最低点作为第一底（头部）
        swing_lows_sorted_by_price = sorted(swing_lows, key=lambda x: x[1])
        first_low = swing_lows_sorted_by_price[0]
        idx1, price1 = first_low

        # 找第二底：必须在第一底之后，且与第一底间隔至少20天
        # 取第一底之后、距离最远的那个swing low作为候选第二底
        candidates = [
            (idx, p) for idx, p in swing_lows
            if idx > idx1 + 20 and abs(p - price1) / price1 < self.db_max_low_diff_pct * 3
        ]
        if not candidates:
            # 也尝试在第一底之前找
            candidates = [
                (idx, p) for idx, p in swing_lows
                if idx < idx1 - 20 and abs(p - price1) / price1 < self.db_max_low_diff_pct * 3
            ]
            if candidates:
                # 第一个底变成右底，原来的第一底变成第二底
                second_low = first_low
                first_low = max(candidates, key=lambda x: x[0])  # 取最靠右的
                idx1, price1 = first_low
                idx2, price2 = second_low
            else:
                return False, False
        else:
            # 取候选中价格最低的作为第二底
            second_low = min(candidates, key=lambda x: x[1])
            idx2, price2 = second_low

        # 确保 idx1 < idx2
        if idx1 > idx2:
            idx1, idx2 = idx2, idx1
            price1, price2 = price2, price1

        # 两低点间隔至少20天
        if idx2 - idx1 < 20:
            return False, False

        # 深度检查
        window_high = low[start:end].max()
        depth = (window_high - min(price1, price2)) / window_high
        if depth < self.db_min_depth_pct:
            return False, False

        # 两低点高度差检查（双底的核心：两底接近）
        low_diff_pct = abs(price1 - price2) / max(price1, price2)
        if low_diff_pct > self.db_max_low_diff_pct:
            return False, False

        # 右底应该 >= 左底（底部抬升）
        right_higher = price2 >= price1 * (1 - self.db_max_low_diff_pct * 0.5)

        # 颈线 = 两低点之间的最高点
        mid_segment = low[idx1 + 1:idx2]
        if len(mid_segment) < 2:
            return False, False
        neckline = mid_segment.max()

        # 颈线至少比低点高一定幅度
        min_neckline_lift = min(price1, price2) * (1 + self.db_min_depth_pct * 0.5)
        if neckline < min_neckline_lift:
            return False, False

        # 当前价格突破颈线
        breakout_price = neckline * (1 + self.db_neckline_break_pct)
        if close[i] <= breakout_price:
            return False, False

        # 关键：只在首次突破时返回detected=True
        # 如果上次突破就在最近（<5天前），说明不是首次突破
        if last_db_breakout_idx >= 0 and (i - last_db_breakout_idx) < 5:
            # 不是首次突破，但检查是否已经确认
            if i - last_db_breakout_idx >= self.db_confirm_days:
                # 检查是否站稳
                hold_above = True
                for j in range(last_db_breakout_idx, min(last_db_breakout_idx + self.db_confirm_days, i + 1)):
                    if close[j] < neckline:
                        hold_above = False
                        break
                if hold_above and right_higher:
                    return False, True  # 已确认
            return False, False

        # 首次突破
        detected = True

        # 确认：突破后站稳N天
        confirmed = False
        if self.db_confirm_days <= 1:
            confirmed = right_higher
        # 如果已经过了确认期，检查是否站稳
        elif i - last_db_breakout_idx >= self.db_confirm_days if last_db_breakout_idx >= 0 else False:
            hold_above = True
            for j in range(i - self.db_confirm_days + 1, i + 1):
                if close[j] < neckline:
                    hold_above = False
                    break
            if hold_above and right_higher:
                confirmed = True

        return detected, confirmed

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

        bb_upper, bb_mid, bb_lower = self._compute_bollinger_bands(close) if self.use_bb_add else (None, None, None)

        last_state = "init"
        short_entry_price = None

        # 双底确认状态
        db_confirmed = False
        db_confirmed_idx = -1
        db_neckline_price = 0.0  # 记录颈线价格，用于止损

        # 布林带加仓冷却（避免连续加仓）
        last_bb_add_idx = -100
        bb_min_gap = 3

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
                    db_confirmed = False
                    db_neckline_price = 0.0

                elif not price_above:
                    # 价格在MA200下方
                    if base_dip_pos > 0:
                        # === 抄底模式 ===
                        current_state = "dip_buy"
                        short_entry_price = None
                        extra_pos = 0.0

                        # 布林带反弹加仓（只加不减）
                        # 逻辑：昨天触及/跌破下轨，今天从下轨反弹 → 确认短期底部 → 加仓
                        if self.use_bb_add and bb_lower is not None and not np.isnan(bb_lower[i]) and i > 0:
                            yesterday_at_or_below = close[i-1] <= bb_lower[i-1] if not np.isnan(bb_lower[i-1]) else False
                            today_rebounded = close[i] > bb_lower[i]
                            if yesterday_at_or_below and today_rebounded and (i - last_bb_add_idx) >= bb_min_gap:
                                extra_pos += self.bb_lower_add_pct
                                self.stats["bb_rebound_add_days"] += 1
                                last_bb_add_idx = i

                            # 深跌后反弹 → 更大加仓
                            if not np.isnan(bb_lower[i-1]) and close[i-1] <= bb_lower[i-1] * 0.98:
                                if today_rebounded and (i - last_bb_add_idx) >= bb_min_gap:
                                    extra_pos += self.bb_lower_deep_add_pct
                                    self.stats["bb_lower_deep_add_days"] += 1
                                    last_bb_add_idx = i

                        # 双底检测
                        if self.use_double_bottom and not db_confirmed:
                            detected, confirmed = self._detect_double_bottom(low, close, i, db_confirmed_idx)
                            if detected:
                                self.stats["double_bottom_detected_days"] += 1
                                db_confirmed_idx = i  # 记录突破日
                                # 计算并记录颈线价格
                                start_db = i - self.db_lookback + 1
                                swing_lows = self._find_swing_lows(low, start_db, i + 1)
                                if len(swing_lows) >= 2:
                                    sorted_by_price = sorted(swing_lows, key=lambda x: x[1])
                                    fl_idx, fl_price = sorted_by_price[0]
                                    cands = [(idx, p) for idx, p in swing_lows if abs(idx - fl_idx) >= 20 and abs(p - fl_price) / fl_price < self.db_max_low_diff_pct * 3]
                                    if cands:
                                        sl_idx, sl_price = min(cands, key=lambda x: x[1])
                                        if fl_idx < sl_idx:
                                            db_neckline_price = low[fl_idx+1:sl_idx].max()
                                        else:
                                            db_neckline_price = low[sl_idx+1:fl_idx].max()
                            if confirmed:
                                db_confirmed = True
                                self.stats["double_bottom_confirmed_days"] += 1

                        # 双底确认后加仓，但如果跌回颈线下方则撤销
                        if db_confirmed and db_neckline_price > 0:
                            if close[i] < db_neckline_price * 0.98:
                                # 跌回颈线下方，撤销双底确认
                                db_confirmed = False
                                db_neckline_price = 0.0
                                self.stats["double_bottom_failed_days"] = self.stats.get("double_bottom_failed_days", 0) + 1
                            else:
                                extra_pos += self.db_boost_pct

                        # 总仓位 = 基础 + 布林带加仓 + 双底加成
                        max_pos = (
                            self.dip_buy_max_position
                            + self.bb_lower_add_pct
                            + self.bb_lower_deep_add_pct
                            + self.db_boost_pct
                        )
                        target_pos = min(base_dip_pos + extra_pos, max_pos)

                        self.stats["dip_buy_days"] += 1

                    else:
                        # === 做空模式（优化版：只有L2）===
                        db_confirmed = False
                        db_neckline_price = 0.0

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
                    # 价格在MA200上方但斜率不为正
                    if base_dip_pos > 0:
                        current_state = "dip_buy"
                        extra_pos = 0.0
                        # 双底确认后加仓，但如果跌回颈线下方则撤销
                        if db_confirmed and db_neckline_price > 0:
                            if close[i] < db_neckline_price * 0.98:
                                db_confirmed = False
                                db_neckline_price = 0.0
                                self.stats["double_bottom_failed_days"] = self.stats.get("double_bottom_failed_days", 0) + 1
                            else:
                                extra_pos += self.db_boost_pct
                        target_pos = min(base_dip_pos + extra_pos, self.dip_buy_max_position + self.db_boost_pct)
                        self.stats["dip_buy_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
                        db_confirmed = False
                        db_neckline_price = 0.0

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
    v2_r = engine.run_scenario_backtest(prices, v2, "v2", symbol="BTC", experiment_name="v37_v2")
    print(f"  夏普 {v2_r.overall_sharpe:.3f} | 收益 {v2_r.overall_total_return:.1%} | 评分 {v2_r.composite_score:.3f}")

    print()
    print("做空优化版（L1=0, L2=0.6）...")
    so = EnhancedMA200Strategy(is_btc=True, bear_short_level1_pct=0.0, bear_short_level2_pct=0.6)
    so_r = engine.run_scenario_backtest(prices, so, "short_opt", symbol="BTC", experiment_name="v37_short_opt")
    print(f"  夏普 {so_r.overall_sharpe:.3f} | 收益 {so_r.overall_total_return:.1%} | 评分 {so_r.composite_score:.3f}")

    print()
    print("v3.7 双底检测 + 布林带只加仓...")
    v37 = DoubleBottomDipStrategy(is_btc=True)
    v37_r = engine.run_scenario_backtest(prices, v37, "v37", symbol="BTC", experiment_name="v37_double_bottom")
    print(f"  夏普 {v37_r.overall_sharpe:.3f} | 收益 {v37_r.overall_total_return:.1%} | 评分 {v37_r.composite_score:.3f}")

    print()
    print("状态统计:")
    for k, v in sorted(v37.get_stats().items(), key=lambda x: -x[1]):
        if v > 0:
            print(f"  {k}: {v}")

    print()
    print("=" * 70)
    print("📊 三方对比：")
    print(f"{'指标':<18} {'v2':>12} {'做空优化':>12} {'v3.7':>12}")
    print("-" * 70)
    metrics = [
        ("总收益", v2_r.overall_total_return, so_r.overall_total_return, v37_r.overall_total_return, ".1%"),
        ("夏普比率", v2_r.overall_sharpe, so_r.overall_sharpe, v37_r.overall_sharpe, ".3f"),
        ("卡玛比率", v2_r.overall_calmar, so_r.overall_calmar, v37_r.overall_calmar, ".3f"),
        ("最大回撤", v2_r.overall_max_drawdown, so_r.overall_max_drawdown, v37_r.overall_max_drawdown, ".1%"),
        ("胜率", v2_r.overall_win_rate, so_r.overall_win_rate, v37_r.overall_win_rate, ".2%"),
        ("综合评分", v2_r.composite_score, so_r.composite_score, v37_r.composite_score, ".3f"),
    ]
    for name, v2_val, so_val, v37_val, fmt in metrics:
        print(f"{name:<18} {v2_val:>12{fmt}} {so_val:>12{fmt}} {v37_val:>12{fmt}}")
