"""路径D: 因子池扩展

SPEC-自进化系统做空能力疏通探讨 §4 路径D：
  扩展三因子池子（pattern_factor / btc_regime / etf_flow_norm），
  新增 3 个做空因子。

新因子:
  1. 资金费率因子: funding_rate > 0.1%（多头过度拥挤，做空赔率高）
     - 数据源: Binance API /fapi/v1/premiumIndex（标准免费 API）
  2. OI-Price 背离因子: OI↑ + Price↓（持仓量上升但价格下跌，空头主力进场）
     - 数据源: Binance API /fapi/v1/openInterest（标准免费 API）
     - 背离窗口: 4h（由调用方提供 4h 变化百分比）
  3. 清算热力图因子: 降级为可选（需 POC 确认数据可用性）
     - 数据源: Coinglass/Coinalyze 等第三方（非标准 API，可能付费）
     - POC 通过后才纳入因子池；POC 失败则永久移除

每个因子独立开关（默认 False）:
  - enable_funding_rate_factor
  - enable_oi_price_divergence_factor
  - enable_liquidation_heatmap_factor

安全侧 FAIL-OPEN: 异常/缺失/NaN/inf → 因子不满足
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpandedFactorResult:
    """因子池扩展结果

    Attributes:
        funding_rate_satisfied: 资金费率因子是否满足
        oi_price_divergence_satisfied: OI-Price 背离因子是否满足
        liquidation_heatmap_satisfied: 清算热力图因子是否满足（降级为可选，始终 False 直到 POC 通过）
        new_factors_satisfied: 新因子满足数（0-2，清算热力图降级不计）
        funding_rate_value: 资金费率原始值
        oi_change_pct: OI 变化百分比
        price_change_pct: 价格变化百分比
    """
    funding_rate_satisfied: bool
    oi_price_divergence_satisfied: bool
    liquidation_heatmap_satisfied: bool
    new_factors_satisfied: int
    funding_rate_value: float | None
    oi_change_pct: float | None
    price_change_pct: float | None


class FactorPoolExpansion:
    """因子池扩展器

    新增 3 个做空因子，每个因子独立开关控制。
    清算热力图因子降级为可选（需 POC），当前始终返回 False。
    """

    FUNDING_RATE_THRESHOLD = 0.001  # 0.1%（严格大于）

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        funding_rate: float | None,
        oi_change_pct: float | None,
        price_change_pct: float | None,
    ) -> ExpandedFactorResult:
        """评估 3 个新因子。

        Args:
            funding_rate: 资金费率（如 0.002 = 0.2%），正值=多头拥挤
            oi_change_pct: OI 变化百分比（如 0.05 = +5%），正值=持仓增加
            price_change_pct: 价格变化百分比（如 -0.02 = -2%），负值=价格下跌

        Returns:
            ExpandedFactorResult: 因子评估结果
        """
        # 因子 1: 资金费率
        fr_satisfied = self._check_funding_rate(funding_rate)

        # 因子 2: OI-Price 背离
        oi_satisfied = self._check_oi_price_divergence(oi_change_pct, price_change_pct)

        # 因子 3: 清算热力图（降级为可选，始终 False 直到 POC 通过）
        lq_satisfied = self._check_liquidation_heatmap()

        # 计数（清算热力图降级不计入 new_factors_satisfied）
        count = int(fr_satisfied) + int(oi_satisfied)

        return ExpandedFactorResult(
            funding_rate_satisfied=fr_satisfied,
            oi_price_divergence_satisfied=oi_satisfied,
            liquidation_heatmap_satisfied=lq_satisfied,
            new_factors_satisfied=count,
            funding_rate_value=self._safe_float(funding_rate),
            oi_change_pct=self._safe_float(oi_change_pct),
            price_change_pct=self._safe_float(price_change_pct),
        )

    def _check_funding_rate(self, funding_rate: float | None) -> bool:
        """资金费率因子: funding_rate > 0.1% (0.001)"""
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_funding_rate_factor"):
                return False
        except Exception as e:
            logger.debug("[FO] funding_rate switch check fail: %s", e)
            return False

        try:
            v = float(funding_rate)
            if math.isnan(v) or math.isinf(v):
                return False
            return v > self.FUNDING_RATE_THRESHOLD
        except (TypeError, ValueError) as e:
            logger.debug("[FO] funding_rate check fail: %s", e)
            return False
        except Exception as e:
            logger.debug("[FO] funding_rate check crash: %s", e)
            return False

    def _check_oi_price_divergence(
        self,
        oi_change_pct: float | None,
        price_change_pct: float | None,
    ) -> bool:
        """OI-Price 背离因子: OI↑ (oi_change_pct > 0) AND Price↓ (price_change_pct < 0)"""
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_oi_price_divergence_factor"):
                return False
        except Exception as e:
            logger.debug("[FO] oi_price switch check fail: %s", e)
            return False

        try:
            oi = float(oi_change_pct)
            if math.isnan(oi) or math.isinf(oi):
                return False

            price = float(price_change_pct)
            if math.isnan(price) or math.isinf(price):
                return False

            # OI↑ AND Price↓
            return oi > 0 and price < 0
        except (TypeError, ValueError) as e:
            logger.debug("[FO] oi_price check fail: %s", e)
            return False
        except Exception as e:
            logger.debug("[FO] oi_price check crash: %s", e)
            return False

    def _check_liquidation_heatmap(self) -> bool:
        """清算热力图因子: 降级为可选（需 POC），当前始终 False"""
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_liquidation_heatmap_factor"):
                return False
        except Exception as e:
            logger.debug("[FO] liquidation switch check fail: %s", e)
            return False

        # POC 未通过，始终返回 False
        # POC 通过后在此处接入清算热力图数据源
        return False

    def _safe_float(self, value: float | None) -> float | None:
        """安全转换为 float，返回 None 如果无效"""
        try:
            v = float(value)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except (TypeError, ValueError):
            return None
