"""P1-B：VIX 三件套单一口径采集器（离线单测，不触网）。"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from data_center.collectors.chain import vix_collector as vc


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.ok = status_code == 200


# ── 解析 ────────────────────────────────────────────────────


def test_fred_csv_parsing_skips_missing(monkeypatch):
    csv = "observation_date,VIXCLS\n2026-11-06,25.64\n2026-11-09,.\n2026-11-10,19.46\n"
    monkeypatch.setattr(vc.requests, "get", lambda *a, **k: _FakeResp(csv))
    pairs = vc._fred_pairs("VIXCLS")
    assert pairs == [(date(2026, 11, 6), 25.64), (date(2026, 11, 10), 19.46)]


def test_cboe_csv_parsing_takes_close(monkeypatch):
    csv = "DATE,OPEN,HIGH,LOW,CLOSE\n09/18/2009,25.91,26.66,25.91,26.54\n"
    monkeypatch.setattr(vc.requests, "get", lambda *a, **k: _FakeResp(csv))
    assert vc._cboe_pairs("VIX3M") == [(date(2009, 9, 18), 26.54)]


def test_fetch_history_unknown_key_returns_empty():
    assert vc.fetch_history("put_call") == []


# ── 单一口径合并 ─────────────────────────────────────────────


def _series(vix_rows, vix3m_rows=None, vvix_rows=None):
    return {"vix": vix_rows, "vix3m": vix3m_rows or [], "vvix": vvix_rows or []}


def test_merge_keeps_fred_primary_and_computes_ratio(monkeypatch):
    series = _series(
        [{"date": "2026-11-09", "value": 20.0}, {"date": "2026-11-10", "value": 22.0}],
        [{"date": "2026-11-09", "value": 21.0}, {"date": "2026-11-10", "value": 20.0}],
        [{"date": "2026-11-10", "value": 95.0}],
    )
    monkeypatch.setattr(vc, "fetch_history", lambda key, days=400, timeout=30: series[key])
    monkeypatch.setattr(vc, "fetch_vix", lambda: {"value": 0, "source": "N/A"})

    rows = vc.merge_daily(days=30, live=False)
    assert [r["date"] for r in rows] == ["2026-11-09", "2026-11-10"]
    assert rows[-1]["vix"] == 22.0
    assert rows[-1]["vix3m"] == 20.0
    assert rows[-1]["vix_ratio"] == pytest.approx(1.1)
    assert rows[-1]["vvix"] == 95.0
    assert rows[-1]["source"] == "fred"


def test_merge_appends_yahoo_for_missing_today(monkeypatch):
    series = _series([{"date": "2026-11-09", "value": 20.0}])
    monkeypatch.setattr(vc, "fetch_history", lambda key, days=400, timeout=30: series[key])
    monkeypatch.setattr(vc, "fetch_vix", lambda: {"value": 23.5, "source": "Yahoo Finance"})

    warn: list[str] = []
    rows = vc.merge_daily(days=30, live=True, warn=warn)
    assert rows[-1]["source"] == "yahoo"
    assert rows[-1]["vix"] == 23.5
    assert rows[-1]["vix3m"] is None and rows[-1]["vix_ratio"] is None
    assert rows[-1]["date"] == datetime.now(timezone.utc).date().isoformat()
    assert any("Yahoo ^VIX 当日补充" in w for w in warn)


def test_merge_warns_and_prefers_fred_on_divergence(monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    series = _series([{"date": today, "value": 20.0}])
    monkeypatch.setattr(vc, "fetch_history", lambda key, days=400, timeout=30: series[key])
    monkeypatch.setattr(vc, "fetch_vix", lambda: {"value": 21.2, "source": "Yahoo Finance"})

    warn: list[str] = []
    rows = vc.merge_daily(days=30, live=True, warn=warn)
    assert rows[-1]["vix"] == 20.0
    assert rows[-1]["source"] == "fred"
    assert any("以 FRED 为准" in w for w in warn)


def test_put_call_stays_null_never_zero(monkeypatch):
    series = _series([{"date": "2026-11-10", "value": 20.0}])
    monkeypatch.setattr(vc, "fetch_history", lambda key, days=400, timeout=30: series[key])
    rows = vc.merge_daily(days=30, live=False)
    assert rows[0]["put_call_ratio"] is None


# ── Collector 契约 ──────────────────────────────────────────


def test_collector_omits_missing_fields_instead_of_zero(monkeypatch):
    monkeypatch.setattr(
        vc,
        "merge_daily",
        lambda **kwargs: [
            {
                "date": "2026-11-10",
                "vix": 19.46,
                "vix3m": None,
                "vix_ratio": None,
                "vvix": None,
                "put_call_ratio": None,
                "source": "fred",
            }
        ],
    )
    records = vc.VixCollector().fetch({"days": 30, "live": False})
    assert len(records) == 1
    metrics = records[0].metrics
    assert metrics["vix"] == 19.46
    assert "vix3m" not in metrics and "vvix" not in metrics and "put_call_ratio" not in metrics
    assert metrics["source"] == "fred"
    assert records[0].timestamp.startswith("2026-11-10T00:00:00")


# ── 单一实现（SPEC §5.2.1 验收） ─────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKIP_PARTS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "site-packages",
}
_DEF_VIX = re.compile(r"^\s*def\s+\w*vix\w*\s*\(", re.MULTILINE)


def _is_production_py(path: Path) -> bool:
    if any(part in _SKIP_PARTS for part in path.parts):
        return False
    if "tests" in path.parts or path.name.startswith("test_"):
        return False
    return True


def test_only_one_vix_implementation_in_production_code():
    hits = []
    for path in _REPO_ROOT.rglob("*.py"):
        if path.is_symlink() or not _is_production_py(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _DEF_VIX.search(text):
            hits.append(path)
    assert [p.name for p in hits] == ["vix_collector.py"], hits
