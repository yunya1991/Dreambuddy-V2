#!/usr/bin/env python3
"""polling_trader P2-9 集成测试：开仓事件含 prediction 字段"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.prediction_bridge import generate_prediction_dict


def test_prediction_dict_has_fields():
    """bridge 生成 prediction dict 含完整字段"""
    inf = {"direction": "LONG", "confidence": 0.7, "volatility": 0.03, "a0_warnings": []}
    pred = generate_prediction_dict(inf)
    assert pred is not None
    assert pred["expected_direction"] == "LONG"
    assert "generated_at" in pred


def test_prediction_dict_failure_returns_none():
    """bridge 异常时返回 None"""
    pred = generate_prediction_dict(None)  # None 输入，None.get 会抛异常，bridge 捕获返回 None
    assert pred is None


if __name__ == "__main__":
    test_prediction_dict_has_fields()
    test_prediction_dict_failure_returns_none()
    print("✅ prediction_bridge 测试通过")
