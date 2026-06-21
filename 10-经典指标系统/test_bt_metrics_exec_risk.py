import ml_trade_service as svc


def test_bt_metrics_slim_derives_stoploss_and_exec_risk_rates():
    row = {
        "trades": 10,
        "exit_reason_summary": [{"key": "stoploss", "trades": 2}],
        "canceled_entry_orders": 1,
        "replaced_entry_orders": 1,
        "timedout_entry_orders": 0,
        "timedout_exit_orders": 0,
    }
    out = svc._bt_metrics_slim(row) or {}
    assert int(out.get("stoploss_trades") or 0) == 2
    assert abs(float(out.get("stoploss_hit_rate") or 0.0) - 0.2) < 1e-9
    assert int(out.get("fat_finger_count") or 0) == 2
    assert abs(float(out.get("fat_finger_rate") or 0.0) - 0.2) < 1e-9
    assert int(out.get("exec_risk_trigger_count") or 0) == 2
    assert abs(float(out.get("exec_risk_trigger_rate") or 0.0) - 0.2) < 1e-9
