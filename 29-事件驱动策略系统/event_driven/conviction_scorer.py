"""
ConvictionScorer — 事件驱动置信度评分器

SPEC §4.2: 6 因子加权置信度（0.0-1.0）
  1. primary_contradiction      (25%): 主要矛盾清晰度（FOMC 方向明确度）
  2. cross_asset                 (20%): 跨资产验证一致性
  3. technical                   (15%): 技术面信号强度
  4. capital_flow                (15%): 资金流方向
  5. data_quality                (10%): 数据完整度
  6. fundamental_verification    (15%): 基本面验证（repricing verification 子阶段）

置信度档位:
  >= 0.85 → 硬过滤（覆盖其他子系统）
  0.70-0.85 → 软过滤（加权增强）
  < 0.70 → 不过滤
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConvictionResult:
    conviction: float
    factors: dict[str, float]
    filter_level: str  # "hard" / "soft" / "none"
    direction: str  # "long" / "short" / "neutral"
    position_params: dict[str, Any] | None = None  # SPEC §4.6.2 仓位映射参数

    def to_dict(self) -> dict[str, Any]:
        return {
            "conviction": self.conviction,
            "factors": self.factors,
            "filter_level": self.filter_level,
            "direction": self.direction,
            "position_params": self.position_params,
        }


class ConvictionScorer:
    """6 因子置信度评分器（含基本面验证因子）。"""

    W_PRIMARY = 0.25
    W_CROSS = 0.20
    W_TECH = 0.15
    W_CAPITAL = 0.15
    W_DATA = 0.10
    W_FUNDAMENTAL = 0.15  # 基本面验证因子（SPEC §0.4.4 Phase B）

    HARD_THRESHOLD = 0.85
    SOFT_THRESHOLD = 0.70

    def score(self, kline_data: dict[str, Any], event_signal: dict[str, Any] | None = None) -> ConvictionResult:
        """
        计算事件驱动置信度。

        Args:
            kline_data: data_pipeline.assemble() 输出
            event_signal: EventDrivenStrategy.evaluate().to_dict() 输出（可选）

        Returns ConvictionResult。
        """
        factors = {
            "primary_contradiction": self._factor_primary(kline_data),
            "cross_asset": self._factor_cross_asset(kline_data),
            "technical": self._factor_technical(kline_data),
            "capital_flow": self._factor_capital(kline_data),
            "data_quality": self._factor_data_quality(kline_data),
            "fundamental_verification": self._factor_fundamental(kline_data),
        }

        conviction = (
            factors["primary_contradiction"] * self.W_PRIMARY
            + factors["cross_asset"] * self.W_CROSS
            + factors["technical"] * self.W_TECH
            + factors["capital_flow"] * self.W_CAPITAL
            + factors["data_quality"] * self.W_DATA
            + factors["fundamental_verification"] * self.W_FUNDAMENTAL
        )
        conviction = max(0.0, min(1.0, conviction))

        # 过滤档位
        if conviction >= self.HARD_THRESHOLD:
            filter_level = "hard"
        elif conviction >= self.SOFT_THRESHOLD:
            filter_level = "soft"
        else:
            filter_level = "none"

        # 方向：从 event_signal 或 event_context 获取
        direction = "neutral"
        if event_signal and event_signal.get("signal") in ("long", "short"):
            direction = event_signal["signal"]
        else:
            event_ctx = kline_data.get("event_context") or {}
            direction = event_ctx.get("dominant_direction", "neutral")

        # SPEC §4.6.2: 置信度→仓位映射（可选，开关关断时为 None）
        position_params = None
        try:
            from dreambuddy_evolution.engines.conviction_position_mapper import (
                ConvictionPositionMapper,
            )
            fomc_phase = (kline_data.get("event_context") or {}).get("cycle_phase")
            mapper = ConvictionPositionMapper()
            position_params = mapper.map(conviction, fomc_phase=fomc_phase)
        except Exception as e:
            logger.debug("ConvictionPositionMapper 跳过: %s", e, exc_info=False)

        return ConvictionResult(
            conviction=round(conviction, 3),
            factors=factors,
            filter_level=filter_level,
            direction=direction,
            position_params=position_params,
        )

    # ---------------------------------------------------------- 因子

    def _factor_primary(self, data: dict) -> float:
        """
        主要矛盾清晰度: FOMC 方向明确度 + 实际利率方向一致性。

        两个维度：
          1. hike_prob 接近 0 或 1 → 方向明确（基础分）
          2. 实际利率方向与黄金方向一致 → 加分
             通胀 > 加息速度 → 实际利率下行 → 利好黄金（加分）
        """
        event_ctx = data.get("event_context") or {}
        hike_prob = event_ctx.get("hike_prob")

        # 基础分：方向明确度
        if hike_prob is None:
            base = 0.3
        else:
            p = float(hike_prob)
            clarity = abs(p - 0.5) * 2.0
            base = clarity

        # 实际利率方向加分
        cpi_actual = data.get("cpi_actual")
        fomc = data.get("fomc_decision", {})
        if isinstance(fomc, dict) and cpi_actual is not None:
            rate_change = fomc.get("rate_change")
            if rate_change is not None:
                try:
                    # 基准 3.625%（3.50-3.75% 中点）+ 加息幅度
                    nominal_rate = 3.625 + float(rate_change)
                    real_rate = nominal_rate - float(cpi_actual)
                    # 实际利率低 → 利好黄金 → 主要矛盾更清晰
                    if real_rate < 1.0:
                        base = min(1.0, base + 0.15)
                    elif real_rate > 3.0:
                        base = max(0.0, base - 0.10)
                except (TypeError, ValueError):
                    pass

        return round(max(0.0, min(1.0, base)), 3)

    def _factor_cross_asset(self, data: dict) -> float:
        """
        跨资产一致性: 黄金/美债/美元方向是否一致指向同一方向。
        """
        signals = []
        gold_ret = data.get("gold_change_pct")
        if gold_ret is not None:
            try:
                signals.append(1.0 if float(gold_ret) > 0 else -1.0)
            except (TypeError, ValueError):
                pass
        us10y = data.get("us10y_change_bp")
        if us10y is not None:
            try:
                signals.append(-1.0 if float(us10y) > 0 else 1.0)  # 收益率降→利好
            except (TypeError, ValueError):
                pass
        dxy = data.get("dxy_change_pct")
        if dxy is not None:
            try:
                signals.append(-1.0 if float(dxy) > 0 else 1.0)  # 美元弱→利好
            except (TypeError, ValueError):
                pass

        if len(signals) < 2:
            return 0.3  # 数据不足
        # 一致性 = 同向比例
        avg = sum(signals) / len(signals)
        return round(max(0.0, min(1.0, abs(avg))), 3)

    def _factor_technical(self, data: dict) -> float:
        """
        技术面强度: 趋势 + 下影线 + 支撑。
        用 ADX + 价格相对 MA20 位置。
        """
        score = 0.5
        close = data.get("close", [])
        # 趋势：价格在 MA20 上方
        try:
            if isinstance(close, (list, tuple)) and len(close) >= 20:
                ma20 = sum(float(x) for x in close[-20:]) / 20
                if float(close[-1]) > ma20:
                    score += 0.2
                else:
                    score -= 0.1
        except Exception:
            pass
        # ADX
        adx = data.get("adx")
        if adx is not None:
            try:
                a = float(adx)
                if a > 25:
                    score += 0.15
                elif a < 15:
                    score -= 0.1
            except (TypeError, ValueError):
                pass
        return round(max(0.0, min(1.0, score)), 3)

    def _factor_capital(self, data: dict) -> float:
        """
        资金流强度: capital_flow 绝对值。
        """
        cf = data.get("capital_flow")
        if cf is None:
            return 0.3
        try:
            return round(max(0.0, min(1.0, abs(float(cf)))), 3)
        except (TypeError, ValueError):
            return 0.3

    def _factor_data_quality(self, data: dict) -> float:
        """
        数据完整度: 关键字段存在比例。
        """
        keys = (
            "cpi_actual", "cpi_expected", "rate_hike_prob", "monetary_cycle",
            "event_context", "capital_flow", "close", "high", "low", "open",
        )
        present = sum(1 for k in keys if data.get(k) is not None)
        return round(present / len(keys), 3)

    def _factor_fundamental(self, data: dict) -> float:
        """
        基本面验证因子（SPEC §0.4.4 Phase B）。

        在 repricing verification 子阶段（5-15天）检查基本面改善：
          - 通胀回落 (cpi_actual < cpi_expected) → 改善
          - 通胀未回落 → 恶化

        评分逻辑：
          - improvement_ratio >= 0.5 → 高分（基本面支撑多头）
          - 有恶化项 → 低分（基本面不支撑）
          - 无数据/非 verification 阶段 → 中性 0.5
        """
        event_ctx = data.get("event_context") or {}
        sub_phase = event_ctx.get("repricing_sub_phase", "none")

        # 仅在 verification 子阶段激活
        if sub_phase != "verification":
            return 0.5

        cpi_actual = data.get("cpi_actual")
        cpi_expected = data.get("cpi_expected")

        if cpi_actual is None or cpi_expected is None:
            return 0.5  # 无数据 → 中性

        try:
            if float(cpi_actual) < float(cpi_expected):
                # 通胀回落 → 基本面改善 → 高分
                return 0.80
            else:
                # 通胀未回落 → 基本面恶化 → 低分
                return 0.20
        except (TypeError, ValueError):
            return 0.5
