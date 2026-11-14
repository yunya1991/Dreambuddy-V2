"""P3：23 独立 exit runner 测试（不依赖 11、不触网）。"""

from __future__ import annotations

from types import SimpleNamespace

from dreambuddy_evolution.scripts.exit_runner import (
    build_ctx,
    collect_positions,
    run_once,
    tag_matches,
)


class _Okx:
    def get_ticker(self, inst_id=None):
        return {"ok": True, "last": 110.0}

    def get_kline(self, inst_id=None, bar="1H", limit=100):
        candles = []
        for i in range(60):
            _p = 100.0 + (i % 5)
            candles.append({"o": _p, "h": _p + 2, "l": _p - 2, "c": _p, "vol": 1})
        return {"ok": True, "candles": list(reversed(candles))}

    def get_algo_orders(self, inst_id=None):
        return {
            "ok": True,
            "orders": [
                {"sl_trigger_px": 95.0, "tp_trigger_px": 130.0, "state": "live"},
            ],
        }

    def get_positions(self, inst_id=None):
        return {"ok": True, "positions": [{"pos": 5, "avg_px": 100.0, "pos_side": "long"}]}


class _Gateway:
    def __init__(self, rows):
        self.rows = rows

    def list_positions(self):
        return self.rows


class _Loop:
    def __init__(self):
        self.seen = []
        self.ctx = {}

    def run(self, positions, enricher=None, on_closed=None, on_ghost=None):
        self.seen = positions
        if positions and enricher:
            self.ctx = enricher(positions[0], {"ess": 0.6})
        return {
            "checked": len(positions),
            "hold": len(positions),
            "executed": [],
            "failed": [],
            "skipped": 0,
        }


def test_tag_matches_prefix():
    assert tag_matches("23-evolution", ("evolution", "23-evolution"))
    assert tag_matches("evolution-v2", ("evolution",))
    assert not tag_matches("nn-yijing", ("23", "evolution"))
    assert not tag_matches("", ("23",))


def test_collect_positions_filters_by_source_tag():
    gw = _Gateway(
        [
            {
                "inst_id": "ETH-USDT-SWAP",
                "pos_side": "long",
                "qty": 3,
                "avg_entry": 100,
                "source": "23-evolution",
            },
            {
                "inst_id": "BTC-USDT-SWAP",
                "pos_side": "long",
                "qty": 1,
                "avg_entry": 50000,
                "source": "11-yijing",
            },
        ]
    )
    out = collect_positions(gw, _Okx(), [], ("23-evolution",))
    assert [p["inst_id"] for p in out] == ["ETH-USDT-SWAP"]


def test_collect_positions_symbols_fallback_to_exchange():
    gw = _Gateway([])
    out = collect_positions(gw, _Okx(), ["SOL-USDT-SWAP"], ("23-evolution",))
    assert out[0]["inst_id"] == "SOL-USDT-SWAP"
    assert out[0]["position_qty"] == 5.0
    assert out[0]["source_tag"] == "exchange"


def test_build_ctx_uses_exchange_truth():
    pos = {
        "inst_id": "ETH-USDT-SWAP",
        "pos_side": "long",
        "entry_price": 100.0,
        "position_qty": 2.0,
    }
    ctx = build_ctx(pos, _Okx())

    assert ctx["current_price"] == 110.0
    assert ctx["current_sl_px"] == 95.0
    assert ctx["current_tp_px"] == 130.0
    assert ctx["atr_pct"] > 0
    assert 0.09 < ctx["upl_ratio"] < 0.11
    assert ctx["position_usdt"] == 220.0


def test_run_once_returns_when_no_positions():
    loop = _Loop()
    rep = run_once(loop, _Gateway([]), _Okx(), SimpleNamespace(symbols=[], tags=["23"]))
    assert rep["checked"] == 0
    assert loop.seen == []


def test_run_once_passes_enriched_ctx():
    loop = _Loop()
    gw = _Gateway(
        [
            {
                "inst_id": "ETH-USDT-SWAP",
                "pos_side": "long",
                "qty": 2,
                "avg_entry": 100,
                "source": "23-evolution",
            }
        ]
    )
    args = SimpleNamespace(symbols=[], tags=["23-evolution"])
    rep = run_once(loop, gw, _Okx(), args)

    assert rep["checked"] == 1
    assert loop.seen[0]["inst_id"] == "ETH-USDT-SWAP"
    assert loop.ctx["current_sl_px"] == 95.0
    assert loop.ctx["ess"] == 0.6
