"""Phase 4.3: 三因子共振做多检测器
对称 three_factor_short.py，用于 BDSM 三层置信度递进开仓的 L2 加强层做多确认。

三因子共振条件（全满足才返回 True）:
  1. pattern_factor >= +0.5  (头肩底看涨，PatternDetector 输出)
  2. btc_regime == "STRONG"  (BTC 与美股脱钩，独立强势)
  3. etf_flow_norm > +0.1    (ETF 净流入)

安全侧 FAIL-OPEN: 任一因子缺失/异常 → False（不升级到 L2 加强层）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ThreeFactorLongDetector:
    """三因子共振做多检测器

    受 enable_three_factor_long 开关控制（默认 True）。
    开关关闭时直接返回 False，不计算。
    """

    PATTERN_THRESHOLD = 0.5  # 头肩底 pattern_factor ≥ 0.5
    ETF_INFLOW_THRESHOLD = 0.1  # ETF 净流入（归一化 > 0.1）

    def __init__(self) -> None:
        pass

    def detect(
        self,
        pattern_factor: float | None,
        btc_regime: str | None,
        etf_flow_norm: float | None,
    ) -> bool:
        """三因子共振检测（做多方向）。

        Args:
            pattern_factor: PatternDetector 的 pattern_factor（正值=看涨）
            btc_regime: RegimeClassifier 的 regime（STRONG/WEAK/NEUTRAL）
            etf_flow_norm: ETF 净流入的归一化值（正值=流入）

        Returns:
            True = 三因子全满足，允许升级到 L2 加强做多
            False = 不满足或异常，停留在 L1 基础做多
        """
        try:
            # 开关检查
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_three_factor_long"):
                return False
        except Exception:
            return False  # FAIL-OPEN: 开关检查异常 → False

        try:
            # 因子 1: 头肩底看涨
            pf = float(pattern_factor) if pattern_factor is not None else 0.0
            if pf < self.PATTERN_THRESHOLD:
                return False

            # 因子 2: BTC regime = STRONG
            regime = str(btc_regime or "").upper()
            if regime != "STRONG":
                return False

            # 因子 3: ETF 净流入
            etf = float(etf_flow_norm) if etf_flow_norm is not None else 0.0
            if etf <= self.ETF_INFLOW_THRESHOLD:
                return False

            # 三因子全满足
            return True

        except (TypeError, ValueError) as e:
            logger.debug("[FO] ThreeFactorLongDetector detect fail: %s", e)
            return False  # 安全侧 FAIL-OPEN: 异常 → False
        except Exception as e:
            logger.debug("[FO] ThreeFactorLongDetector detect crash: %s", e)
            return False
