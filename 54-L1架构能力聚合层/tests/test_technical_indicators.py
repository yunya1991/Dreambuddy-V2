# -*- coding: utf-8 -*-
"""D-B00–B07 技术指标批：K 线适配 + I 组方法 + 能力编排（RED 先行）。

口径来源：[docs/TECHNICAL_DESIGN.md §2.2](../docs/TECHNICAL_DESIGN.md)、
[docs/METHOD_LIBRARY.md §6/§12](../docs/METHOD_LIBRARY.md)：
- 意图 `technical_indicator` 数据前提 candles ≥120 根；
- 依赖 high/low 的方法（I12/I20–I23）在 `has_ohlc=False` 时必须显式
  `insufficient_history`，禁止用 close 伪造高低点；
- 所有指标为纯 stdlib、无网络、无写库。
"""

import math
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.candles import (  # noqa: E402
    CandleError,
    CandleSet,
    from_l0_envelope,
    load,
)
from l1agg.methods import run  # noqa: E402
from l1agg.technical import MIN_BARS, analyze  # noqa: E402

N = 130


def _trend(n=N, start=100.0, step=0.5):
    close = [start + step * i for i in range(n)]
    return {
        "close": close,
        "high": [c + 1.0 for c in close],
        "low": [c - 1.0 for c in close],
        "volume": [1000.0 + 10.0 * i for i in range(n)],
    }


def _flat(n=N, price=100.0):
    return {
        "close": [price] * n,
        "high": [price + 1.0] * n,
        "low": [price - 1.0] * n,
        "volume": [1000.0] * n,
    }


def _candleset(data, *, bar="1d", now_ts=None, keep_volume=True):
    ts = [1700000000 + 86400 * i for i in range(len(data["close"]))]
    points = [
        {
            "ts": t,
            "close": c,
            "high": data["high"][i],
            "low": data["low"][i],
            "volume": data["volume"][i] if keep_volume else None,
        }
        for i, (t, c) in enumerate(zip(ts, data["close"], strict=True))
    ]
    env = {
        "ok": True,
        "data": {"symbol": "BTC", "bar": bar, "points": points, "has_ohlc": True},
        "meta": {"quality": "good", "sample_n": len(points), "timezone": "UTC"},
    }
    return from_l0_envelope(env, now_ts=now_ts)


# ============================================================
# D-B00：K 线适配
# ============================================================


def test_candles_parse_l0_envelope_with_ohlc():
    cs = _candleset(_trend())
    assert isinstance(cs, CandleSet)
    assert cs.symbol == "BTC" and cs.bar == "1d"
    assert cs.sample_n == N
    assert cs.has_ohlc is True
    assert cs.high[0] == pytest.approx(101.0)
    assert cs.to_method_data()["low"][0] == pytest.approx(99.0)


def test_candles_close_only_is_not_ohlc():
    cs = from_l0_envelope(
        {
            "data": {
                "symbol": "BTC",
                "points": [{"ts": 1, "close": 100.0}, {"ts": 2, "close": 101.0}],
            }
        }
    )
    assert cs.sample_n == 2
    assert cs.has_ohlc is False
    assert cs.high == ()


def test_candles_malformed_envelope_rejected():
    with pytest.raises(CandleError):
        from_l0_envelope({"meta": {"sample_n": 0}})


def test_candles_stale_flag():
    now = 1700000000 + 86400 * (N - 1) + 86400 * 5
    cs = _candleset(_trend(), now_ts=now)
    assert cs.is_stale is True
    assert cs.stale_days == 5
    fresh = _candleset(_trend(), now_ts=1700000000 + 86400 * (N - 1))
    assert fresh.is_stale is False


def test_candles_load_uses_injected_fetcher():
    payload = {
        "ok": True,
        "data": {
            "symbol": "ETH",
            "bar": "1d",
            "points": [{"ts": 1700000000 + i * 86400, "close": 10.0 + i} for i in range(3)],
        },
        "meta": {},
    }
    seen = {}

    def fake_fetcher(params):
        seen.update(params)
        return payload

    cs = load("ETH", bar="1d", days=30, fetcher=fake_fetcher)
    assert seen["symbol"] == "ETH" and seen["bar"] == "1d"
    assert cs.symbol == "ETH" and cs.sample_n == 3


# ============================================================
# I01/I02：MA / EMA
# ============================================================


def test_i01_sma_exact():
    out = run("I01", {"close": [float(i) for i in range(1, 121)]}, periods=(5, 20))
    assert out["gate"] == "ok"
    assert out["result"]["ma"]["5"] == pytest.approx(118.0)
    assert out["result"]["ma"]["20"] == pytest.approx(110.5)


