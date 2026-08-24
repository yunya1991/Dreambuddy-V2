"""ScoreComposer — Phase 0 Layer 2 Level/Trend 合成 + 钳制（Spec §2.4 规则 1-2）

两步：
  1) Unbound 加权：Σ( weight × contribution ) / Σ( weight )
  2) 9 格扩展：线性 × 4 → 钳制到 [-4, +4]
  3) 每日 clamp_delta：
       - 常规日 |ΔL|, |ΔT| ≤ max_daily_delta（默认 0.5）
       - 日收益 |pct_change| ≥ extreme_threshold（默认 8%）→ 放宽到 extreme_delta（默认 1.0）
       - 量能 ratio ≥ 1.5 额外 × 1.2 放宽
  4) Sperandeo 1-2-3 渐进式趋势反转调整（Spec §2.4 规则 2）：
       - 牛市反转：① close 突破下降趋势线 → +0.33
                    ② 回撤不破前低 → +0.33
                    ③ close 突破前高 → +0.34 (累计 +1.0)
       - 熊市反转同理（-1.0）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from bcrm2.indicators import _detect_swings

__all__ = ["ScoreComposer", "DEFAULT_LEVEL_WEIGHTS", "DEFAULT_TREND_WEIGHTS"]


# ================================================================
# 模块级辅助函数
# ================================================================

def _trend_line_val(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """线性外推：通过 (x1,y1) 和 (x2,y2) 的直线在 x 处的值。

    公式：y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    当 x1 == x2（退化情况）返回 y1。
    """
    if x2 == x1:
        return y1
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


# ================================================================
# 默认权重（Spec §2.2-2.3）
# ================================================================

# Level 6 指标（L1..L6），对应 contribution 值为 indicators 中 key 的值本身，
# 因为 indicators 已经做了 ± 映射，权重仅对大小归一化。
DEFAULT_LEVEL_WEIGHTS: Dict[str, float] = {
    "ma200_above_3d":      2.0,   # L1 → ±1
    "ma50_above":          1.0,   # L2 → ±0.5  → 权重 1 对应总贡献 ±0.5
    "ma20_vs_ma50_order":  1.0,   # L3 → ±0.5
    "cycle_position_365d": 1.2,   # L4 → ±0.5
    "ma_alignment_score":  1.5,   # L5 → ±1.0（限幅后）
    "ma200_slope_signed":  1.0,   # L6 → ±0.5
}

DEFAULT_TREND_WEIGHTS: Dict[str, float] = {
    "dow_hhhl_score":      2.0,   # T1 → ±2
    "log_ret_90d":         1.5,   # T2 → ±1
    "log_ret_30d":         1.0,   # T3 → ±0.5
    "ma_slope_wavg":       1.2,   # T4 → ±1（tanh 后）
    "volume_trend_conf":   1.0,   # T5 → ±0.5
}


# ================================================================
# 主类
# ================================================================

@dataclass
class ScoreComposer:
    """Level/Trend 双维度合成 + 每日钳制。"""

    level_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LEVEL_WEIGHTS))
    trend_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TREND_WEIGHTS))

    # 钳制超参（Spec §2.4 规则 1）
    #   选取保守默认值以确保真实 BTC 全样本 |ΔL+ΔT| p99 ≤ 1.0：
    #     常规日 0.4+0.4=0.8 / 放量 0.48+0.48=0.96 / 极端日 0.7+0.7=1.4（仅 <1% 样本触发）
    max_daily_delta: float = 0.4       # 常规日 |Δ| 上限
    extreme_threshold: float = 0.08    # 日涨跌幅≥8% → 视为极端日
    extreme_delta: float = 0.7         # 极端日 |Δ| 上限
    volume_amplify_ratio: float = 1.5  # 量能放量 ≥ 1.5 再放宽 1.2 倍

    # 9 格扩展倍数：归一化合成 × grid_scale 得到 [-4, +4] 区间
    grid_scale: float = 4.0

    # Sperandeo 1-2-3 渐进式趋势反转调整开关（Spec §2.4 规则 2）
    #   True  → compose() 在 clamp_delta 之后叠加 Sperandeo 调整
    #   False → compose() 输出与原规则 1 完全一致（回滚兼容）
    sperandeo_enabled: bool = True

    # Sperandeo swing 检测窗口（传入 apply_sperandeo_adjustment）
    sperandeo_swing_window: int = 5

    # ===== 公共 API =====
    def compose(self, indicators: Dict[str, pd.Series],
                df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """返回 (level_series, trend_series)，长度与 df.index 对齐。"""
        close = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1], index=df.index)
        close = close.astype(float)
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=close.index)
        high = df["high"].astype(float) if "high" in df.columns else close * 1.001
        low = df["low"].astype(float) if "low" in df.columns else close * 0.999

        n = len(close)
        if n == 0:
            return (pd.Series(dtype=float), pd.Series(dtype=float))

        # step 1 + 2: 加权归一化 + 9 格扩展
        level_unbound = self._weighted_sum(indicators, self.level_weights) * self.grid_scale
        trend_unbound = self._weighted_sum(indicators, self.trend_weights) * self.grid_scale
        # 钳制到 [-4, +4] 作为 raw
        level_raw = np.clip(np.asarray(level_unbound, dtype=float),
                            -self.grid_scale, self.grid_scale)
        trend_raw = np.clip(np.asarray(trend_unbound, dtype=float),
                            -self.grid_scale, self.grid_scale)

        # step 3: 每日 clamp_delta（序列连续化）
        level_smooth = np.empty(n, dtype=float)
        trend_smooth = np.empty(n, dtype=float)

        # 前置：日收益 & 量能 ratio（20 日均量）
        pct_change_arr = close.pct_change().fillna(0.0).values.astype(float)
        vol_ma20 = volume.rolling(20, min_periods=10).mean().replace(0, np.nan).fillna(1.0)
        vol_ratio_arr = (volume / vol_ma20).replace([np.inf, -np.inf], np.nan).fillna(1.0).values.astype(float)

        L_prev = float(np.nan_to_num(level_raw[0], nan=0.0))
        T_prev = float(np.nan_to_num(trend_raw[0], nan=0.0))
        level_smooth[0] = L_prev
        trend_smooth[0] = T_prev

        for i in range(1, n):
            # 当日目标 raw
            L_target = float(level_raw[i])
            T_target = float(trend_raw[i])

            # 根据日涨跌幅 & 量能决定允许的最大每日变化
            #   规则：极端日（≥8%）→ extreme_delta；其他 → max_daily_delta。
            #         量能放量 ≥ 1.5 仅在非极端日时放宽（避免 8% 大跌+放量叠加过松）。
            base_L_limit = self.max_daily_delta
            base_T_limit = self.max_daily_delta
            extreme = abs(pct_change_arr[i]) >= self.extreme_threshold
            if extreme:
                base_L_limit = self.extreme_delta
                base_T_limit = self.extreme_delta
            elif vol_ratio_arr[i] >= self.volume_amplify_ratio:
                # 非极端日放量：放宽到 1.2 × max_daily_delta；但上限不超过 extreme_delta
                amp = min(self.max_daily_delta * 1.2, self.extreme_delta)
                base_L_limit = amp
                base_T_limit = amp

            # 钳制：L_smooth_i 在 [L_prev - limit, L_prev + limit] 内最靠近 target
            L_new = float(np.clip(L_target, L_prev - base_L_limit, L_prev + base_L_limit))
            T_new = float(np.clip(T_target, T_prev - base_T_limit, T_prev + base_T_limit))

            level_smooth[i] = L_new
            trend_smooth[i] = T_new
            L_prev, T_prev = L_new, T_new

        # step 4: Sperandeo 1-2-3 渐进式趋势反转调整（Spec §2.4 规则 2）
        #   在 clamp_delta 之后叠加，仅调整 trend_smooth，不影响 level_smooth
        if self.sperandeo_enabled:
            trend_smooth = self.apply_sperandeo_adjustment(
                level_smooth, trend_smooth,
                high.values, low.values, close.values,
                swing_window=self.sperandeo_swing_window,
            )

        return (pd.Series(level_smooth, index=close.index),
                pd.Series(trend_smooth, index=close.index))

    # ===== 内部 =====
    @staticmethod
    def _weighted_sum(indicators: Dict[str, pd.Series],
                      weights: Dict[str, float]) -> np.ndarray:
        """Σ w_i * x_i / Σ w_i。缺失指标用 0 填充。"""
        keys = list(weights.keys())
        if not keys:
            raise ValueError("weights 不能为空")
        n = len(indicators[keys[0]]) if keys else 0
        acc = np.zeros(n, dtype=float)
        wsum = 0.0
        for k, w in weights.items():
            w = float(w)
            if abs(w) < 1e-15:
                continue
            if k in indicators:
                x = np.asarray(indicators[k], dtype=float)
                x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            else:
                x = np.zeros(n, dtype=float)
            acc += w * x
            wsum += abs(w)
        if wsum < 1e-12:
            return np.zeros(n, dtype=float)
        return acc / wsum

    # ===== Sperandeo 1-2-3 趋势反转调整 =====
    @staticmethod
    def apply_sperandeo_adjustment(
        level_smooth: np.ndarray,
        trend_smooth: np.ndarray,
        high,
        low,
        close,
        swing_window: int = 5,
    ) -> np.ndarray:
        """Sperandeo 1-2-3 渐进式趋势反转调整（Spec §2.4 规则 2）。

        牛市反转（下降趋势 → 上升趋势）:
          ① close 突破下降趋势线(SH_prev→SH_last) → Trend +0.33
          ② 回撤不破前低(SL_last) → Trend +0.33
          ③ close 突破前高(SH_last) → Trend +0.34 (累计 +1.0)

        熊市反转同理（-1.0）。不满足 = +0，不反向扣分。

        Args:
            level_smooth: clamp_delta 后的 level 数组（当前不修改，预留扩展）。
            trend_smooth: clamp_delta 后的 trend 数组（基准）。
            high/low/close: 价格数组（numpy array 或 list）。
            swing_window: swing 检测窗口，默认 5。

        Returns:
            调整后的 trend 数组，clip 到 [-4, +4]。
        """
        n = len(trend_smooth)
        if n == 0:
            return np.zeros(0, dtype=float)

        # 检测 swing 点（复用 indicators._detect_swings）
        high_arr = np.asarray(high, dtype=float)
        low_arr = np.asarray(low, dtype=float)
        close_arr = np.asarray(close, dtype=float)

        is_sh, is_sl = _detect_swings(
            pd.Series(high_arr), pd.Series(low_arr), lookback=swing_window
        )
        sh_flags = is_sh.values.astype(bool)
        sl_flags = is_sl.values.astype(bool)

        # 调整量数组
        adj = np.zeros(n, dtype=float)

        # 状态机
        SCANNING = 0        # 扫描：寻找两个下降 SH（牛市）或两个上升 SL（熊市）
        WAIT_BREAKOUT = 1   # 等待 close 突破趋势线（条件①）
        WAIT_PULLBACK = 2   # 等待回撤不破前低/前高（条件②）
        WAIT_NEW_EXTREME = 3  # 等待 close 突破前高/前低（条件③）

        state = SCANNING
        direction = 0       # +1 = 牛市反转, -1 = 熊市反转

        # 趋势线两点 (bar, price)：牛市用 SH_prev/SH_last，熊市用 SL_prev/SL_last
        tl_a_bar, tl_a_price = -1, 0.0
        tl_b_bar, tl_b_price = -1, 0.0  # tl_b 也是条件③的突破目标

        # 条件②的测试价：牛市 = SL_last，熊市 = SH_last
        test_price = 0.0

        # 当前累计调整量
        current_adj = 0.0
        breakout_bar = -1  # 条件①满足的 bar

        # Swing high/low 历史（按 bar 顺序）
        sh_hist: list = []  # [(bar, price), ...]
        sl_hist: list = []

        for i in range(n):
            # —— 记录当日 swing 点 ——
            if sh_flags[i]:
                sh_hist.append((i, float(high_arr[i])))
            if sl_flags[i]:
                sl_hist.append((i, float(low_arr[i])))

            # —— 状态机 ——
            if state == SCANNING:
                # 尝试检测牛市反转（两个下降的 SH + SL_last）
                if len(sh_hist) >= 2:
                    sh_prev = sh_hist[-2]
                    sh_last = sh_hist[-1]
                    if sh_prev[1] > sh_last[1] + 1e-9:  # 下降趋势
                        # 找 SH_last 之后的 swing low 作为 SL_last
                        recent_sls = [(b, p) for b, p in sl_hist if b > sh_last[0]]
                        if recent_sls and sh_last[0] < i:
                            state = WAIT_BREAKOUT
                            direction = 1
                            current_adj = 0.0  # 重置前一周期的调整
                            tl_a_bar, tl_a_price = sh_prev
                            tl_b_bar, tl_b_price = sh_last
                            test_price = recent_sls[-1][1]

                # 尝试检测熊市反转（两个上升的 SL + SH_last）
                if state == SCANNING and len(sl_hist) >= 2:
                    sl_prev = sl_hist[-2]
                    sl_last = sl_hist[-1]
                    if sl_prev[1] < sl_last[1] - 1e-9:  # 上升趋势
                        recent_shs = [(b, p) for b, p in sh_hist if b > sl_last[0]]
                        if recent_shs and sl_last[0] < i:
                            state = WAIT_BREAKOUT
                            direction = -1
                            current_adj = 0.0
                            tl_a_bar, tl_a_price = sl_prev
                            tl_b_bar, tl_b_price = sl_last
                            test_price = recent_shs[-1][1]

            elif state == WAIT_BREAKOUT:
                # 计算趋势线在当前 bar 的值
                tl_val = _trend_line_val(
                    tl_a_bar, tl_a_price, tl_b_bar, tl_b_price, i
                )
                if direction == 1 and close_arr[i] > tl_val:
                    # 牛市条件①：close 突破下降趋势线
                    current_adj = 0.33
                    breakout_bar = i
                    state = WAIT_PULLBACK
                elif direction == -1 and close_arr[i] < tl_val:
                    # 熊市条件①：close 跌破上升趋势线
                    current_adj = -0.33
                    breakout_bar = i
                    state = WAIT_PULLBACK

            elif state == WAIT_PULLBACK:
                # 条件②需要在条件①之后至少 1 天才能确认
                if i > breakout_bar:
                    if direction == 1:
                        # 牛市条件②：回撤不破前低(SL_last)
                        if low_arr[i] <= test_price:
                            # 失败：跌破前低 → 重置状态机
                            state = SCANNING
                            direction = 0
                            current_adj = 0.0
                        elif close_arr[i] < close_arr[i - 1]:
                            # 回撤日且不破前低 → 条件②满足
                            current_adj = 0.66
                            state = WAIT_NEW_EXTREME
                    elif direction == -1:
                        # 熊市条件②：反弹不破前高(SH_last)
                        if high_arr[i] >= test_price:
                            # 失败：突破前高 → 重置状态机
                            state = SCANNING
                            direction = 0
                            current_adj = 0.0
                        elif close_arr[i] > close_arr[i - 1]:
                            # 反弹日且不破前高 → 条件②满足
                            current_adj = -0.66
                            state = WAIT_NEW_EXTREME

            elif state == WAIT_NEW_EXTREME:
                if direction == 1:
                    # 牛市条件③：close 突破前高(SH_last)
                    if close_arr[i] > tl_b_price:
                        current_adj = 1.00
                        state = SCANNING
                        direction = 0
                elif direction == -1:
                    # 熊市条件③：close 跌破前低(SL_last)
                    if close_arr[i] < tl_b_price:
                        current_adj = -1.00
                        state = SCANNING
                        direction = 0

            adj[i] = current_adj

        # 合成最终 trend 并 clip 到 [-4, +4]
        result = np.asarray(trend_smooth, dtype=float) + adj
        return np.clip(result, -4.0, 4.0)
