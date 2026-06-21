import json
from pathlib import Path


def test_refresh_okx_market_intel_writes_output(tmp_path, monkeypatch) -> None:
    from ops.nanoclaw.core_task1.narrative.scripts import narrative_analyzer as na

    monkeypatch.setattr(na, "CORE_DIR", tmp_path)
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "okx" / "market-intel").mkdir(parents=True, exist_ok=True)

    def fake_collect(*, output_dir: Path, raw_dir: Path, asset: str, cmd=None):
        latest = Path(output_dir) / "okx_market_intel_latest.json"
        raw = Path(raw_dir) / "okx_market_intel_20260408_0000.json"
        obj = {"quality": {"status": "ok"}, "topics": [{"title": "ETF", "heat": 0.9, "sentiment": 0.1, "url": "x", "ts": "t"}]}
        latest.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        raw.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return latest, raw

    from ops.nanoclaw.core_task1.flow.scripts import okx_skill_collector as c
    monkeypatch.setattr(c, "collect_okx_market_intel_latest", fake_collect)

    analyzer = na.NarrativeAnalyzer(hours=24)
    latest_path = analyzer.refresh_okx_market_intel()
    assert latest_path.exists()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest.get("topics")
