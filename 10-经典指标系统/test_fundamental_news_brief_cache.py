import builtins
from pathlib import Path

import ml_trade_service as svc


def test_fundamental_news_brief_latest_uses_http_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(svc, "BRIEF_V3_TITLE", "# T")
    monkeypatch.setattr(svc, "BRIEF_V3_REQUIRED_HEADINGS", [])

    brief = tmp_path / "brief.md"
    brief.write_text("# T\n\n**生成时间**: 2026-04-08 00:00 UTC\n\nok\n", encoding="utf-8")

    coverage = tmp_path / "coverage.json"
    coverage.write_text('{"ok": true}', encoding="utf-8")

    risk = tmp_path / "risk.json"
    risk.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(svc, "_fundamental_news_pick_file", lambda name="": brief)
    monkeypatch.setattr(svc, "_fundamental_news_pick_coverage_report_file", lambda name="": coverage)
    monkeypatch.setattr(svc, "_fundamental_news_pick_risk_events_file", lambda name="": risk)

    client = svc.app.test_client()
    r1 = client.get("/fundamental/news/brief/latest?max_chars=4000")
    assert r1.status_code == 200
    body1 = r1.get_json(force=True)
    assert body1["ok"] is True
    assert body1["name"] == "brief.md"

    def _boom(*args, **kwargs):
        raise AssertionError("unexpected disk read after caching")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(svc, "_fundamental_news_pick_file", lambda name="": (_boom()))
    monkeypatch.setattr(svc, "_fundamental_news_pick_coverage_report_file", lambda name="": (_boom()))
    monkeypatch.setattr(svc, "_fundamental_news_pick_risk_events_file", lambda name="": (_boom()))

    r2 = client.get("/fundamental/news/brief/latest?max_chars=4000")
    assert r2.status_code == 200
    body2 = r2.get_json(force=True)
    assert body2["ok"] is True
    assert body2["name"] == "brief.md"
