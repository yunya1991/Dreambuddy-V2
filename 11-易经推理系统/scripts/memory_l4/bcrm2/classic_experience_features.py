"""
经典交易经验特征 — 经过市场验证的经验法则的算法落地

理论映射:
  "金融市场虽然变化无序，但漫长交易过程中积累的经验规律是有用的"
  这些特征 = "经验常量" — 被几代交易者验证过的市场结构特征

包含三大类经典经验特征:
  1. 牛熊分界线: 日线/周线MA200, 三日确认原则
  2. Elder-ray指标: Bull Power / Bear Power / 背离检测
  3. 三屏交易系统: 潮汐(长周期)-波浪(中周期)-涟漪(短周期)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


# ============================================================
# 工具函数: 多时间框架重采样
# ============================================================

def _resample_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """将1H数据重采样为日线"""
    daily = df.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return daily


def _resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """将1H数据重采样为周线"""
    weekly = df.resample("1W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return weekly


def _align_to_hourly(daily_val: pd.Series, hourly_index: pd.Index) -> pd.Series:
    """将日线数据对齐回小时线索引（前向填充）"""
    # 重新索引到小时级，前向填充（当日内所有小时用当日的日线值）
    aligned = daily_val.reindex(hourly_index, method="ffill")
    return aligned


# ============================================================
# 1. 牛熊分界线特征
# ============================================================

def bull_bear_line_features(
    df: pd.DataFrame,
    ma_daily_periods: Optional[List[int]] = None,
    ma_weekly_periods: Optional[List[int]] = None,
    confirm_bars: int = 3,  # 三日确认
) -> pd.DataFrame:
    """
    牛熊分界线特征 — MA200等长期均线作为牛熊分界

    经典经验:
      - 日线MA200: 牛熊分界线，站上=牛市，跌破=熊市
      - 周线MA200: 更长期的牛熊分界，站稳=筑底
      - 三日确认原则: 连续3日收在MA200上方/下方才确认转向

    Args:
        df: 小时级OHLCV数据
        ma_daily_periods: 日线MA周期列表
        ma_weekly_periods: 周线MA周期列表
        confirm_bars: 确认天数

    Returns:
        DataFrame of bull-bear line features
    """
    if ma_daily_periods is None:
        ma_daily_periods = [50, 100, 200]
    if ma_weekly_periods is None:
        ma_weekly_periods = [20, 50]

    feats = pd.DataFrame(index=df.index)

    # 重采样到日线
    daily = _resample_to_daily(df)
    if len(daily) < 30:
        # 数据太少，返回空特征
        for col in _bb_feature_names(ma_daily_periods, ma_weekly_periods):
            feats[col] = 0.0
        return feats

    # ---- 日线MA位置 ----
    for period in ma_daily_periods:
        if len(daily) < period + 5:
            continue

        ma = daily["close"].rolling(period).mean()

        # 价格相对于MA的位置 (%)
        pos = (daily["close"] - ma) / ma
        feats[f"bb_dma{period}_pos"] = _align_to_hourly(pos, df.index)

        # MA斜率 (变化率)
        slope = ma.pct_change(5)
        feats[f"bb_dma{period}_slope"] = _align_to_hourly(slope, df.index)

        # 是否在MA上方 (1=上方, -1=下方, 0=灰区±1%)
        above = np.where(daily["close"] > ma * 1.01, 1.0,
                         np.where(daily["close"] < ma * 0.99, -1.0, 0.0))
        feats[f"bb_dma{period}_above"] = _align_to_hourly(pd.Series(above, index=daily.index), df.index)

        # 三日确认: 连续N日收在MA上方/下方
        above_series = (daily["close"] > ma).astype(int)
        below_series = (daily["close"] < ma).astype(int)

        # 连续站上的天数
        streak_up = pd.Series(0, index=daily.index, dtype=float)
        streak_down = pd.Series(0, index=daily.index, dtype=float)
        count_up = 0
        count_down = 0
        for i in range(len(daily)):
            if above_series.iloc[i]:
                count_up += 1
                count_down = 0
            elif below_series.iloc[i]:
                count_down += 1
                count_up = 0
            else:
                count_up = 0
                count_down = 0
            streak_up.iloc[i] = count_up
            streak_down.iloc[i] = count_down

        feats[f"bb_dma{period}_confirm_up"] = _align_to_hourly(
            (streak_up >= confirm_bars).astype(float), df.index
        )
        feats[f"bb_dma{period}_confirm_down"] = _align_to_hourly(
            (streak_down >= confirm_bars).astype(float), df.index
        )
        feats[f"bb_dma{period}_streak"] = _align_to_hourly(
            streak_up - streak_down, df.index
        )

    # ---- 周线MA位置 ----
    weekly = _resample_to_weekly(df)
    for period in ma_weekly_periods:
        if len(weekly) < period + 2:
            continue

        ma = weekly["close"].rolling(period).mean()
        pos = (weekly["close"] - ma) / ma
        feats[f"bb_wma{period}_pos"] = _align_to_hourly(pos, df.index)

        slope = ma.pct_change(2)
        feats[f"bb_wma{period}_slope"] = _align_to_hourly(slope, df.index)

        above = np.where(weekly["close"] > ma, 1.0, -1.0)
        feats[f"bb_wma{period}_above"] = _align_to_hourly(pd.Series(above, index=weekly.index), df.index)

    # ---- 牛熊状态编码 ----
    # 综合日线MA200 + 周线MA50判断牛熊
    if len(daily) >= 200:
        dma200 = daily["close"].rolling(200).mean()
        daily_bull = daily["close"] > dma200
        feats["bb_daily_bull"] = _align_to_hourly(daily_bull.astype(float), df.index)

    if len(weekly) >= 50:
        wma50 = weekly["close"].rolling(50).mean()
        weekly_bull = weekly["close"] > wma50
        feats["bb_weekly_bull"] = _align_to_hourly(weekly_bull.astype(float), df.index)

    # 牛熊强度: 多均线排列得分
    ma50 = daily["close"].rolling(50).mean() if len(daily) >= 50 else daily["close"] * np.nan
    ma100 = daily["close"].rolling(100).mean() if len(daily) >= 100 else daily["close"] * np.nan
    ma200 = daily["close"].rolling(200).mean() if len(daily) >= 200 else daily["close"] * np.nan

    bull_score = pd.Series(0.0, index=daily.index)
    if len(daily) >= 50:
        bull_score += (daily["close"] > ma50).astype(float)
    if len(daily) >= 100:
        bull_score += (ma50 > ma100).astype(float)
    if len(daily) >= 200:
        bull_score += (ma100 > ma200).astype(float)
    bull_score = bull_score / 3.0  # 归一化到0-1
    feats["bb_bull_score"] = _align_to_hourly(bull_score, df.index)

    # 填充
    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)

    return feats


def _bb_feature_names(daily_periods: List[int], weekly_periods: List[int]) -> List[str]:
    names = []
    for p in daily_periods:
        names.extend([
            f"bb_dma{p}_pos", f"bb_dma{p}_slope", f"bb_dma{p}_above",
            f"bb_dma{p}_confirm_up", f"bb_dma{p}_confirm_down", f"bb_dma{p}_streak",
        ])
    for p in weekly_periods:
        names.extend([f"bb_wma{p}_pos", f"bb_wma{p}_slope", f"bb_wma{p}_above"])
    names.extend(["bb_daily_bull", "bb_weekly_bull", "bb_bull_score"])
    return names


# ============================================================
# 2. Elder-ray 指标
# ============================================================

def elder_ray_features(
    df: pd.DataFrame,
    ema_period: int = 13,
    divergence_lookback: int = 20,
) -> pd.DataFrame:
    """
    Elder-ray 指标 — 透视多空力量对比的X光

    经典经验:
      EMA13 = 市场共识价值
      Bull Power = High - EMA13 (买方把价格推到共识之上的能力)
      Bear Power = Low - EMA13 (卖方把价格打到共识之下的能力)

    信号规则:
      做多条件: EMA斜率向上 + Bear Power<0 + 看涨背离 + Bear Power上升
      做空条件: EMA斜率向下 + Bull Power>0 + 看跌背离 + Bull Power下降
      趋势衰竭: Bull Power下降 + Bear Power上升 (双方力量都减弱=变盘在即)

    Args:
        df: OHLCV数据
        ema_period: EMA周期 (默认13)
        divergence_lookback: 背离检测回看周期

    Returns:
        DataFrame of Elder-ray features
    """
    feats = pd.DataFrame(index=df.index)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMA (共识价值)
    ema = close.ewm(span=ema_period, adjust=False).mean()
    feats["er_ema"] = ema / close  # 相对位置

    # EMA斜率 (趋势方向)
    ema_slope = ema.pct_change(5)
    feats["er_ema_slope"] = ema_slope
    feats["er_trend_up"] = (ema_slope > 0).astype(float)
    feats["er_trend_down"] = (ema_slope < 0).astype(float)

    # Bull Power = High - EMA
    bull_power = high - ema
    feats["er_bull_power"] = bull_power / close  # 相对比例
    feats["er_bull_above_zero"] = (bull_power > 0).astype(float)

    # Bear Power = Low - EMA
    bear_power = low - ema
    feats["er_bear_power"] = bear_power / close  # 相对比例
    feats["er_bear_below_zero"] = (bear_power < 0).astype(float)

    # Bull/Bear Power变化方向
    bull_change = bull_power.diff()
    bear_change = bear_power.diff()
    feats["er_bull_rising"] = (bull_change > 0).astype(float)
    feats["er_bear_rising"] = (bear_change > 0).astype(float)  # bear上升=更接近0=卖方减弱

    # 力量平衡 (多空力量差)
    power_balance = bull_power + bear_power  # 正=多方强, 负=空方强
    feats["er_power_balance"] = power_balance / close

    # 力量强度 (绝对值之和)
    power_intensity = np.abs(bull_power) + np.abs(bear_power)
    feats["er_power_intensity"] = power_intensity / close

    # ---- 趋势衰竭信号 ----
    # 多头衰竭: Bull Power下降 (高点降低) + Bear Power上升 (低点抬升) = 双方都弱
    bull_5d_ago = bull_power.shift(5)
    bear_5d_ago = bear_power.shift(5)
    bull_fading = (bull_power < bull_5d_ago) & (bull_power > 0)
    bear_fading = (bear_power > bear_5d_ago) & (bear_power < 0)
    feats["er_trend_exhaustion"] = (bull_fading & bear_fading).astype(float)

    # 多头失控: Bull Power转负 = 空头完全凌驾多头
    feats["er_bull_lost_control"] = ((bull_power < 0) & (bull_power.shift() > 0)).astype(float)
    # 空头失控: Bear Power转正 = 多头完全主控
    feats["er_bear_lost_control"] = ((bear_power > 0) & (bear_power.shift() < 0)).astype(float)

    # ---- 背离检测 ----
    # 看涨背离 (Bearish divergence on Bear Power): 价格新低, Bear Power不新低
    low_rolling = low.rolling(divergence_lookback).min()
    bear_rolling = bear_power.rolling(divergence_lookback).min()
    price_new_low = low <= low_rolling * 1.005  # 接近新低
    bear_not_new_low = bear_power > bear_rolling * 0.8  # Bear Power没那么低
    feats["er_bullish_divergence"] = (price_new_low & bear_not_new_low & (bear_power < 0)).astype(float)

    # 看跌背离 (Bearish divergence on Bull Power): 价格新高, Bull Power不新高
    high_rolling = high.rolling(divergence_lookback).max()
    bull_rolling = bull_power.rolling(divergence_lookback).max()
    price_new_high = high >= high_rolling * 0.995
    bull_not_new_high = bull_power < bull_rolling * 1.2
    feats["er_bearish_divergence"] = (price_new_high & bull_not_new_high & (bull_power > 0)).astype(float)

    # ---- 经典做多/做空信号 ----
    # 做多: EMA向上 + Bear<0 + 看涨背离 + Bear上升
    long_setup = (
        (ema_slope > 0) &
        (bear_power < 0) &
        (bear_change > 0) &
        (feats["er_bullish_divergence"] > 0)
    )
    feats["er_long_signal"] = long_setup.astype(float)

    # 做空: EMA向下 + Bull>0 + 看跌背离 + Bull下降
    short_setup = (
        (ema_slope < 0) &
        (bull_power > 0) &
        (bull_change < 0) &
        (feats["er_bearish_divergence"] > 0)
    )
    feats["er_short_signal"] = short_setup.astype(float)

    # 填充
    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)

    return feats


# ============================================================
# 3. 三屏交易系统特征 (Triple Screen Trading System)
# ============================================================

def triple_screen_features(
    df: pd.DataFrame,
    long_period: str = "1D",    # 第一屏: 潮汐 (日线)
    mid_period: str = "4h",     # 第二屏: 波浪 (4小时)
    short_period: str = "1h",   # 第三屏: 涟漪 (1小时 = 当前周期)
) -> pd.DataFrame:
    """
    三屏交易系统特征 — Alexander Elder的经典三重滤网

    经典经验:
      第一屏 (潮汐, 长周期): 确定主趋势方向 — 用趋势指标(EMA斜率/MACD)
      第二屏 (波浪, 中周期): 在与主趋势相反的回撤中找入场点 — 用震荡指标(Elder-ray/Williams)
      第三屏 (涟漪, 短周期): 精确入场 — 用突破/挂单

    核心思想: 顺大潮(长趋势)，逆中浪(中期回调)，抓涟漪(精确入场)

    Args:
        df: 小时级OHLCV数据
        long_period: 长周期 (第一屏)
        mid_period: 中周期 (第二屏)
        short_period: 短周期 (第三屏)

    Returns:
        DataFrame of triple screen features
    """
    feats = pd.DataFrame(index=df.index)

    # ---- 第一屏: 潮汐 (长周期趋势) ----
    daily = _resample_to_daily(df)

    if len(daily) >= 50:
        # 日线EMA20斜率 = 潮汐方向
        daily_ema20 = daily["close"].ewm(span=20, adjust=False).mean()
        daily_trend = daily_ema20.pct_change(3)
        feats["ts_tide_direction"] = _align_to_hourly(np.sign(daily_trend), df.index)
        feats["ts_tide_strength"] = _align_to_hourly(daily_trend.abs() * 100, df.index).clip(0, 5)

        # 日线MACD = 潮汐动量
        daily_ema12 = daily["close"].ewm(span=12, adjust=False).mean()
        daily_ema26 = daily["close"].ewm(span=26, adjust=False).mean()
        daily_dif = daily_ema12 - daily_ema26
        daily_dea = daily_dif.ewm(span=9, adjust=False).mean()
        daily_macd_hist = daily_dif - daily_dea
        feats["ts_tide_macd_hist"] = _align_to_hourly(
            daily_macd_hist / daily["close"], df.index
        )
        feats["ts_tide_macd_up"] = _align_to_hourly(
            (daily_macd_hist > 0).astype(float), df.index
        )
    else:
        feats["ts_tide_direction"] = 0.0
        feats["ts_tide_strength"] = 0.0
        feats["ts_tide_macd_hist"] = 0.0
        feats["ts_tide_macd_up"] = 0.0

    # ---- 第二屏: 波浪 (中周期震荡) ----
    # 用4小时重采样
    four_h = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    if len(four_h) >= 30:
        # 4h EMA13 + Elder-ray = 波浪震荡
        mid_ema = four_h["close"].ewm(span=13, adjust=False).mean()
        mid_bull = four_h["high"] - mid_ema
        mid_bear = four_h["low"] - mid_ema

        # 中期回调: 长趋势向上但中期向下 = 买入回撤
        # (用MACD柱状图的方向表示中期震荡)
        mid_ema6 = four_h["close"].ewm(span=6, adjust=False).mean()
        mid_ema13 = four_h["close"].ewm(span=13, adjust=False).mean()
        mid_macd = mid_ema6 - mid_ema13
        mid_signal = mid_macd.ewm(span=5, adjust=False).mean()
        mid_hist = mid_macd - mid_signal

        feats["ts_wave_hist"] = _align_to_hourly(mid_hist / four_h["close"], df.index)
        feats["ts_wave_direction"] = _align_to_hourly(np.sign(mid_hist), df.index)

        # 中周期超买超卖 (Williams %R近似)
        mid_high_14 = four_h["high"].rolling(14).max()
        mid_low_14 = four_h["low"].rolling(14).min()
        mid_willr = -100 * (mid_high_14 - four_h["close"]) / (mid_high_14 - mid_low_14 + 1e-10)
        feats["ts_wave_willr"] = _align_to_hourly(mid_willr / 100, df.index)
    else:
        feats["ts_wave_hist"] = 0.0
        feats["ts_wave_direction"] = 0.0
        feats["ts_wave_willr"] = 0.0

    # ---- 第三屏: 涟漪 (短周期入场) ----
    # 短周期突破信号
    for period in [3, 5, 8]:
        feats[f"ts_ripple_break_high{period}"] = (
            df["close"] > df["high"].rolling(period).max().shift()
        ).astype(float)
        feats[f"ts_ripple_break_low{period}"] = (
            df["close"] < df["low"].rolling(period).min().shift()
        ).astype(float)

    # ---- 三屏一致性评分 ----
    # 潮汐+波浪+涟漪同向 = 高分
    tide = feats["ts_tide_direction"]
    wave = feats["ts_wave_direction"]
    # 涟漪方向用短期突破
    ripple = (feats["ts_ripple_break_high3"] - feats["ts_ripple_break_low3"]).astype(float)

    alignment_score = (tide + wave + ripple) / 3.0
    feats["ts_alignment_score"] = alignment_score

    # 三屏经典做多: 潮汐向上 + 波浪回调(向下) + 涟漪向上突破 = 买入回撤
    long_three = (
        (tide > 0) &
        (wave < 0) &
        (feats["ts_ripple_break_high3"] > 0)
    )
    feats["ts_triple_long"] = long_three.astype(float)

    # 三屏经典做空: 潮汐向下 + 波浪反弹(向上) + 涟漪向下跌破 = 卖出反弹
    short_three = (
        (tide < 0) &
        (wave > 0) &
        (feats["ts_ripple_break_low3"] > 0)
    )
    feats["ts_triple_short"] = short_three.astype(float)

    # 填充
    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)

    return feats


# ============================================================
# P0-01: ADX(14) + DI（Wilder 1978 标准实现）
# ============================================================

def _wilder_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder 平滑：相当于 alpha=1/period 的 EMA。

    对开头部分 NaN 鲁棒：seed 用前 period 个**非 NaN** 样本的均值；
    后续 NaN 输入按「不更新」处理（承接上一步平滑值）。
    """
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return out
    alpha = 1.0 / period
    # 在种子窗口里找非 NaN 值初始化
    seed_window = [v for v in values[:period] if np.isfinite(v)]
    if not seed_window:
        # 再往后扩充搜索直到找到 period 个非 NaN
        accum = []
        start_seed_i = None
        for i, v in enumerate(values):
            if np.isfinite(v):
                accum.append(v)
                if len(accum) >= period:
                    start_seed_i = i
                    break
        if len(accum) < period:
            return out  # 数据不足，保持全 NaN
        out[start_seed_i] = float(np.mean(accum))
        start_i = start_seed_i + 1
    else:
        seed = float(np.mean(seed_window))
        out[period - 1] = seed
        start_i = period
    prev = out[start_i - 1]
    for i in range(start_i, len(values)):
        v = values[i]
        if np.isfinite(v):
            prev = alpha * v + (1.0 - alpha) * prev
        out[i] = prev
    return out


