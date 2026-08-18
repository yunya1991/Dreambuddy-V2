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


# ============================================================================
# P2-01: 爆仓 + 期权 IV 形态特征校正器（PURE 函数，零状态依赖）
# ============================================================================

# 8 态枚举全集（来自 GUA_REGIME_MAP.values()），下游用此做合法性校验
VALID_8STATE_REGIMES: set = set(GUA_REGIME_MAP.values())

# TREND_UP 家族（R4 覆盖范围：skew 出现尾部保护时，反转趋势多）
_TREND_UP_FAMILY = {"TREND_UP_STRONG", "TREND_UP_MILD", "BREAKOUT"}

# IV 档位 ≥ HIGH 的集合（R2/R5 强信号门槛）
_IV_LEVEL_HIGH_OR_ABOVE = {"HIGH", "EXTREME"}

# Skew 情绪枚举（与 FreeMarketFeed._interpret_option_skew 输出 100% 一致）
_SKEW_FEAR_TAIL = "FEAR_TAIL_PROTECTION"
_SKEW_FOMO_BINGE = "FOMO_RALLY_CALL_BINGE"


def apply_macro_regime_correction(
    base_regime: str,
    macro_feats: dict,
    strength: float = 0.6,
) -> str:
    """用爆仓/期权二阶数据校正基础形态预测结果（8 态）

    优先级（高→低）命中即返回：
      R1. panic ≥ 0.70 (极高恐慌) → VOLATILE_DROP（覆盖一切 base，风险最高优先级）
      R2. options_regime_hint=VOLATILE_DROP + iv_level ∈ {HIGH,EXTREME} → VOLATILE_DROP
      R3. liq_regime_hint=FOMO_RALLY + panic ≥ 0.4 → FOMO_RALLY
      R4. skew_sentiment=FEAR_TAIL + base ∈ TREND_UP* → REVERSAL
      R5. skew_sentiment=FOMO_RALLY_CALL_BINGE + iv_level ≥ NORMAL → FOMO_RALLY
      R6. 默认 → base_regime（不修正）

    strength 灵敏度：
      0.0 → 永不覆盖（即便条件命中，保护原推断）
      (0, 0.5] → 仅强规则 R1/R2 生效（最保守）
      (0.5, 0.8] → 默认强度，弱规则 R3/R4/R5 门槛抬高（panic +0.1，skew 需 iv 确认）
      (0.8, 1.0] → 命中即覆盖（最灵敏）

    全部 macro_feats 字段缺失/None → 不修正，字节等价未调用本函数。
    """
    # ---- 快速通道：完全不覆盖 ----
    if strength <= 0.0:
        return base_regime
    if not macro_feats:
        return base_regime

    def _num(key: str):
        """安全取数值字段，None/非法 → None"""
        v = macro_feats.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _str(key: str):
        """安全取字符串字段，None/空 → None"""
        v = macro_feats.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    panic = _num("liq_panic_score_0_to_1") or 0.0
    liq_hint = _str("liq_regime_hint")
    opt_hint = _str("options_regime_hint")
    iv_level = _str("btc_option_iv_level")
    skew_sent = _str("btc_option_skew_sentiment")

    # 弱规则（R3/R4/R5）的额外门槛：当 strength ≤ 0.8 时抬高
    s_is_sensitive = strength > 0.8
    # R3 门槛：敏感=0.40 / 默认=0.50 / 保守=0.60
    if s_is_sensitive:
        r3_panic_threshold = 0.40
    elif strength > 0.5:
        r3_panic_threshold = 0.50
    else:
        r3_panic_threshold = 0.60

    # ==========================================================
    # R1: 极高恐慌 → VOLATILE_DROP（任何 strength>0 都应覆盖，极高风险）
    # ==========================================================
    if panic >= 0.70:
        return "VOLATILE_DROP"

    # ==========================================================
    # R2: 期权链 VOLATILE_DROP + 高 IV 确认
    # ==========================================================
    if opt_hint == "VOLATILE_DROP" and iv_level in _IV_LEVEL_HIGH_OR_ABOVE:
        return "VOLATILE_DROP"

    # ==========================================================
    # R3: 爆仓 regime_hint=FOMO_RALLY + 恐慌确认
    # ==========================================================
    if liq_hint == "FOMO_RALLY" and panic >= r3_panic_threshold:
        return "FOMO_RALLY"

    # ==========================================================
    # R4: Skew=FEAR_TAIL_PROTECTION + base ∈ TREND_UP 家族 → REVERSAL（看反转）
    #     注：FEAR_TAIL 本身就是高置信信号，无需 IV 额外确认
    # ==========================================================
    if skew_sent == _SKEW_FEAR_TAIL and base_regime in _TREND_UP_FAMILY:
        return "REVERSAL"

    # ==========================================================
    # R5: Skew=CALL_BINGE + IV≥NORMAL 确认 → FOMO_RALLY
    # ==========================================================
    if skew_sent == _SKEW_FOMO_BINGE:
        if iv_level in ("NORMAL",) or iv_level in _IV_LEVEL_HIGH_OR_ABOVE:
            return "FOMO_RALLY"

    # ==========================================================
    # R6: 不修正（保持原形态）
    # ==========================================================
    return base_regime


