"""WashoutFeatureExtractor — 洗盘判定 8 维传统金融特征 + 4 维加密独有 + Wyckoff climax.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4.4 / §9.2 / §9.3

8 维传统金融特征 (F1-F8, W2 落地):
  F1 volume_ratio_20d      — vol / vol_ma20（缩量 < 0.8 / 放量 > 1.5）
  F2 support_holds_count   — 近 30d swing low 守住次数（3+ → 强支撑）
  F3 atr_compress_ratio    — ATR_5d / ATR_20d（< 1 收窄 / > 1 扩大）
  F4 oi_change_rate_7d     — (OI_t - OI_{t-7d}) / OI_{t-7d}（<-0.10 多头投降）
  F5 cycle_position_365d   — (price - low_365d) / (high_365d - low_365d)（< 0.3 低位）
  F6 rebound_ratio_5d      — (price - low_5d) / (high_5d - low_5d)（> 0.5 反弹强）
  F7 news_negative_score   — 负面新闻占比（高 → 真弱势催化）
  F8 btc_correlation_30d   — corr(coin_ret, btc_ret, 30d)（> 0.7 跟随下跌）

4 维加密独有特征 (F9-F12, W3a 落地):
  F9  oi_price_quadrant      — OI×Price 四象限 (0=OI↑Price↑, 1=OI↑Price↓, 2=OI↓Price↑, 3=OI↓Price↓)
  F10 funding_rate_zscore   — Funding rate 30d zscore (持续负=洗盘, 突然转正=真弱势反转)
  F11 cvd_price_divergence  — CVD 与价格相关性 (负=trapped trader 洗盘, 正=同步下行真弱势)
  F12 ofi_std_20d           — 20d OFI 滚动标准差 (低方差+高 vol=可疑洗盘, 高方差=真弱势)

Wyckoff climax (F13, W3a 落地):
  F13 wyckoff_climax_stage  — Wyckoff climax 阶段 (0=未触发, 1=Panic, 2=Sustained, 3=Exhaustion)

设计原则:
  - 复用 IndicatorBank 滚动 365d 区间位置逻辑（避免重复实现）
  - 每个维度独立子开关（WASHOUT_CONFIG）—— 关闭该维度 → extract_all 不输出该 key
  - FAIL-OPEN 铁律：任何异常 → 中性默认值（不抛错、不阻塞）
  - 公式遵循 §4.4 特征明细表，不重写已稳定的指标计算
  - W3a 数据源通过 macro_data dict 接入 (oi_series/cvd_series/ofi_series 等)
    缺失时返回中性默认值 (FAIL-OPEN, 与 W2 F4 OI 处理一致)
  - W3b 后续: 18-数据获取中心 3 采集器 + 奖章架构 Bronze→Silver→Gold 清洗链路
"""
from __future__ import annotations

import logging
import traceback
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .washout_detector import WASHOUT_CONFIG

__all__ = ["WashoutFeatureExtractor"]

logger = logging.getLogger(__name__)


# ============================================================
# 中性默认值（FAIL-OPEN 兜底，§4.4 特征语义中性点）
# ============================================================
NEUTRAL_DEFAULTS: Dict[str, float] = {
    # W2: 8 维传统金融特征
    "volume_ratio_20d": 1.0,        # 中性 = 与均量持平
    "support_holds_count": 0.0,    # 中性 = 无守住记录
    "atr_compress_ratio": 1.0,     # 中性 = 振幅无变化
    "oi_change_rate_7d": 0.0,      # 中性 = OI 无变化
    "cycle_position_365d": 0.5,    # 中性 = 区间中位
    "rebound_ratio_5d": 0.5,       # 中性 = 反弹至区间中位
    "news_negative_score": 0.0,    # 中性 = 无负面
    "btc_correlation_30d": 0.5,    # 中性 = 中等联动
    # W3a: 4 维加密独有特征
    "oi_price_quadrant": -1.0,    # 中性 = 无信号 (象限编码 0-3, -1 表示数据不足)
    "funding_rate_zscore": 0.0,    # 中性 = 无偏离
    "cvd_price_divergence": 0.0,    # 中性 = 无相关性
    "ofi_std_20d": 0.0,            # 中性 = 无 OFI 数据
    # W3a: Wyckoff climax
    "wyckoff_climax_stage": 0.0,   # 中性 = 未触发 climax
}


