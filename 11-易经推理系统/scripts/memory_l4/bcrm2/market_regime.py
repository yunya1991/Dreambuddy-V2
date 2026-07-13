"""
市场模式聚类模块 — 八卦力学→8种市场状态

理论映射 (BCRM八卦 → 市场模式):
  乾(天) → TREND_UP_STRONG: 强趋势上涨，乾健不息
  坤(地) → RANGE_BOUND: 震荡区间，坤厚承载
  震(雷) → BREAKOUT: 突破爆发，震动奋发
  巽(风) → TREND_UP_MILD: 温和上涨，风入渗透
  坎(水) → VOLATILE_DROP: 波动下跌，水险下陷
  离(火) → FOMO_RALLY: 狂热上涨，火明炎上
  艮(山) → CONSOLIDATION: 横盘整理，山静止稳
  兑(泽) → REVERSAL: 转折反转，泽润相变

核心思想:
  不同市态下，价格行为模式不同，策略参数也应不同
  乾市: 顺势做多，止盈宽，止损紧
  坎市: 做空或观望，止盈紧，止损宽
  艮市: 减少交易频率，降低仓位
  ...
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import warnings


# 八卦对应的8种市场模式
GUA_REGIME_MAP = {
    "qian": "TREND_UP_STRONG",     # 乾 - 强趋势上涨
    "kun": "RANGE_BOUND",          # 坤 - 震荡区间
    "zhen": "BREAKOUT",            # 震 - 突破爆发
    "xun": "TREND_UP_MILD",        # 巽 - 温和上涨
    "kan": "VOLATILE_DROP",        # 坎 - 波动下跌
    "li": "FOMO_RALLY",            # 离 - 狂热上涨
    "gen": "CONSOLIDATION",        # 艮 - 横盘整理
    "dui": "REVERSAL",             # 兑 - 转折反转
}

REGIME_GUA_MAP = {v: k for k, v in GUA_REGIME_MAP.items()}

# 8种市态的策略参数预设
@dataclass
class RegimeParams:
    """单种市态的策略参数"""
    regime_name: str = "CONSOLIDATION"
    gua_name: str = "gen"          # 对应的八卦
    gua_trigram: str = "☶"         # 卦符
    gua_meaning: str = "艮为山，止而不动"  # 卦义

    # 交易开关
    allow_long: bool = True        # 是否允许做多
    allow_short: bool = True       # 是否允许做空

    # 置信度阈值 (越高越谨慎)
    long_conf_threshold: float = 0.40
    short_conf_threshold: float = 0.40

    # 止盈止损 (ATR倍数)
    tp_atr: float = 3.0
    sl_atr: float = 2.0

    # 最大持仓bar数
    max_hold_bars: int = 60

    # 仓位系数 (1.0=标准仓位)
    position_factor: float = 1.0


# 8种市态的预设参数 (基于BCRM理论 + 交易经验)
DEFAULT_REGIME_PARAMS = {
    "TREND_UP_STRONG": RegimeParams(
        regime_name="TREND_UP_STRONG",
        gua_name="qian", gua_trigram="☰",
        gua_meaning="乾为天，天行健，君子以自强不息",
        allow_long=True, allow_short=False,  # 强趋势只做多
        long_conf_threshold=0.35, short_conf_threshold=0.60,
        tp_atr=4.0, sl_atr=1.5,  # 宽止盈紧止损
        max_hold_bars=80,
        position_factor=1.2,
    ),
    "RANGE_BOUND": RegimeParams(
        regime_name="RANGE_BOUND",
        gua_name="kun", gua_trigram="☷",
        gua_meaning="坤为地，厚德载物，柔顺利贞",
        allow_long=True, allow_short=True,
        long_conf_threshold=0.45, short_conf_threshold=0.45,
        tp_atr=2.0, sl_atr=2.0,  # 窄止盈，快进快出
        max_hold_bars=30,
        position_factor=0.8,
    ),
    "BREAKOUT": RegimeParams(
        regime_name="BREAKOUT",
        gua_name="zhen", gua_trigram="☳",
        gua_meaning="震为雷，洊雷震，恐惧修省",
        allow_long=True, allow_short=True,
        long_conf_threshold=0.35, short_conf_threshold=0.35,
        tp_atr=3.5, sl_atr=2.5,  # 突破波动大
        max_hold_bars=50,
        position_factor=1.0,
    ),
    "TREND_UP_MILD": RegimeParams(
        regime_name="TREND_UP_MILD",
        gua_name="xun", gua_trigram="☴",
        gua_meaning="巽为风，随风巽，申命行事",
        allow_long=True, allow_short=False,
        long_conf_threshold=0.38, short_conf_threshold=0.55,
        tp_atr=3.0, sl_atr=1.8,
        max_hold_bars=70,
        position_factor=1.0,
    ),
    "VOLATILE_DROP": RegimeParams(
        regime_name="VOLATILE_DROP",
        gua_name="kan", gua_trigram="☵",
        gua_meaning="坎为水，习坎有孚，维心亨",
        allow_long=False, allow_short=True,  # 下跌市只做空
        long_conf_threshold=0.60, short_conf_threshold=0.35,
        tp_atr=2.5, sl_atr=3.0,
        max_hold_bars=40,
        position_factor=0.8,
    ),
    "FOMO_RALLY": RegimeParams(
        regime_name="FOMO_RALLY",
        gua_name="li", gua_trigram="☲",
        gua_meaning="离为火，明两作离，继明照四方",
        allow_long=True, allow_short=False,
        long_conf_threshold=0.30, short_conf_threshold=0.65,
        tp_atr=5.0, sl_atr=1.2,  # FOMO涨势猛
        max_hold_bars=40,
        position_factor=1.5,
    ),
    "CONSOLIDATION": RegimeParams(
        regime_name="CONSOLIDATION",
        gua_name="gen", gua_trigram="☶",
        gua_meaning="艮为山，兼山艮，思不出其位",
        allow_long=True, allow_short=True,
        long_conf_threshold=0.50, short_conf_threshold=0.50,
        tp_atr=2.0, sl_atr=2.0,
        max_hold_bars=25,
        position_factor=0.5,  # 横盘降低仓位
    ),
    "REVERSAL": RegimeParams(
        regime_name="REVERSAL",
        gua_name="dui", gua_trigram="☱",
        gua_meaning="兑为泽，丽泽兑，朋友讲习",
        allow_long=True, allow_short=True,
        long_conf_threshold=0.45, short_conf_threshold=0.45,
        tp_atr=2.5, sl_atr=2.5,
        max_hold_bars=35,
        position_factor=0.7,
    ),
}


class MarketRegimeClassifier:
    """
    市场模式分类器 — 用八卦特征将每根K线归类为8种市态之一

    分类方法:
      1. 计算8个八卦维度的活跃度 (每个维度下特征的z-score绝对值均值)
      2. 取活跃度最高的维度作为主市态
      3. 结合第二高维度做微调 (可选)

    与卦象映射器的区别:
      卦象映射器: 用64卦做可解释性叙事 (上下卦组合)
      市场模式分类器: 用8种主市态做策略参数切换 (主导卦)
    """

    def __init__(
        self,
        feature_names_by_gua: Optional[Dict[str, List[str]]] = None,
        n_regimes: int = 8,
        lookback_bars: int = 20,  # 用过去N根K线的平均活跃度判断市态
    ):
        self.feature_names_by_gua = feature_names_by_gua or {}
        self.n_regimes = n_regimes
        self.lookback_bars = lookback_bars

        self._feature_stats = None  # z-score归一化统计量
        self._gua_dimensions = []   # 八卦维度列表 (只含八卦，不含其他模块)

    def fit(self, X: np.ndarray, feature_names: List[str]):
        """
        用训练集计算特征统计量 (用于z-score归一化和市态阈值)

        Args:
            X: 特征矩阵
            feature_names: 特征名列表
        """
        means = np.mean(X, axis=0)
        stds = np.std(X, axis=0)
        stds = np.where(stds < 1e-8, 1.0, stds)
        self._feature_stats = {"mean": means, "std": stds, "names": feature_names}

        # 提取八卦维度 (排除cross_asset, classic_exp等非八卦模块)
        from .dialectical_ml_engine import GUA_DIMENSION_MAP
        self._gua_dimensions = [
            g for g in self.feature_names_by_gua.keys()
            if g in GUA_DIMENSION_MAP
        ]

        # 计算各卦得分在训练集上的分布 (用于自适应阈值)
        gua_scores = {g: [] for g in self._gua_dimensions}
        for i in range(min(len(X), 2000)):  # 抽样计算，加快速度
            row = X[i]
            norm_row = (row - means) / stds
            for g in self._gua_dimensions:
                feat_names = self.feature_names_by_gua.get(g, [])
                indices = [j for j, fn in enumerate(feature_names) if fn in feat_names]
                if indices:
                    gua_scores[g].append(float(np.mean(norm_row[indices])))

        # 计算各卦得分的百分位数 (用于阈值)
        self._gua_percentiles = {}
        for g in self._gua_dimensions:
            if gua_scores[g]:
                arr = np.array(gua_scores[g])
                self._gua_percentiles[g] = {
                    'p10': np.percentile(arr, 10),
                    'p25': np.percentile(arr, 25),
                    'p50': np.percentile(arr, 50),
                    'p75': np.percentile(arr, 75),
                    'p90': np.percentile(arr, 90),
                    'mean': np.mean(arr),
                    'std': np.std(arr),
                }

        return self

    def _compute_gua_activity(self, X_row: np.ndarray, feature_names: List[str]) -> Dict[str, float]:
        """计算单根K线的8卦活跃度"""
        # z-score归一化
        if self._feature_stats is not None:
            norm_vals = (X_row - self._feature_stats["mean"]) / self._feature_stats["std"]
        else:
            norm_vals = X_row

        activity = {}
        for gua in self._gua_dimensions:
            feat_names = self.feature_names_by_gua.get(gua, [])
            indices = [i for i, fn in enumerate(feature_names) if fn in feat_names]
            if indices:
                vals = np.abs(norm_vals[indices])
                activity[gua] = float(np.mean(vals))
            else:
                activity[gua] = 0.0

        return activity

    def _compute_gua_scores(self, X_row: np.ndarray, feature_names: List[str]) -> Dict[str, float]:
        """计算单根K线的8卦得分 (保留方向，不归一化绝对值)"""
        if self._feature_stats is not None:
            norm_vals = (X_row - self._feature_stats["mean"]) / self._feature_stats["std"]
        else:
            norm_vals = X_row

        scores = {}
        for gua in self._gua_dimensions:
            feat_names = self.feature_names_by_gua.get(gua, [])
            indices = [i for i, fn in enumerate(feature_names) if fn in feat_names]
            if indices:
                scores[gua] = float(np.mean(norm_vals[indices]))
            else:
                scores[gua] = 0.0

        return scores

    def predict(self, X: np.ndarray, feature_names: List[str]) -> np.ndarray:
        """
        预测每根K线的市场模式

        自适应阈值: 用训练集各卦得分的百分位数作为判断基准
        这样不同特征量纲下都能得到合理分布

        8种市态:
          0: TREND_UP_STRONG (乾) - 强趋势上涨
          1: RANGE_BOUND (坤) - 区间震荡
          2: BREAKOUT (震) - 突破爆发
          3: TREND_UP_MILD (巽) - 温和上涨
          4: VOLATILE_DROP (坎) - 波动下跌
          5: FOMO_RALLY (离) - 狂热上涨
          6: CONSOLIDATION (艮) - 横盘整理
          7: REVERSAL (兑) - 转折反转
        """
        n = len(X)
        regimes = np.zeros(n, dtype=int)

        # 获取各卦的百分位阈值
        pct = self._gua_percentiles if hasattr(self, '_gua_percentiles') else {}

        def _th(gua, pct_key, default=0.0):
            if gua in pct and pct_key in pct[gua]:
                return pct[gua][pct_key]
            return default

        # 阈值 (基于z-score百分位)
        qian_p75 = _th('qian', 'p75', 0.5)   # 乾卦75分位 = 强趋势
        qian_p50 = _th('qian', 'p50', 0.2)   # 乾卦50分位 = 趋势
        qian_p25 = _th('qian', 'p25', -0.2)  # 乾卦25分位 = 弱趋势
        zhen_p75 = _th('zhen', 'p75', 0.5)   # 震卦75分位 = 强动量
        zhen_p50 = _th('zhen', 'p50', 0.2)   # 震卦50分位 = 动量
        xun_p75 = _th('xun', 'p75', 0.5)     # 巽卦75分位 = 高波动
        xun_p50 = _th('xun', 'p50', 0.2)     # 巽卦50分位 = 中波动
        dui_p50 = _th('dui', 'p50', 0.3)     # 兑卦50分位 = 多周期信号
        kun_p50 = _th('kun', 'p50', 0.3)     # 坤卦50分位 = 支撑阻力

        for i in range(n):
            scores = self._compute_gua_scores(X[i], feature_names)

            qian_s = scores.get('qian', 0.0)
            zhen_s = scores.get('zhen', 0.0)
            xun_s = scores.get('xun', 0.0)
            dui_s = scores.get('dui', 0.0)
            kun_s = scores.get('kun', 0.0)
            gen_s = scores.get('gen', 0.0)
            li_s = scores.get('li', 0.0)

            # 波动率代理
            vol_proxy = abs(xun_s) + abs(gen_s) * 0.5

            # 趋势强度
            trend_strength = qian_s + zhen_s * 0.3

            regime_code = 6  # 默认CONSOLIDATION(艮)

            # FOMO (离): 极强趋势 + 极强动量 + 高波动 (top 10%)
            if qian_s > _th('qian', 'p90', 1.0) and zhen_s > _th('zhen', 'p90', 1.0) and vol_proxy > xun_p75:
                regime_code = 5  # FOMO_RALLY
            # 暴跌 (坎): 极弱趋势 + 高波动
            elif qian_s < _th('qian', 'p10', -1.0) and vol_proxy > xun_p75:
                regime_code = 4  # VOLATILE_DROP
            # 突破 (震): 动量极强 (top 25%) + 波动率放大
            elif abs(zhen_s) > zhen_p75 and vol_proxy > xun_p50:
                regime_code = 2  # BREAKOUT
            # 强趋势上涨 (乾): 趋势强 + 动量正 + 波动不极端
            elif qian_s > qian_p75 and zhen_s > zhen_p50 and vol_proxy < _th('xun', 'p90', 1.5):
                regime_code = 0  # TREND_UP_STRONG
            # 温和上涨 (巽): 趋势正 + 动量正
            elif qian_s > qian_p50 and zhen_s > 0:
                regime_code = 3  # TREND_UP_MILD
            # 转折 (兑): 趋势中性 + 多周期信号强
            elif abs(qian_s) < qian_p50 and dui_s > dui_p50:
                regime_code = 7  # REVERSAL
            # 区间震荡 (坤): 支撑阻力强 + 波动中等
            elif kun_s > kun_p50 and vol_proxy > xun_p50 * 0.5:
                regime_code = 1  # RANGE_BOUND
            # 横盘 (艮): 低波动 (默认)
            else:
                regime_code = 6  # CONSOLIDATION

            regimes[i] = regime_code

        # 滑动窗口平滑 (取众数)
        if self.lookback_bars > 1 and n > self.lookback_bars:
            smoothed = np.zeros_like(regimes)
            window = self.lookback_bars
            for i in range(n):
                start = max(0, i - window + 1)
                window_vals = regimes[start:i+1]
                counts = np.bincount(window_vals.astype(int), minlength=8)
                smoothed[i] = np.argmax(counts)
            regimes = smoothed

        return regimes

    def predict_regime_names(self, X: np.ndarray, feature_names: List[str]) -> List[str]:
        """返回市态名称列表"""
        regimes = self.predict(X, feature_names)
        # 编码 -> 名称映射 (与predict()中的编码一致)
        code_to_name = {
            0: "TREND_UP_STRONG",   # 乾
            1: "RANGE_BOUND",       # 坤
            2: "BREAKOUT",          # 震
            3: "TREND_UP_MILD",     # 巽
            4: "VOLATILE_DROP",     # 坎
            5: "FOMO_RALLY",        # 离
            6: "CONSOLIDATION",     # 艮
            7: "REVERSAL",          # 兑
        }
        regime_names = [code_to_name.get(int(r), "CONSOLIDATION") for r in regimes]
        return regime_names

    def get_regime_params(self, regime_name: str) -> RegimeParams:
        """获取指定市态的策略参数"""
        return DEFAULT_REGIME_PARAMS.get(regime_name, DEFAULT_REGIME_PARAMS["CONSOLIDATION"])

    def get_all_regime_params(self) -> Dict[str, RegimeParams]:
        """获取所有市态的策略参数"""
        return DEFAULT_REGIME_PARAMS.copy()

    def regime_distribution(self, X: np.ndarray, feature_names: List[str]) -> Dict[str, float]:
        """计算各市场模式占比"""
        regime_names = self.predict_regime_names(X, feature_names)
        counts = {}
        for r in regime_names:
            counts[r] = counts.get(r, 0) + 1
        total = len(regime_names)
        return {k: v / total for k, v in counts.items()}


def classify_regime_by_price_action(df: pd.DataFrame) -> str:
    """
    用价格行为快速判断市态 (不依赖八卦特征，用于冷启动)

    简单规则:
      - 强趋势: 价格>MA20且MA20斜率>0.5%且ATR较低
      - 温和上涨: 价格>MA20且MA20斜率正但<0.5%
      - FOMO: 价格>MA20且近10根涨幅>10%且波动率大
      - 震荡: 价格在MA20附近±2%区间
      - 横盘: ATR很低且价格波动小
      - 下跌: 价格<MA20且MA20斜率负
      - 暴跌: 价格<MA20且近10根跌幅>10%
      - 转折: MA20斜率由负转正或由正转负
    """
    close = df["close"].values
    n = len(close)
    if n < 50:
        return "CONSOLIDATION"

    # 计算MA20和斜率
    ma20 = pd.Series(close).rolling(20, min_periods=10).mean().values
    ma20_slope = np.zeros(n)
    ma20_slope[20:] = (ma20[20:] - ma20[:-20]) / ma20[:-20] * 100

    # ATR (近似)
    high = df["high"].values
    low = df["low"].values
    tr = high - low
    atr14 = pd.Series(tr).rolling(14, min_periods=5).mean().values
    atr_pct = atr14 / close * 100

    last = -1
    price_vs_ma = (close[last] - ma20[last]) / ma20[last] * 100 if ma20[last] > 0 else 0
    slope = ma20_slope[last]
    atr = atr_pct[last] if not np.isnan(atr_pct[last]) else 1.0

    # 近10根涨跌幅
    ret_10 = (close[last] - close[max(0, last-10)]) / close[max(0, last-10)] * 100

    # FOMO判断: 短期涨幅大 + 波动率高 + 趋势向上
    if ret_10 > 10 and price_vs_ma > 2 and slope > 0:
        return "FOMO_RALLY"

    # 强趋势上涨
    if price_vs_ma > 3 and slope > 0.3 and atr < 2.0:
        return "TREND_UP_STRONG"

    # 温和上涨
    if price_vs_ma > 1 and slope > 0:
        return "TREND_UP_MILD"

    # 波动下跌
    if price_vs_ma < -3 and slope < -0.3:
        return "VOLATILE_DROP"

    # 转折 (斜率方向变化)
    if n > 30:
        slope_prev = ma20_slope[last-10] if last-10 >= 0 else 0
        if slope_prev < 0 and slope > 0:
            return "REVERSAL"
        if slope_prev > 0 and slope < 0:
            return "REVERSAL"

    # 突破 (短期波动率放大 + 价格突破区间)
    if atr > 3.0 and abs(ret_10) > 5:
        return "BREAKOUT"

    # 横盘 (低波动 + 价格在MA附近)
    if atr < 1.0 and abs(price_vs_ma) < 1:
        return "CONSOLIDATION"

    # 震荡区间 (中等波动)
    if abs(price_vs_ma) < 2 and atr < 2.5:
        return "RANGE_BOUND"

    # 默认
    return "CONSOLIDATION"
