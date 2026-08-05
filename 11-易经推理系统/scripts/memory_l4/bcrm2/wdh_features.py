"""
周/日/时三屏 + 量变积累特征 — 基于易经"量变引起质变"理论

理论映射:
  量变 → 周线级别的趋势/动量/成交量持续积累 (量的准备)
  质变 → 长期积累后的趋势反转/加速 (质的飞跃)
  量变-质变规律 → 当量变积累到一定程度，质变发生的概率显著上升

三屏逻辑 (周/日/时):
  第一屏 (周线, 潮汐): 量变积累层 — 主趋势方向 + 积累强度
  第二屏 (日线, 波浪): 质变确认层 — 中期趋势是否与周线共振/背离
  第三屏 (小时线, 涟漪): 入场时机层 — 短期突破/动量确认

核心量化重点 (用户确认): 动量/收益率累积
  - N周累计收益率 (1/2/4/8/12周)
  - 周线RSI持续性 (连续高于/低于阈值周数)
  - 周线成交量累积趋势
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

# 复用经典经验特征里的重采样工具
from .classic_experience_features import (
    _resample_to_daily,
    _resample_to_weekly,
    _align_to_hourly,
)


# ============================================================
# 第一屏: 周线 — 量变积累层 (核心)
# ============================================================

def _streak_count(series: pd.Series, condition_fn) -> pd.Series:
    """计算连续满足条件的次数（streak长度）"""
    result = pd.Series(0, index=series.index, dtype=float)
    count = 0
    prev_valid = False
    for i in range(len(series)):
        val = series.iloc[i]
        if pd.isna(val):
            count = 0
            prev_valid = False
        elif condition_fn(val):
            count = count + 1 if prev_valid else 1
            prev_valid = True
        else:
            count = 0
            prev_valid = False
        result.iloc[i] = count
    return result


def weekly_accumulation_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    周线量变积累特征 — "量"的积累程度

    核心思想:
      趋势持续越久、累计收益越大、RSI持续性越高 → 量变积累越深
      深度量变积累后出现反向信号 → 质变发生概率高

    量化维度:
      1. 累计收益率 (1/2/4/8/12周)
      2. 周线RSI及持续性
      3. 周线成交量累积趋势
      4. 周线EMA趋势持续性
    """
    feats = pd.DataFrame(index=df.index)

    weekly = _resample_to_weekly(df)
    if len(weekly) < 30:
        # 数据不足，返回占位特征
        for col in _weekly_accumulation_names():
            feats[col] = 0.0
        return feats

    close_w = weekly["close"]
    high_w = weekly["high"]
    low_w = weekly["low"]
    vol_w = weekly["volume"]

    # ---- 1. 累计收益率 (动量累积的核心) ----
    for n in [1, 2, 4, 8, 12]:
        ret = close_w.pct_change(n)
        feats[f"wa_ret_{n}w"] = _align_to_hourly(ret, df.index)
        # 累计收益的符号一致性 (同向积累强度)
        if n >= 2:
            # 计算n周内每周收益的符号一致比例
            signs = np.sign(close_w.pct_change(1))
            consistency = signs.rolling(n).apply(
                lambda x: abs(np.mean(x)) if len(x) == n else 0, raw=False
            )
            feats[f"wa_ret_{n}w_consistency"] = _align_to_hourly(consistency, df.index)

    # ---- 2. 周线RSI及持续性 ----
    delta = close_w.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=14, adjust=False).mean()
    avg_loss = loss.ewm(span=14, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi_w = 100 - 100 / (1 + rs)
    feats["wa_rsi_14w"] = _align_to_hourly(rsi_w, df.index)

    # RSI连续高于50的周数 (多头量变积累)
    rsi_above50 = _streak_count(rsi_w, lambda x: x > 50)
    feats["wa_rsi_streak_above50"] = _align_to_hourly(rsi_above50.clip(0, 26), df.index)
    # RSI连续低于50的周数 (空头量变积累)
    rsi_below50 = _streak_count(rsi_w, lambda x: x < 50)
    feats["wa_rsi_streak_below50"] = _align_to_hourly(rsi_below50.clip(0, 26), df.index)
    # RSI连续超买(>70)/超卖(<30)周数 — 极端量变
    rsi_overbought = _streak_count(rsi_w, lambda x: x > 70)
    feats["wa_rsi_streak_overbought"] = _align_to_hourly(rsi_overbought.clip(0, 10), df.index)
    rsi_oversold = _streak_count(rsi_w, lambda x: x < 30)
    feats["wa_rsi_streak_oversold"] = _align_to_hourly(rsi_oversold.clip(0, 10), df.index)

    # ---- 3. 周线成交量累积趋势 ----
    # 成交量EMA斜率 (量能趋势)
    vol_ema = vol_w.ewm(span=4, adjust=False).mean()
    vol_slope = vol_ema.pct_change(2)
    feats["wa_vol_slope"] = _align_to_hourly(vol_slope.clip(-1, 1), df.index)

    # 4周/8周累计成交量变化率 (量能积累)
    vol_sum_4 = vol_w.rolling(4).sum()
    vol_sum_8 = vol_w.rolling(8).sum()
    vol_sum_prev_4 = vol_sum_4.shift(4)
    vol_sum_prev_8 = vol_sum_8.shift(8)
    feats["wa_vol_accum_4w"] = _align_to_hourly(
        (vol_sum_4 - vol_sum_prev_4) / (vol_sum_prev_4 + 1e-10), df.index
    ).clip(-2, 2)
    feats["wa_vol_accum_8w"] = _align_to_hourly(
        (vol_sum_8 - vol_sum_prev_8) / (vol_sum_prev_8 + 1e-10), df.index
    ).clip(-2, 2)

    # 价量同向性 (价格上涨+成交量放大 = 健康量变)
    price_ret = close_w.pct_change(1)
    vol_chg = vol_w.pct_change(1)
    pv_align = np.sign(price_ret) * np.sign(vol_chg)
    feats["wa_price_vol_align"] = _align_to_hourly(pv_align, df.index)

    # ---- 4. 周线EMA趋势持续性 ----
    ema20_w = close_w.ewm(span=20, adjust=False).mean()
    ema_slope_w = ema20_w.pct_change(1)
    feats["wa_ema20_slope"] = _align_to_hourly(ema_slope_w.clip(-0.3, 0.3), df.index)

    # EMA连续向上/向下周数
    ema_rising = _streak_count(ema_slope_w, lambda x: x > 0)
    ema_falling = _streak_count(ema_slope_w, lambda x: x < 0)
    feats["wa_ema_streak_up"] = _align_to_hourly(ema_rising.clip(0, 26), df.index)
    feats["wa_ema_streak_down"] = _align_to_hourly(ema_falling.clip(0, 26), df.index)

    # ---- 5. 量变积累度综合评分 (0-1) ----
    # 综合: 累计收益幅度 + RSI持续性 + EMA持续性 + 成交量配合
    # 用4周累计收益的绝对值 (量变幅度)
    accum_magnitude = (feats["wa_ret_4w"].abs() if "wa_ret_4w" in feats else 0)
    # 持续性: RSI连续周数归一化
    persist_score = (
        feats["wa_rsi_streak_above50"] / 26.0 - feats["wa_rsi_streak_below50"] / 26.0
    ).clip(-1, 1)
    # EMA持续性
    ema_persist = (
        feats["wa_ema_streak_up"] / 26.0 - feats["wa_ema_streak_down"] / 26.0
    ).clip(-1, 1)
    # 量变积累度 = 幅度(归一化) * 持续性方向
    accum_score = np.tanh(accum_magnitude * 5) * (0.4 * persist_score + 0.6 * ema_persist)
    feats["wa_accumulation_score"] = accum_score.clip(-1, 1)

    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)
    return feats


