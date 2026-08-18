"""市场数据指标注入 —— PROP-20260816 P1 (修复 F-1: B层数据饥饿)。

F层 orchestration_cycle job 原先只给 B层喂 {symbol, entry_price, close_price},
YijingSignalGenerator 的 12 个指标字段全部落默认值 → 所有币种输出相同的
HOLD 0.1312 (2026-08-15 实盘验证发现)。

本模块从 AutoTrader._fetch_market_data() 的产出(价格/EMA/RSI/ATR/48根1hK线)
推导 B层所需的全部指标。四维评分为价格行为代理(简化版,PROP-20260816 已声明):
  - technical_score:      MA 排列 + RSI 偏离
  - supply_demand_score:  区间位置 + 短期动量
  - capital_flow_score:   量能比确认的 24h 方向
  - sentiment_score:      RSI 直接映射
降级契约: K线不足/获取失败 → 只注入价格,其余字段保持默认(不阻塞周期)。
"""
from typing import Any, Callable, Dict


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sma(values, n: int) -> float:
    if len(values) < n:
        return 0.0
    return sum(values[-n:]) / n


def enrich_market_data(
    symbol: str,
    base_md: Dict[str, Any],
    fetch_data: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """为 B层信号生成器注入指标数据。

    Args:
        symbol: 币种 (如 "BTC")
        base_md: 基础 market_data (至少含 symbol)
        fetch_data: 数据获取函数,签名 symbol -> dict,
                    生产传 AutoTrader._fetch_market_data

    Returns:
        注入指标后的 market_data (新 dict,不改 base_md)。
        获取失败时仅保留原有字段(降级不阻塞)。
    """
    md = dict(base_md)
    md["symbol"] = symbol

    try:
        data = fetch_data(symbol) or {}
    except Exception:
        return md

    price = float(data.get("price") or 0)
    if price <= 0:
        return md  # 降级: 连价格都没有,保持现状

    md["entry_price"] = price
    md["close_price"] = price

    candles = data.get("candles_1h") or []
    closes = [float(c.get("c", 0)) for c in candles if c.get("c") is not None]
    highs = [float(c.get("h", 0)) for c in candles if c.get("h") is not None]
    lows = [float(c.get("l", 0)) for c in candles if c.get("l") is not None]
    vols = [float(c.get("v", 0)) for c in candles if c.get("v") is not None]

    if len(closes) < 24:
        return md  # 降级: K线不足,只有价格

    # ── 均线与动量 ─────────────────────────────────────────────
    ma5, ma10, ma20 = _sma(closes, 5), _sma(closes, 10), _sma(closes, 20)
    md["ma5"] = round(ma5, 6)
    md["ma10"] = round(ma10, 6)
    md["ma20"] = round(ma20, 6)

    change_4h = float(data.get("change_4h") or 0)  # 小数形式 (0.01 = 1%)
    if change_4h > 0.005 and ma5 > ma10:
        md["momentum_direction"] = "UP"
    elif change_4h < -0.005 and ma5 < ma10:
        md["momentum_direction"] = "DOWN"
    else:
        md["momentum_direction"] = "FLAT"

    # ── 波动与量能 ─────────────────────────────────────────────
    atr_pct = float(data.get("atr_pct") or 0)
    md["volatility"] = round(_clamp(atr_pct * 10, 0.05, 1.0), 4)

    if len(vols) >= 25 and sum(vols[-25:-1]) > 0:
        avg_vol = sum(vols[-25:-1]) / 24
        md["volume_ratio"] = round(vols[-1] / avg_vol, 4) if avg_vol > 0 else 1.0
    else:
        md["volume_ratio"] = 1.0

    if len(lows) >= 24 and len(highs) >= 24:
        lo, hi = min(lows[-48:]), max(highs[-48:])
        md["price_position"] = round(_clamp((price - lo) / (hi - lo)) if hi > lo else 0.5, 4)
    else:
        md["price_position"] = 0.5

    # ── 趋势强度: MA 发散度(3%满档) × 24h方向一致性 ─────────────
    spread = abs(ma5 - ma20) / price if price > 0 else 0
    trend = _clamp(spread / 0.03)
    change_24h = float(data.get("change_24h") or 0)
    if (ma5 > ma20 and change_24h > 0) or (ma5 < ma20 and change_24h < 0):
        trend = _clamp(trend * 1.2)
    md["trend_strength"] = round(trend, 4)

    # ── 四维评分 (价格行为代理,简化版) ─────────────────────────
    # technical: MA 排列 ±0.4 + RSI 偏离 ±0.1
    rsi = float(data.get("rsi14") or 50)
    tech = 0.5
    tech += 0.2 if price > ma20 else -0.2
    tech += 0.1 if ma5 > ma10 else -0.1
    tech += 0.1 if ma10 > ma20 else -0.1
    tech += _clamp((rsi - 50) / 50, -1, 1) * 0.1
    md["technical_score"] = round(_clamp(tech), 4)

    # supply_demand: 区间位置 ±0.25 + 4h 动量 ±0.25
    pp = md["price_position"]
    mom = _clamp(change_4h / 0.04, -1, 1)  # 4% 的 4h 波动为满档
    md["supply_demand_score"] = round(_clamp(0.5 + (pp - 0.5) * 0.5 + mom * 0.25), 4)

    # capital_flow: 量能比确认的 24h 方向 (vr 超均量 3 倍满档 ±0.3)
    vr = md["volume_ratio"]
    direction_sign = 1.0 if change_24h > 0 else (-1.0 if change_24h < 0 else 0.0)
    md["capital_flow_score"] = round(
        _clamp(0.5 + direction_sign * _clamp(vr - 1.0, 0, 2.0) * 0.15), 4
    )

    # sentiment: RSI 直接映射
    md["sentiment_score"] = round(_clamp(rsi / 100), 4)

    return md
