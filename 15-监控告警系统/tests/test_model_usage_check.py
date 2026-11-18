"""model_usage_check.py 单测：余额解析、消耗推算、阈值判定与凭证回退。"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/model_usage_check.py"
spec = importlib.util.spec_from_file_location("model_usage_check", SCRIPT)
mu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mu)

TZ = ZoneInfo("Asia/Shanghai")
PROVIDER = {
    "name": "deepseek",
    "type": "deepseek_balance",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "env_files": ["1-ARCHITECTURE/dreamos/.env", "11-易经推理系统/.env"],
    "thresholds": {
        "min_balance": 10.0,
        "warn_balance": 20.0,
        "min_days_remaining": 3.0,
        "burn_spike_ratio": 3.0,
        "min_baseline_days": 3,
    },
}


def snap(day: str, total: float, hour: int = 23, minute: int = 50) -> dict:
    return {
        "ts": f"{day}T{hour:02d}:{minute:02d}:00+08:00",
        "provider": "deepseek",
        "currency": "CNY",
        "total": total,
    }


def test_key_candidates_prefers_env_and_dedupes(tmp_path: Path, monkeypatch):
    env_dir = tmp_path / "1-ARCHITECTURE/dreamos"
    env_dir.mkdir(parents=True)
    (env_dir / ".env").write_text("DEEPSEEK_API_KEY=file-key\n", encoding="utf-8")
    second = tmp_path / "11-易经推理系统"
    second.mkdir(parents=True)
    (second / ".env").write_text("DEEPSEEK_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")

    candidates = mu.key_candidates(PROVIDER, tmp_path)
    assert candidates[0] == ("env-key", "env:DEEPSEEK_API_KEY")
    assert candidates[1] == ("file-key", "1-ARCHITECTURE/dreamos/.env")
    assert len(candidates) == 2


def test_fetch_deepseek_balance_picks_cny(monkeypatch):
    payload = {
        "is_available": True,
        "balance_infos": [
            {"currency": "USD", "total_balance": "1.00"},
            {
                "currency": "CNY",
                "total_balance": "72.98",
                "granted_balance": "0",
                "topped_up_balance": "72.98",
            },
        ],
    }

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(mu.urllib.request, "urlopen", lambda *a, **k: Resp())
    out = mu.fetch_deepseek_balance("https://api.deepseek.com", "k")
    assert out["currency"] == "CNY"
    assert out["total"] == 72.98
    assert out["topped_up"] == 72.98
    assert out["is_available"] is True


def test_collect_provider_falls_back_on_401(tmp_path: Path, monkeypatch):
    for rel in PROVIDER["env_files"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"DEEPSEEK_API_KEY=key-{p.parent.name}\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    calls: list[str] = []

    def fake_fetch(base_url, key, timeout=15):
        calls.append(key)
        if len(calls) == 1:
            raise urllib.error.HTTPError(base_url, 401, "Unauthorized", None, None)
        return {
            "is_available": True,
            "currency": "CNY",
            "total": 50.0,
            "granted": 0,
            "topped_up": 50.0,
        }

    monkeypatch.setattr(mu, "fetch_deepseek_balance", fake_fetch)
    balance, problem = mu.collect_provider(PROVIDER, tmp_path)
    assert problem is None
    assert balance["key_source"] == "11-易经推理系统/.env"
    assert len(calls) == 2


def test_collect_provider_all_keys_unauthorized(tmp_path: Path, monkeypatch):
    for rel in PROVIDER["env_files"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("DEEPSEEK_API_KEY=bad\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def fake_fetch(base_url, key, timeout=15):
        raise urllib.error.HTTPError(base_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(mu, "fetch_deepseek_balance", fake_fetch)
    balance, problem = mu.collect_provider(PROVIDER, tmp_path)
    assert balance is None
    assert problem["key"] == "deepseek_unavailable"
    assert problem["level"] == "P1"


def test_compute_usage_burn_and_days():
    now = datetime(2026, 11, 18, 9, 0, tzinfo=TZ)
    snaps = [
        snap("2026-11-15", 80.0),
        snap("2026-11-16", 78.0),
        snap("2026-11-17", 75.0),
        snap("2026-11-18", 74.5, hour=8, minute=50),
    ]
    usage = mu.compute_usage(snaps, now)
    assert usage["current"] == 74.5
    assert usage["burn_24h"] == 3.5
    assert usage["avg_daily_burn"] == 2.5
    assert usage["days_remaining"] == 29.8
    assert usage["baseline_days"] == 2
    assert usage["spike_ratio"] is None


def test_compute_usage_ignores_topup():
    now = datetime(2026, 11, 18, 9, 0, tzinfo=TZ)
    snaps = [
        snap("2026-11-16", 80.0),
        snap("2026-11-17", 95.0),
        snap("2026-11-18", 94.0, hour=8, minute=50),
    ]
    usage = mu.compute_usage(snaps, now)
    assert usage["burn_24h"] is None
    assert usage["baseline_days"] == 0
    assert usage["days_remaining"] is None


def test_evaluate_balance_low_is_p1():
    usage = {
        "current": 5.0,
        "currency": "CNY",
        "burn_24h": 1.0,
        "avg_daily_burn": 1.0,
        "days_remaining": 5.0,
    }
    findings = mu.evaluate(PROVIDER, usage, TZ)
    keys = {f["key"] for f in findings}
    assert "deepseek_balance_low" in keys
    assert findings[0]["level"] == "P1"


def test_evaluate_days_remaining_warns():
    usage = {
        "current": 30.0,
        "currency": "CNY",
        "burn_24h": 2.0,
        "avg_daily_burn": 12.0,
        "days_remaining": 2.5,
    }
    findings = mu.evaluate(PROVIDER, usage, TZ)
    assert [f["key"] for f in findings] == ["deepseek_days_remaining"]
    assert findings[0]["level"] == "P2"


def test_evaluate_burn_spike():
    usage = {
        "current": 60.0,
        "currency": "CNY",
        "burn_24h": 9.0,
        "avg_daily_burn": 2.0,
        "days_remaining": 30.0,
        "spike_ratio": 4.5,
        "baseline_days": 5,
    }
    findings = mu.evaluate(PROVIDER, usage, TZ)
    assert [f["key"] for f in findings] == ["deepseek_burn_spike"]


def test_snapshot_roundtrip(tmp_path: Path):
    balance = {
        "is_available": True,
        "currency": "CNY",
        "total": 72.98,
        "granted": 0.0,
        "topped_up": 72.98,
        "key_source": "env:DEEPSEEK_API_KEY",
    }
    mu.append_snapshot(tmp_path, "deepseek", balance, TZ)
    rows = mu.load_snapshots(tmp_path, "deepseek", 14)
    assert len(rows) == 1
    assert rows[0]["total"] == 72.98
    assert rows[0]["provider"] == "deepseek"