def test_i02_ema_constant_and_ramp():
    flat = run("I02", {"close": [100.0] * 40}, periods=(12,))
    assert flat["result"]["ema"]["12"] == pytest.approx(100.0)
    ramp = run("I02", {"close": [float(i) for i in range(1, 61)]}, periods=(12,))
    # 线性序列的 EMA 滞后于现价且高于价格均值
    assert 40.0 < ramp["result"]["ema"]["12"] < 60.0


# ============================================================
# I07：RSI（Wilder）
# ============================================================


def test_i07_rsi_monotone_up_is_100():
    out = run("I07", {"close": [float(i) for i in range(1, 41)]})
    assert out["result"]["rsi"] == pytest.approx(100.0)
    assert out["result"]["zone"] == "超买"


def test_i07_rsi_flat_is_neutral_50():
    out = run("I07", {"close": [100.0] * 40})
    assert out["result"]["rsi"] == pytest.approx(50.0)
    assert out["result"]["zone"] == "中性"


def test_i07_rsi_monotone_down_is_oversold():
    out = run("I07", {"close": [float(i) for i in range(60, 20, -1)]})
    assert out["result"]["rsi"] == pytest.approx(0.0)
    assert out["result"]["zone"] == "超卖"


# ============================================================
# I09：MACD
# ============================================================


def test_i09_macd_flat_zero_cross_none():
    out = run("I09", {"close": [100.0] * 60})
    r = out["result"]
    assert r["dif"] == pytest.approx(0.0)
    assert r["dea"] == pytest.approx(0.0)
    assert r["hist"] == pytest.approx(0.0)
    assert r["cross"] == "none"


def test_i09_macd_uptrend_positive_dif():
    out = run("I09", {"close": [100.0 + 0.5 * i for i in range(80)]})
    assert out["result"]["dif"] > 0
    assert out["result"]["cross"] in ("golden", "death", "none")


# ============================================================
# I12：ATR（需 HLC）
# ============================================================


def test_i12_atr_requires_high_low():
    with pytest.raises(ValueError):
        run("I12", {"close": [100.0] * 40})


def test_i12_atr_known_range():
    data = _flat(40)
    out = run("I12", data)
    # 恒定 H=101/L=99/C=100 → TR=2 → ATR=2，atr_pct=2%
    assert out["result"]["atr"] == pytest.approx(2.0)
    assert out["result"]["atr_pct"] == pytest.approx(0.02)


# ============================================================
# I14/I15：布林带
# ============================================================


def test_i14_boll_flat_collapses():
    out = run("I14", {"close": [100.0] * 40})
    assert out["result"]["upper"] == pytest.approx(100.0)
    assert out["result"]["lower"] == pytest.approx(100.0)


def test_i14_boll_band_position():
    close = [100.0, 102.0] * 10
    out = run("I14", {"close": close})
    r = out["result"]
    assert r["upper"] > r["mid"] > r["lower"]
    pctb = run("I15", {"close": close})["result"]["pctb"]
    assert pctb == pytest.approx(0.75)
    flat = run("I15", {"close": [100.0] * 20})["result"]["pctb"]
    assert flat == pytest.approx(0.5)


# ============================================================
# I17：量能比
# ============================================================


def test_i17_volume_ratio():
    volumes = [100.0] * 20 + [200.0]
    out = run("I17", {"close": [100.0] * 21, "volume": volumes}, period=20)
    assert out["result"]["base_vol"] == pytest.approx(100.0)
    assert out["result"]["vol_ratio"] == pytest.approx(2.0)


# ============================================================
# I20–I23：支撑 / 压力 / 触碰 / 距离
# ============================================================


def _zigzag():
    """构造两个明确高点(120/125)与两个明确低点(90/95)的锯齿序列。"""
    path = [100, 110, 120, 110, 100, 90, 100, 110, 115, 105, 95, 105, 115, 125, 115, 105, 100]
    path = path * 4  # 长度 68，保证窗口充足
    close = [float(x) for x in path]
    return {
        "close": close,
        "high": [c + 0.5 for c in close],
        "low": [c - 0.5 for c in close],
        "volume": [1000.0] * len(close),
    }


def test_i20_i21_level_clusters():
    data = _zigzag()
    sup = run("I20", data, window=60)["result"]["levels"]
    res = run("I21", data, window=60)["result"]["levels"]
    assert sup and res
    assert all(level["price"] < 100.0 for level in sup)
    assert all(level["price"] > 100.0 for level in res)
    assert any(abs(level["price"] - 125.0) <= 1.0 for level in res)