def _weekly_accumulation_names() -> List[str]:
    return [
        "wa_ret_1w", "wa_ret_2w", "wa_ret_4w", "wa_ret_8w", "wa_ret_12w",
        "wa_ret_2w_consistency", "wa_ret_4w_consistency", "wa_ret_8w_consistency",
        "wa_ret_12w_consistency",
        "wa_rsi_14w", "wa_rsi_streak_above50", "wa_rsi_streak_below50",
        "wa_rsi_streak_overbought", "wa_rsi_streak_oversold",
        "wa_vol_slope", "wa_vol_accum_4w", "wa_vol_accum_8w", "wa_price_vol_align",
        "wa_ema20_slope", "wa_ema_streak_up", "wa_ema_streak_down",
        "wa_accumulation_score",
    ]


# ============================================================
# 第二屏: 日线 — 质变确认层
# ============================================================

def daily_confirmation_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    日线质变确认特征 — 日线是否与周线主趋势共振/背离

    核心思想:
      质变需要日线确认 — 周线量变积累后，日线出现同向加速=质变确认
      日线与周线背离 = 量变可能未到质变点 (只是回调)

    量化维度:
      1. 日线趋势方向 (EMA斜率/MACD)
      2. 日线相对周线位置 (偏离度)
      3. 日线动量与周线同向性
    """
    feats = pd.DataFrame(index=df.index)

    daily = _resample_to_daily(df)
    weekly = _resample_to_weekly(df)

    if len(daily) < 50:
        for col in _daily_confirmation_names():
            feats[col] = 0.0
        return feats

    close_d = daily["close"]

    # ---- 1. 日线趋势方向 ----
    ema20_d = close_d.ewm(span=20, adjust=False).mean()
    ema_slope_d = ema20_d.pct_change(3)
    feats["dc_ema20_slope"] = _align_to_hourly(ema_slope_d.clip(-0.2, 0.2), df.index)
    feats["dc_trend_up"] = _align_to_hourly((ema_slope_d > 0).astype(float), df.index)
    feats["dc_trend_down"] = _align_to_hourly((ema_slope_d < 0).astype(float), df.index)

    # 日线MACD
    ema12_d = close_d.ewm(span=12, adjust=False).mean()
    ema26_d = close_d.ewm(span=26, adjust=False).mean()
    dif_d = ema12_d - ema26_d
    dea_d = dif_d.ewm(span=9, adjust=False).mean()
    macd_hist_d = dif_d - dea_d
    feats["dc_macd_hist"] = _align_to_hourly(macd_hist_d / close_d, df.index)
    feats["dc_macd_up"] = _align_to_hourly((macd_hist_d > 0).astype(float), df.index)

    # ---- 2. 日线相对周线位置 ----
    if len(weekly) >= 20:
        ema20_w = weekly["close"].ewm(span=20, adjust=False).mean()
        # 日线close相对周线EMA的偏离
        daily_vs_weekly = (close_d - _align_to_hourly(ema20_w, daily.index)) / (
            _align_to_hourly(ema20_w, daily.index) + 1e-10
        )
        feats["dc_deviation_from_weekly"] = _align_to_hourly(
            daily_vs_weekly.clip(-0.3, 0.3), df.index
        )
        # 日线是否在周线EMA上方 (质变确认)
        feats["dc_above_weekly_ema"] = _align_to_hourly(
            (daily_vs_weekly > 0).astype(float), df.index
        )

    # ---- 3. 日线动量与周线同向性 ----
    if len(weekly) >= 5:
        weekly_ret = weekly["close"].pct_change(1)
        weekly_dir = _align_to_hourly(np.sign(weekly_ret), daily.index)
        daily_dir = np.sign(ema_slope_d)
        # 同向 = +1, 反向 = -1
        align = (weekly_dir * daily_dir).fillna(0)
        feats["dc_daily_weekly_align"] = _align_to_hourly(align, df.index)
        # 质变确认: 周线+日线同向
        feats["dc_qualitative_confirm"] = _align_to_hourly(
            (align > 0).astype(float), df.index
        )

    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)
    return feats


def _daily_confirmation_names() -> List[str]:
    return [
        "dc_ema20_slope", "dc_trend_up", "dc_trend_down",
        "dc_macd_hist", "dc_macd_up",
        "dc_deviation_from_weekly", "dc_above_weekly_ema",
        "dc_daily_weekly_align", "dc_qualitative_confirm",
    ]


# ============================================================
# 第三屏: 小时线 — 入场时机层
# ============================================================

def hourly_timing_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    小时线入场时机特征 — 短期突破/动量确认

    核心思想:
      涟漪层提供精确入场时机 — 在潮汐(周)+波浪(日)方向确定后
      用小时线突破信号捕捉入场点
    """
    feats = pd.DataFrame(index=df.index)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ---- 突破日高/日低 ----
    # 重采样日内高/低点
    daily_high = high.resample("1D").max()
    daily_low = low.resample("1D").min()
    daily_high_aligned = daily_high.reindex(df.index, method="ffill").shift()
    daily_low_aligned = daily_low.reindex(df.index, method="ffill").shift()

    feats["ht_break_daily_high"] = (close > daily_high_aligned).astype(float)
    feats["ht_break_daily_low"] = (close < daily_low_aligned).astype(float)

    # ---- 小时线短期动量 ----
    ema5 = close.ewm(span=5, adjust=False).mean()
    ema13 = close.ewm(span=13, adjust=False).mean()
    feats["ht_ema5_13_spread"] = ((ema5 - ema13) / (ema13 + 1e-10)).clip(-0.05, 0.05)
    feats["ht_short_momentum"] = close.pct_change(3).clip(-0.1, 0.1)

    # 小时线RSI(6) — 短期超买超卖
    delta_h = close.diff()
    gain_h = delta_h.clip(lower=0)
    loss_h = -delta_h.clip(upper=0)
    avg_gain_h = gain_h.ewm(span=6, adjust=False).mean()
    avg_loss_h = loss_h.ewm(span=6, adjust=False).mean()
    rsi_h = 100 - 100 / (1 + avg_gain_h / (avg_loss_h + 1e-10))
    feats["ht_rsi_6"] = rsi_h / 100.0

    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)
    return feats


