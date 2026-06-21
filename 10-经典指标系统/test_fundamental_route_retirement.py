import ml_trade_service as svc


def test_non_news_fundamental_routes_are_retired():
    client = svc.app.test_client()
    cases = [
        ("get", "/fundamental/overview/latest"),
        ("get", "/fundamental/flows/brief/latest"),
        ("get", "/fundamental/flows/automation"),
        ("post", "/fundamental/flows/automation/run"),
        ("get", "/fundamental/narrative/brief/latest"),
        ("post", "/fundamental/narrative/automation/run"),
        ("get", "/fundamental/trading/latest"),
        ("post", "/fundamental/trading/automation/config"),
    ]
    for method, path in cases:
        if method == "post":
            resp = client.post(path, json={})
        else:
            resp = client.get(path)
        assert resp.status_code == 410
        body = resp.get_json(force=True)
        assert body["ok"] is False
        assert body["error"] == "module_retired"


def test_news_routes_remain_available():
    client = svc.app.test_client()
    resp = client.get("/fundamental/news/automation")
    assert resp.status_code == 200
    body = resp.get_json(force=True)
    assert body["ok"] is True


def test_non_news_fundamental_handlers_keep_retired_shell():
    retained_handler_names = [
        "fundamental_flows_brief_latest",
        "fundamental_flows_regime_latest",
        "fundamental_narrative_brief_latest",
        "fundamental_narrative_registry_latest",
        "fundamental_narrative_history",
        "fundamental_narrative_automation_get",
        "fundamental_narrative_automation_config",
        "fundamental_narrative_automation_run",
        "fundamental_trading_latest",
        "fundamental_trading_automation_get",
        "fundamental_trading_automation_config",
        "fundamental_trading_automation_run",
        "fundamental_overview_latest",
    ]
    for name in retained_handler_names:
        assert hasattr(svc, name), name
