"""PROP-20260816 P1 测试 —— B层指标注入 (修复 F-1 数据饥饿)。

2026-08-15 实盘验证: F层只喂 {symbol, entry_price, close_price},
B层 12 个指标全部默认值 → 所有币种输出相同 HOLD 0.1312。
本测试验证 market_enrichment:
  1. 指标完整注入且取值合法
  2. 降级路径不阻塞 (价格0/K线不足/异常)
  3. 多空行情注入后 B层信号产生分化 (闭环证据)
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.market_enrichment import enrich_market_data


def _make_candles(start: float, drift: float, n: int = 48, vol: float = 1000.0):
    """构造 n 根 1h K线: drift>0 多头趋势, drift<0 空头趋势。"""
    candles, price = [], start
    for i in range(n):
        o = price
        c = price + drift
        candles.append({
            "t": i, "o": o,
            "h": max(o, c) * 1.002, "l": min(o, c) * 0.998,
            "c": c, "v": vol,
        })
        price = c
    return candles


def _fake_fetch(candles, price, rsi):
    def fetch(sym):
        closes = [c["c"] for c in candles]
        return {
            "symbol": sym, "price": price,
            "change_24h": (closes[-1] - closes[-7]) / closes[-7] if len(closes) > 7 else 0,
            "change_4h": (closes[-1] - closes[-2]) / closes[-2] if len(closes) > 1 else 0,
            "change_1h": (closes[-1] - closes[-2]) / closes[-2] if len(closes) > 1 else 0,
            "ema20": closes[-1], "ema50": closes[-1], "ema200": closes[-1],
            "rsi14": rsi, "atr_pct": 0.02,
            "candles_1h": candles,
        }
    return fetch


def test_enrich_full_indicators_injected():
    """完整K线 → 全部指标注入且取值合法。"""
    candles = _make_candles(100.0, 1.0)  # drift 1.0 ≈ 0.7%/根,越过 FLAT 中性带
    md = enrich_market_data(
        "BTC", {"symbol": "BTC", "entry_price": 0.0, "close_price": 0.0},
        _fake_fetch(candles, candles[-1]["c"], rsi=68.0),
    )
    # 价格注入
    assert md["entry_price"] == candles[-1]["c"]
    assert md["close_price"] == candles[-1]["c"]
    # 均线
    for k in ("ma5", "ma10", "ma20"):
        assert md[k] > 0, f"{k} 未注入"
    assert md["ma5"] > md["ma10"] > md["ma20"], "多头趋势应多头排列"
    # 动量/波动/量能/区间位置
    assert md["momentum_direction"] == "UP"
    assert 0.05 <= md["volatility"] <= 1.0
    assert md["volume_ratio"] > 0
    assert 0.0 <= md["price_position"] <= 1.0
    assert 0.0 <= md["trend_strength"] <= 1.0
    # 四维评分
    for k in ("technical_score", "supply_demand_score", "capital_flow_score", "sentiment_score"):
        assert 0.0 <= md[k] <= 1.0, f"{k}={md[k]} 越界"
    # 多头趋势 technical 应偏多
    assert md["technical_score"] > 0.5


def test_enrich_degrades_on_zero_price():
    """价格0 → 保持原样(降级不阻塞)。"""
    base = {"symbol": "BTC", "entry_price": 0.0, "close_price": 0.0}
    md = enrich_market_data("BTC", base, lambda s: {"symbol": s, "price": 0})
    assert "ma20" not in md
    assert md["entry_price"] == 0.0


def test_enrich_degrades_on_fetch_exception():
    """获取异常 → 原样返回,不抛出。"""
    def boom(sym):
        raise RuntimeError("network down")
    base = {"symbol": "ETH", "entry_price": 0.0, "close_price": 0.0}
    md = enrich_market_data("ETH", base, boom)
    assert md == base


def test_enrich_degrades_on_short_candles():
    """K线不足24根 → 只注价格,不注指标。"""
    candles = _make_candles(100.0, 0.5, n=10)
    md = enrich_market_data(
        "SOL", {"symbol": "SOL", "entry_price": 0.0, "close_price": 0.0},
        _fake_fetch(candles, candles[-1]["c"], rsi=50.0),
    )
    assert md["entry_price"] == candles[-1]["c"], "价格仍应注入"
    assert "ma20" not in md, "K线不足不应注入指标"


def test_enrich_bull_vs_bear_drives_different_signals():
    """闭环证据: 多空行情注入后 B层信号必须分化 (F-1 修复核心验收)。"""
    from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator

    bull_candles = _make_candles(100.0, 0.8)
    bear_candles = _make_candles(140.0, -0.8)
    md_bull = enrich_market_data(
        "BTC", {"symbol": "BTC", "entry_price": 0.0, "close_price": 0.0},
        _fake_fetch(bull_candles, bull_candles[-1]["c"], rsi=75.0),
    )
    md_bear = enrich_market_data(
        "BTC", {"symbol": "BTC", "entry_price": 0.0, "close_price": 0.0},
        _fake_fetch(bear_candles, bear_candles[-1]["c"], rsi=25.0),
    )

    # 注入数据本身应方向相反
    assert md_bull["momentum_direction"] == "UP"
    assert md_bear["momentum_direction"] == "DOWN"
    assert md_bull["technical_score"] > md_bear["technical_score"]

    # B层信号不再千篇一律 (同 seed 双生成器,排除 RNG 漂移干扰)
    sig_bull = YijingSignalGenerator(seed=42).generate(md_bull)
    sig_bear = YijingSignalGenerator(seed=42).generate(md_bear)
    identical = (
        sig_bull.get("direction") == sig_bear.get("direction")
        and abs(float(sig_bull.get("confidence", 0)) - float(sig_bear.get("confidence", 0))) < 1e-6
        and sig_bull.get("hexagram") == sig_bear.get("hexagram")
    )
    assert not identical, (
        f"注入真实指标后多空信号仍完全相同(F-1 未修复): "
        f"bull={sig_bull} bear={sig_bear}"
    )