def _hourly_timing_names() -> List[str]:
    return [
        "ht_break_daily_high", "ht_break_daily_low",
        "ht_ema5_13_spread", "ht_short_momentum", "ht_rsi_6",
    ]


# ============================================================
# 质变触发信号 + 三级共振 (量变→质变合成)
# ============================================================

def qualitative_trigger_features(
    df: pd.DataFrame,
    weekly_feats: pd.DataFrame,
    daily_feats: pd.DataFrame,
    hourly_feats: pd.DataFrame,
) -> pd.DataFrame:
    """
    质变触发信号 + 周/日/时三级共振

    核心思想:
      1. 量变积累度高 + 出现反转信号 = 质变触发
      2. 周/日/时三级同向 = 强共振 (趋势加速)
      3. 量变积累度高但方向未变 = 趋势延续 (未到质变)
    """
    feats = pd.DataFrame(index=df.index)

    accum_score = weekly_feats.get("wa_accumulation_score", pd.Series(0, index=df.index))
    rsi_w = weekly_feats.get("wa_rsi_14w", pd.Series(50, index=df.index))
    rsi_streak_overbought = weekly_feats.get("wa_rsi_streak_overbought", pd.Series(0, index=df.index))
    rsi_streak_oversold = weekly_feats.get("wa_rsi_streak_oversold", pd.Series(0, index=df.index))
    ema_streak_up = weekly_feats.get("wa_ema_streak_up", pd.Series(0, index=df.index))
    ema_streak_down = weekly_feats.get("wa_ema_streak_down", pd.Series(0, index=df.index))

    dc_align = daily_feats.get("dc_daily_weekly_align", pd.Series(0, index=df.index))
    dc_confirm = daily_feats.get("dc_qualitative_confirm", pd.Series(0, index=df.index))

    ht_break_high = hourly_feats.get("ht_break_daily_high", pd.Series(0, index=df.index))
    ht_break_low = hourly_feats.get("ht_break_daily_low", pd.Series(0, index=df.index))
    ht_momentum = hourly_feats.get("ht_short_momentum", pd.Series(0, index=df.index))

    # ---- 1. 质变触发: 顶部质变 (超买后回落) ----
    # 周线RSI连续超买 + 日线与周线背离 + 小时线向下跌破
    top_trigger = (
        (rsi_streak_overbought >= 2) &
        (rsi_w < 70) &  # RSI从超买区回落
        (ht_break_low > 0)
    ).astype(float)
    feats["qt_top_trigger"] = top_trigger

    # ---- 2. 质变触发: 底部质变 (超卖后反弹) ----
    bottom_trigger = (
        (rsi_streak_oversold >= 2) &
        (rsi_w > 30) &  # RSI从超卖区回升
        (ht_break_high > 0)
    ).astype(float)
    feats["qt_bottom_trigger"] = bottom_trigger

    # ---- 3. 趋势延续 (量变未到质变) ----
    # 量变积累度高 + 方向未反转 + 日线确认 = 趋势延续
    trend_continue_up = (
        (ema_streak_up >= 3) &
        (accum_score > 0.2) &
        (dc_confirm > 0) &
        (ht_momentum > 0)
    ).astype(float)
    feats["qt_trend_continue_up"] = trend_continue_up

    trend_continue_down = (
        (ema_streak_down >= 3) &
        (accum_score < -0.2) &
        (dc_confirm > 0) &
        (ht_momentum < 0)
    ).astype(float)
    feats["qt_trend_continue_down"] = trend_continue_down

    # ---- 4. 周/日/时三级共振评分 ----
    # 周线方向 (用EMA斜率符号)
    weekly_dir = np.sign(weekly_feats.get("wa_ema20_slope", pd.Series(0, index=df.index)))
    # 日线方向
    daily_dir = np.sign(daily_feats.get("dc_ema20_slope", pd.Series(0, index=df.index)))
    # 小时线方向 (用短期动量符号)
    hourly_dir = np.sign(ht_momentum)

    # 三级共振: 同向得1分，反向得-1，权重 周线0.5 + 日线0.3 + 小时线0.2
    resonance = 0.5 * weekly_dir + 0.3 * daily_dir + 0.2 * hourly_dir
    feats["qt_resonance_score"] = resonance.clip(-1, 1)

    # 三级强共振 (全部同向)
    all_up = ((weekly_dir > 0) & (daily_dir > 0) & (hourly_dir > 0)).astype(float)
    all_down = ((weekly_dir < 0) & (daily_dir < 0) & (hourly_dir < 0)).astype(float)
    feats["qt_strong_resonance_up"] = all_up
    feats["qt_strong_resonance_down"] = all_down

    # ---- 5. 量变→质变综合信号 ----
    # 量变积累度 × 质变触发 = 强反转信号
    strong_reversal_up = (bottom_trigger * (1 + np.abs(accum_score))).clip(0, 2)
    feats["qt_strong_reversal_up"] = strong_reversal_up
    strong_reversal_down = (top_trigger * (1 + np.abs(accum_score))).clip(0, 2)
    feats["qt_strong_reversal_down"] = strong_reversal_down

    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)
    return feats