# 维度 → 子开关 key 映射（§3.3 WASHOUT_CONFIG）
DIM_TO_SWITCH: Dict[str, str] = {
    # W2: 8 维传统金融特征
    "volume_ratio_20d": "enable_volume_dim",
    "support_holds_count": "enable_support_dim",
    "atr_compress_ratio": "enable_amplitude_dim",
    "oi_change_rate_7d": "enable_oi_dim",
    "cycle_position_365d": "enable_position_dim",
    "rebound_ratio_5d": "enable_rebound_dim",
    "news_negative_score": "enable_news_dim",
    "btc_correlation_30d": "enable_market_dim",
    # W3a: 4 维加密独有特征
    "oi_price_quadrant": "enable_oi_price_quadrant",
    "funding_rate_zscore": "enable_funding_rate",
    "cvd_price_divergence": "enable_cvd",
    "ofi_std_20d": "enable_ofi",
    # W3a: Wyckoff climax
    "wyckoff_climax_stage": "enable_wyckoff_climax",
}


# ============================================================
# 主类
# ============================================================
class WashoutFeatureExtractor:
    """8 维传统金融特征提取器。

    每个 _extract_* 方法返回 float 中性默认值（异常时不抛错）。
    extract_all(df, macro_data) 是主入口，按子开关门控聚合输出。
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(config) if config else dict(WASHOUT_CONFIG)

    # ============================================================
    # 主入口：按子开关聚合 8 维特征
    # ============================================================
    def extract_all(self, df: pd.DataFrame, macro_data: Dict) -> Dict[str, float]:
        """提取所有开启维度的特征。

        Args:
            df: OHLCV DataFrame
            macro_data: 宏观特征字典（含 oi_series/btc_close/news_list 等）

        Returns:
            Dict[str, float] — 仅含开启维度的特征 key。
            关闭的维度不会出现在返回 dict 中（§3.3 子开关门控）。
        """
        out: Dict[str, float] = {}
        if df is None or macro_data is None:
            return out

        # F1: volume_ratio_20d
        if self._dim_enabled("volume_ratio_20d"):
            out["volume_ratio_20d"] = self.extract_volume_ratio_20d(df)

        # F2: support_holds_count
        if self._dim_enabled("support_holds_count"):
            out["support_holds_count"] = self.extract_support_holds_count(df)

        # F3: atr_compress_ratio
        if self._dim_enabled("atr_compress_ratio"):
            out["atr_compress_ratio"] = self.extract_atr_compress_ratio(df)

        # F4: oi_change_rate_7d
        if self._dim_enabled("oi_change_rate_7d"):
            out["oi_change_rate_7d"] = self.extract_oi_change_rate_7d(df, macro_data)

        # F5: cycle_position_365d
        if self._dim_enabled("cycle_position_365d"):
            out["cycle_position_365d"] = self.extract_cycle_position_365d(df)

        # F6: rebound_ratio_5d
        if self._dim_enabled("rebound_ratio_5d"):
            out["rebound_ratio_5d"] = self.extract_rebound_ratio_5d(df)

        # F7: news_negative_score
        if self._dim_enabled("news_negative_score"):
            out["news_negative_score"] = self.extract_news_negative_score(df, macro_data)

        # F8: btc_correlation_30d
        if self._dim_enabled("btc_correlation_30d"):
            out["btc_correlation_30d"] = self.extract_btc_correlation_30d(df, macro_data)

        # ============ W3a: 4 维加密独有特征 (F9-F12) ============
        # F9: oi_price_quadrant
        if self._dim_enabled("oi_price_quadrant"):
            out["oi_price_quadrant"] = self.extract_oi_price_quadrant(df, macro_data)

        # F10: funding_rate_zscore
        if self._dim_enabled("funding_rate_zscore"):
            out["funding_rate_zscore"] = self.extract_funding_rate_zscore(df, macro_data)

        # F11: cvd_price_divergence
        if self._dim_enabled("cvd_price_divergence"):
            out["cvd_price_divergence"] = self.extract_cvd_price_divergence(df, macro_data)

        # F12: ofi_std_20d
        if self._dim_enabled("ofi_std_20d"):
            out["ofi_std_20d"] = self.extract_ofi_std_20d(df, macro_data)

        # ============ W3a: Wyckoff climax (F13) ============
        if self._dim_enabled("wyckoff_climax_stage"):
            out["wyckoff_climax_stage"] = self.extract_wyckoff_climax_stage(df, macro_data)

        return out

    def _dim_enabled(self, dim_name: str) -> bool:
        """检查某维度的子开关是否开启（默认 True）。"""
        switch_key = DIM_TO_SWITCH.get(dim_name)
        if switch_key is None:
            return True
        return bool(self.config.get(switch_key, True))

    # ============================================================
    # F1: volume_ratio_20d — vol / vol_ma20
    # ============================================================
    def extract_volume_ratio_20d(self, df: pd.DataFrame) -> float:
        """F1: 当前成交量 / 20 日均量。

        - vol=0 或 vol_ma20=0 → 1.0 中性
        - 异常 → 1.0 中性
        """
        try:
            if df is None or "volume" not in df.columns or len(df) < 20:
                return NEUTRAL_DEFAULTS["volume_ratio_20d"]
            vol = float(df["volume"].iloc[-1])
            vol_ma = float(df["volume"].iloc[-20:].mean())
            if vol_ma <= 0 or vol <= 0:
                return NEUTRAL_DEFAULTS["volume_ratio_20d"]
            return float(vol / vol_ma)
        except Exception as e:
            logger.debug("washout F1 volume_ratio FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["volume_ratio_20d"]

    # ============================================================
    # F2: support_holds_count — 近 30d swing low 守住次数
    # ============================================================
    def extract_support_holds_count(
        self, df: pd.DataFrame, lookback: int = 30, swing_window: int = 2
    ) -> float:
        """F2: 近 30d swing low 守住次数。

        - swing low 检测：lows[i] == min(lows[i-w : i+w+1])
        - 守住定义：后续 swing low >= 前一个 swing low × (1 - tol)（1% 容差）
        - 当前价跌破最近 swing low × (1 - tol) → 强制返回 0（破支撑）
        - 异常 → 0.0
        """
        try:
            if df is None or "low" not in df.columns or "close" not in df.columns:
                return NEUTRAL_DEFAULTS["support_holds_count"]
            n = len(df)
            if n < (swing_window * 2 + 1):
                return NEUTRAL_DEFAULTS["support_holds_count"]
            recent_n = min(n, lookback)
            recent = df.iloc[-recent_n:]
            lows = recent["low"].astype(float).values
            # 检测 swing low（严格局部最小：等于窗口最小且严格小于窗口最大，
            # 过滤掉平坦段被误判为 swing low 的情况）
            swing_low_vals: List[float] = []
            for i in range(swing_window, len(lows) - swing_window):
                window = lows[i - swing_window : i + swing_window + 1]
                w_min = window.min()
                w_max = window.max()
                if lows[i] == w_min and lows[i] < w_max:
                    swing_low_vals.append(float(lows[i]))
            if len(swing_low_vals) < 2:
                return NEUTRAL_DEFAULTS["support_holds_count"]
            # 守住次数：相邻 swing low 中后者 >= 前者 × (1 - 0.01)
            tol = 0.01
            holds = 0
            for i in range(1, len(swing_low_vals)):
                if swing_low_vals[i] >= swing_low_vals[i - 1] * (1.0 - tol):
                    holds += 1
            # 当前价跌破最近 swing low → 破支撑，返回 0
            current_price = float(df["close"].iloc[-1])
            last_swing_low = swing_low_vals[-1]
            if current_price < last_swing_low * (1.0 - tol):
                return 0.0
            return float(holds)
        except Exception as e:
            logger.debug("washout F2 support_holds FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["support_holds_count"]

    # ============================================================
    # F3: atr_compress_ratio — ATR_5d / ATR_20d
    # ============================================================
    def extract_atr_compress_ratio(self, df: pd.DataFrame) -> float:
        """F3: ATR_5d / ATR_20d。

        - < 1: 振幅收窄（洗盘特征）
        - > 1: 振幅扩大（真弱势特征）
        - 异常 → 1.0 中性
        """
        try:
            if df is None or not all(c in df.columns for c in ("high", "low", "close")):
                return NEUTRAL_DEFAULTS["atr_compress_ratio"]
            if len(df) < 20:
                return NEUTRAL_DEFAULTS["atr_compress_ratio"]
            tr = self._true_range(df)
            atr_5d = float(tr.iloc[-5:].mean())
            atr_20d = float(tr.iloc[-20:].mean())
            if atr_20d <= 0 or np.isnan(atr_5d) or np.isnan(atr_20d):
                return NEUTRAL_DEFAULTS["atr_compress_ratio"]
            return float(atr_5d / atr_20d)
        except Exception as e:
            logger.debug("washout F3 atr_compress FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["atr_compress_ratio"]

    # ============================================================
    # F4: oi_change_rate_7d — (OI_t - OI_{t-7d}) / OI_{t-7d}
    # ============================================================
    def extract_oi_change_rate_7d(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F4: OI 7 日变化率。

        数据源候选 key：oi_series / open_interest / oi。
        长度 < 8 → 0.0 中性（无足够历史）。
        OI_{t-7d} <= 0 → 0.0 中性。
        异常 → 0.0 中性。
        """
        try:
            if not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["oi_change_rate_7d"]
            oi = (
                macro_data.get("oi_series")
                or macro_data.get("open_interest")
                or macro_data.get("oi")
            )
            if oi is None:
                return NEUTRAL_DEFAULTS["oi_change_rate_7d"]
            # 转换为 list/array
            if isinstance(oi, pd.Series):
                oi_arr = oi.astype(float).values
            elif isinstance(oi, (list, tuple, np.ndarray)):
                oi_arr = np.asarray(oi, dtype=float)
            else:
                return NEUTRAL_DEFAULTS["oi_change_rate_7d"]
            if len(oi_arr) < 8:
                return NEUTRAL_DEFAULTS["oi_change_rate_7d"]
            o_t = float(oi_arr[-1])
            o_prev = float(oi_arr[-8])
            if o_prev <= 0 or np.isnan(o_t) or np.isnan(o_prev):
                return NEUTRAL_DEFAULTS["oi_change_rate_7d"]
            return float((o_t - o_prev) / o_prev)
        except Exception as e:
            logger.debug("washout F4 oi_change_rate FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["oi_change_rate_7d"]

    # ============================================================
    # F5: cycle_position_365d — (price - low) / (high - low)
    # ============================================================
    def extract_cycle_position_365d(self, df: pd.DataFrame) -> float:
        """F5: 365d 区间位置（复用 IndicatorBank 滚动 365d 区间位置逻辑）。

        - < 0.3: 低位（洗盘更可能）
        - > 0.7: 高位（真弱势更可能）
        - 异常 → 0.5 中性
        """
        try:
            if df is None or "close" not in df.columns:
                return NEUTRAL_DEFAULTS["cycle_position_365d"]
            close = df["close"].astype(float)
            if len(close) < 2:
                return NEUTRAL_DEFAULTS["cycle_position_365d"]
            # 取最近 min(len, 365) 日作为 365d 窗口
            n = min(len(close), 365)
            recent = close.iloc[-n:]
            high = float(recent.max())
            low = float(recent.min())
            price = float(close.iloc[-1])
            denom = high - low
            if denom <= 0:
                return NEUTRAL_DEFAULTS["cycle_position_365d"]
            pos = (price - low) / denom
            # 裁剪到 [0, 1]
            pos = max(0.0, min(1.0, float(pos)))
            return pos
        except Exception as e:
            logger.debug("washout F5 cycle_position FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["cycle_position_365d"]

    # ============================================================
    # F6: rebound_ratio_5d — (price - low_5d) / (high_5d - low_5d)
    # ============================================================
    def extract_rebound_ratio_5d(self, df: pd.DataFrame) -> float:
        """F6: 5d 反弹比例。

        - > 0.5: 反弹强（洗盘更可能）
        - < 0.3: 反弹弱（真弱势更可能）
        - 异常 → 0.5 中性
        """
        try:
            if df is None or "close" not in df.columns:
                return NEUTRAL_DEFAULTS["rebound_ratio_5d"]
            if len(df) < 5:
                return NEUTRAL_DEFAULTS["rebound_ratio_5d"]
            recent = df.iloc[-5:]
            # 优先用 high/low，缺则退回 close
            if "high" in recent.columns and "low" in recent.columns:
                high = float(recent["high"].astype(float).max())
                low = float(recent["low"].astype(float).min())
            else:
                closes_arr = recent["close"].astype(float)
                high = float(closes_arr.max())
                low = float(closes_arr.min())
            price = float(recent["close"].iloc[-1])
            denom = high - low
            if denom <= 0:
                return NEUTRAL_DEFAULTS["rebound_ratio_5d"]
            r = (price - low) / denom
            r = max(0.0, min(1.0, float(r)))
            return r
        except Exception as e:
            logger.debug("washout F6 rebound_ratio FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["rebound_ratio_5d"]

    # ============================================================
    # F7: news_negative_score — 负面新闻占比
    # ============================================================
    def extract_news_negative_score(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F7: 负面新闻占比。

        数据源候选 key：news_list / news。
        每条新闻为 dict，sentiment 字段 == 'negative' 计为负面。
        无新闻 → 0.0 中性。
        异常 → 0.0 中性。
        """
        try:
            if not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["news_negative_score"]
            news_list = macro_data.get("news_list") or macro_data.get("news")
            if not news_list or not isinstance(news_list, (list, tuple)):
                return NEUTRAL_DEFAULTS["news_negative_score"]
            total = len(news_list)
            if total == 0:
                return NEUTRAL_DEFAULTS["news_negative_score"]
            neg_count = 0
            for item in news_list:
                if isinstance(item, dict) and str(item.get("sentiment", "")).lower() == "negative":
                    neg_count += 1
            return float(neg_count / total)
        except Exception as e:
            logger.debug("washout F7 news_negative FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["news_negative_score"]

    # ============================================================
    # F8: btc_correlation_30d — corr(coin_ret, btc_ret, 30d)
    # ============================================================
    def extract_btc_correlation_30d(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F8: 币种收益与 BTC 收益的 30 日滚动相关性。

        数据源候选 key：btc_close_series / btc_close / btc_closes。
        - > 0.7: 跟随下跌（真弱势更可能）
        - < 0.5: 独立整理（洗盘更可能）
        - 异常 → 0.5 中性
        """
        try:
            if df is None or "close" not in df.columns or not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            btc_close = (
                macro_data.get("btc_close_series")
                or macro_data.get("btc_close")
                or macro_data.get("btc_closes")
            )
            if btc_close is None:
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            # 转 array
            if isinstance(btc_close, pd.Series):
                btc_arr = btc_close.astype(float).values
            elif isinstance(btc_close, (list, tuple, np.ndarray)):
                btc_arr = np.asarray(btc_close, dtype=float)
            else:
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            coin_close = df["close"].astype(float).values
            # 取最近 30+1 个用于算 30 个收益率
            n = min(len(coin_close), len(btc_arr), 31)
            if n < 6:  # 至少 5 个收益率才有统计意义
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            coin_seg = coin_close[-n:]
            btc_seg = btc_arr[-n:]
            # 算收益率
            coin_ret = np.diff(coin_seg) / coin_seg[:-1]
            btc_ret = np.diff(btc_seg) / btc_seg[:-1]
            # 替换 inf/nan 为 0
            coin_ret = np.nan_to_num(coin_ret, nan=0.0, posinf=0.0, neginf=0.0)
            btc_ret = np.nan_to_num(btc_ret, nan=0.0, posinf=0.0, neginf=0.0)
            if len(coin_ret) < 3 or len(btc_ret) < 3:
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            # std=0 时 corrcoef 返回 NaN → 中性
            if np.std(coin_ret) < 1e-12 or np.std(btc_ret) < 1e-12:
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            corr_mat = np.corrcoef(coin_ret, btc_ret)
            corr = float(corr_mat[0, 1])
            if np.isnan(corr):
                return NEUTRAL_DEFAULTS["btc_correlation_30d"]
            # 裁剪到 [-1, 1]
            corr = max(-1.0, min(1.0, corr))
            return corr
        except Exception as e:
            logger.debug("washout F8 btc_correlation FAIL-OPEN: %s\n%s",
                         e, traceback.format_exc())
            return NEUTRAL_DEFAULTS["btc_correlation_30d"]

    # ============================================================
    # F9: oi_price_quadrant — OI×Price 四象限
    # ============================================================
    def extract_oi_price_quadrant(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F9: OI×Price 四象限编码 (W3a).

        数据源候选 key: oi_series / open_interest_series / oi.
        比较 OI[-1] vs OI[-2] 与 close[-1] vs close[-2].

        象限编码:
          0 = OI↑ + Price↑ (多头增仓, 健康上涨)
          1 = OI↑ + Price↓ (空头建仓, 洗盘特征, 看多反向)
          2 = OI↓ + Price↑ (多头平仓 / 空头回补)
          3 = OI↓ + Price↓ (多头投降, 真弱势, 本地底部反转前兆)

        spec §2.2: OI↑+Price↓=空头建仓（看多反向, 洗盘）
                  OI↓+Price↓=多头投降（本地底部反转前兆, 真弱势）

        - 数据缺失或长度不足 → -1.0 中性 (无信号)
        - 异常 → -1.0 中性
        """
        try:
            if df is None or not isinstance(macro_data, dict) or "close" not in df.columns:
                return NEUTRAL_DEFAULTS["oi_price_quadrant"]
            oi = (
                macro_data.get("oi_series")
                or macro_data.get("open_interest_series")
                or macro_data.get("oi")
            )
            if oi is None:
                return NEUTRAL_DEFAULTS["oi_price_quadrant"]
            # 转 array
            if isinstance(oi, pd.Series):
                oi_arr = oi.astype(float).values
            elif isinstance(oi, (list, tuple, np.ndarray)):
                oi_arr = np.asarray(oi, dtype=float)
            else:
                return NEUTRAL_DEFAULTS["oi_price_quadrant"]
            close = df["close"].astype(float).values
            if len(oi_arr) < 2 or len(close) < 2:
                return NEUTRAL_DEFAULTS["oi_price_quadrant"]
            oi_t, oi_prev = float(oi_arr[-1]), float(oi_arr[-2])
            p_t, p_prev = float(close[-1]), float(close[-2])
            # NaN 检查
            if any(np.isnan(v) for v in (oi_t, oi_prev, p_t, p_prev)):
                return NEUTRAL_DEFAULTS["oi_price_quadrant"]
            oi_up = oi_t > oi_prev
            price_up = p_t > p_prev
            if oi_up and price_up:
                return 0.0  # 多头增仓
            if oi_up and not price_up:
                return 1.0  # 空头建仓 (洗盘)
            if not oi_up and price_up:
                return 2.0  # 多头平仓
            return 3.0  # 多头投降 (真弱势)
        except Exception as e:
            logger.debug("washout F9 oi_price_quadrant FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["oi_price_quadrant"]

    # ============================================================
    # F10: funding_rate_zscore — 30d 滚动 zscore
    # ============================================================
    def extract_funding_rate_zscore(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F10: Funding rate 30d zscore (W3a).

        数据源候选 key:
          - funding_rate_zscore (precomputed, 优先复用)
          - funding_rate_series / funding_rate (历史序列)
          - funding_rate scalar (无 zscore, 返回 0.0 中性)

        spec §2.2: 持续负 = 空头偏向 (洗多头, 洗盘特征)
                  突然转正 = 反转信号 (真弱势反转前兆)

        - std=0 (持续值无偏离) → 0.0 中性 (FAIL-OPEN)
        - 数据缺失 → 0.0 中性
        - 异常 → 0.0 中性
        """
        try:
            if not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["funding_rate_zscore"]
            # 1. 优先用 precomputed zscore
            pre = macro_data.get("funding_rate_zscore")
            if pre is not None:
                z = float(pre)
                # 裁剪到合理范围 [-10, 10]
                return max(-10.0, min(10.0, z))
            # 2. 用 series 算 30d zscore
            fr_series = (
                macro_data.get("funding_rate_series")
                or macro_data.get("funding_rate")
            )
            if fr_series is None:
                return NEUTRAL_DEFAULTS["funding_rate_zscore"]
            if isinstance(fr_series, pd.Series):
                arr = fr_series.astype(float).values
            elif isinstance(fr_series, (list, tuple, np.ndarray)):
                arr = np.asarray(fr_series, dtype=float)
            else:
                # scalar, 无 zscore 可算
                return NEUTRAL_DEFAULTS["funding_rate_zscore"]
            n = len(arr)
            if n < 2:
                return NEUTRAL_DEFAULTS["funding_rate_zscore"]
            # 30d zscore (或全部, 取较小窗口)
            win = min(n, 30)
            seg = arr[-win:]
            mean = float(np.mean(seg))
            std = float(np.std(seg))
            if std <= 1e-12 or np.isnan(std):
                # 持续值无偏离 → 0.0 (中性, 表示无偏离)
                return 0.0
            z = (float(arr[-1]) - mean) / std
            return max(-10.0, min(10.0, float(z)))
        except Exception as e:
            logger.debug("washout F10 funding_rate_zscore FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["funding_rate_zscore"]

    # ============================================================
    # F11: cvd_price_divergence — CVD 与价格相关性
    # ============================================================
    def extract_cvd_price_divergence(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F11: CVD 与价格相关性 (W3a).

        数据源候选 key: cvd_series / cvd.
        实现: corr(cvd_level, price_level, 30d) — Pearson 相关系数.

        spec §2.2: CVD 下行 + 价格守住/微涨 → 负相关 (trapped trader fakeout, 洗盘)
                  CVD 与价格同步下行 → 正相关 (真弱势)

        - std=0 (无波动) → 0.0 中性
        - 数据缺失 → 0.0 中性
        - 异常 → 0.0 中性
        """
        try:
            if df is None or "close" not in df.columns or not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            cvd = macro_data.get("cvd_series") or macro_data.get("cvd")
            if cvd is None:
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            if isinstance(cvd, pd.Series):
                cvd_arr = cvd.astype(float).values
            elif isinstance(cvd, (list, tuple, np.ndarray)):
                cvd_arr = np.asarray(cvd, dtype=float)
            else:
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            close = df["close"].astype(float).values
            n = min(len(cvd_arr), len(close))
            if n < 5:  # 至少 5 个点才有统计意义
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            cvd_seg = cvd_arr[-n:]
            price_seg = close[-n:]
            # std=0 → 无相关性
            if np.std(cvd_seg) < 1e-12 or np.std(price_seg) < 1e-12:
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            corr_mat = np.corrcoef(cvd_seg, price_seg)
            corr = float(corr_mat[0, 1])
            if np.isnan(corr):
                return NEUTRAL_DEFAULTS["cvd_price_divergence"]
            # 裁剪到 [-1, 1]
            return max(-1.0, min(1.0, corr))
        except Exception as e:
            logger.debug("washout F11 cvd_price_divergence FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["cvd_price_divergence"]

    # ============================================================
    # F12: ofi_std_20d — 20d OFI 滚动标准差
    # ============================================================
    def extract_ofi_std_20d(self, df: pd.DataFrame, macro_data: Dict) -> float:
        """F12: 20d OFI 滚动标准差 (W3a).

        数据源候选 key: ofi_series / ofi.
        spec §2.2: 低 OFI 方差 + 高 volume = 可疑洗盘 (庄家对倒)
                  高 OFI 方差 + 持续卖压 = 真弱势

        - 数据缺失 → 0.0 中性 (无 OFI 数据)
        - 异常 → 0.0 中性
        """
        try:
            if not isinstance(macro_data, dict):
                return NEUTRAL_DEFAULTS["ofi_std_20d"]
            ofi = macro_data.get("ofi_series") or macro_data.get("ofi")
            if ofi is None:
                return NEUTRAL_DEFAULTS["ofi_std_20d"]
            if isinstance(ofi, pd.Series):
                arr = ofi.astype(float).values
            elif isinstance(ofi, (list, tuple, np.ndarray)):
                arr = np.asarray(ofi, dtype=float)
            else:
                return NEUTRAL_DEFAULTS["ofi_std_20d"]
            n = len(arr)
            if n < 2:
                return NEUTRAL_DEFAULTS["ofi_std_20d"]
            # 20d 滚动 std (或全部, 取较小窗口)
            win = min(n, 20)
            seg = arr[-win:]
            std = float(np.std(seg))
            # 浮点精度: 全相同时 np.std 可能返回极小值 (1e-18), 视为 0
            if np.isnan(std) or std < 1e-12:
                return 0.0
            return max(0.0, std)
        except Exception as e:
            logger.debug("washout F12 ofi_std_20d FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["ofi_std_20d"]

    # ============================================================
    # F13: wyckoff_climax_stage — Wyckoff Selling Climax 3 阶段
    # ============================================================
    def extract_wyckoff_climax_stage(
        self, df: pd.DataFrame, macro_data: Dict
    ) -> float:
        """F13: Wyckoff Selling Climax 3 阶段判定 (W3a).

        spec §2.3 + §9.3 测试 17-20:
          Stage 1 Panic: 5-10min downtick>75%, 跌1-3%
            → 1h bar 近似: 最近 3 bar close<open 占比 > 0.66, 累计跌幅 ∈ [0.01, 0.03]
          Stage 2 Sustained: 5-10min downtick>80%, vol 2-3x, 跌3-5%
            → 1h bar 近似: vol/vol_ma20 ∈ [2.0, 3.0], 累计跌幅 ∈ [0.03, 0.05]
          Stage 3 Exhaustion: 量能衰减, 速度放缓
            → 1h bar 近似: 最近 3 bar vol 递减 > 0.3, |close-open| 递减 > 0.3
          触发: volume ≥ 2 × 20d 均量 且 价格跌破 20d 低点
          失效: 后续下跌量更大 → 真弱势非 climax (本实现不判定失效, 由 L3 WashoutClassifier 处理)

        输出: 0.0 (未触发) / 1.0 (Stage 1) / 2.0 (Stage 2) / 3.0 (Stage 3)
        - 数据缺失 → 0.0 中性
        - 异常 → 0.0 中性
        """
        try:
            if df is None or not all(
                c in df.columns for c in ("open", "close", "high", "low", "volume")
            ):
                return NEUTRAL_DEFAULTS["wyckoff_climax_stage"]
            # 需要 21 个 bar: 前 20d 低点 (不含当前) + 当前 bar
            if len(df) < 21:
                return NEUTRAL_DEFAULTS["wyckoff_climax_stage"]
            vol = df["volume"].astype(float).values
            close = df["close"].astype(float).values
            open_ = df["open"].astype(float).values
            low = df["low"].astype(float).values

            vol_ma20 = float(np.mean(vol[-21:-1]))  # 前 20d 均量 (不含当前)
            current_vol = float(vol[-1])
            low_20d = float(np.min(low[-21:-1]))  # 前 20d 低点 (不含当前 bar)
            current_close = float(close[-1])

            # 触发条件: 最近 10 bar 内有 vol >= 2x 20d 均量 且 价格跌破前 20d 低点
            # (Wyckoff climax: Stage 1/2 放量触发, Stage 3 量能衰减但之前有放量)
            recent_vol_n = min(10, len(vol))
            recent_vol_max = float(np.max(vol[-recent_vol_n:]))
            vol_trigger = vol_ma20 > 0 and recent_vol_max >= 2.0 * vol_ma20
            price_break = current_close < low_20d
            if not (vol_trigger and price_break):
                return 0.0  # 未触发

            # 累计跌幅 (最近 3 bar)
            n_recent = min(3, len(close))
            recent_close = close[-n_recent:]
            recent_open = open_[-n_recent:]
            if recent_close[0] <= 0:
                return 0.0
            decline_pct = float((recent_close[0] - recent_close[-1]) / recent_close[0])

            # close<open 占比 (最近 3 bar)
            bearish_bars = sum(1 for o, c in zip(recent_open, recent_close) if c < o)
            bearish_pct = bearish_bars / float(n_recent)

            # Stage 1 Panic: 跌幅 ∈ [0.01, 0.03], close<open 占比 > 0.66
            if 0.01 <= decline_pct <= 0.03 and bearish_pct > 0.66:
                return 1.0

            # Stage 2 Sustained: vol/vol_ma20 ∈ [2.0, 3.0], 跌幅 ∈ [0.03, 0.05]
            vol_ratio = recent_vol_max / vol_ma20 if vol_ma20 > 0 else 0.0
            if 2.0 <= vol_ratio <= 3.0 and 0.03 <= decline_pct <= 0.05:
                return 2.0

            # Stage 3 Exhaustion: 量能衰减 > 0.3, 下跌速度放缓 > 0.3
            # 量能衰减: 最近 3 bar vol 递减
            recent_vol = vol[-n_recent:]
            vol_decline = (
                (recent_vol[0] - recent_vol[-1]) / recent_vol[0]
                if recent_vol[0] > 0 else 0.0
            )
            # 下跌速度放缓: |close-open| 递减
            recent_speed = [abs(c - o) for o, c in zip(recent_open, recent_close)]
            speed_decline = (
                (recent_speed[0] - recent_speed[-1]) / recent_speed[0]
                if recent_speed[0] > 0 else 0.0
            )
            if vol_decline > 0.3 and speed_decline > 0.3:
                return 3.0

            # 触发但未明确分类 → 默认 Stage 1 (Panic)
            return 1.0
        except Exception as e:
            logger.debug("washout F13 wyckoff_climax_stage FAIL-OPEN: %s", e)
            return NEUTRAL_DEFAULTS["wyckoff_climax_stage"]

    # ============================================================
    # 辅助：True Range
    # ============================================================
    @staticmethod
    def _true_range(df: pd.DataFrame) -> pd.Series:
        """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        # 第 0 行 prev_close=NaN → tr[0] = high[0]-low[0]（fillna 保险）
        return tr.fillna(high - low)
