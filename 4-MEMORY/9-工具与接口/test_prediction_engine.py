#!/usr/bin/env python3
"""PredictionEngine 单测（P2-9 事前预测）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from prediction_engine import PredictionEngine, Prediction, PredictionError


def test_generate_prediction_fields():
    """生成预测含完整字段"""
    engine = PredictionEngine()
    inf = {
        "direction": "LONG",
        "confidence": 0.72,
        "volatility": 0.03,
        "a0_warnings": ["c1", "c2"],
    }
    pred = engine.generate_prediction(inf)
    assert pred.expected_direction == "LONG"
    assert pred.expected_horizon_bars == 24  # vol 0.03 < 0.05 → 24
    assert 0.0 <= pred.stop_loss_prob <= 0.8
    assert pred.target_return_pct > 0
    assert 0.1 <= pred.prediction_confidence <= 0.95
    assert pred.generated_at  # 非空


def test_vol_to_horizon_high_vol():
    """高波动→短周期"""
    engine = PredictionEngine()
    assert engine._vol_to_horizon(0.15) == 6   # >0.10 → 6
    assert engine._vol_to_horizon(0.08) == 12  # 0.05-0.10 → 12
    assert engine._vol_to_horizon(0.03) == 24  # 0.02-0.05 → 24
    assert engine._vol_to_horizon(0.01) == 48  # <0.02 → 48


def test_compute_error_direction_hit():
    """方向命中"""
    engine = PredictionEngine()
    pred = Prediction(
        expected_direction="LONG", expected_horizon_bars=24,
        stop_loss_prob=0.3, target_return_pct=3.5,
        prediction_confidence=0.72, generated_at="2026-08-05T00:00:00Z",
    )
    actual = {"direction": "long", "return_pct": 4.0, "stop_triggered": False}
    err = engine.compute_error(pred, actual)
    assert err.direction_hit is True
    assert err.target_hit is True  # 4.0 >= 3.5
    assert err.stop_triggered is False
    assert err.magnitude_error >= 0


def test_compute_error_direction_miss():
    """方向未命中"""
    engine = PredictionEngine()
    pred = Prediction(
        expected_direction="LONG", expected_horizon_bars=24,
        stop_loss_prob=0.3, target_return_pct=3.5,
        prediction_confidence=0.72, generated_at="2026-08-05T00:00:00Z",
    )
    actual = {"direction": "SHORT", "return_pct": -2.0, "stop_triggered": True}
    err = engine.compute_error(pred, actual)
    assert err.direction_hit is False
    assert err.target_hit is False
    assert err.stop_triggered is True


def test_generate_prediction_missing_fields():
    """inference 缺字段时返回默认 Prediction（不抛异常，confidence 默认 0.5 中性）"""
    engine = PredictionEngine()
    pred = engine.generate_prediction({})
    assert pred.expected_direction == "HOLD"
    assert pred.prediction_confidence == 0.5  # 缺 confidence → 默认 0.5（中性无信息）


def test_stop_loss_prob_capped():
    """止损概率上限 0.8"""
    engine = PredictionEngine()
    inf = {"direction": "LONG", "confidence": 0.9, "volatility": 0.5, "a0_warnings": ["c"]*10}
    pred = engine.generate_prediction(inf)
    assert pred.stop_loss_prob <= 0.8


if __name__ == "__main__":
    for fn in [
        test_generate_prediction_fields,
        test_vol_to_horizon_high_vol,
        test_compute_error_direction_hit,
        test_compute_error_direction_miss,
        test_generate_prediction_missing_fields,
        test_stop_loss_prob_capped,
    ]:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            print(f"❌ {fn.__name__}: {e}")
            raise