def _qualitative_trigger_names() -> List[str]:
    return [
        "qt_top_trigger", "qt_bottom_trigger",
        "qt_trend_continue_up", "qt_trend_continue_down",
        "qt_resonance_score", "qt_strong_resonance_up", "qt_strong_resonance_down",
        "qt_strong_reversal_up", "qt_strong_reversal_down",
    ]


# ============================================================
# 主入口: 周/日/时 + 量变质变特征引擎
# ============================================================

class WDHFeatures:
    """
    周/日/时三屏 + 量变积累特征引擎

    基于易经"量变引起质变"理论:
      - 周线层量化"量变积累" (累计收益/RSI持续性/成交量累积)
      - 日线层确认"质变发生"
      - 小时线层捕捉"入场时机"
      - 合成层产生"量变→质变"触发信号

    与现有 classic_experience_features.triple_screen_features (日/4H/1H) 并存，
    不重复，本模块聚焦周/日/时维度 + 量变积累量化。
    """

    def __init__(self):
        pass

    def compute(self, df: pd.DataFrame, weekly_only: bool = False) -> pd.DataFrame:
        """计算周/日/时 + 量变质变特征

        Args:
            df: 小时级OHLCV数据
            weekly_only: 只保留周线量变积累层 (用于消融实验)
        """
        # 1. 周线量变积累 (核心层)
        weekly_feats = weekly_accumulation_features(df)

        if weekly_only:
            result = weekly_feats.copy()
            result = result.ffill().fillna(0)
            result = result.replace([np.inf, -np.inf], 0)
            return result

        # 2. 日线质变确认
        daily_feats = daily_confirmation_features(df)

        # 3. 小时线入场时机
        hourly_feats = hourly_timing_features(df)

        # 4. 质变触发 + 三级共振 (依赖前三层)
        trigger_feats = qualitative_trigger_features(df, weekly_feats, daily_feats, hourly_feats)

        result = pd.concat([weekly_feats, daily_feats, hourly_feats, trigger_feats], axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result

    @property
    def feature_count(self) -> int:
        """特征总数"""
        return (
            len(_weekly_accumulation_names())
            + len(_daily_confirmation_names())
            + len(_hourly_timing_names())
            + len(_qualitative_trigger_names())
        )

    @property
    def feature_categories(self) -> Dict[str, str]:
        """特征分类（用于卦象映射）"""
        return {
            "weekly_accumulation": "周线量变积累 - 趋势/动量/成交量累积",
            "daily_confirmation": "日线质变确认 - 中期趋势共振",
            "hourly_timing": "小时线入场时机 - 短期突破/动量",
            "qualitative_trigger": "质变触发信号 - 量变→质变合成",
        }


# ===== FeatureRegistry 注册 =====
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry, _wdh_sub_key_splitter

FeatureRegistry.register(
    name="wdh",
    factory=WDHFeatures,
    sub_key_splitter=_wdh_sub_key_splitter,
)