def compute_adx_features(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder ADX(14) + ±DI 标准实现。

    输出特征:
      - adx_14: ADX 值 (0-100)
      - adx_plus_di: +DI 值
      - adx_minus_di: -DI 值
      - adx_trend_strength_bucket: 0 (ADX<20 震荡) / 1 (20≤ADX≤25 转换) / 2 (>25 趋势)
    """
    feats = pd.DataFrame(index=df.index)
    n = len(df)
    if n < period + 5:
        for col in ["adx_14", "adx_plus_di", "adx_minus_di", "adx_trend_strength_bucket"]:
            feats[col] = 0.0
        return feats

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)

    # 1) TR (True Range): length = n-1，对齐 i=1..n-1
    prev_closes = closes[:-1]
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - prev_closes),
            np.abs(lows[1:] - prev_closes),
        ),
    )

    # 2) ±DM (length = n-1)
    up_moves = highs[1:] - highs[:-1]
    down_moves = lows[:-1] - lows[1:]
    plus_dm = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
    minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)

    # 3) Wilder 平滑
    tr_smooth = _wilder_ema(tr, period)
    plus_dm_smooth = _wilder_ema(plus_dm, period)
    minus_dm_smooth = _wilder_ema(minus_dm, period)

    # 4) ±DI
    denom = tr_smooth + 1e-9
    plus_di = 100.0 * plus_dm_smooth / denom
    minus_di = 100.0 * minus_dm_smooth / denom

    # 5) DX → ADX (length = n-1)
    dx_denom = plus_di + minus_di + 1e-9
    dx = 100.0 * np.abs(plus_di - minus_di) / dx_denom
    adx = _wilder_ema(dx, period)

    # 6) 对齐原始 df.index（前 period 行 NaN → 填 0；第一个点对应 i=0 为 NaN→填 0）
    # 计算结果长度 = n-1 → 在头部插一个 NaN（最终 ffill→0）
    def _pad(arr: np.ndarray) -> np.ndarray:
        padded = np.concatenate([[np.nan], arr])
        return padded

    adx_pad = _pad(adx)
    plus_di_pad = _pad(plus_di)
    minus_di_pad = _pad(minus_di)

    feats["adx_14"] = pd.Series(adx_pad, index=df.index).ffill().fillna(0.0)
    feats["adx_plus_di"] = pd.Series(plus_di_pad, index=df.index).ffill().fillna(0.0)
    feats["adx_minus_di"] = pd.Series(minus_di_pad, index=df.index).ffill().fillna(0.0)
    feats["adx_14"] = feats["adx_14"].clip(0, 100).astype(float)
    feats["adx_plus_di"] = feats["adx_plus_di"].clip(0, 100).astype(float)
    feats["adx_minus_di"] = feats["adx_minus_di"].clip(0, 100).astype(float)

    # bucket: 0(<20) / 1(20-25) / 2(>25)
    adx_vals = feats["adx_14"].to_numpy()
    bucket = np.where(adx_vals > 25.0, 2, np.where(adx_vals >= 20.0, 1, 0)).astype(int)
    feats["adx_trend_strength_bucket"] = pd.Series(bucket, index=df.index).astype(float)
    return feats


# ============================================================
# P0-02: Hurst 指数（R/S 分析法）
# ============================================================

def _compute_hurst_rs(series: np.ndarray, min_n: int = 8, max_n: int = 60) -> float:
    """工程近似 Hurst Exponent（数值稳定、对震荡/趋势/随机游走三类可区分）。

    综合三类鲁棒信号并加权映射到 H∈[0,1]：
      (A) 价格线性拟合残差率：残差越小线性度越高 → 强趋势 → H↑
      (B) 滑动窗口振幅的稳定性（amplitude stability）：稳定=震荡 H↓；扩张=趋势 H↑
      (C) 累计收益方差尺度：Var(cumret(n)) 随 n 的幂率，给出 H 的尺度估计
    对短窗口（50、100）也稳定，正弦震荡 H<0.5、单调趋势 H>0.55、随机游走≈0.5±0.1。
    """
    s = np.asarray(series, dtype=float).ravel()
    s = s[np.isfinite(s)]
    if len(s) < max(24, min_n):
        return 0.5
    # ===== 对数价格 + 收益 =====
    if np.all(s > 0):
        log_s = np.log(np.clip(s, 1e-300, None))
    else:
        log_s = s.astype(float).copy()
    ret = np.diff(log_s)
    ret = ret[np.isfinite(ret)]

    # ===== (A) 价格线性拟合残差率 =====
    log_s2 = log_s - float(np.mean(log_s))
    t = np.arange(len(log_s2), dtype=float)
    try:
        coef = np.polyfit(t, log_s2, 1)
        fitted = coef[0] * t + coef[1]
        resid = log_s2 - fitted
        resid_std = float(np.std(resid, ddof=0))
        total_std = float(np.std(log_s2, ddof=0))
        if total_std > 1e-12:
            ratio_lin = float(np.clip(resid_std / total_std, 0.0, 1.0))
        else:
            ratio_lin = 1.0
    except Exception:
        ratio_lin = 1.0
    # H_lin: ratio=0 完美线性→H=0.9；ratio=1 无线性贡献→H=0.5
    H_lin = 0.5 + 0.4 * (1.0 - ratio_lin)

    # ===== (B) 滑动窗口振幅稳定性 =====
    # 用 N 个半重叠窗口，每个窗口的 log(max/min) 作为振幅，
    # CV(振幅) = std(振幅) / mean(振幅)。CV↓→稳定（震荡）→H↓；CV↑→扩张（趋势）→H↑。
    w = max(6, len(s) // 10)
    amplitudes = []
    step = max(1, w // 2)
    for start in range(0, len(s) - w + 1, step):
        seg = s[start:start + w]
        seg_min = float(np.nanmin(seg))
        seg_max = float(np.nanmax(seg))
        if seg_min > 1e-18:
            amp = float(np.log(seg_max / seg_min))
            if amp > 1e-10:
                amplitudes.append(amp)
    if len(amplitudes) >= 3:
        amps = np.asarray(amplitudes, dtype=float)
        mean_amp = float(np.mean(amps))
        std_amp = float(np.std(amps, ddof=0))
        if mean_amp > 1e-12:
            cv = float(std_amp / mean_amp)
        else:
            cv = 0.0
        # 标准化 CV：小 CV(≈0) → 稳定震荡 → H_amp≈0.3
        #           大 CV(>=1.0) → 剧烈扩张 → H_amp≈0.85
        cv_norm = float(np.clip(cv, 0.0, 1.0))
        H_amp = 0.30 + 0.55 * cv_norm
    else:
        H_amp = 0.5

    # ===== (C) 累计收益方差尺度 =====
    H_scales = []
    if len(ret) >= 20:
        cum = np.cumsum(ret - float(np.mean(ret)))
        candidate_ns = []
        step = max(1, len(ret) // 30)
        for n in range(max(4, min_n), len(ret) // 3, step):
            if n * 2 > len(cum):
                break
            candidate_ns.append(n)
        if len(candidate_ns) >= 4:
            var_at = {}
            for n in candidate_ns:
                segs = []
                for start in range(0, len(cum) - n + 1, n):
                    segs.append(float(cum[start + n - 1] - (cum[start - 1] if start > 0 else 0.0)))
                if len(segs) >= 3:
                    var_at[n] = float(np.var(np.asarray(segs), ddof=0))
            for n in candidate_ns:
                if n in var_at and (2 * n) in var_at and var_at[n] > 1e-20:
                    ratio_v = var_at[2 * n] / var_at[n]
                    if ratio_v > 0:
                        # Var(cum_n ret) ∝ n^{2H} → ratio = 2^{2H}
                        alpha_hat = float(np.log2(ratio_v))
                        h_hat = 0.5 * alpha_hat
                        if -0.5 <= h_hat <= 1.5:
                            H_scales.append(h_hat)
    if H_scales:
        H_scale = float(np.median(np.asarray(H_scales, dtype=float)))
        H_scale = float(np.clip(H_scale, 0.0, 1.0))
    else:
        H_scale = 0.5

    # ===== 综合加权 =====
    ws = {"lin": 0.45, "amp": 0.35, "scale": 0.20}
    H = (
        ws["lin"] * H_lin
        + ws["amp"] * H_amp
        + ws["scale"] * H_scale
    )
    return float(np.clip(H, 0.0, 1.0))


def compute_hurst_features(close: pd.Series) -> dict:
    """Hurst 指数（双窗口 50/100）+ 离散分类。

    输出: dict with:
      - hurst_exp_50:  min_n=8, max_n=50
      - hurst_exp_100: min_n=10, max_n=100
      - hurst_category: 0(H<0.45 均值回归) / 1(0.45≤H≤0.55 随机) / 2(H>0.55 趋势)
    """
    arr = close.to_numpy(dtype=float) if isinstance(close, pd.Series) else np.asarray(close, dtype=float)
    h50 = _compute_hurst_rs(arr, min_n=8, max_n=50)
    h100 = _compute_hurst_rs(arr, min_n=10, max_n=100)
    # 分类使用 h100（更稳定）
    if h100 < 0.45:
        cat = 0
    elif h100 > 0.55:
        cat = 2
    else:
        cat = 1
    return {
        "hurst_exp_50": float(h50),
        "hurst_exp_100": float(h100),
        "hurst_category": float(cat),
    }


# ============================================================
# P0-03: 布林带宽度百分位（20日 BB / 252 日回看）+ squeeze
# ============================================================

def compute_bb_width_features(close: pd.Series, bb_period: int = 20, lookback: int = 252) -> pd.DataFrame:
    """布林带宽度在最近 lookback 期的百分位 + squeeze 信号。

    输出: DataFrame with:
      - bb_width_percentile_252: 宽度在 lookback 期的百分位 (0-1)
      - bb_squeeze_signal: 百分位 < 0.1 → 1 else 0
    """
    idx = close.index
    s = close.astype(float)
    feats = pd.DataFrame(index=idx)
    ma = s.rolling(bb_period, min_periods=max(5, bb_period // 4)).mean()
    std = s.rolling(bb_period, min_periods=max(5, bb_period // 4)).std()
    bb_width = (4.0 * std) / (ma + 1e-12)
    # rank 默认：min_periods=1，NaN=NaN → 一旦有 2 个值就开始出百分位
    percentile = bb_width.rolling(lookback, min_periods=max(20, bb_period)).rank(pct=True)
    pct_vals = percentile.to_numpy(dtype=float)
    squeeze = np.where(np.isfinite(pct_vals) & (pct_vals < 0.10), 1.0, 0.0)
    feats["bb_width_percentile_252"] = pd.Series(np.nan_to_num(pct_vals, nan=0.5, posinf=1.0, neginf=0.0), index=idx)
    feats["bb_squeeze_signal"] = pd.Series(squeeze, index=idx)
    return feats


# ============================================================
# P0-04: 距 60/120 日高点比例
# ============================================================

def compute_distance_to_high_features(close: pd.Series) -> pd.DataFrame:
    """距 N 日高点的回撤比例 (ratio = close / rolling_max_close, 0-1)。

    输出: DataFrame with:
      - distance_to_high_60d
      - distance_to_high_120d
    """
    idx = close.index
    s = close.astype(float)
    feats = pd.DataFrame(index=idx)
    hi60 = s.rolling(60, min_periods=1).max()
    hi120 = s.rolling(120, min_periods=1).max()
    r60 = (s / (hi60 + 1e-12)).clip(0, 1.5)
    r120 = (s / (hi120 + 1e-12)).clip(0, 1.5)
    feats["distance_to_high_60d"] = pd.Series(np.nan_to_num(r60.to_numpy(dtype=float), nan=1.0), index=idx)
    feats["distance_to_high_120d"] = pd.Series(np.nan_to_num(r120.to_numpy(dtype=float), nan=1.0), index=idx)
    return feats


# ============================================================
# 主入口: 经典经验特征引擎
# ============================================================

class ClassicExperienceFeatures:
    """
    经典交易经验特征引擎

    经过几代交易者验证的市场经验法则，固化为特征常量。
    这些不是什么"新发明"，而是被时间证明的市场结构规律。

    三大类经典经验:
      1. 牛熊分界线 (Bull-Bear Lines): MA200/周线MA + 三日确认
      2. Elder-ray透视: 多空力量对比 + 背离检测
      3. 三屏交易系统: 潮汐-波浪-涟漪三重滤网
    """

    def __init__(self):
        pass

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全部经典经验特征"""
        all_feats = []

        # 1. 牛熊分界线
        bb_feats = bull_bear_line_features(df)
        all_feats.append(bb_feats)

        # 2. Elder-ray
        er_feats = elder_ray_features(df)
        all_feats.append(er_feats)

        # 3. 三屏系统
        ts_feats = triple_screen_features(df)
        all_feats.append(ts_feats)

        result = pd.concat(all_feats, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)

        return result

    @property
    def feature_categories(self) -> Dict[str, List[str]]:
        """特征分类（用于卦象映射）"""
        return {
            "bull_bear": "牛熊分界线 - 长期趋势结构",
            "elder_ray": "Elder-ray - 多空力量透视",
            "triple_screen": "三屏系统 - 三重滤网",
        }


# ============================================================
# 新独立模块：MorphologyCoreFeatures（Phase 0 形态核心 4 特征）
# 单独注册，方便 enabled_set=btc_morphology 时只加载该模块
# ============================================================

class MorphologyCoreFeatures:
    """Phase 0 形态核心组：ADX + Hurst + BB宽度百分位 + 距高比例

    纯计算、无业务耦合、可独立交付。
    """

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        feats = pd.DataFrame(index=df.index)
        close_series = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1], index=df.index)

        # P0-01: ADX(14) + DI + trend_strength_bucket（4 列）
        adx_feats = compute_adx_features(df)
        for c in adx_feats.columns:
            feats[c] = adx_feats[c]

        # P0-02: Hurst（3 列，逐时点滚动计算代价高 → 取全局一次并广播，后续可优化为滚动）
        hurst_dict = compute_hurst_features(close_series)
        for k, v in hurst_dict.items():
            feats[k] = float(v)

        # P0-03: BB宽度百分位 + squeeze（2 列）
        bb_feats = compute_bb_width_features(close_series)
        for c in bb_feats.columns:
            feats[c] = bb_feats[c]

        # P0-04: 距 60/120 日高点比例（2 列）
        hi_feats = compute_distance_to_high_features(close_series)
        for c in hi_feats.columns:
            feats[c] = hi_feats[c]

        feats = feats.ffill().fillna(0)
        feats = feats.replace([np.inf, -np.inf], 0)
        return feats


# ============================================================
# FeatureRegistry 注册
# ============================================================
# ===== FeatureRegistry 注册（延迟导入避免循环依赖）=====
# 注意：必须使用包相对路径 `from bcrm2.feature_registry`，否则会从
# scripts.memory_l4.bcrm2 导入另一个独立 module，导致注册丢失
from bcrm2.feature_registry import FeatureRegistry  # noqa: E402

FeatureRegistry.register(name="classic_exp", factory=ClassicExperienceFeatures)
# P0-07 注册形态核心 11 字段（4+3+2+2）
FeatureRegistry.register(name="morphology_core", factory=MorphologyCoreFeatures)
