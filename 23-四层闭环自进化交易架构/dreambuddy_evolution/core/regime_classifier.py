"""RegimeClassifier — BTC-美股相关性 regime 分类器

Phase 4.2: 市场理解补齐 — BTC 强弱 regime

基于滚动相关系数 + 波动率分类：
  - STRONG（强BTC）：与美股脱钩，独立行情，相关性低
  - WEAK（弱BTC）：与美股高相关，风险资产联动
  - NEUTRAL：相关性不显著

接入点：战略层"天"维度因子 + BCRM2.0 方向约束
硬约束：
  HC-AGI-07: 默认关闭，Shadow 模式验证
  HC-FO: 任何异常 → "NEUTRAL" 兜底
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

logger = logging.getLogger(__name__)


# ====================================================================
# 常量（硬约束对齐）
# ====================================================================
STRONG_CORR_THRESHOLD = 0.30      # |corr| < 0.30 → 强BTC（脱钩）
WEAK_CORR_THRESHOLD = 0.60        # |corr| > 0.60 → 弱BTC（联动）
ROLLING_WINDOW = 30               # 滚动窗口 30 日
MIN_SAMPLES = 30                  # 最少样本数


class RegimeClassifier:
    """BTC-美股相关性 regime 分类器

    基于滚动皮尔逊相关系数 + 波动率比率分类：
      - STRONG: BTC 与美股相关性低（脱钩，独立行情）
      - WEAK:   BTC 与美股相关性高（风险资产联动）
      - NEUTRAL: 相关性不显著或数据不足
    """

    def __init__(self,
                 strong_threshold: float = STRONG_CORR_THRESHOLD,
                 weak_threshold: float = WEAK_CORR_THRESHOLD,
                 rolling_window: int = ROLLING_WINDOW,
                 min_samples: int = MIN_SAMPLES):
        self.strong_threshold = strong_threshold
        self.weak_threshold = weak_threshold
        self.rolling_window = rolling_window
        self.min_samples = min_samples

    def classify(self,
                 btc_returns: List[float],
                 spy_returns: List[float]) -> str:
        """分类 BTC-美股 regime

        Args:
            btc_returns: BTC 日收益率序列
            spy_returns: 美股（SPY）日收益率序列

        Returns:
            "STRONG" / "WEAK" / "NEUTRAL"
        """
        try:
            # 确保输入是 list（避免 numpy array 的 truth value 歧义）
            btc_returns = list(btc_returns) if btc_returns is not None else []
            spy_returns = list(spy_returns) if spy_returns is not None else []

            if not btc_returns or not spy_returns:
                return "NEUTRAL"

            n = min(len(btc_returns), len(spy_returns))
            if n < self.min_samples:
                return "NEUTRAL"

            # 取最近 rolling_window 个数据点
            btc = btc_returns[-n:]
            spy = spy_returns[-n:]
            window = min(self.rolling_window, n)
            btc_w = btc[-window:]
            spy_w = spy[-window:]

            # 1. 计算滚动相关系数
            corr = self._pearson_corr(btc_w, spy_w)

            # 2. 计算波动率比率（BTC相对SPY的波动率）
            btc_vol = self._std(btc_w)
            spy_vol = self._std(spy_w)
            vol_ratio = btc_vol / max(spy_vol, 1e-9) if spy_vol > 0 else 1.0

            # 3. regime 判定
            abs_corr = abs(corr)
            if abs_corr < self.strong_threshold:
                # 低相关 → 强BTC（脱钩）
                return "STRONG"
            elif abs_corr > self.weak_threshold:
                # 高相关 → 弱BTC（联动）
                return "WEAK"
            else:
                # 中等相关 → 波动率辅助判断
                # 若 BTC 波动率远高于 SPY 且相关中等，视为弱BTC（风险资产联动）
                if vol_ratio > 2.0 and abs_corr > 0.45:
                    return "WEAK"
                return "NEUTRAL"

        except Exception as e:
            logger.warning("[FO] RegimeClassifier.classify: %s", e)
            return "NEUTRAL"

    def classify_with_detail(self,
                             btc_returns: List[float],
                             spy_returns: List[float]) -> dict:
        """分类并返回详细指标

        Returns:
            {
                "regime": "STRONG"/"WEAK"/"NEUTRAL",
                "correlation": float,
                "vol_ratio": float,
                "n_samples": int,
            }
        """
        try:
            # 确保输入是 list（避免 numpy array 的 truth value 歧义）
            btc_returns = list(btc_returns) if btc_returns is not None else []
            spy_returns = list(spy_returns) if spy_returns is not None else []

            if not btc_returns or not spy_returns:
                return {"regime": "NEUTRAL", "correlation": 0.0,
                        "vol_ratio": 1.0, "n_samples": 0}

            n = min(len(btc_returns), len(spy_returns))
            if n < self.min_samples:
                return {"regime": "NEUTRAL", "correlation": 0.0,
                        "vol_ratio": 1.0, "n_samples": n}

            btc = btc_returns[-n:]
            spy = spy_returns[-n:]
            window = min(self.rolling_window, n)
            btc_w = btc[-window:]
            spy_w = spy[-window:]

            corr = self._pearson_corr(btc_w, spy_w)
            btc_vol = self._std(btc_w)
            spy_vol = self._std(spy_w)
            vol_ratio = btc_vol / max(spy_vol, 1e-9) if spy_vol > 0 else 1.0

            abs_corr = abs(corr)
            if abs_corr < self.strong_threshold:
                regime = "STRONG"
            elif abs_corr > self.weak_threshold:
                regime = "WEAK"
            else:
                if vol_ratio > 2.0 and abs_corr > 0.45:
                    regime = "WEAK"
                else:
                    regime = "NEUTRAL"

            return {
                "regime": regime,
                "correlation": round(corr, 4),
                "vol_ratio": round(vol_ratio, 4),
                "n_samples": n,
            }

        except Exception as e:
            logger.warning("[FO] RegimeClassifier.classify_with_detail: %s", e)
            return {"regime": "NEUTRAL", "correlation": 0.0,
                    "vol_ratio": 1.0, "n_samples": 0}

    # ----------------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------------

    @staticmethod
    def _pearson_corr(x: List[float], y: List[float]) -> float:
        """皮尔逊相关系数"""
        try:
            n = len(x)
            if n < 2:
                return 0.0
            mean_x = sum(x) / n
            mean_y = sum(y) / n
            cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
            std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
            std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)
            if std_x < 1e-12 or std_y < 1e-12:
                return 0.0
            return float(cov / (std_x * std_y))
        except Exception:
            return 0.0

    @staticmethod
    def _std(data: List[float]) -> float:
        """标准差"""
        try:
            if len(data) < 2:
                return 0.0
            mean = sum(data) / len(data)
            var = sum((x - mean) ** 2 for x in data) / len(data)
            return float(math.sqrt(var))
        except Exception:
            return 0.0
