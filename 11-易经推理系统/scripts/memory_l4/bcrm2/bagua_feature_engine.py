"""
八卦特征工程引擎 — 八卦力学的算法落地

理论映射:
  八卦力学的8种力场拓扑模式 → 8个特征维度
  每一卦对应一类市场结构特征

八卦-特征映射:
  乾(天) ☰ → 趋势强度特征 (Trend) — 天行健，趋势的力量
  坤(地) ☷ → 支撑阻力特征 (Support/Resistance) — 地势坤，承载与压力
  震(雷) ☳ → 动量突破特征 (Momentum) — 雷动震动，突破的力量
  巽(风) ☴ → 波动率特征 (Volatility) — 风无定形，波动的变化
  坎(水) ☵ → 成交量特征 (Volume) — 水流无形，资金的流动
  离(火) ☲ → 蜡烛形态特征 (Candlestick) — 火明而丽，价格形态
  艮(山) ☶ → 市场结构特征 (Structure) — 山止不动，结构与形态
  兑(泽) ☱ → 多周期共振特征 (Multi-TF) — 泽悦而和，周期的共鸣
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple


# ============================================================
# 卦象-特征维度映射
# ============================================================

BAGUA_FEATURE_MAP = {
    "qian_trend": "乾卦-趋势强度",
    "kun_sr": "坤卦-支撑阻力",
    "zhen_momentum": "震卦-动量突破",
    "xun_volatility": "巽卦-波动率",
    "kan_volume": "坎卦-成交量",
    "li_candlestick": "离卦-蜡烛形态",
    "gen_structure": "艮卦-市场结构",
    "dui_multitf": "兑卦-多周期共振",
}


# ============================================================
# 乾卦 ☰ 趋势强度特征 (Trend)
# ============================================================

def _qian_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """乾卦: 天行健，君子以自强不息 — 趋势的力量"""
    feats = pd.DataFrame(index=df.index)

    # MA均线族
    for period in [5, 10, 20, 50, 100, 200]:
        ma = df["close"].rolling(window=period).mean()
        feats[f"qian_ma{period}_pos"] = (df["close"] - ma) / ma
        feats[f"qian_ma{period}_slope"] = ma.pct_change(5)

    # EMA
    for period in [12, 26, 50]:
        ema = df["close"].ewm(span=period, adjust=False).mean()
        feats[f"qian_ema{period}_pos"] = (df["close"] - ema) / ema

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = dif - dea
    feats["qian_macd_dif"] = dif / df["close"]
    feats["qian_macd_dea"] = dea / df["close"]
    feats["qian_macd_hist"] = macd_hist / df["close"]
    feats["qian_macd_signal"] = (dif > dea).astype(float)

    # ADX趋势强度
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    plus_dm = np.where((df["high"] - df["high"].shift()) > (df["low"].shift() - df["low"]),
                       np.maximum(df["high"] - df["high"].shift(), 0), 0)
    minus_dm = np.where((df["low"].shift() - df["low"]) > (df["high"] - df["high"].shift()),
                        np.maximum(df["low"].shift() - df["low"], 0), 0)

    atr14 = tr.rolling(14).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean()

    feats["qian_adx"] = adx / 100.0
    feats["qian_plus_di"] = plus_di / 100.0
    feats["qian_minus_di"] = minus_di / 100.0
    feats["qian_trend_dir"] = np.where(plus_di > minus_di, 1.0, -1.0)

    # 均线排列: 多头排列=1, 空头排列=-1, 混乱=0
    ma5 = df["close"].rolling(5).mean()
    ma10 = df["close"].rolling(10).mean()
    ma20 = df["close"].rolling(20).mean()
    ma50 = df["close"].rolling(50).mean()
    bull = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma50)
    bear = (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma50)
    feats["qian_ma_alignment"] = np.where(bull, 1.0, np.where(bear, -1.0, 0.0))

    return feats


# ============================================================
# 坤卦 ☷ 支撑阻力特征 (Support/Resistance)
# ============================================================

def _kun_sr_features(df: pd.DataFrame) -> pd.DataFrame:
    """坤卦: 地势坤，君子以厚德载物 — 支撑与压力的承载"""
    feats = pd.DataFrame(index=df.index)

    # 布林带位置
    for period in [20, 50]:
        ma = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        # %b指标: 当前价格在布林带中的位置
        feats[f"kun_boll{period}_pctb"] = (df["close"] - lower) / (upper - lower + 1e-10)
        feats[f"kun_boll{period}_width"] = (upper - lower) / ma
        feats[f"kun_boll{period}_expand"] = ((upper - lower) / ma).pct_change(5)

    # 近期高低点位置
    for period in [20, 60, 120]:
        roll_high = df["high"].rolling(period).max()
        roll_low = df["low"].rolling(period).min()
        feats[f"kun_high{period}_dist"] = (roll_high - df["close"]) / df["close"]
        feats[f"kun_low{period}_dist"] = (df["close"] - roll_low) / df["close"]
        feats[f"kun_range{period}_pos"] = (df["close"] - roll_low) / (roll_high - roll_low + 1e-10)

    # Keltner通道
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    tr = pd.concat([
        df["high"] - df["low"],
        np.abs(df["high"] - df["close"].shift()),
        np.abs(df["low"] - df["close"].shift())
    ], axis=1).max(axis=1)
    atr10 = tr.rolling(10).mean()
    kupper = ema20 + 2 * atr10
    klower = ema20 - 2 * atr10
    feats["kun_kelt_pctb"] = (df["close"] - klower) / (kupper - klower + 1e-10)

    # VWAP位置 (日内近似用滚动vwap)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (typical_price * df["volume"]).rolling(24).sum() / df["volume"].rolling(24).sum()
    feats["kun_vwap_pos"] = (df["close"] - vwap) / (vwap + 1e-10)

    # 整数关口距离 (价格相对于最近整数的位置)
    round_levels = [round(df["close"].iloc[i] / (10 ** max(0, int(np.log10(abs(df["close"].iloc[i]))) - 1)))
                    * (10 ** max(0, int(np.log10(abs(df["close"].iloc[i]))) - 1))
                    for i in range(len(df))]
    feats["kun_round_dist"] = np.abs(df["close"].values - np.array(round_levels)) / df["close"].values

    return feats


# ============================================================
# 震卦 ☳ 动量突破特征 (Momentum)
# ============================================================

def _zhen_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """震卦: 洊雷震，君子以恐惧修省 — 动量与突破的震动"""
    feats = pd.DataFrame(index=df.index)

    # RSI族
    for period in [6, 14, 28]:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        feats[f"zhen_rsi{period}"] = rsi / 100.0

    # Stochastic随机指标
    for k_period in [14, 28]:
        lowest_low = df["low"].rolling(k_period).min()
        highest_high = df["high"].rolling(k_period).max()
        stoch_k = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low + 1e-10)
        stoch_d = stoch_k.rolling(3).mean()
        feats[f"zhen_stoch{k_period}_k"] = stoch_k / 100.0
        feats[f"zhen_stoch{k_period}_d"] = stoch_d / 100.0
        feats[f"zhen_stoch{k_period}_cross"] = np.where(stoch_k > stoch_d, 1.0, -1.0)

    # CCI商品通道指数
    for period in [20]:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = tp.rolling(period).mean()
        mad = np.abs(tp - sma_tp).rolling(period).mean()
        cci = (tp - sma_tp) / (0.015 * mad + 1e-10)
        feats[f"zhen_cci{period}"] = np.clip(cci / 200.0, -2, 2)

    # ROC变动率
    for period in [5, 10, 20, 60]:
        feats[f"zhen_roc{period}"] = df["close"].pct_change(period)

    # MFI资金流量指数
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos_mf = np.where(df["close"] > df["close"].shift(), mf, 0)
    neg_mf = np.where(df["close"] < df["close"].shift(), mf, 0)
    mr = pd.Series(pos_mf, index=df.index).rolling(14).sum() / (
        pd.Series(neg_mf, index=df.index).rolling(14).sum() + 1e-10)
    feats["zhen_mfi"] = 100 - 100 / (1 + mr)
    feats["zhen_mfi"] = feats["zhen_mfi"] / 100.0

    # Williams %R
    for period in [14]:
        highest_high = df["high"].rolling(period).max()
        lowest_low = df["low"].rolling(period).min()
        willr = -100 * (highest_high - df["close"]) / (highest_high - lowest_low + 1e-10)
        feats[f"zhen_willr{period}"] = willr / 100.0  # -1到0

    # 突破标记: 突破N日新高/新低
    for period in [20, 60]:
        feats[f"zhen_break_high{period}"] = (df["close"] > df["high"].rolling(period).max().shift()).astype(float)
        feats[f"zhen_break_low{period}"] = (df["close"] < df["low"].rolling(period).min().shift()).astype(float)

    return feats


# ============================================================
# 巽卦 ☴ 波动率特征 (Volatility)
# ============================================================

def _xun_volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    """巽卦: 随风巽，君子以申命行事 — 波动的风性，无形而多变"""
    feats = pd.DataFrame(index=df.index)

    # 历史波动率 (标准差法)
    returns = df["close"].pct_change()
    for period in [10, 20, 60, 120]:
        vol = returns.rolling(period).std()
        feats[f"xun_vol{period}"] = vol * np.sqrt(365 * 24)  # 年化 (1h K线)
        feats[f"xun_vol{period}_change"] = vol.pct_change(5)

    # ATR真实波幅
    tr = pd.concat([
        df["high"] - df["low"],
        np.abs(df["high"] - df["close"].shift()),
        np.abs(df["low"] - df["close"].shift())
    ], axis=1).max(axis=1)
    for period in [14, 28]:
        atr = tr.rolling(period).mean()
        feats[f"xun_atr{period}"] = atr / df["close"]
        feats[f"xun_atr{period}_ratio"] = atr / atr.rolling(period * 2).mean()

    # 波动率锥位置
    vol_20 = returns.rolling(20).std()
    vol_60 = returns.rolling(60).std()
    vol_120 = returns.rolling(120).std()
    feats["xun_vol_cone_pos"] = (vol_20 - vol_120) / (vol_60 + 1e-10)

    # K线实体与影线比例
    body = np.abs(df["close"] - df["open"])
    upper_shadow = df["high"] - np.maximum(df["close"], df["open"])
    lower_shadow = np.minimum(df["close"], df["open"]) - df["low"]
    tr_val = tr + 1e-10
    feats["xun_body_ratio"] = body / tr_val
    feats["xun_upper_shadow_ratio"] = upper_shadow / tr_val
    feats["xun_lower_shadow_ratio"] = lower_shadow / tr_val

    # 波动率压缩/扩张 (Bollinger带宽变化)
    bb_width = (df["close"].rolling(20).std() * 2) / (df["close"].rolling(20).mean() + 1e-10)
    feats["xun_bb_squeeze"] = bb_width / bb_width.rolling(60).mean()  # <1=压缩

    return feats


# ============================================================
# 坎卦 ☵ 成交量特征 (Volume)
# ============================================================

def _kan_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """坎卦: 习坎，有孚维心亨 — 水流无形，资金如流水"""
    feats = pd.DataFrame(index=df.index)

    vol = df["volume"].replace(0, np.nan).ffill().fillna(1)

    # 成交量变化率
    for period in [1, 5, 10, 20]:
        vol_ma = vol.rolling(period).mean()
        feats[f"kan_vol_ratio{period}"] = vol / (vol_ma + 1e-10)

    # 量价配合
    price_change = df["close"].pct_change()
    feats["kan_vol_price_corr"] = price_change.rolling(20).corr(vol.pct_change().fillna(0))
    feats["kan_vol_price_corr"] = feats["kan_vol_price_corr"].fillna(0)

    # 量价背离
    price_ma20 = df["close"].rolling(20).mean()
    vol_ma20 = vol.rolling(20).mean()
    price_trend = price_ma20.pct_change(10)
    vol_trend = vol_ma20.pct_change(10)
    # 顶背离: 价格新高, 量不新高
    feats["kan_bear_divergence"] = ((price_trend > 0) & (vol_trend < 0)).astype(float)
    # 底背离: 价格新低, 量不新低
    feats["kan_bull_divergence"] = ((price_trend < 0) & (vol_trend > 0)).astype(float)

    # OBV能量潮
    obv = pd.Series(0.0, index=df.index)
    direction = np.sign(df["close"].diff()).fillna(0)
    obv = (direction * vol).cumsum()
    feats["kan_obv"] = obv
    feats["kan_obv_slope"] = obv.pct_change(10).replace([np.inf, -np.inf], 0)

    # VWAP偏离
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (typical_price * vol).rolling(24).sum() / vol.rolling(24).sum()
    feats["kan_vwap_dev"] = (df["close"] - vwap) / (vwap + 1e-10)

    # 放量/缩量标记
    vol_ma20 = vol.rolling(20).mean()
    vol_std20 = vol.rolling(20).std()
    feats["kan_high_vol"] = (vol > vol_ma20 + 2 * vol_std20).astype(float)
    feats["kan_low_vol"] = (vol < vol_ma20 - vol_std20).astype(float)

    return feats


# ============================================================
# 离卦 ☲ 蜡烛形态特征 (Candlestick)
# ============================================================

def _li_candlestick_features(df: pd.DataFrame) -> pd.DataFrame:
    """离卦: 明两作离，大人以继明照于四方 — 蜡烛图如火焰照亮市场"""
    feats = pd.DataFrame(index=df.index)

    open_p = df["open"]
    high_p = df["high"]
    low_p = df["low"]
    close_p = df["close"]

    # 基本形态编码
    body = close_p - open_p
    body_abs = np.abs(body)
    tr = pd.concat([high_p - low_p,
                    np.abs(high_p - close_p.shift()),
                    np.abs(low_p - close_p.shift())], axis=1).max(axis=1)

    # 阴阳线
    feats["li_bull_candle"] = (body > 0).astype(float)
    feats["li_body_size"] = body_abs / (tr + 1e-10)

    # 十字星 (小实体)
    feats["li_doji"] = (body_abs < 0.1 * tr).astype(float)

    # 锤子/流星 (长下影/长上影 + 小实体)
    upper_shadow = high_p - np.maximum(close_p, open_p)
    lower_shadow = np.minimum(close_p, open_p) - low_p
    feats["li_hammer"] = ((lower_shadow > 2 * body_abs) &
                          (upper_shadow < 0.5 * body_abs) &
                          (body_abs > 0)).astype(float)
    feats["li_shooting_star"] = ((upper_shadow > 2 * body_abs) &
                                 (lower_shadow < 0.5 * body_abs) &
                                 (body_abs > 0)).astype(float)

    # 吞没形态 (简化版)
    prev_body = body.shift()
    feats["li_bull_engulf"] = ((prev_body < 0) & (body > 0) &
                               (open_p <= close_p.shift()) &
                               (close_p >= open_p.shift())).astype(float)
    feats["li_bear_engulf"] = ((prev_body > 0) & (body < 0) &
                               (open_p >= close_p.shift()) &
                               (close_p <= open_p.shift())).astype(float)

    # 连续涨跌根数
    direction = np.sign(body)
    streak = pd.Series(0, index=df.index, dtype=float)
    for i in range(1, len(df)):
        if direction.iloc[i] == direction.iloc[i-1] and direction.iloc[i] != 0:
            streak.iloc[i] = streak.iloc[i-1] + 1
        else:
            streak.iloc[i] = 1.0 if direction.iloc[i] != 0 else 0.0
    feats["li_trend_streak"] = streak * direction

    # 跳空缺口
    feats["li_gap_up"] = (open_p > high_p.shift()).astype(float)
    feats["li_gap_down"] = (open_p < low_p.shift()).astype(float)
    feats["li_gap_size"] = np.where(open_p > high_p.shift(),
                                    (open_p - high_p.shift()) / close_p.shift(),
                                    np.where(open_p < low_p.shift(),
                                             (low_p.shift() - open_p) / close_p.shift(), 0))

    return feats


# ============================================================
# 艮卦 ☶ 市场结构特征 (Structure)
# ============================================================

def _gen_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    """艮卦: 兼山艮，君子以思不出其位 — 市场如山，结构稳定"""
    feats = pd.DataFrame(index=df.index)

    returns = df["close"].pct_change()

    # 市场状态: 趋势vs震荡 (ADX)
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    plus_dm = np.where((df["high"] - df["high"].shift()) > (df["low"].shift() - df["low"]),
                       np.maximum(df["high"] - df["high"].shift(), 0), 0)
    minus_dm = np.where((df["low"].shift() - df["low"]) > (df["high"] - df["high"].shift()),
                        np.maximum(df["low"].shift() - df["low"], 0), 0)
    atr14 = tr.rolling(14).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean()
    feats["gen_regime"] = np.where(adx > 25, 1.0, 0.0)  # 1=趋势, 0=震荡

    # Hurst指数近似 (用RS法简化)
    def hurst_approx(series, n=20):
        lags = [2, 4, 8, 16]
        tau = []
        for lag in lags:
            if len(series) < lag * 4:
                continue
            delta = series.diff(lag).dropna()
            tau.append(np.std(delta))
        if len(tau) < 2:
            return 0.5
        return np.polyfit(np.log(lags[:len(tau)]), np.log(tau), 1)[0] / 2.0

    # 滚动Hurst估计
    hurst_vals = pd.Series(0.5, index=df.index, dtype=float)
    log_close = np.log(df["close"])
    for i in range(60, len(df)):
        hurst_vals.iloc[i] = hurst_approx(log_close.iloc[i-60:i])
    feats["gen_hurst"] = hurst_vals

    # 自相关性
    feats["gen_autocorr_1"] = returns.rolling(60).apply(
        lambda x: pd.Series(x).autocorr(1) if len(x) > 10 else 0, raw=False
    ).fillna(0)

    # 波动率聚类 (ARCH效应近似)
    sq_ret = returns ** 2
    feats["gen_vol_cluster"] = sq_ret.rolling(20).corr(sq_ret.shift()).fillna(0)

    # 局部高点/低点标记 (用前后N根K线比较)
    for period in [5, 10]:
        feats[f"gen_local_high{period}"] = (
            df["high"] == df["high"].rolling(2*period+1, center=True).max()
        ).astype(float)
        feats[f"gen_local_low{period}"] = (
            df["low"] == df["low"].rolling(2*period+1, center=True).min()
        ).astype(float)

    # 支撑阻力位强度计数 (简化: 价格触及次数)
    for period in [60, 120]:
        roll_high = df["high"].rolling(period).max()
        roll_low = df["low"].rolling(period).min()
        near_high = (df["high"] >= roll_high * 0.97).astype(int)
        near_low = (df["low"] <= roll_low * 1.03).astype(int)
        feats[f"gen_resistance_touches{period}"] = near_high.rolling(period).sum()
        feats[f"gen_support_touches{period}"] = near_low.rolling(period).sum()

    return feats


# ============================================================
# 兑卦 ☱ 多周期共振特征 (Multi-TF)
# ============================================================

def _dui_multitf_features(df: pd.DataFrame) -> pd.DataFrame:
    """兑卦: 丽泽兑，君子以朋友讲习 — 多周期如两泽相通，共振则强"""
    feats = pd.DataFrame(index=df.index)

    returns = df["close"].pct_change()

    # 多周期动量一致性
    mom_5 = returns.rolling(5).sum()
    mom_10 = returns.rolling(10).sum()
    mom_20 = returns.rolling(20).sum()
    mom_60 = returns.rolling(60).sum()

    # 方向一致性比例
    directions = pd.DataFrame({
        "m5": np.sign(mom_5),
        "m10": np.sign(mom_10),
        "m20": np.sign(mom_20),
        "m60": np.sign(mom_60),
    })
    feats["dui_dir_consistency"] = directions.abs().mean(axis=1) * np.sign(directions.mean(axis=1))

    # 均线多周期排列一致性
    ma5 = df["close"].rolling(5).mean()
    ma10 = df["close"].rolling(10).mean()
    ma20 = df["close"].rolling(20).mean()
    ma50 = df["close"].rolling(50).mean()
    ma200 = df["close"].rolling(200).mean()

    alignment_score = (
        (ma5 > ma10).astype(float) +
        (ma10 > ma20).astype(float) +
        (ma20 > ma50).astype(float) +
        (ma50 > ma200).astype(float)
    ) / 4.0
    feats["dui_ma_alignment_score"] = alignment_score * 2 - 1  # -1到1

    # RSI多周期共振
    def rsi(series, period):
        delta = series.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs))

    rsi6 = rsi(df["close"], 6)
    rsi14 = rsi(df["close"], 14)
    rsi28 = rsi(df["close"], 28)

    feats["dui_rsi_consistency"] = (
        ((rsi6 > 50).astype(float) + (rsi14 > 50).astype(float) + (rsi28 > 50).astype(float)) / 3.0
    ) * 2 - 1

    # 波动率期限结构 (短/长波动率比)
    vol5 = returns.rolling(5).std()
    vol20 = returns.rolling(20).std()
    vol60 = returns.rolling(60).std()
    feats["dui_vol_term_slope"] = (vol5 - vol60) / (vol20 + 1e-10)

    # 成交量趋势一致性
    vol_trend = df["volume"].rolling(20).mean().pct_change(10)
    price_trend = df["close"].rolling(20).mean().pct_change(10)
    feats["dui_vol_price_trend_aligned"] = np.sign(vol_trend) == np.sign(price_trend)
    feats["dui_vol_price_trend_aligned"] = feats["dui_vol_price_trend_aligned"].astype(float)

    return feats


# ============================================================
# 主入口: 八卦特征引擎
# ============================================================

class BaguaFeatureEngine:
    """八卦特征工程引擎 — 8维度特征对应八卦力学的8种力场模式

    理论映射:
        乾卦 → 趋势强度 (天行健，趋势的力量)
        坤卦 → 支撑阻力 (地势坤，承载与压力)
        震卦 → 动量突破 (雷动震动，突破的力量)
        巽卦 → 波动率 (风无定形，波动的变化)
        坎卦 → 成交量 (水流无形，资金的流动)
        离卦 → 蜡烛形态 (火明而丽，价格形态)
        艮卦 → 市场结构 (山止不动，结构与形态)
        兑卦 → 多周期共振 (泽悦而和，周期的共鸣)
    """

    def __init__(self):
        self.feature_generators = {
            "qian": _qian_trend_features,
            "kun": _kun_sr_features,
            "zhen": _zhen_momentum_features,
            "xun": _xun_volatility_features,
            "kan": _kan_volume_features,
            "li": _li_candlestick_features,
            "gen": _gen_structure_features,
            "dui": _dui_multitf_features,
        }
        self.feature_names_by_gua = {}
        self.all_feature_names = []

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全部八卦特征

        Args:
            df: 包含 open/high/low/close/volume 的K线DataFrame

        Returns:
            DataFrame of features, index aligned with df
        """
        all_feats = []

        for gua_name, gen_fn in self.feature_generators.items():
            feats = gen_fn(df)
            self.feature_names_by_gua[gua_name] = list(feats.columns)
            all_feats.append(feats)

        result = pd.concat(all_feats, axis=1)
        self.all_feature_names = list(result.columns)

        # 填充NaN: 前向填充 + 最后用0填充
        result = result.ffill().fillna(0)
        # 替换 inf
        result = result.replace([np.inf, -np.inf], 0)

        return result

    def get_features_by_gua(self, gua: str) -> List[str]:
        """获取某一卦对应的特征名列表"""
        return self.feature_names_by_gua.get(gua, [])

    def gua_feature_count(self) -> Dict[str, int]:
        """各卦特征数量统计"""
        return {gua: len(names) for gua, names in self.feature_names_by_gua.items()}
