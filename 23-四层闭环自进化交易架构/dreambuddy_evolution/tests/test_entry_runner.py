"""23 独立开仓 runner 测试（不依赖 11、不触网）。"""

from __future__ import annotations

from dreambuddy_evolution.scripts.entry_runner import (
    DataCenterMarketClient,
    EntryRunner,
    _authority,
)


# ── 18 行情源包装 ─────────────────────────────────────────────────────
def test_to_ccxt_symbol_accepts_okx_inst():
    assert DataCenterMarketClient.to_ccxt_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"
    assert DataCenterMarketClient.to_ccxt_symbol("eth") == "ETH/USDT:USDT"


def test_get_kline_converts_ascending_to_okx_descending():
    _asc = [
        {"ts": 1, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "vol": 10.0},
        {"ts": 2, "o": 1.5, "h": 2.5, "l": 1.0, "c": 2.0, "vol": 20.0},
    ]
    client = DataCenterMarketClient(candles_fn=lambda sym, bar, limit: _asc)
    out = client.get_kline("BTC-USDT-SWAP", bar="1H", limit=2)
    assert out["ok"] is True
    assert [c["ts"] for c in out["candles"]] == [2, 1]


def test_get_kline_empty_is_fail_open():
    client = DataCenterMarketClient(candles_fn=lambda sym, bar, limit: [])
    out = client.get_kline("BTC-USDT-SWAP")
    assert out["ok"] is False


def test_get_ticker_uses_latest_price():
    client = DataCenterMarketClient(ticker_fn=lambda sym: {"last": 123.0})
    out = client.get_ticker("BTC-USDT-SWAP")
    assert out["ok"] is True and out["last"] == 123.0


# ── 执行权闸门 ────────────────────────────────────────────────────────
def test_authority_blocks_all_in_dry_run():
    fn = _authority(True, ("23-evolution",))
    assert fn("23-evolution") is False


def test_authority_allows_only_whitelisted_tags_live():
    fn = _authority(False, ("23-evolution", "evolution"))
    assert fn("23-evolution") is True
    assert fn("evolution") is True
    assert fn("legacy-11") is False


def test_authority_respects_global_kill_switch(monkeypatch):
    monkeypatch.setenv("EVOLUTION_ENTRY23_ENABLED", "off")
    fn = _authority(False, ("23-evolution",))
    assert fn("23-evolution") is False


# ── runner 编排 ───────────────────────────────────────────────────────
class _Adapter:
    def __init__(self, n_bars: int = 30):
        self.n_bars = n_bars
        self.calls = []

    def assemble(self, symbol: str, inst_id: str):
        self.calls.append((symbol, inst_id))
        return {"close": [100.0] * self.n_bars, "top_ftc_track": "exploit"}


class _Handler:
    def __init__(self):
        self._build_position_callback = None
        self.seen = []

    def on_kline_close(self, kline_data, alpha=0.0, beta=0.0, gamma=0.0):
        self.seen.append(kline_data)
        return {"symbol": kline_data["symbol"], "action": "long", "ri": 0.8, "tier": "standard"}


class _Loop:
    def __init__(self):
        self.runs = []

    def run(self, **kwargs):
        self.runs.append(kwargs)
        return {"status": "opened", "symbol": kwargs.get("symbol")}


def _runner(adapter=None, handler=None, loop=None, symbols=("BTC",)):
    return EntryRunner(
        adapter=adapter or _Adapter(),
        handler=handler or _Handler(),
        loop=loop or _Loop(),
        symbols=list(symbols),
    )


def test_run_once_assembles_symbol_and_invokes_handler():
    adapter = _Adapter()
    handler = _Handler()
    runner = _runner(adapter=adapter, handler=handler)
    report = runner.run_once()
    assert adapter.calls == [("BTC", "BTC-USDT-SWAP")]
    assert handler.seen[0]["symbol"] == "BTC"
    assert report["signal"] == 1 and report["failed"] == 0


def test_run_once_skips_short_history():
    handler = _Handler()
    runner = _runner(adapter=_Adapter(n_bars=5), handler=handler)
    report = runner.run_once()
    assert handler.seen == []
    assert report["failed"] == 1


def test_on_signal_forwards_cached_kline_to_entry_loop():
    loop = _Loop()
    runner = _runner(loop=loop)
    runner._klines["BTC"] = {"symbol": "BTC", "close": [1.0, 2.0]}
    runner.on_signal(
        symbol="BTC-USDT-SWAP",
        action="long",
        u_open=0.8,
        d_star="long",
        confidence=0.7,
        tier="standard",
        source_tag="23-evolution",
        signal={"decision_id": "dec-1"},
    )
    run = loop.runs[0]
    assert run["symbol"] == "BTC"
    assert run["kline"]["close"] == [1.0, 2.0]
    assert run["signal"]["decision_id"] == "dec-1"
