"""leader_form — P 层龙头形态特征（SPEC-EMERGENCE-FINANCIAL-ENV §6.2，补齐 G6）

补齐 21-特征工程中心 缺失的形态层：多均线栈 / Pivot Point / OBV 背离 / 布林状态 /
RSI14 / MACD。SMA 10/20/50、EMA 12、RSI14、MACD、BOLL、ATR、ADX、OBV、
Williams %R 等仍由 `classic_indicators.py` 提供；本模块只补龙头日线口径的新增项
（RSI 用 Wilder 平滑，柱状图 `2*(DIF-DEA)`，与 classic 的简单均值口径不同，避免混用）。

⚠️ 形态层自律（SPEC §6.3，改代码前必读）
  1. 5/13/65/128/200 这组参数**没有普适最优**，属参数拟合；本模块使用它们
     仅因业务方指定，`ma_stack_state` / `ma_dist_*` 的任何结论必须标注
     「参数敏感性未验证」。
  2. Pivot Point **无学术预测力证据**，只能当"共识参考位"，禁止单独触发交易。
  3. OBV 背离**证据混合**，只能作辅助确认。
  4. 形态层因子进入决策前必须过 SPEC §7.5 四道统计关；若增量 IC 不显著 →
     如实标记 `falsified`，**不得因为"业务方要求"而保留为信号**。

前视纪律：Pivot 用**前一根 bar** 的 H/L/C 计算（当日盘中即可得），
不使用当日收盘价，避免同日特征含同日收盘信息。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

MA_PERIODS = (5, 13, 65, 128, 200)
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
# 相邻均线距离 < 1% 视为 compressed（SPEC §6.2）
FLAT_EPS = 0.01
OBV_SLOPE_WINDOW = 20
OBV_DIV_WINDOW = 60
BOLL_WINDOW = 20
BOLL_STD = 2.0
SQUEEZE_WINDOW = 20


MA_STACK_STATES = ("perfect_bull", "perfect_bear", "compressed", "mixed")


def _ma_stack_state(mas: list[pd.Series]) -> pd.DataFrame:
    """均线排列状态 one-hot（任意均线缺失时四列全为 NaN，不猜）。

    perfect_bull: ma5 > ma13 > ma65 > ma128 > ma200
    perfect_bear: 完全反向
    compressed:   相邻均线距离全部 < 1%
    mixed:        其余

    输出 one-hot 而非字符串列：FeatureHub 清洗链（InfNaNImpute/VIF）按数值矩阵处理，
    字符串列会触发 "Cannot convert [...] to numeric" 并让整个集合降级为 raw features。
    """
    stack = pd.concat(mas, axis=1)
    labels = pd.Series(np.nan, index=stack.index, dtype=object)
    ok = stack.notna().all(axis=1)
    if ok.any():
        vals = stack[ok].to_numpy(dtype=float)
        diffs = np.diff(vals, axis=1)
        bull = (diffs < 0).all(axis=1)
        bear = (diffs > 0).all(axis=1)
        gaps = np.abs(diffs) / (np.abs(vals[:, :-1]) + 1e-12) < FLAT_EPS
        compressed = gaps.all(axis=1) & ~bull & ~bear
        labels[ok] = np.where(
            bull,
            "perfect_bull",
            np.where(bear, "perfect_bear", np.where(compressed, "compressed", "mixed")),
        )
    return pd.DataFrame(
        {state: (labels == state).astype(float) for state in MA_STACK_STATES},
        index=stack.index,
    ).where(labels.notna(), np.nan)


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """龙头形态特征（SPEC §6.2 全量）。

    Args:
        df: 必须含 close / high / low / volume（按日期升序）
        ref_df / macro_df / symbol: FeatureHub 统一签名，本模块未使用

    Returns:
        与 df 同索引的 DataFrame，列见 SPEC §6.2：
        ma_* / ma_stack_state / ma_dist_* / above_ma200 /
        pivot_* / dist_to_* / vol_ratio_5_20 / obv_slope_20 /
        obv_divergence / rsi14 / macd_dif / macd_dea / macd_hist / boll_*
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    result = pd.DataFrame(index=df.index)

    # === 多均线栈（描述用，参数敏感性未验证）===
    mas = []
    for period in MA_PERIODS:
        ma = close.rolling(period).mean()
        result[f"ma_{period}"] = ma
        mas.append(ma)
        result[f"ma_dist_{period}"] = (close - ma) / ma  # SPEC ma_dist_pct[i]
    result["above_ma200"] = (close > result["ma_200"]).astype(float)
    stack_state = _ma_stack_state(mas)
    for state in MA_STACK_STATES:
        result[f"ma_stack_{state}"] = stack_state[state]

    # === Pivot Point（前一根 bar 的 H/L/C；仅共识参考位）===
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    p = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * p - prev_low
    s1 = 2 * p - prev_high
    r2 = p + (prev_high - prev_low)
    s2 = p - (prev_high - prev_low)
    result["pivot_p"], result["pivot_r1"], result["pivot_s1"] = p, r1, s1
    result["pivot_r2"], result["pivot_s2"] = r2, s2
    for name, level in (("pivot", p), ("r1", r1), ("s1", s1)):
        result[f"dist_to_{name}"] = (close - level) / level

    # === 量能 ===
    result["vol_ratio_5_20"] = volume.rolling(5).mean() / volume.rolling(20).mean()

    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    idx = np.arange(OBV_SLOPE_WINDOW)
    result["obv_slope_20"] = obv.rolling(OBV_SLOPE_WINDOW).apply(
        lambda y: float(np.polyfit(idx, y, 1)[0]), raw=True
    )
    # OBV 背离（±1/0）：-1 = 价格创 60 日新高但 OBV 未创新高（顶背离），
    # +1 = 价格创 60 日新低但 OBV 未创新低（底背离），0 = 无背离/预热期
    px_high = close >= close.rolling(OBV_DIV_WINDOW).max()
    px_low = close <= close.rolling(OBV_DIV_WINDOW).min()
    obv_high = obv >= obv.rolling(OBV_DIV_WINDOW).max()
    obv_low = obv <= obv.rolling(OBV_DIV_WINDOW).min()
    result["obv_divergence"] = np.select(
        [px_high & ~obv_high, px_low & ~obv_low], [-1.0, 1.0], default=0.0
    )

    # === RSI14（Wilder 平滑；与 classic_indicators 的简单均值口径不同，见模块 docstring）===
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1.0 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # 单边行情：无下跌 → 100；无上涨 → 0；完全横盘 → 50（不伪造极值）
    flat = avg_gain.eq(0.0) & avg_loss.eq(0.0)
    rsi = rsi.where(~avg_loss.eq(0.0), 100.0).where(~avg_gain.eq(0.0), 0.0)
    result["rsi14"] = rsi.where(~flat, 50.0).where(avg_gain.notna())

    # === MACD（EMA12/26/9）；柱状图按 A 股惯例 `2*(DIF-DEA)` ===
    ema_fast = close.ewm(span=MACD_FAST, adjust=False, min_periods=MACD_FAST).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False, min_periods=MACD_SLOW).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=MACD_SIGNAL, adjust=False, min_periods=MACD_SIGNAL).mean()
    result["macd_dif"], result["macd_dea"] = dif, dea
    result["macd_hist"] = 2.0 * (dif - dea)

    # === 布林状态 ===
    middle = close.rolling(BOLL_WINDOW).mean()
    std = close.rolling(BOLL_WINDOW).std()
    upper = middle + BOLL_STD * std
    lower = middle - BOLL_STD * std
    span = (upper - lower).replace(0, np.nan)
    result["boll_pctb"] = (close - lower) / span
    result["boll_bandwidth"] = (upper - lower) / middle
    result["boll_squeeze"] = (
        result["boll_bandwidth"] <= result["boll_bandwidth"].rolling(SQUEEZE_WINDOW).min()
    ).astype(float)

    return result
