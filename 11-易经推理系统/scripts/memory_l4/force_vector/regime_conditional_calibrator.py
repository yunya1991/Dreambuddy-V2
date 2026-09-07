"""阶段依赖性校准器 —— regime 条件期望校准 + CBR背离检测。

纯 Python 实现。所有路径 FAIL-OPEN（异常返回中性默认值）。
对应 Spec §三-A Step 3-A-2 RegimeConditionalCalibrator。

adjustment_factor = E[r|event,regime_current] / E[r|event,all_regimes]
  若 |adjustment_factor| < 0.3 → 力向量强度 ×0.5
  若 |adjustment_factor| > 2.0 → 力向量强度 ×1.5
  方向相反（sign 不同）→ 调整因子归零（反映冲突，触发 ×0.5 衰减）
  异常 → 1.0（不调整）

CBR背离：当前事件收益与历史同类事件收益方向相反
  方向相反 = sign(current) != sign(mean(historical)) 且 |mean(historical)| > 0.01
  样本不足（<3）→ False
"""
from __future__ import annotations

import math


class RegimeConditionalCalibrator:
    """阶段依赖性校准器。

    compute_adjustment：计算 regime 条件期望与全 regime 期望的比值（调整因子）。
    detect_cbr_divergence：检测当前事件与历史同类事件方向相反（CBR背离）。
    所有异常路径 FAIL-OPEN。
    """

    # 调整因子阈值
    _REDUCE_THRESHOLD = 0.3     # |adjustment_factor| < 0.3 → 力向量强度 ×0.5
    _BOOST_THRESHOLD = 2.0     # |adjustment_factor| > 2.0 → 力向量强度 ×1.5
    _EPS = 1e-12                # 分母接近 0 的判定阈值
    _NEUTRAL = 1.0              # FAIL-OPEN 中性（不调整）

    # CBR背离阈值
    _MIN_SAMPLES = 3            # 历史样本下限
    _MEAN_EPS = 0.01            # 历史均值显著下限（避免噪声误判）

    def compute_adjustment(self, e_r_current: float, e_r_all: float) -> float:
        """阶段依赖性校准因子。

        adjustment_factor = E[r|event,regime_current] / E[r|event,all_regimes]
        方向相反时归零（触发 ×0.5 衰减）；异常返回 1.0。
        """
        try:
            cur = float(e_r_current)
            all_ = float(e_r_all)
            # 分母≈0 → FAIL-OPEN 不调整
            if abs(all_) < self._EPS:
                return self._NEUTRAL
            # 方向相反 → 调整因子归零（反映冲突，触发 ×0.5 衰减）
            if self._sign(cur) * self._sign(all_) < 0:
                return 0.0
            # 同向 → 调整因子 = E[r|current] / E[r|all]
            ratio = cur / all_
            if not math.isfinite(ratio):
                return self._NEUTRAL
            return float(ratio)
        except Exception:
            return self._NEUTRAL

    def detect_cbr_divergence(self, current_result: float,
                             historical_results: list) -> bool:
        """CBR背离检测：当前事件结果与历史同类事件方向相反。

        方向相反 = sign(current) != sign(mean(historical)) 且 |mean(historical)| > 0.01
        样本不足（<3）返回 False。
        """
        try:
            cur = float(current_result)
            hist = list(historical_results)
            if len(hist) < self._MIN_SAMPLES:
                return False
            hist_f = [float(x) for x in hist]
            mean_h = sum(hist_f) / len(hist_f)
            # 历史均值不显著 → 避免噪声误判
            if abs(mean_h) <= self._MEAN_EPS:
                return False
            # 方向相反 = sign(current) != sign(mean(historical))
            return self._sign(cur) != self._sign(mean_h)
        except Exception:
            return False

    @staticmethod
    def _sign(x: float) -> int:
        """符号函数：正→1，负→-1，零→0。异常→0。"""
        try:
            v = float(x)
            if v > 0:
                return 1
            if v < 0:
                return -1
            return 0
        except Exception:
            return 0
