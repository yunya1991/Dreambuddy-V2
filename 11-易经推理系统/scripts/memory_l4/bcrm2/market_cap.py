"""
市值维度模块 — 币种分类与特征配置

理论映射 (BCRM矛盾特殊性原理):
  不同市值的币种有不同的运动规律 (矛盾特殊性)
  大市值: 趋势性强, 周期明显, 波动小
  中市值: 趋势+题材混合, 波动中等
  小市值: 题材驱动, 波动大, 周期不明显

市值等级定义:
  LARGE (大市值): BTC, ETH — 趋势明确, 周期特征有效
  MID (中市值): SOL, BNB, XRP — 趋势+题材混合
  SMALL (小市值): UNI, LINK, DOT等 — 题材驱动, 波动大
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field


# 市值等级
MARKET_CAP_LARGE = "large"
MARKET_CAP_MID = "mid"
MARKET_CAP_SMALL = "small"


@dataclass
class FeatureConfig:
    """按市值等级的特征配置预设"""
    # 八卦特征 (基础层, 全等级开启)
    enable_bagua: bool = True
    # 经典经验特征 (牛熊线+Elder-ray+三屏)
    enable_classic: bool = True
    # 斐波那契特征
    enable_fibonacci: bool = True
    # 枢纽点特征
    enable_pivot: bool = True
    # RSI情绪特征 (建议小市值开启, 大市值禁用)
    enable_rsi: bool = False
    # 周/日/时三屏+量变积累
    enable_wdh: bool = True
    # WDH仅周线层 (大市值可能只需要周线量变)
    wdh_weekly_only: bool = False
    # 库存周期特征 (大市值效果好, 小市值效果差)
    enable_cycle: bool = True
    cycle_halving: bool = True
    cycle_ath: bool = True
    cycle_inventory: bool = True
    cycle_long_term: bool = True
    # 跨资产特征 (非BTC币种开启)
    enable_cross_asset: bool = True
    # 市值特征 (将市值等级作为特征输入)
    enable_mcap_feature: bool = True
    # L2 Meta-Labeling (小市值有效, 大/中市值禁用)
    enable_meta_labeling: bool = False
    # 美林时钟周期特征 (跨资产资金流转, 大市值效果好)
    enable_merrill: bool = True
    merrill_inflation: bool = True
    merrill_growth: bool = True
    merrill_capital_flow: bool = True
    merrill_phase: bool = True
    merrill_cross: bool = True


# 预设配置
PRESET_CONFIGS = {
    MARKET_CAP_LARGE: FeatureConfig(
        enable_bagua=True,
        enable_classic=True,
        enable_fibonacci=True,
        enable_pivot=True,
        enable_rsi=False,
        enable_wdh=True,
        wdh_weekly_only=False,
        enable_cycle=True,
        cycle_halving=True,
        cycle_ath=True,
        cycle_inventory=True,
        cycle_long_term=True,
        enable_cross_asset=True,
        enable_mcap_feature=True,
        enable_meta_labeling=False,  # 回退基线: Meta-Labeling效果不佳
        enable_merrill=False,
        merrill_inflation=False,
        merrill_growth=False,
        merrill_capital_flow=False,
        merrill_phase=False,
        merrill_cross=False,
    ),
    MARKET_CAP_MID: FeatureConfig(
        enable_bagua=True,
        enable_classic=True,
        enable_fibonacci=True,
        enable_pivot=True,
        enable_rsi=False,
        enable_wdh=True,
        wdh_weekly_only=False,
        enable_cycle=True,
        cycle_halving=True,
        cycle_ath=True,
        cycle_inventory=True,
        cycle_long_term=True,
        enable_cross_asset=True,
        enable_mcap_feature=True,
        enable_meta_labeling=False,  # 回退基线: Meta-Labeling效果不佳
        enable_merrill=False,
        merrill_inflation=False,
        merrill_growth=False,
        merrill_capital_flow=False,
        merrill_phase=False,
        merrill_cross=False,
    ),
    MARKET_CAP_SMALL: FeatureConfig(
        enable_bagua=True,
        enable_classic=True,
        enable_fibonacci=True,
        enable_pivot=True,
        enable_rsi=False,
        enable_wdh=True,
        wdh_weekly_only=False,
        enable_cycle=False,
        cycle_halving=False,
        cycle_ath=False,
        cycle_inventory=False,
        cycle_long_term=False,
        enable_cross_asset=True,
        enable_mcap_feature=True,
        enable_meta_labeling=False,  # 暂时禁用，待优化
        enable_merrill=False,
        merrill_inflation=False,
        merrill_growth=False,
        merrill_capital_flow=False,
        merrill_phase=False,
        merrill_cross=False,
    ),
}


# 已知市值的币种映射 (作为先验, 没有的用分类器估算)
KNOWN_MCAP = {
    "BTC": MARKET_CAP_LARGE,
    "ETH": MARKET_CAP_LARGE,
    "BNB": MARKET_CAP_MID,
    "SOL": MARKET_CAP_MID,
    "XRP": MARKET_CAP_MID,
    "ADA": MARKET_CAP_MID,
    "DOGE": MARKET_CAP_MID,
    "AVAX": MARKET_CAP_MID,
    "DOT": MARKET_CAP_MID,
    "LINK": MARKET_CAP_MID,
    "MATIC": MARKET_CAP_SMALL,
    "UNI": MARKET_CAP_SMALL,
    "LTC": MARKET_CAP_MID,
    "ATOM": MARKET_CAP_SMALL,
    "ETC": MARKET_CAP_SMALL,
    "FIL": MARKET_CAP_SMALL,
    "APT": MARKET_CAP_MID,
    "ARB": MARKET_CAP_SMALL,
    "OP": MARKET_CAP_SMALL,
    "PEPE": MARKET_CAP_SMALL,
    "COMP": MARKET_CAP_SMALL,
    "TIA": MARKET_CAP_SMALL,
    "SUI": MARKET_CAP_SMALL,
    "SEI": MARKET_CAP_SMALL,
    "INJ": MARKET_CAP_SMALL,
    "STRK": MARKET_CAP_SMALL,
    "JUP": MARKET_CAP_SMALL,
    "WIF": MARKET_CAP_SMALL,
    "JTO": MARKET_CAP_SMALL,
    "BLUR": MARKET_CAP_SMALL,
}


class MarketCapClassifier:
    """
    市值分类器 — 基于K线数据估算币种市值等级

    由于没有实时市值API, 用可从K线推导的代理指标:
      1. 价格水平 (高价格通常对应高市值, 如BTC)
      2. 年化波动率 (低波动率=大市值, 高波动率=小市值)
      3. 日均成交量 (成交量越大市值通常越大)

    分类方法: 已知币种直接查表, 未知币种用代理指标估算
    """

    def __init__(self):
        self.known_mcap = KNOWN_MCAP.copy()

    def classify(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
    ) -> str:
        """
        估算币种的市值等级

        Args:
            symbol: 币种代码 (如 BTC, ETH)
            df: OHLCV数据 (用于未知币种估算)

        Returns:
            市值等级: large/mid/small
        """
        symbol = symbol.upper().replace("-USDT", "").replace("USDT", "")

        # 已知币种直接返回
        if symbol in self.known_mcap:
            return self.known_mcap[symbol]

        # 未知币种用K线数据估算
        if df is None or len(df) < 100:
            return MARKET_CAP_MID  # 默认中市值

        return self._estimate_from_klines(df)

    def _estimate_from_klines(self, df: pd.DataFrame) -> str:
        """从K线数据估算市值等级"""
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values if "volume" in df.columns else None

        # 1. 价格水平 (对数价格)
        avg_price = np.median(close)
        log_price = np.log(max(avg_price, 1e-8))

        # 2. 年化波动率
        returns = np.diff(np.log(close))
        daily_vol = np.std(returns) * np.sqrt(24)  # 1H数据, 一天24根
        annual_vol = daily_vol * np.sqrt(365)

        # 3. 成交量 (如果有)
        vol_score = 0.5
        if volume is not None and len(volume) > 0:
            avg_vol = np.median(volume[-100:])
            # 成交量越大, 分数越高 (0-1)
            vol_score = min(1.0, np.log10(max(avg_vol, 1)) / 10)

        # 综合评分 (0=小市值, 1=大市值)
        # 价格权重: 0.4, 波动率(负相关): 0.4, 成交量: 0.2
        price_score = min(1.0, max(0.0, (log_price + 2) / 10))
        volatilty_score = min(1.0, max(0.0, 1 - annual_vol / 2.0))

        total_score = price_score * 0.4 + volatilty_score * 0.4 + vol_score * 0.2

        if total_score > 0.6:
            return MARKET_CAP_LARGE
        elif total_score > 0.3:
            return MARKET_CAP_MID
        else:
            return MARKET_CAP_SMALL

    def get_config(self, symbol: str, df: Optional[pd.DataFrame] = None) -> FeatureConfig:
        """获取币种对应的特征配置"""
        mcap = self.classify(symbol, df)
        return PRESET_CONFIGS[mcap]

    def get_mcap_features(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        生成市值特征 (作为输入特征的一部分)

        特征:
          - mcap_level: 市值等级编码 (0=小, 1=中, 2=大)
          - mcap_large: 是否大市值 (0/1)
          - mcap_mid: 是否中市值 (0/1)
          - mcap_small: 是否小市值 (0/1)
          - mcap_score: 市值估算分数 (0-1)
        """
        result = pd.DataFrame(index=df.index)
        symbol = symbol.upper().replace("-USDT", "").replace("USDT", "")

        mcap = self.classify(symbol, df)

        # 等级编码
        level_map = {MARKET_CAP_SMALL: 0, MARKET_CAP_MID: 1, MARKET_CAP_LARGE: 2}
        result["mcap_level"] = level_map.get(mcap, 1)

        # one-hot编码
        result["mcap_large"] = 1 if mcap == MARKET_CAP_LARGE else 0
        result["mcap_mid"] = 1 if mcap == MARKET_CAP_MID else 0
        result["mcap_small"] = 1 if mcap == MARKET_CAP_SMALL else 0

        # 估算分数 (已知币种直接给满分/半分)
        score_map = {MARKET_CAP_LARGE: 0.9, MARKET_CAP_MID: 0.5, MARKET_CAP_SMALL: 0.1}
        result["mcap_score"] = score_map.get(mcap, 0.5)

        # 波动率归一化因子 (不同市值波动率不同, 用作交互特征)
        close = df["close"].values
        returns = np.diff(np.log(close))
        if len(returns) > 0:
            daily_vol = np.std(returns[-240:]) * np.sqrt(24) if len(returns) >= 240 else np.std(returns) * np.sqrt(24)
        else:
            daily_vol = 0.05
        result["mcap_vol_ratio"] = daily_vol

        return result


def apply_mcap_feature_config(
    backtester,
    symbol: str,
    df: pd.DataFrame,
    classifier: Optional[MarketCapClassifier] = None,
) -> Dict:
    """
    应用市值维度的特征配置到回测器参数

    返回可直接传给backtester.run()的参数字典
    """
    if classifier is None:
        classifier = MarketCapClassifier()

    config = classifier.get_config(symbol, df)

    params = {
        "enable_pivot": config.enable_pivot,
        "enable_rsi": config.enable_rsi,
        "enable_wdh": config.enable_wdh,
        "wdh_weekly_only": config.wdh_weekly_only,
        "enable_cycle": config.enable_cycle,
        "cycle_halving": config.cycle_halving,
        "cycle_ath": config.cycle_ath,
        "cycle_inventory": config.cycle_inventory,
        "cycle_long_term": config.cycle_long_term,
    }

    return params
