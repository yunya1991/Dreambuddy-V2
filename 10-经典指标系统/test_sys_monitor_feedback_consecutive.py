import ml_trade_service as m


def test_sys_monitor_feedback_requires_consecutive_hits(monkeypatch):
    m.TRACKER_STATE.clear()
    m.AUTOMATION["sys_monitor_feedback_poll_interval_sec"] = 300
    m.AUTOMATION["sys_monitor_feedback_consecutive_n"] = 3
    m.AUTOMATION["sys_monitor_feedback_min_samples"] = 10**9

    now_ms = 1_700_000_000_000

    def fake_route_json(_fn, path: str):
        if path.startswith("/signals/recent"):
            return {"ok": True, "items": []}
        if path.startswith("/orders/recent"):
            return {"ok": True, "orders": []}
        if path.startswith("/signals/reject_stats"):
            return {"ok": True, "by_reason": {"bar_not_closed": 100}}
        if path.startswith("/gating/state"):
            return {"ok": True}
        if path.startswith("/universe/status"):
            return {"core": [], "shadow": [], "watchlist": [], "last_update": int(now_ms - 2 * 3600 * 1000)}
        if path.startswith("/quant/pairs/btcalt/candidates"):
            return {"ok": True, "alts": []}
        if path.startswith("/quant/pairs/btcalt/orders/recent"):
            return {"ok": True, "orders": []}
        if path.startswith("/quant/pairs/btceth/orders/recent"):
            return {"ok": True, "orders": []}
        if path.startswith("/three_screen/weekly/status"):
            return {"ok": True}
        if path.startswith("/three_screen/daily/signal"):
            return {"ok": True}
        if path.startswith("/three_screen/5m/signal"):
            return {"ok": True}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(m, "_sys_monitor_route_json", fake_route_json)
    monkeypatch.setattr(m, "_agent_emit_envelope_event", lambda **kwargs: None)

    rep1 = m._sys_monitor_feedback_5m_poll_run(now_ms)
    assert rep1["triggered"] is False
    assert rep1["hits"] == []

    rep2 = m._sys_monitor_feedback_5m_poll_run(now_ms + 300_000)
    assert rep2["triggered"] is False
    assert rep2["hits"] == []

    rep3 = m._sys_monitor_feedback_5m_poll_run(now_ms + 600_000)
    assert rep3["triggered"] is True
    assert any(x.get("id") == "universe_pool_core_empty" for x in rep3["hits"])
