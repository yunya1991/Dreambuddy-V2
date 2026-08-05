#!/usr/bin/env python3
"""
prediction_bridge — P2-9 事前预测桥接层

将 4-MEMORY 的 PredictionEngine 暴露给 11-易经推理系统使用，
避免 11→4 包级反向依赖（与 ab_bridge 模式一致）。
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# 注入 4-MEMORY/9-工具与接口 到 sys.path
# __file__ = 11-易经推理系统/scripts/memory_l4/prediction_bridge.py
# parents[3] = 项目根 dreambuddy-v2/
_MEM_TOOLS = Path(__file__).resolve().parents[3] / "4-MEMORY" / "9-工具与接口"
if str(_MEM_TOOLS) not in sys.path:
    sys.path.insert(0, str(_MEM_TOOLS))


def generate_prediction_dict(inference: Dict) -> Optional[Dict[str, Any]]:
    """从 inference 生成预测 dict（失败返回 None）"""
    try:
        from prediction_engine import PredictionEngine
        engine = PredictionEngine()
        pred = engine.generate_prediction(inference)
        return {
            "expected_direction": pred.expected_direction,
            "expected_horizon_bars": pred.expected_horizon_bars,
            "stop_loss_prob": pred.stop_loss_prob,
            "target_return_pct": pred.target_return_pct,
            "prediction_confidence": pred.prediction_confidence,
            "generated_at": pred.generated_at,
        }
    except Exception:
        return None


def compute_prediction_error_dict(prediction_dict: Dict, actual: Dict) -> Optional[Dict[str, Any]]:
    """从 prediction dict + actual 计算误差 dict（失败返回 None）"""
    if not prediction_dict:
        return None
    try:
        from prediction_engine import Prediction, PredictionEngine
        pred = Prediction(
            expected_direction=prediction_dict.get("expected_direction", "HOLD"),
            expected_horizon_bars=prediction_dict.get("expected_horizon_bars", 0),
            stop_loss_prob=prediction_dict.get("stop_loss_prob", 0.0),
            target_return_pct=prediction_dict.get("target_return_pct", 0.0),
            prediction_confidence=prediction_dict.get("prediction_confidence", 0.0),
            generated_at=prediction_dict.get("generated_at", ""),
        )
        engine = PredictionEngine()
        err = engine.compute_error(pred, actual)
        return {
            "direction_hit": err.direction_hit,
            "target_hit": err.target_hit,
            "stop_triggered": err.stop_triggered,
            "magnitude_error": err.magnitude_error,
            "computed_at": err.computed_at,
        }
    except Exception:
        return None
