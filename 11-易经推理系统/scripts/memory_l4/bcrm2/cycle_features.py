"""
库存周期特征模块 — 4年基钦周期 × 加密货币减半周期

理论映射 (基钦周期 → 加密市场):
  被动去库存(复苏) → 熊市底部 → 价格触底回升，成交量温和放大
  主动补库存(繁荣) → 牛市上升 → 价格持续上涨，FOMO情绪
  被动补库存(滞胀) → 牛市顶部 → 价格见顶震荡，成交量萎缩
  主动去库存(衰退) → 熊市下跌 → 价格持续下跌，恐慌抛售

与其他时间框架的关系:
  4年库存周期(大周期) → MA200牛熊线(年线) → 周线(月) → 日线(周) → 小时线(日)
  构成完整的多周期嵌套时间框架
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime


# BTC减半历史日期 (用于硬时间锚点)
BTC_HALVING_DATES = [
    datetime(2012, 11, 28),   # 第1次减半
    datetime(2016, 7, 9),     # 第2次减半
    datetime(2020, 5, 11),    # 第3次减半
    datetime(2024, 4, 20),    # 第4次减半
    datetime(2028, 4, 1),     # 第5次减半 (预估)
]

CYCLE_LENGTH_DAYS = 1440  # 约4年 (365*4=1460，取1440方便计算)


def halving_cycle_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    减半周期特征 — 基于BTC减半日期的硬时间锚点

    特征:
      - hc_days_since_halving: 距上次减半天数
      - hc_days_to_next_halving: 距下次减半天数
      - hc_phase: 周期相位 (0=刚减半, 1=下次减半)
      - hc_sine: 周期位置的正弦表示 (捕捉周期性)
      - hc_cosine: 周期位置的余弦表示
    """
    result = pd.DataFrame(index=df.index)

    # 找到每个时间点对应的上次/下次减半
    timestamps = df.index

    def find_halving_idx(ts):
        for i, hdate in enumerate(BTC_HALVING_DATES[:-1]):
            next_hdate = BTC_HALVING_DATES[i + 1]
            if hdate.tzinfo is not None:
                hdate = hdate.replace(tzinfo=None)
                next_hdate = next_hdate.replace(tzinfo=None)
            if hdate <= ts.replace(tzinfo=None) < next_hdate:
                return i, hdate, next_hdate
        # 默认用最后两个
        return len(BTC_HALVING_DATES) - 2, BTC_HALVING_DATES[-2], BTC_HALVING_DATES[-1]

    days_since = []
    days_to = []
    phase = []
    sine_vals = []
    cosine_vals = []

    for ts in timestamps:
        _, prev_h, next_h = find_halving_idx(ts)
        prev_h = prev_h.replace(tzinfo=None)
        next_h = next_h.replace(tzinfo=None)
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts

        ds = (ts_naive - prev_h).days
        dt = (next_h - ts_naive).days
        total = (next_h - prev_h).days

        p = ds / total if total > 0 else 0.5
        days_since.append(ds)
        days_to.append(dt)
        phase.append(p)
        sine_vals.append(np.sin(2 * np.pi * p))
        cosine_vals.append(np.cos(2 * np.pi * p))

    result['hc_days_since_halving'] = days_since
    result['hc_days_to_next_halving'] = days_to
    result['hc_phase'] = phase
    result['hc_sine'] = sine_vals
    result['hc_cosine'] = cosine_vals

    return result


