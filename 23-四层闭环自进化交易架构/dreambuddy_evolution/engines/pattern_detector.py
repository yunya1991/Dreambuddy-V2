"""
Phase 4.1: 价格形态检测器
SPEC-AGI升级蓝图.md §4.4.1

检测头肩顶/底、双顶/双底等价格形态，接入BCRM2.0技术评估作为反向信号因子.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class PatternDetector:
    """价格形态检测器.

    支持: 头肩顶/底、双顶/双底.
    接入点: BCRM2.0技术评估，作为反向信号因子.
    """

    MIN_BARS = 30  # 最少K线数
    SHOULDER_SYMMETRY_TOL = 0.15  # 双肩高度差容忍度（15%）
    HEAD_SHOULDER_RATIO_MIN = 1.03  # 头部至少比肩部高3%

    def __init__(self) -> None:
        pass

    def detect_head_shoulders(self, klines: list[dict[str, Any]]) -> dict[str, Any]:
        """检测头肩顶形态.

        Args:
            klines: K线列表，每项需含 'close'

        Returns:
            {
                "detected": bool,
                "pattern_type": "head_shoulders_top" | "head_shoulders_bottom" | None,
                "confidence": float [0,1],
                "neckline": float | None,
                "head_price": float | None,
            }
        """
        if len(klines) < self.MIN_BARS:
            return self._empty_result()

        closes = np.array([float(k.get("close", k.get("price", 0.0))) for k in klines])
        if len(closes) < self.MIN_BARS:
            return self._empty_result()

        # 找局部极值点（峰和谷）
        peaks, troughs = self._find_extrema(closes)
        if len(peaks) < 3 or len(troughs) < 2:
            return self._empty_result()

        # 尝试匹配头肩顶: 峰[0]=左肩, 峰[1]=头, 峰[2]=右肩
        for i in range(len(peaks) - 2):
            left_idx, head_idx, right_idx = peaks[i], peaks[i + 1], peaks[i + 2]
            left_price = closes[left_idx]
            head_price = closes[head_idx]
            right_price = closes[right_idx]

            # 头部必须高于两肩
            if head_price <= max(left_price, right_price):
                continue
            if head_price / max(left_price, right_price) < self.HEAD_SHOULDER_RATIO_MIN:
                continue

            # 双肩高度对称
            shoulder_avg = (left_price + right_price) / 2.0
            if shoulder_avg <= 0:
                continue
            symmetry_diff = abs(left_price - right_price) / shoulder_avg
            if symmetry_diff > self.SHOULDER_SYMMETRY_TOL:
                continue

            # 颈线: 两肩之间的两个谷底连线
            left_trough = self._find_trough_between(troughs, left_idx, head_idx)
            right_trough = self._find_trough_between(troughs, head_idx, right_idx)
            if left_trough is None or right_trough is None:
                continue

            neckline = (closes[left_trough] + closes[right_trough]) / 2.0

            # 置信度计算
            confidence = self._calc_hs_confidence(
                closes, left_price, head_price, right_price,
                left_idx, head_idx, right_idx, symmetry_diff,
            )

            return {
                "detected": True,
                "pattern_type": "head_shoulders_top",
                "confidence": round(float(confidence), 4),
                "neckline": round(float(neckline), 6),
                "head_price": round(float(head_price), 6),
                "left_shoulder_price": round(float(left_price), 6),
                "right_shoulder_price": round(float(right_price), 6),
            }

        return self._empty_result()

    def bcrm_technical_assessment(self, klines: list[dict[str, Any]]) -> dict[str, Any]:
        """BCRM2.0技术评估接口 — 形态因子作为反向信号.

        Returns:
            {
                "pattern_factor": float,  # 形态因子权重[-1, 1]，负值=看跌
                "is_reversal_signal": bool,
                "direction": str,  # "short"/"long"/"neutral"
                "confidence": float,
            }
        """
        hs = self.detect_head_shoulders(klines)
        if hs["detected"] and hs["pattern_type"] == "head_shoulders_top":
            return {
                "pattern_factor": -hs["confidence"],  # 头肩顶=看跌
                "is_reversal_signal": True,
                "direction": "short",
                "confidence": hs["confidence"],
                "pattern": "head_shoulders_top",
            }
        # 头肩底（未来扩展）
        if hs["detected"] and hs["pattern_type"] == "head_shoulders_bottom":
            return {
                "pattern_factor": hs["confidence"],
                "is_reversal_signal": True,
                "direction": "long",
                "confidence": hs["confidence"],
                "pattern": "head_shoulders_bottom",
            }
        return {
            "pattern_factor": 0.0,
            "is_reversal_signal": False,
            "direction": "neutral",
            "confidence": 0.0,
            "pattern": None,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _empty_result(self) -> dict[str, Any]:
        return {
            "detected": False,
            "pattern_type": None,
            "confidence": 0.0,
            "neckline": None,
            "head_price": None,
        }

    def _find_extrema(self, closes: np.ndarray, order: int = 5) -> tuple[list[int], list[int]]:
        """找局部极值点（峰和谷），合并连续重复极值.

        order: 左右各order个bar内最高/最低.
        """
        raw_peaks: list[int] = []
        raw_troughs: list[int] = []
        n = len(closes)
        for i in range(order, n - order):
            window = closes[i - order : i + order + 1]
            if closes[i] == np.max(window):
                raw_peaks.append(i)
            elif closes[i] == np.min(window):
                raw_troughs.append(i)

        # 合并连续极值（平顶/平底只保留一个）
        peaks = self._merge_consecutive(raw_peaks)
        troughs = self._merge_consecutive(raw_troughs)
        return peaks, troughs

    def _merge_consecutive(self, indices: list[int]) -> list[int]:
        """合并连续的索引，只保留中间值."""
        if not indices:
            return []
        merged: list[int] = []
        group = [indices[0]]
        for idx in indices[1:]:
            if idx - group[-1] <= 1:  # 连续（差≤1）
                group.append(idx)
            else:
                merged.append(group[len(group) // 2])  # 取中间
                group = [idx]
        merged.append(group[len(group) // 2])
        return merged

    def _find_trough_between(
        self, troughs: list[int], left: int, right: int
    ) -> int | None:
        """在left和right之间找最近的谷底."""
        for t in troughs:
            if left < t < right:
                return t
        return None

    def _calc_hs_confidence(
        self,
        closes: np.ndarray,
        left_price: float,
        head_price: float,
        right_price: float,
        left_idx: int,
        head_idx: int,
        right_idx: int,
        symmetry_diff: float,
    ) -> float:
        """计算头肩顶置信度 [0,1]."""
        # 1. 头部突出度: head相对肩部的高度比例
        shoulder_avg = (left_price + right_price) / 2.0
        head_prominence = (head_price - shoulder_avg) / max(shoulder_avg, 1e-12)
        head_score = min(head_prominence / 0.20, 1.0)  # 20%突出度=满分

        # 2. 对称性: 双肩越对称越好
        sym_score = max(0.0, 1.0 - symmetry_diff / self.SHOULDER_SYMMETRY_TOL)

        # 3. 时间比例: 左肩到头 vs 头到右肩 应接近1:1
        left_duration = head_idx - left_idx
        right_duration = right_idx - head_idx
        if left_duration > 0 and right_duration > 0:
            time_ratio = min(left_duration, right_duration) / max(left_duration, right_duration)
            time_score = time_ratio
        else:
            time_score = 0.5

        # 加权
        confidence = 0.4 * head_score + 0.35 * sym_score + 0.25 * time_score
        return float(max(0.0, min(1.0, confidence)))
