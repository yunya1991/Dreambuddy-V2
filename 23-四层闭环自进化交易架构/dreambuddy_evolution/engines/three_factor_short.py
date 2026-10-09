"""Phase 4.3: 三因子共振做空检测器
SPEC-AGI升级蓝图.md §4.4.3

三因子共振条件（全满足才豁免 SHORT_BAN）:
  1. pattern_factor <= -0.5  (头肩顶看跌，PatternDetector 输出)
  2. btc_regime == "WEAK"     (BTC 与美股高相关，RegimeClassifier 输出)
  3. etf_flow_norm < -0.1     (ETF 净流出，stagnation 后强信号)

安全侧 FAIL-OPEN: 任一因子缺失/异常 → False（维持 SHORT_BAN 铁律）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ThreeFactorShortDetector:
    """三因子共振做空检测器

    受 enable_three_factor_short 开关控制（默认 True）。
    开关关闭时直接返回 False，不计算。
    """

    PATTERN_THRESHOLD = -0.5  # 头肩顶 pattern_factor ≤ -0.5
    ETF_OUTFLOW_THRESHOLD = -0.1  # ETF 净流出（归一化 < -0.1）

    def __init__(self) -> None:
        pass

    def detect(
        self,
        pattern_factor: float | None,
        btc_regime: str | None,
        etf_flow_norm: float | None,
    ) -> bool:
        """三因子共振检测。

        Args:
            pattern_factor: PatternDetector 的 pattern_factor（负值=看跌）
            btc_regime: RegimeClassifier 的 regime（STRONG/WEAK/NEUTRAL）
            etf_flow_norm: ETF 净流出的归一化值（负值=流出）

        Returns:
            True = 三因子全满足，允许做空豁免
            False = 不满足或异常，维持 SHORT_BAN 铁律
        """
        try:
            # 开关检查
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_three_factor_short"):
                return False
        except Exception:
            return False  # FAIL-OPEN: 开关检查异常 → False

        try:
            # 因子 1: 头肩顶看跌
            pf = float(pattern_factor) if pattern_factor is not None else 0.0
            if pf > self.PATTERN_THRESHOLD:
                return False

            # 因子 2: BTC regime = WEAK
            regime = str(btc_regime or "").upper()
            if regime != "WEAK":
                return False

            # 因子 3: ETF 净流出
            etf = float(etf_flow_norm) if etf_flow_norm is not None else 0.0
            if etf > self.ETF_OUTFLOW_THRESHOLD:
                return False

            # 三因子全满足
            return True

        except (TypeError, ValueError) as e:
            logger.debug("[FO] ThreeFactorShortDetector detect fail: %s", e)
            return False  # 安全侧 FAIL-OPEN: 异常 → False（不豁免）
        except Exception as e:
            logger.debug("[FO] ThreeFactorShortDetector detect crash: %s", e)
            return False

    # ------------------------------------------------------------------
    # 路径D: 因子池扩展（资金费率 / OI-Price背离 / 清算热力图）
    # ------------------------------------------------------------------

    def detect_expanded_factors(
        self,
        funding_rate: float | None,
        oi_change_pct: float | None,
        price_change_pct: float | None,
    ):
        """路径D: 扩展因子检测。

        委托 FactorPoolExpansion 评估 3 个新做空因子。
        每个因子独立开关（默认 False）。

        Args:
            funding_rate: 资金费率（正值=多头拥挤）
            oi_change_pct: OI 变化百分比（正值=持仓增加）
            price_change_pct: 价格变化百分比（负值=下跌）

        Returns:
            ExpandedFactorResult: 扩展因子评估结果
        """
        try:
            from dreambuddy_evolution.engines.factor_pool_expansion import (
                ExpandedFactorResult,
                FactorPoolExpansion,
            )
            _fpe = FactorPoolExpansion()
            return _fpe.evaluate(funding_rate, oi_change_pct, price_change_pct)
        except Exception as e:
            logger.debug("[FO] detect_expanded_factors fail: %s", e)
            from dreambuddy_evolution.engines.factor_pool_expansion import (
                ExpandedFactorResult,
            )
            return ExpandedFactorResult(
                funding_rate_satisfied=False,
                oi_price_divergence_satisfied=False,
                liquidation_heatmap_satisfied=False,
                new_factors_satisfied=0,
                funding_rate_value=None,
                oi_change_pct=None,
                price_change_pct=None,
            )