def all_time_high_features(
    df: pd.DataFrame,
    windows: List[int] = None,
) -> pd.DataFrame:
    """
    历史高低点特征 — 与斐波那契呼应

    特征:
      - ath_dist_xxx: 距xxx日高点跌幅百分比
      - atl_dist_xxx: 距xxx日低点涨幅百分比
      - ath_position_xxx: 在xxx日高低区间的位置 (0=低点, 1=高点)
      - ath_drawdown_xxx: 从高点回撤百分比
      - fib_05_retrace: 是否在50%回撤位附近
      - fib_0618_retrace: 是否在61.8%回撤位附近
    """
    if windows is None:
        windows = [60, 120, 240, 480, 1000]

    result = pd.DataFrame(index=df.index)
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    for w in windows:
        # 滚动最高/最低
        roll_high = pd.Series(high).rolling(window=w, min_periods=max(10, w//10)).max().values
        roll_low = pd.Series(low).rolling(window=w, min_periods=max(10, w//10)).min().values

        # 距高点跌幅
        ath_dist = (close - roll_high) / np.where(roll_high > 0, roll_high, 1) * 100
        result[f'ath_dist_{w}'] = ath_dist

        # 距低点涨幅
        atl_dist = (close - roll_low) / np.where(roll_low > 0, roll_low, 1) * 100
        result[f'atl_dist_{w}'] = atl_dist

        # 在区间内的位置 (0=最低, 1=最高)
        range_vals = roll_high - roll_low
        position = np.where(range_vals > 0, (close - roll_low) / range_vals, 0.5)
        result[f'ath_position_{w}'] = position

        # 回撤幅度 (正数代表回撤多少%)
        drawdown = np.where(roll_high > 0, (roll_high - close) / roll_high * 100, 0)
        result[f'ath_drawdown_{w}'] = drawdown

        # 斐波那契回撤位 proximity
        # 0.382, 0.5, 0.618 回撤位
        for fib_level, fib_name in [(0.382, 'fib382'), (0.5, 'fib500'), (0.618, 'fib618')]:
            fib_price = roll_high - (roll_high - roll_low) * fib_level
            dist_from_fib = np.abs(close - fib_price) / np.where(roll_high > 0, roll_high, 1) * 100
            result[f'ath_{fib_name}_dist_{w}'] = dist_from_fib

    return result


def inventory_cycle_phase(df: pd.DataFrame) -> pd.DataFrame:
    """
    库存周期四阶段识别 — 用价格+波动率+成交量代理

    四阶段映射:
      被动去库存(复苏): 价格上升 + 波动率下降 + 成交量温和
      主动补库存(繁荣): 价格快速上升 + 波动率上升 + 成交量放大
      被动补库存(滞胀): 价格见顶横盘 + 波动率高 + 成交量萎缩
      主动去库存(衰退): 价格下降 + 波动率高 + 成交量放大

    特征:
      - ic_phase: 四阶段编码 (0-3)
      - ic_phase_sine/cosine: 周期位置的三角函数表示
      - ic_recovery_score: 复苏强度
      - ic_expansion_score: 繁荣强度
      - ic_stagflation_score: 滞胀强度
      - ic_contraction_score: 衰退强度
    """
    result = pd.DataFrame(index=df.index)

    close = df['close'].values
    volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))

    # 价格变化率 (20日动量)
    roc20 = pd.Series(close).pct_change(20).fillna(0).values * 100
    roc60 = pd.Series(close).pct_change(60).fillna(0).values * 100

    # 波动率 (20日ATR / 价格)
    high = df['high'].values
    low = df['low'].values
    tr = np.maximum(high - low, np.maximum(
        np.abs(high - np.roll(close, 1)),
        np.abs(low - np.roll(close, 1))
    ))
    tr[0] = high[0] - low[0]
    atr20 = pd.Series(tr).rolling(20, min_periods=5).mean().values
    vol_ratio = atr20 / np.where(close > 0, close, 1) * 100

    # 成交量变化 (20日均量 / 60日均量)
    vol_ma20 = pd.Series(volume).rolling(20, min_periods=5).mean().fillna(0).values
    vol_ma60 = pd.Series(volume).rolling(60, min_periods=10).mean().fillna(0).values
    vol_change = np.where(vol_ma60 > 0, (vol_ma20 - vol_ma60) / vol_ma60 * 100, 0)

    # 趋势方向 (MA20 vs MA60)
    ma20 = pd.Series(close).rolling(20, min_periods=5).mean().values
    ma60 = pd.Series(close).rolling(60, min_periods=10).mean().values
    trend = np.where(ma60 > 0, (ma20 - ma60) / ma60 * 100, 0)

    # 四阶段评分
    # 复苏: 价格正 + 波动率低 + 成交量温和增长
    recovery = np.clip(roc20 * 0.3 + (10 - vol_ratio) * 0.4 + np.clip(vol_change, 0, 50) * 0.3, 0, 100)

    # 繁荣: 价格强正 + 波动率中高 + 成交量大增
    expansion = np.clip(roc60 * 0.4 + vol_ratio * 0.2 + np.clip(vol_change, 0, 100) * 0.4, 0, 100)

    # 滞胀: 价格走平/微跌 + 波动率高 + 成交量下降
    stagflation = np.clip(
        (np.abs(roc20) < 5).astype(float) * 30
        + vol_ratio * 3
        + np.clip(-vol_change, 0, 50) * 0.8,
        0, 100
    )

    # 衰退: 价格负 + 波动率高 + 成交量大
    contraction = np.clip(-roc20 * 0.3 + vol_ratio * 0.3 + np.clip(vol_change, -50, 50) * 0.2, 0, 100)
    contraction = np.where(roc20 < 0, contraction, contraction * 0.3)

    result['ic_recovery_score'] = recovery
    result['ic_expansion_score'] = expansion
    result['ic_stagflation_score'] = stagflation
    result['ic_contraction_score'] = contraction

    # 主导阶段 (0=复苏, 1=繁荣, 2=滞胀, 3=衰退)
    scores = np.column_stack([recovery, expansion, stagflation, contraction])
    dominant_phase = np.argmax(scores, axis=1)
    result['ic_phase'] = dominant_phase

    # 周期位置 (0-1, 用四阶段得分的加权角)
    phase_angle = dominant_phase / 4.0 + (scores[np.arange(len(scores)), dominant_phase] / 200)
    result['ic_phase_sine'] = np.sin(2 * np.pi * phase_angle)
    result['ic_phase_cosine'] = np.cos(2 * np.pi * phase_angle)

    return result


def long_term_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    长期趋势特征 — MA200 + 更长周期均线

    与MA200牛熊线呼应，构成完整的大周期判断:
      - ma200_slope: 200日均线斜率 (牛熊方向)
      - ma300_slope: 300日均线斜率
      - price_vs_ma200: 价格相对MA200的位置 (%)
      - ma200_breadth: MA50/MA200宽度 (%)
      - golden_death_cross: 金叉/死叉信号 (MA50穿越MA200)
    """
    result = pd.DataFrame(index=df.index)
    close = df['close'].values

    for period in [100, 200, 300]:
        ma = pd.Series(close).rolling(period, min_periods=period//2).mean().values
        result[f'lt_ma{period}'] = ma
        # 斜率 (10日变化率)
        ma_lag = np.roll(ma, 10)
        slope = np.where(ma_lag > 0, (ma - ma_lag) / ma_lag * 100, 0)
        result[f'lt_ma{period}_slope'] = slope
        # 价格相对位置
        result[f'lt_price_vs_ma{period}'] = np.where(ma > 0, (close - ma) / ma * 100, 0)

    # MA50 vs MA200 宽度
    ma50 = pd.Series(close).rolling(50, min_periods=25).mean().values
    ma200 = result['lt_ma200'].values
    result['lt_ma50_ma200_spread'] = np.where(ma200 > 0, (ma50 - ma200) / ma200 * 100, 0)

    # 金叉/死叉 (MA50上穿/下穿MA200)
    spread = ma50 - ma200
    spread_prev = np.roll(spread, 1)
    golden_cross = (spread_prev < 0) & (spread > 0)
    death_cross = (spread_prev > 0) & (spread < 0)
    result['lt_golden_cross'] = golden_cross.astype(int)
    result['lt_death_cross'] = death_cross.astype(int)

    # 距上次金叉/死叉的bar数
    bars_since_gc = np.zeros(len(close))
    bars_since_dc = np.zeros(len(close))
    gc_count = 0
    dc_count = 0
    for i in range(len(close)):
        if golden_cross[i]:
            gc_count = 0
        else:
            gc_count += 1
        if death_cross[i]:
            dc_count = 0
        else:
            dc_count += 1
        bars_since_gc[i] = gc_count
        bars_since_dc[i] = dc_count
    result['lt_bars_since_golden'] = bars_since_gc
    result['lt_bars_since_death'] = bars_since_dc

    return result


class CycleFeatures:
    """
    库存周期特征总入口

    四大类特征:
      1. 减半周期特征 (硬时间锚点) - 5个特征
      2. 历史高低点特征 (斐波那契呼应) - ~30个特征
      3. 库存周期四阶段 (基钦周期映射) - 7个特征
      4. 长期趋势特征 (MA200牛熊线) - ~15个特征

    总计: ~57个特征
    """

    def __init__(self, symbol: str = "BTC"):
        self.symbol = symbol

    def compute(
        self,
        df: pd.DataFrame,
        enable_halving: bool = True,
        enable_ath: bool = True,
        enable_inventory: bool = True,
        enable_long_term: bool = True,
    ) -> pd.DataFrame:
        """计算周期特征 (子模块可开关)

        Args:
            df: OHLCV数据
            enable_halving: 减半周期特征
            enable_ath: 历史高低点+斐波那契回撤
            enable_inventory: 库存周期四阶段
            enable_long_term: 长期趋势MA100/200/300
        """
        feats_list = []

        if enable_halving:
            feats_list.append(halving_cycle_features(df))
        if enable_ath:
            feats_list.append(all_time_high_features(df))
        if enable_inventory:
            feats_list.append(inventory_cycle_phase(df))
        if enable_long_term:
            feats_list.append(long_term_trend_features(df))

        if not feats_list:
            return pd.DataFrame(index=df.index)

        result = pd.concat(feats_list, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result

    @property
    def n_features(self) -> int:
        """特征总数 (估算)"""
        return 57
