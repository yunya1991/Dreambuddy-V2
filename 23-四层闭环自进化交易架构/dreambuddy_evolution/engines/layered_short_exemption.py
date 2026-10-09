"""路径B: 三因子分层豁免（AND → 分层）

SPEC-自进化系统做空能力疏通探讨 §4 路径B：
  将三因子豁免从 AND 逻辑（全满足才豁免）升级为分层豁免。

分层规则:
  - 3 因子全满足 → 全豁免，仓位 0.7x，止损 0.5x，允许加仓
  - 2 因子满足 → 试探豁免，仓位 0.2x，止损 0.5x，禁止加仓
  - 1/0 因子满足 → 不豁免，维持 SHORT_BAN

三因子条件（与 ThreeFactorShortDetector 一致）:
  1. pattern_factor <= -0.5  (头肩顶看跌)
  2. btc_regime == "WEAK"     (BTC 与美股高相关弱市)
  3. etf_flow_norm < -0.1     (ETF 净流出)

安全侧 FAIL-OPEN: 异常/缺失/NaN/inf → 不豁免（维持 SHORT_BAN 铁律）
开关: enable_layered_short_exemption（默认 False → 回退 AND 逻辑：仅 3 因子全满足才豁免）
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayeredExemptionResult:
    """分层豁免结果

    Attributes:
        layer: 豁免层级 (0=不豁免, 1=试探豁免, 2=全豁免)
        exempted: 是否豁免 SHORT_BAN
        position_multiplier: 仓位倍数 (0.0 / 0.2 / 0.7)
        stop_loss_multiplier: 止损倍数 (0.0 / 0.5)
        factors_satisfied: 满足的因子数 (0-3)
        allow_add_position: 是否允许加仓 (全豁免=True, 试探/不豁免=False)
    """
    layer: int
    exempted: bool
    position_multiplier: float
    stop_loss_multiplier: float
    factors_satisfied: int
    allow_add_position: bool


class LayeredShortExemption:
    """三因子分层豁免检测器

    受 enable_layered_short_exemption 开关控制（默认 False）。
    开关关闭时回退到 AND 逻辑（仅 3 因子全满足才豁免）。
    开关开启时启用分层豁免（2 因子也能试探豁免）。
    """

    PATTERN_THRESHOLD = -0.5   # 头肩顶 pattern_factor <= -0.5
    ETF_OUTFLOW_THRESHOLD = -0.1  # ETF 净流出（归一化 < -0.1，严格小于）

    # 分层参数（SPEC §4 路径B 探讨值）
    FULL_POSITION = 0.7    # 全豁免仓位
    TRIAL_POSITION = 0.2   # 试探豁免仓位
    STOP_LOSS = 0.5        # 止损倍数（全豁免和试探豁免统一 0.5x）

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        pattern_factor: float | None,
        btc_regime: str | None,
        etf_flow_norm: float | None,
    ) -> LayeredExemptionResult:
        """三因子分层豁免检测。

        Args:
            pattern_factor: PatternDetector 的 pattern_factor（负值=看跌）
            btc_regime: RegimeClassifier 的 regime（STRONG/WEAK/NEUTRAL）
            etf_flow_norm: ETF 净流出的归一化值（负值=流出）

        Returns:
            LayeredExemptionResult: 分层豁免结果
        """
        try:
            # 开关检查
            from dreambuddy_evolution.agi_config import get_switch
            switch_on = get_switch("enable_layered_short_exemption")
        except Exception as e:
            logger.debug("[FO] LayeredShortExemption switch check fail: %s", e)
            return self._not_exempted()

        # 因子计数（FAIL-OPEN: 任一输入异常 → 不豁免）
        count = self._count_factors(pattern_factor, btc_regime, etf_flow_norm)
        if count < 0:
            return self._not_exempted()

        # 分层判定
        if not switch_on:
            # 开关关闭: AND 逻辑回退（仅 3 因子全满足才豁免）
            if count >= 3:
                return self._full_exemption(count)
            return self._not_exempted(count)

        # 开关开启: 分层豁免
        if count >= 3:
            return self._full_exemption(count)
        elif count == 2:
            return self._trial_exemption(count)
        else:
            return self._not_exempted(count)

    def evaluate_with_expansion(
        self,
        pattern_factor: float | None,
        btc_regime: str | None,
        etf_flow_norm: float | None,
        expanded_result=None,
    ) -> LayeredExemptionResult:
        """路径B+D: 分层豁免 + 扩展因子协同。

        开关关闭时扩展因子不参与（回退 AND 逻辑）。
        开关开启时扩展因子纳入分层计算（合并因子计数）。

        Args:
            pattern_factor: PatternDetector 的 pattern_factor
            btc_regime: RegimeClassifier 的 regime
            etf_flow_norm: ETF 净流出的归一化值
            expanded_result: FactorPoolExpansion 的 ExpandedFactorResult（可选）

        Returns:
            LayeredExemptionResult: 合并后的分层豁免结果
        """
        base_result = self.evaluate(pattern_factor, btc_regime, etf_flow_norm)

        # 开关关闭时，扩展因子不参与
        try:
            from dreambuddy_evolution.agi_config import get_switch
            if not get_switch("enable_layered_short_exemption"):
                return base_result
        except Exception:
            return base_result

        # 开关开启时，扩展因子纳入分层计算
        if expanded_result is None or expanded_result.new_factors_satisfied <= 0:
            return base_result

        # 合并因子计数 = 原始因子 + 扩展因子
        combined_count = base_result.factors_satisfied + expanded_result.new_factors_satisfied

        if combined_count >= 3:
            return self._full_exemption(combined_count)
        elif combined_count == 2:
            return self._trial_exemption(combined_count)
        else:
            return self._not_exempted(combined_count)

    def _count_factors(
        self,
        pattern_factor: float | None,
        btc_regime: str | None,
        etf_flow_norm: float | None,
    ) -> int:
        """统计满足的因子数。

        Returns:
            0-3: 满足的因子数
            -1: 任一输入异常（FAIL-OPEN 信号）
        """
        try:
            # 因子 1: pattern_factor <= -0.5
            pf = float(pattern_factor)
            if math.isnan(pf) or math.isinf(pf):
                return -1
            f1 = pf <= self.PATTERN_THRESHOLD

            # 因子 2: btc_regime == "WEAK"（大小写不敏感）
            if btc_regime is None:
                return -1
            regime = str(btc_regime).upper()
            f2 = regime == "WEAK"

            # 因子 3: etf_flow_norm < -0.1（严格小于）
            etf = float(etf_flow_norm)
            if math.isnan(etf) or math.isinf(etf):
                return -1
            f3 = etf < self.ETF_OUTFLOW_THRESHOLD

            return int(f1) + int(f2) + int(f3)

        except (TypeError, ValueError) as e:
            logger.debug("[FO] LayeredShortExemption factor count fail: %s", e)
            return -1
        except Exception as e:
            logger.debug("[FO] LayeredShortExemption factor count crash: %s", e)
            return -1

    def _full_exemption(self, factors_satisfied: int) -> LayeredExemptionResult:
        """全豁免: 3 因子全满足"""
        return LayeredExemptionResult(
            layer=2,
            exempted=True,
            position_multiplier=self.FULL_POSITION,
            stop_loss_multiplier=self.STOP_LOSS,
            factors_satisfied=factors_satisfied,
            allow_add_position=True,
        )

    def _trial_exemption(self, factors_satisfied: int) -> LayeredExemptionResult:
        """试探豁免: 2 因子满足"""
        return LayeredExemptionResult(
            layer=1,
            exempted=True,
            position_multiplier=self.TRIAL_POSITION,
            stop_loss_multiplier=self.STOP_LOSS,
            factors_satisfied=factors_satisfied,
            allow_add_position=False,
        )

    def _not_exempted(self, factors_satisfied: int = 0) -> LayeredExemptionResult:
        """不豁免: 维持 SHORT_BAN"""
        return LayeredExemptionResult(
            layer=0,
            exempted=False,
            position_multiplier=0.0,
            stop_loss_multiplier=0.0,
            factors_satisfied=factors_satisfied,
            allow_add_position=False,
        )