# =====================================================================
# P3 历史 OHLCV → 宏观特征 proxy 合成器（回测专用）
#
# 输出字段契约 与 FreeMarketFeed fallback proxy 100% 一致，
# 保证 apply_macro_regime_correction 运行期/回测期口径零漂移。
#
# 4 维度 proxy（与 FreeMarketFeed._estimate_liquidation_panic_proxy 对齐）：
#   D1 OI爆仓代理   = 成交量分位 × 实体幅度（级联爆仓/轧空小时计数）
#   D2 Taker失衡代理 = EMA20/EMA60 斜率 z-score + 实体方向 → PC Skew
#   D3 波动簇/费率代理 = rolling_24bar realized vol rank → ATM IV proxy
#   D4 TopTrader LS 代理 = close 相对 MA20/MA60 偏离度 → LS ratio proxy
# =====================================================================
def synthesize_macro_proxy_from_ohlcv(
    df: pd.DataFrame,
    bar_idx: int = -1,
    lookback: int = 60,
) -> Dict[str, object]:
    """基于历史 OHLCV 合成 macro_feats proxy（供 WalkForwardBacktester 回测注入）。

    Args:
        df: 含 OHLCV 列的 DataFrame（open/high/low/close/volume，按时间升序）
        bar_idx: 要合成的 bar 索引，-1 表示最后一根
        lookback: 合成时回看窗口（默认 60bar ≈ 1h × 60 根）

    Returns:
        dict with 8 keys（contract same as FMF fallback proxy）
    """
    # --- 1. 基础切片与最小长度校验 ---
    n_total = len(df)
    if n_total == 0:
        return {
            "liq_panic_score_0_to_1": 0.0, "liq_regime_hint": None,
            "btc_atm_iv_pct": 0.0, "btc_option_iv_level": "LOW",
            "btc_option_pc_skew_25d_pct": 0.0, "btc_option_skew_sentiment": None,
            "btc_option_skew_interpret": None, "btc_options_regime_hint": None,
            "top_ls_ratio_pct": None, "_provenance": "ohlcv_proxy_v1",
        }
    if bar_idx < 0:
        bar_idx = n_total + bar_idx
    start = max(0, bar_idx - lookback + 1)
    sub = df.iloc[start : bar_idx + 1].copy()
    n = len(sub)

    opens = sub["open"].to_numpy(dtype=float)
    highs = sub["high"].to_numpy(dtype=float)
    lows  = sub["low"].to_numpy(dtype=float)
    closes = sub["close"].to_numpy(dtype=float)
    vols  = sub["volume"].to_numpy(dtype=float)

    EMPTY = {
        "liq_panic_score_0_to_1": 0.0, "liq_regime_hint": None,
        "btc_atm_iv_pct": 0.0, "btc_option_iv_level": "LOW",
        "btc_option_pc_skew_25d_pct": 0.0, "btc_option_skew_sentiment": None,
        "btc_option_skew_interpret": None, "btc_options_regime_hint": None,
        "top_ls_ratio_pct": None, "_provenance": "ohlcv_proxy_v1",
    }

    MIN_RELIABLE = 20
    if n < MIN_RELIABLE:
        return EMPTY

    # --- 2. 公共指标 ---
    rets = np.diff(closes) / np.maximum(np.abs(closes[:-1]), 1e-9)
    rets = np.concatenate([[0.0], rets])  # 对齐 n
    bodies = closes - opens
    abs_body_pct = np.abs(bodies) / np.maximum(np.abs(opens), 1e-9)  # n
    # ATR 近似 (简化版，避免与真实 ATR 精确对齐)
    tr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))),
    )
    tr[0] = highs[0] - lows[0] if tr[0] == 0 else tr[0]
    atr14 = pd.Series(tr).rolling(14, min_periods=5).mean().to_numpy()
    atr_pct = atr14 / np.maximum(closes, 1e-9)

    # ===================================================================
    # D1 — OI 爆仓代理（成交量突变 + 实体幅度 → panic 0..1）
    # ===================================================================
    vol_series = pd.Series(vols)
    vol_rank = vol_series.rank(pct=True).to_numpy()  # 0..1
    last_vol_rank = float(vol_rank[-1])

    # 最近 24 bar：同时满足 volume top 10% + 实体≥1×ATR 的 bar 数 → "级联爆仓小时"
    cascade_window = min(24, n)
    tail_mask_vol = vol_rank[-cascade_window:] >= 0.90
    big_body = abs_body_pct[-cascade_window:] >= np.clip(atr_pct[-cascade_window:], 1e-4, None)
    cascade_count = int(np.sum(tail_mask_vol & big_body))

    # panic = 0.6 * last_vol_rank * tanh(abs_body_pct * 25) + 0.4 * (cascade_count / 6)
    tail_body = abs_body_pct[-1]
    panic_p1 = 0.60 * last_vol_rank * np.tanh(tail_body * 25.0)
    panic_p2 = 0.40 * min(cascade_count / 6.0, 1.0)
    liq_panic = float(np.clip(panic_p1 + panic_p2, 0.0, 1.0))

    # D1 hint：根据 panic + 连续实体方向组合推断
    liq_regime_hint: Optional[str] = None
    tail_direction = np.sign(bodies[-min(6, n):])  # +1 阳, -1 阴
    if liq_panic >= 0.70 and cascade_count >= 3:
        if np.mean(tail_direction) <= -0.4:  # 连阴
            liq_regime_hint = "VOLATILE_DROP"
        elif np.mean(tail_direction) >= 0.4:  # 连阳
            liq_regime_hint = "FOMO_RALLY"
    elif liq_panic >= 0.40 and cascade_count >= 1:
        if np.mean(tail_direction) >= 0.5:
            liq_regime_hint = "FOMO_RALLY"
        elif np.mean(tail_direction) <= -0.5:
            liq_regime_hint = "VOLATILE_DROP"

    # ===================================================================
    # D3 — ATM IV proxy（rolling realized volatility → rank 分档 0..1）
    # ===================================================================
    rv24 = pd.Series(rets).rolling(24, min_periods=8).std().to_numpy()
    rv_rank_nan = pd.Series(rv24).rank(pct=True).to_numpy()
    rv_rank = float(np.nan_to_num(rv_rank_nan[-1], nan=0.33))
    atm_iv_pct = float(np.clip(rv_rank, 0.0, 1.0))

    # ===================================================================
    # D2 — PC Skew 25Δ proxy（EMA20/EMA60 斜率 z-score + 最近 3bar 实体方向）
    # ===================================================================
    close_s = pd.Series(closes)
    ema20 = close_s.ewm(span=20, min_periods=8).mean().to_numpy()
    ema60 = close_s.ewm(span=60, min_periods=20).mean().to_numpy() if n >= 30 else (
        close_s.ewm(span=min(60, max(20, n // 2)), min_periods=10).mean().to_numpy()
    )
    spread_ema = (ema20 - ema60) / np.maximum(ema60, 1e-9)
    # zscore of spread_ema（within lookback window）
    spread_std = float(np.nanstd(spread_ema))
    spread_mean = float(np.nanmean(spread_ema))
    if spread_std <= 1e-9:
        slope_z = 0.0
    else:
        slope_z = float(np.clip((spread_ema[-1] - spread_mean) / spread_std, -2.5, 2.5)) / 2.5  # 归一到 -1..1

    # 最近 3bar 平均实体方向（红=跌=PUT 保护需求=正 skew）
    tail3_bodies = bodies[-min(3, n):]
    body_dir_avg = float(np.mean(
        np.clip(tail3_bodies / np.maximum(np.abs(opens[-min(3, n):]), 1e-9) /
                np.clip(atr_pct[-min(3, n):], 1e-4, None), -1.0, 1.0)
    )) if min(3, n) >= 2 else 0.0

    # skew_25d: +1 = 极恐慌 PUT 拥挤, -1 = 极贪婪 CALL 拥挤
    pc_skew_25d = float(np.clip(0.55 * (-slope_z) + 0.45 * (-body_dir_avg), -1.0, 1.0))

    # Interpretation（与 FMF._interpret_option_skew 口径一致）
    iv_tier = (
        "LOW" if atm_iv_pct < 0.33
        else "NORMAL" if atm_iv_pct < 0.66
        else "HIGH" if atm_iv_pct < 0.85
        else "EXTREME"
    )
    skew_sentiment = None
    skew_interpret = None
    options_regime_hint: Optional[str] = None
    if pc_skew_25d >= 0.30:
        skew_sentiment = _SKEW_FEAR_TAIL  # PUT 端贵 → 尾部保护
        skew_interpret = _SKEW_FEAR_TAIL
        # FEAR_TAIL + 强/中 IV → REVERSAL 警示（上涨趋势中主力对冲下行）
        if iv_tier in ("NORMAL", "HIGH", "EXTREME"):
            options_regime_hint = "REVERSAL"
        # FEAR_TAIL + EXTREME_IV + 连跌 = VOLATILE_DROP 期权确认
        if iv_tier == "EXTREME" and np.mean(tail_direction) <= -0.3:
            options_regime_hint = "VOLATILE_DROP"
    elif pc_skew_25d <= -0.30:
        skew_sentiment = _SKEW_FOMO_BINGE  # CALL 端贵 → 散户抢购看涨
        skew_interpret = _SKEW_FOMO_BINGE
        # CALL 拥挤 + IV≥NORMAL → FOMO_RALLY 期权链确认
        if iv_tier in ("NORMAL", "HIGH", "EXTREME"):
            options_regime_hint = "FOMO_RALLY"

    # ===================================================================
    # D4 — TopTrader Long/Short ratio proxy（价格相对均线偏离 → 多空占比 proxy）
    # ===================================================================
    ma20 = close_s.rolling(20, min_periods=10).mean().to_numpy()
    ma60 = close_s.rolling(60, min_periods=20).mean().to_numpy() if n >= 30 else (
        close_s.rolling(min(60, max(15, n // 2)), min_periods=10).mean().to_numpy()
    )
    dev20 = (closes[-1] - ma20[-1]) / max(ma20[-1], 1e-9)
    dev60 = (closes[-1] - ma60[-1]) / max(ma60[-1], 1e-9) if not np.isnan(ma60[-1]) else dev20
    # sigmoid(-2..+2) → [0.1..0.9]：+正偏差=多头强→ls ratio 大
    ls_proxy = float(np.clip(0.5 + 0.35 * (0.6 * dev20 / max(atr_pct[-1], 1e-4) / 4.0
                                           + 0.4 * dev60 / max(float(np.nanmean(atr_pct) or atr_pct[-1]), 1e-4) / 4.0),
                             0.0, 1.0))
    top_ls_ratio_pct: Optional[float] = ls_proxy if n >= MIN_RELIABLE else None

    return {
        "liq_panic_score_0_to_1": liq_panic,
        "liq_regime_hint": liq_regime_hint,
        "btc_atm_iv_pct": atm_iv_pct,
        "btc_option_iv_level": iv_tier,  # 与 FMF collect_global 顶层字段同命名
        "btc_option_pc_skew_25d_pct": pc_skew_25d,
        "btc_option_skew_sentiment": skew_sentiment,  # apply_macro_regime_correction 消费字段
        "btc_option_skew_interpret": skew_interpret,
        "btc_options_regime_hint": options_regime_hint,
        "top_ls_ratio_pct": top_ls_ratio_pct,
        "_provenance": "ohlcv_proxy_v1",
    }
