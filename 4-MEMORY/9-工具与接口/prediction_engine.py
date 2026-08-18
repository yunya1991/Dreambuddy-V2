#!/usr/bin/env python3
"""
事前预测引擎 (Prediction Engine) — P2-9 主动推理

对齐 Friston 主动推理：开仓前生成预测，平仓后计算预测误差，
误差驱动贝叶斯更新（最小化自由能）。

关联文档: COGNITIVE_ARCHITECTURE.md §5.4 P2-9 / spec 2026-08-05-cognitive-science-p2-p3-design.md §2
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict


@dataclass
class Prediction:
    """事前预测（开仓时生成，平仓后校验）"""
    expected_direction: str       # "LONG" / "SHORT" / "HOLD"
    expected_horizon_bars: int    # 预期持仓周期（K线根数）
    stop_loss_prob: float         # 预期止损触发概率 [0,1]
    target_return_pct: float      # 预期目标收益率（%）
    prediction_confidence: float  # 预测置信度 [0,1]
    generated_at: str             # ISO 时间戳


@dataclass
class PredictionError:
    """预测误差（平仓后计算）"""
    direction_hit: bool           # 方向是否命中
    target_hit: bool              # 目标收益是否达成
    stop_triggered: bool          # 止损是否触发
    magnitude_error: float        # 误差幅度
    computed_at: str              # ISO 时间戳


class PredictionEngine:
    """事前预测生成器（对齐 Friston 主动推理）"""

    # 波动率→持仓周期映射（高波动短周期）
    _HORIZON_MAP = [
        (0.02, 48),   # vol<2% → 48根（约1天）
        (0.05, 24),   # vol<5% → 24根（约12小时）
        (0.10, 12),   # vol<10% → 12根（约6小时）
        (float("inf"), 6),  # 高波动 → 6根（约3小时）
    ]

    def generate_prediction(self, inference: Dict) -> Prediction:
        """从开仓 inference 生成事前预测"""
        direction = inference.get("direction", "HOLD")
        confidence = float(inference.get("confidence", 0.5))
        volatility = float(inference.get("volatility", 0.0))
        a0_warnings = inference.get("a0_warnings", [])

        horizon = self._vol_to_horizon(volatility)
        contradiction_count = len(a0_warnings)
        stop_loss_prob = min(0.8, 0.2 + contradiction_count * 0.1 + volatility * 2)
        target_return_pct = confidence * 5 + volatility * 10
        prediction_confidence = max(0.1, min(0.95, confidence))

        return Prediction(
            expected_direction=direction,
            expected_horizon_bars=horizon,
            stop_loss_prob=round(stop_loss_prob, 4),
            target_return_pct=round(target_return_pct, 4),
            prediction_confidence=round(prediction_confidence, 4),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def compute_error(self, prediction: Prediction, actual: Dict) -> PredictionError:
        """平仓后计算预测误差"""
        actual_direction = str(actual.get("direction", ""))
        actual_return_pct = float(actual.get("return_pct", 0.0))
        stop_triggered = bool(actual.get("stop_triggered", False))

        direction_hit = (actual_direction.upper() == prediction.expected_direction.upper())
        target_hit = (actual_return_pct >= prediction.target_return_pct)
        magnitude_error = (
            abs(actual_return_pct - prediction.target_return_pct)
            / max(abs(prediction.target_return_pct), 0.01)
        )

        return PredictionError(
            direction_hit=direction_hit,
            target_hit=target_hit,
            stop_triggered=stop_triggered,
            magnitude_error=round(magnitude_error, 4),
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _vol_to_horizon(self, volatility: float) -> int:
        for threshold, horizon in self._HORIZON_MAP:
            if volatility < threshold:
                return horizon
        return 6
