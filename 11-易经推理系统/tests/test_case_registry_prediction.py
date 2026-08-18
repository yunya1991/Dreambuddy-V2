#!/usr/bin/env python3
"""case_registry P2-9 集成测试：PREDICTION stage + EXIT prediction_error"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.trade_event import TradeEvent
from scripts.memory_l4.case_registry import UnifiedCaseRegistry


def _make_registry():
    """构造不依赖 __init__ 的 registry 实例（_build_thinking_chain 不需 cases_dir）"""
    return UnifiedCaseRegistry.__new__(UnifiedCaseRegistry)


def test_prediction_stage_added_when_prediction_present():
    """decision_context 含 prediction → thinking_chain 含 PREDICTION stage"""
    registry = _make_registry()
    event = TradeEvent(
        event_id="evt_test_1",
        system_source="yijing_inference",
        trade_id="t1",
        ts_entry="2026-08-05T00:00:00Z",
        symbol="BTC-USDT-SWAP",
        direction="LONG",
        entry_price=50000.0,
        decision_context={
            "hexagram": "乾",
            "confidence": 0.7,
            "prediction": {
                "expected_direction": "LONG",
                "expected_horizon_bars": 24,
                "stop_loss_prob": 0.3,
                "target_return_pct": 3.5,
                "prediction_confidence": 0.7,
                "generated_at": "2026-08-05T00:00:00Z",
            },
        },
    )
    chain = registry._build_thinking_chain(event)
    stages = [s.get("stage") for s in chain]
    assert "PREDICTION" in stages, f"PREDICTION stage missing, got {stages}"
    pred_stage = next(s for s in chain if s.get("stage") == "PREDICTION")
    assert pred_stage.get("prediction_snapshot", {}).get("expected_direction") == "LONG"


def test_no_prediction_stage_when_absent():
    """decision_context 无 prediction → thinking_chain 不含 PREDICTION stage"""
    registry = _make_registry()
    event = TradeEvent(
        event_id="evt_test_2",
        system_source="yijing_inference",
        trade_id="t2",
        ts_entry="2026-08-05T00:00:00Z",
        symbol="BTC-USDT-SWAP",
        direction="LONG",
        entry_price=50000.0,
        decision_context={"hexagram": "坤", "confidence": 0.5},
    )
    chain = registry._build_thinking_chain(event)
    stages = [s.get("stage") for s in chain]
    assert "PREDICTION" not in stages, f"PREDICTION should not exist, got {stages}"


def test_exit_prediction_error_computed():
    """case 含 PREDICTION stage 时，update_case_on_exit 计算 prediction_error"""
    registry = _make_registry()
    # 构造一个含 PREDICTION stage 的 case
    case = {
        "case_id": "tc_test_3",
        "direction": "LONG",
        "symbol": "BTC-USDT-SWAP",
        "thinking_chain": [
            {"stage": "A0", "ts": "2026-08-05T00:00:00Z", "decision_context": {}},
            {
                "stage": "PREDICTION",
                "ts": "2026-08-05T00:00:00Z",
                "prediction_snapshot": {
                    "expected_direction": "LONG",
                    "expected_horizon_bars": 24,
                    "stop_loss_prob": 0.3,
                    "target_return_pct": 3.5,
                    "prediction_confidence": 0.7,
                    "generated_at": "2026-08-05T00:00:00Z",
                },
            },
        ],
    }
    # 模拟 update_case_on_exit 的 prediction_error 计算逻辑
    # （直接调 update_case_on_exit 需要 cases_dir，这里测核心逻辑）
    chain = case.get("thinking_chain", [])
    direction = case.get("direction", "UNKNOWN")
    pnl_pct = 4.0
    exit_reason = "target_hit"

    prediction_snapshot = None
    for stage in chain:
        if stage.get("stage") == "PREDICTION":
            prediction_snapshot = stage.get("prediction_snapshot")
            break
    assert prediction_snapshot is not None

    from scripts.memory_l4.prediction_bridge import compute_prediction_error_dict
    actual = {
        "direction": direction,
        "return_pct": pnl_pct,
        "stop_triggered": exit_reason == "stop_loss",
    }
    err = compute_prediction_error_dict(prediction_snapshot, actual)
    assert err is not None
    assert err["direction_hit"] is True   # LONG == LONG
    assert err["target_hit"] is True      # 4.0 >= 3.5
    assert err["stop_triggered"] is False


if __name__ == "__main__":
    test_prediction_stage_added_when_prediction_present()
    test_no_prediction_stage_when_absent()
    test_exit_prediction_error_computed()
    print("✅ case_registry prediction 测试通过")
