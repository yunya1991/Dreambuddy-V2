from ops.nanoclaw.core_task1.narrative.scripts.narrative_analyzer import Narrative, NarrativeAnalyzer


def test_contract_includes_market_intel_focus_and_evidence(monkeypatch) -> None:
    a = NarrativeAnalyzer(hours=24)
    monkeypatch.setattr(a, "_load_flow_skill_snapshot_latest", lambda: {"items": []})
    monkeypatch.setattr(a, "_load_okx_market_intel_latest", lambda: {
        "quality": {"status": "ok"},
        "generated_at": "2026-04-08T00:00:00Z",
        "topics": [
            {"title": "ETF flow narrative", "heat": 0.9, "sentiment": 0.2, "url": "https://example.com/1", "ts": "2026-04-08T00:00:00Z"},
            {"title": "Regulation watch", "heat": 0.7, "sentiment": -0.1, "url": "https://example.com/2", "ts": "2026-04-08T00:00:00Z"},
        ],
    })
    contract, ext = a._build_structured_payload(
        events=[{"title": "macro", "summary": "", "timestamp": "2026-04-08T00:00:00Z"}],
        narratives=[
            Narrative(
                narrative_id="macro_finance_1",
                narrative_name="宏观金融",
                category="macro_finance",
                status="active",
                heat_score=0.6,
                sentiment_score=0.0,
                sentiment_trend="stable",
                related_tokens=["BTC"],
                event_count=1,
                lifecycle_stage="emerging",
                confidence=0.6,
                created_at="2026-04-08T00:00:00Z",
                updated_at="2026-04-08T00:00:00Z",
            )
        ],
        overall_sentiment=0.0,
        overall_heat=0.6,
        generated_at="2026-04-08T00:00:00Z",
    )
    assert isinstance(contract.get("market_focus"), list)
    assert len(contract.get("market_focus") or []) >= 1
    ev = contract.get("evidence_refs") or []
    assert any(isinstance(x, dict) and str(x.get("source") or "").startswith("okx:market-intel") for x in ev)
    assert isinstance(ext.get("okx_market_intel"), dict)
