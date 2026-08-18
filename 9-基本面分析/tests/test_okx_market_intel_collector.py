import json
from pathlib import Path
from types import SimpleNamespace


def test_collect_okx_market_intel_writes_latest_and_raw(tmp_path, monkeypatch) -> None:
    from ops.nanoclaw.core_task1.flow.scripts import okx_skill_collector as c

    out_dir = tmp_path / "outputs"
    raw_dir = tmp_path / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(c.shutil, "which", lambda name: "/usr/local/bin/okx" if name == "okx" else None)

    payload = {
        "quality": {"status": "ok"},
        "generated_at": "2026-04-08T00:00:00Z",
        "topics": [
            {"title": "ETF narrative", "heat": 0.9, "sentiment": 0.2, "url": "https://example.com/1", "ts": "2026-04-08T00:00:00Z"},
        ],
    }

    def fake_run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(c.subprocess, "run", fake_run)

    latest_path, raw_path = c.collect_okx_market_intel_latest(output_dir=out_dir, raw_dir=raw_dir, asset="BTC", cmd=["okx", "market-intel", "--json"])

    assert latest_path.exists()
    assert raw_path.exists()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert isinstance(latest.get("topics"), list) and len(latest.get("topics")) >= 1
    assert latest.get("quality", {}).get("status") in {"ok", "stale", "backfilled", "missing", "suspect"}


def test_okx_subprocess_env_injects_node_options_dns_patch(tmp_path, monkeypatch) -> None:
    from ops.nanoclaw.core_task1.flow.scripts import okx_skill_collector as c

    out_dir = tmp_path / "outputs"
    raw_dir = tmp_path / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(c.shutil, "which", lambda name: "/usr/local/bin/okx" if name == "okx" else None)

    seen = {}

    def fake_run(cmd, capture_output, text, timeout, check, env=None):  # noqa: ANN001
        seen["env"] = env or {}
        return SimpleNamespace(stdout=json.dumps({"topics": [{"title": "t", "heat": 0.5, "sentiment": 0.0}]}), stderr="", returncode=0)

    monkeypatch.setattr(c.subprocess, "run", fake_run)
    c.collect_okx_market_intel_latest(output_dir=out_dir, raw_dir=raw_dir, asset="BTC", cmd=["okx", "market", "ticker", "BTC-USDT", "--json"])
    node_opts = str(seen.get("env", {}).get("NODE_OPTIONS") or "")
    assert "--require" in node_opts
    assert "okx_dns_patch.cjs" in node_opts
