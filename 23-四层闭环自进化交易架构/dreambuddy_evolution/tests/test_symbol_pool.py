"""23 动态币池（symbol_pool）测试。

覆盖动态扫描/兜底/上限/失败降级，确保 23 全量开池不会因扫描异常或未注册标的失控。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.scripts.symbol_pool import (  # noqa: E402
    SNAPSHOT_ANCHORS,
    DynamicSymbolProvider,
    load_universe,
)

_UNIVERSE = {"BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "BNB": "crypto", "XAU": "metal"}


class _Scanner:
    def __init__(self, rows=None, exc: Exception | None = None):
        self.rows = rows or []
        self.exc = exc
        self.calls = []

    def scan(self, top_n=20, force=False, allow=None):
        self.calls.append({"top_n": top_n, "allow": allow})
        if self.exc:
            raise self.exc
        return list(self.rows)


def _provider(scanner, universe=None, **kw):
    return DynamicSymbolProvider(scanner, universe_fn=lambda: dict(universe or _UNIVERSE), **kw)


def test_dynamic_scan_filters_unregistered_and_respects_max_pool():
    scanner = _Scanner(
        [
            {"symbol": "BTC-USDT-SWAP"},
            {"symbol": "PEPE-USDT-SWAP"},  # 未注册
            {"symbol": "ETH-USDT-SWAP"},
            {"symbol": "SOL-USDT-SWAP"},
        ]
    )
    p = _provider(scanner, scan_top=3, max_pool=2)
    out = p.get()
    assert out == ["BTC", "ETH"]
    assert p.last_source == "scan"
    assert scanner.calls[0]["allow"] == set(_UNIVERSE)


def test_scan_exception_falls_back_to_baseline_within_universe():
    p = _provider(_Scanner(exc=RuntimeError("okx timeout")), max_pool=11)
    out = p.get()
    assert out and all(s in _UNIVERSE for s in out)
    assert "BTC" in out and "XAU" in out
    assert p.last_source == "fallback"


def test_empty_scan_result_falls_back_to_baseline():
    p = _provider(_Scanner(rows=[]))
    out = p.get()
    assert out == [s for s in SNAPSHOT_ANCHORS if s in _UNIVERSE]


def test_previous_good_pool_used_when_next_scan_fails():
    ok = _provider(_Scanner(rows=[{"symbol": "BNB-USDT-SWAP"}]), max_pool=3)
    assert ok.get() == ["BNB"]

    scanner = _Scanner(rows=[{"symbol": "BNB-USDT-SWAP"}])
    p = _provider(scanner, max_pool=3)
    p.get()
    scanner.exc = RuntimeError("boom")
    assert p.get() == ["BNB"]
    assert p.last_source == "cache"


def test_empty_universe_skips_scan_and_keeps_baseline():
    scanner = _Scanner(rows=[{"symbol": "BTC-USDT-SWAP"}])
    p = DynamicSymbolProvider(scanner, max_pool=len(SNAPSHOT_ANCHORS), universe_fn=dict)
    out = p.get()
    assert scanner.calls == []
    assert out == list(SNAPSHOT_ANCHORS)


def test_load_universe_includes_exclusive_anchors(tmp_path, monkeypatch):
    import json

    import dreambuddy_evolution.scripts.symbol_pool as sp

    data = {
        "symbols": {
            "BNB": {"inst_id": "BNB-USDT-SWAP", "asset_class": "crypto"},
            "XAU": {"inst_id": "XAU-USDT-SWAP", "asset_class": "metal"},
        }
    }
    f = tmp_path / "live_symbols.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(sp, "_LIVE_SYMBOLS_PATH", f)
    monkeypatch.setattr(sp, "_UNIVERSE_CACHE", None)
    monkeypatch.setattr(sp, "_UNIVERSE_MTIME", -1.0)

    u = load_universe()
    assert u["BNB"] == "crypto" and u["XAU"] == "metal"
    assert {"BTC", "ETH", "SOL"} <= set(u)


def test_load_universe_filters_symbols_without_23_rights(tmp_path, monkeypatch):
    """19:54 线上事故：CVX 属 50 单出口，进 23 池必被 single_outlet_denied。"""
    import json

    import dreambuddy_evolution.scripts.symbol_pool as sp

    live = {
        "symbols": {
            "BTC": {"inst_id": "BTC-USDT-SWAP", "asset_class": "crypto"},
            "CVX": {"inst_id": "CVX-USDT-SWAP", "asset_class": "crypto"},
            "AVAX": {"inst_id": "AVAX-USDT-SWAP", "asset_class": "crypto"},
        }
    }
    rights = {
        "symbols": {
            "BTC-USDT-SWAP": {"outcome": "live:23-gateway"},
            "CVX-USDT-SWAP": {"outcome": "live:50-bypass"},
            "AVAX-USDT-SWAP": {
                "outcome": "live:50-bypass",
                "shared_outcomes": {"23-evolution": "live:23-gateway"},
            },
        }
    }
    lf = tmp_path / "live_symbols.json"
    rf = tmp_path / "execution_rights.json"
    lf.write_text(json.dumps(live), encoding="utf-8")
    rf.write_text(json.dumps(rights), encoding="utf-8")
    monkeypatch.setattr(sp, "_LIVE_SYMBOLS_PATH", lf)
    monkeypatch.setattr(sp, "_RIGHTS_PATH", rf)
    monkeypatch.setattr(sp, "_UNIVERSE_CACHE", None)
    monkeypatch.setattr(sp, "_UNIVERSE_MTIME", -1.0)
    monkeypatch.setattr(sp, "_RIGHTS_CACHE", None)
    monkeypatch.setattr(sp, "_RIGHTS_MTIME", -1.0)

    u = load_universe()
    assert "CVX" not in u
    assert "BTC" in u and "AVAX" in u
