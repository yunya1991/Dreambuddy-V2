"""EnhancedWashoutClassifier — 多因子洗盘分类器（W4 阶段）。

基于回测验证的外部因子判定规则:
  真洗盘 (WASHOUT): 缩量 + OI 温和下降 + CVD 与价格背离 → hold
  假洗盘 (WEAKNESS): 缩量 + OI 上升 + CVD 与价格同步 → force_close
  信号不足 → UNKNOWN

回测准确率: 77.5% (vs volume-only 32.5%)，有判定准确率 96.9%。
Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from .washout_detector import WashoutLabel, WashoutVerdict

__all__ = ["EnhancedWashoutClassifier"]

_logger = logging.getLogger(__name__)


class EnhancedWashoutClassifier:
    """多因子洗盘分类器: volume + OI + CVD + funding。

    判定规则（回测验证）:
      WASHOUT: volume_ratio < 0.8 AND oi_change_rate_7d < -0.02
               AND cvd_price_divergence < -0.1
      WEAKNESS: volume_ratio < 0.8 AND oi_change_rate_7d > 0.03
                AND cvd_price_divergence > 0.2
      WEAKNESS (funding辅助): funding_rate_zscore < -2.5
      其他 → UNKNOWN
    """

    # 阈值常量（回测验证后固定）
    VOL_WASHOUT_THRESHOLD = 0.8      # 缩量阈值
    VOL_WEAKNESS_THRESHOLD = 1.5     # 放量阈值
    OI_DECLINE_THRESHOLD = -0.02     # OI 温和下降（弱手离场）
    OI_RISE_THRESHOLD = 0.03         # OI 上升（新空头涌入）
    CVD_DIVERGENCE_THRESHOLD = -0.1  # CVD 与价格背离（聪明钱吸收）
    CVD_SYNC_THRESHOLD = 0.2         # CVD 与价格同步下行（出货）
    FUNDING_DEEP_NEGATIVE = -2.5     # funding 深度负值

    WASHOUT_CONFIDENCE = 0.85
    WEAKNESS_CONFIDENCE = 0.80
    WEAKNESS_FUNDING_CONFIDENCE = 0.70

    def predict(self, features: Dict[str, float]) -> Optional[WashoutVerdict]:
        """基于多因子特征输出判定。

        Args:
            features: WashoutFeatureExtractor.extract_all() 的输出

        Returns:
            WashoutVerdict 或 None (FAIL-OPEN)
        """
        try:
            if not features or not isinstance(features, dict):
                return WashoutVerdict.unknown()

            vol = features.get("volume_ratio_20d", 1.0)
            oi_rate = features.get("oi_change_rate_7d", 0.0)
            cvd_corr = features.get("cvd_price_divergence", 0.0)
            funding_z = features.get("funding_rate_zscore", 0.0)

            # 放量 → WEAKNESS
            if vol > self.VOL_WEAKNESS_THRESHOLD:
                return WashoutVerdict(
                    label=WashoutLabel.WEAKNESS,
                    confidence=self.WEAKNESS_CONFIDENCE,
                    trigger_activated=True,
                    feature_snapshot=features,
                    reason="enhanced_weakness_high_volume",
                    timestamp="",
                )

            # 缩量回调场景下进一步判定
            if vol < self.VOL_WASHOUT_THRESHOLD:
                # 真洗盘: OI 温和下降 + CVD 背离
                if (oi_rate < self.OI_DECLINE_THRESHOLD
                        and cvd_corr < self.CVD_DIVERGENCE_THRESHOLD):
                    return WashoutVerdict(
                        label=WashoutLabel.WASHOUT,
                        confidence=self.WASHOUT_CONFIDENCE,
                        trigger_activated=True,
                        feature_snapshot=features,
                        reason="enhanced_washout_oi_decline_cvd_divergence",
                        timestamp="",
                    )
                # 假洗盘: OI 上升 + CVD 同步下行
                if (oi_rate > self.OI_RISE_THRESHOLD
                        and cvd_corr > self.CVD_SYNC_THRESHOLD):
                    return WashoutVerdict(
                        label=WashoutLabel.WEAKNESS,
                        confidence=self.WEAKNESS_CONFIDENCE,
                        trigger_activated=True,
                        feature_snapshot=features,
                        reason="enhanced_weakness_oi_rise_cvd_sync",
                        timestamp="",
                    )
                # funding 辅助: 深度负值倾向真弱势
                if funding_z < self.FUNDING_DEEP_NEGATIVE:
                    return WashoutVerdict(
                        label=WashoutLabel.WEAKNESS,
                        confidence=self.WEAKNESS_FUNDING_CONFIDENCE,
                        trigger_activated=True,
                        feature_snapshot=features,
                        reason="enhanced_weakness_deep_negative_funding",
                        timestamp="",
                    )

            # 信号不足 → UNKNOWN
            return WashoutVerdict.unknown()
        except Exception as e:
            _logger.warning("EnhancedWashoutClassifier FAIL-OPEN: %s", e)
            return WashoutVerdict.unknown()
