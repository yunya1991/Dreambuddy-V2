"""CoinScanner allow 白名单测试（动态币池依赖）。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.adapters.coin_scanner import CoinScanner  # noqa: E402


def _scanner(tickers):
    s = CoinScanner(object())
    s._get_all_swap_tickers = lambda: list(tickers)
    s._calc_signal = lambda inst, sym: (0.5, {"momentum": 0.5})
    s._calc_confidence = lambda m: 0.6
    s._confidence_to_position = lambda c: 0.5
    return s


def test_scan_allow_filters_to_whitelist():
    s = _scanner(
        [
            {"inst_id": "BTC-USDT-SWAP", "vol24h_usd": 1e9},
            {"inst_id": "PEPE-USDT-SWAP", "vol24h_usd": 1e9},
        ]
    )
    out = s.scan(top_n=5, force=True, allow={"BTC"})
    assert [r["symbol"] for r in out] == ["BTC"]


def test_scan_without_allow_returns_all_liquid():
    s = _scanner(
        [
            {"inst_id": "BTC-USDT-SWAP", "vol24h_usd": 1e9},
            {"inst_id": "PEPE-USDT-SWAP", "vol24h_usd": 1e9},
        ]
    )
    out = s.scan(top_n=5, force=True)
    assert {r["symbol"] for r in out} == {"BTC", "PEPE"}


def test_scan_allow_empty_set_returns_nothing():
    s = _scanner([{"inst_id": "BTC-USDT-SWAP", "vol24h_usd": 1e9}])
    assert s.scan(top_n=5, force=True, allow=set()) == []