def test_i22_touches_counts_band_hits():
    data = {
        "high": [101.0] * 10 + [105.0] * 10,
        "low": [99.0] * 10 + [103.0] * 10,
        "close": [100.0] * 10 + [104.0] * 10,
    }
    out = run("I22", data, level=100.0, eps_pct=0.01)
    assert out["result"]["touches"] == 10


def test_i23_distance_uses_support_resistance():
    data = {"close": [100.0], "high": [101.0], "low": [99.0]}
    out = run("I23", data, support=95.0, resistance=110.0)
    assert out["result"]["support_dist"] == pytest.approx(0.05)
    assert out["result"]["resistance_dist"] == pytest.approx(0.10)


# ============================================================
# 能力编排：D-B00–B07
# ============================================================


def test_analyze_requires_120_bars():
    cs = _candleset(_trend(60))
    out = analyze(cs)
    assert out["gate"] == "insufficient_history"
    assert out["sample_n"] == 60
    assert out["capabilities"]["D-B00"]["sample_n"] == 60
    assert len(out["capabilities"]) == 1


def test_analyze_close_only_degrades_ohlc_capabilities():
    data = _trend()
    points = [
        {"ts": 1700000000 + 86400 * i, "close": c, "volume": 1000.0 + i}
        for i, c in enumerate(data["close"])
    ]
    cs = from_l0_envelope({"data": {"symbol": "BTC", "points": points}})
    out = analyze(cs)
    assert out["gate"] == "ok"
    assert out["has_ohlc"] is False
    caps = out["capabilities"]
    assert caps["D-B01"]["gate"] == "ok"
    assert caps["D-B02"]["gate"] == "ok"
    assert caps["D-B03"]["gate"] == "ok"
    assert caps["D-B05"]["gate"] == "ok"
    assert caps["D-B06"]["gate"] == "ok"
    assert caps["D-B04"]["gate"] == "insufficient_history"
    assert caps["D-B04"]["reason"] == "no_ohlc"
    assert caps["D-B07"]["gate"] == "insufficient_history"
    assert "D-B04" in out["degraded"] and "D-B07" in out["degraded"]


def test_analyze_full_ohlc_reports_all_capabilities():
    cs = _candleset(_trend())
    out = analyze(cs)
    assert out["gate"] == "ok"
    assert out["intent"] == "technical_indicator"
    assert out["caveat"]
    caps = out["capabilities"]
    assert set(caps) == {f"D-B0{i}" for i in range(8)}
    b1 = caps["D-B01"]
    assert b1["ma20"] > 0 and b1["ma60"] > 0 and b1["ema12"] > 0 and b1["ema26"] > 0
    assert caps["D-B02"]["zone"] in ("超买", "超卖", "中性")
    assert caps["D-B03"]["hist"] is not None
    assert caps["D-B04"]["atr14"] == pytest.approx(2.0)
    assert caps["D-B05"]["upper"] >= caps["D-B05"]["mid"] >= caps["D-B05"]["lower"]
    assert caps["D-B06"]["vol_ratio"] > 1.0
    assert caps["D-B07"]["resistance"] > caps["D-B07"]["support"]
    assert out["degraded"] == []


def test_analyze_empty_candles():
    cs = from_l0_envelope({"data": {"symbol": "BTC", "points": []}})
    out = analyze(cs)
    assert out["gate"] == "empty"
    assert out["sample_n"] == 0


def test_analyze_stale_is_disclosed():
    now = 1700000000 + 86400 * (N - 1 + 10)
    cs = _candleset(_trend(), now_ts=now)
    out = analyze(cs, now_ts=now)
    assert out["is_stale"] is True
    assert out["stale_days"] == 10


def test_min_bars_matches_method_library():
    assert MIN_BARS == 120


# ============================================================
# 集成：真实 BTC 日线（L0 market.candles）
# 回填真实日线 OHLC 后 has_ohlc 应为 True；未回填的库则为 close-only。
# ============================================================


def test_real_btc_candles_pipeline():
    try:
        cs = load("BTC", bar="1d", days=1825)
    except CandleError as e:  # 数据缺失时跳过，不伪造
        pytest.skip(f"L0 candles unavailable: {e}")
    if cs.sample_n < MIN_BARS:
        pytest.skip("insufficient real candles")
    out = analyze(cs)
    assert out["gate"] == "ok"
    assert out["capabilities"]["D-B02"]["rsi14"] is not None
    assert math.isfinite(out["capabilities"]["D-B03"]["dif"])
    b07 = out["capabilities"]["D-B07"]
    if cs.has_ohlc:
        # 有真实高低点：支撑/压力必须可算且方向正确
        assert b07["gate"] == "ok"
        assert b07["resistance"] > b07["support"]
    else:
        # close-only 库不得伪造支撑压力
        assert b07["gate"] == "insufficient_history"
