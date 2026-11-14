# -*- coding: utf-8 -*-
"""意图 `technical_indicator` 能力编排：D-B00–B07 统一信封。

契约（TECHNICAL_DESIGN §2.2 / METHOD_LIBRARY §12）：
  - 数据前提 candles ≥ `MIN_BARS`(120) 根，不足只回 `insufficient_history`；
  - 依赖 high/low 的能力（D-B04 ATR、D-B07 支撑/压力）在 close-only 时
    显式降级为 `insufficient_history`+`reason=no_ohlc`，绝不伪造；
  - 输出必带 `sample_n/span/is_stale/timezone/align_method/caveat`，
    并逐能力标注 `gate`，供 L1 直答模板按门禁降级。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional

from l1agg.candles import ALIGN_METHOD, TIMEZONE, CandleSet

from .methods import run as run_method

INTENT = "technical_indicator"
MIN_BARS = 120
CAVEAT = "历史统计，不代表未来"
LEVEL_WINDOW = 60


def _now(now_ts: Optional[int]) -> int:
    return int(now_ts) if now_ts is not None else int(time.time())


def _stale(candles: CandleSet, now_ts: int) -> tuple[int, bool]:
    if not candles.ts:
        return 0, False
    days = max(0, (now_ts - candles.ts[-1]) // 86400)
    return days, days > 3


def _call(method_id: str, data: Mapping[str, Any], **params: Any) -> Dict[str, Any]:
    """调方法层；输入腿缺失（ValueError）统一收敛为 insufficient_history。"""
    try:
        envelope = run_method(method_id, data, **params)
    except ValueError as e:
        return {"gate": "insufficient_history", "reason": str(e), "result": None}
    if envelope.get("gate") != "ok":
        return {"gate": envelope.get("gate"), "result": None, "method": method_id}
    out = {"gate": "ok", "result": envelope["result"], "method": method_id}
    return out


def _block(gate: str, **fields: Any) -> Dict[str, Any]:
    block: Dict[str, Any] = {"gate": gate}
    block.update(fields)
    return block


def _d_b01(data, close: float) -> Dict[str, Any]:
    sma = _call("I01", data, periods=(20, 60))
    ema = _call("I02", data, periods=(12, 26))
    if sma["gate"] != "ok" or ema["gate"] != "ok":
        return _block("insufficient_history", method=["I01", "I02"])
    ma, em = sma["result"]["ma"], ema["result"]["ema"]
    return _block(
        "ok",
        ma20=ma.get("20"),
        ma60=ma.get("60"),
        ema12=em.get("12"),
        ema26=em.get("26"),
        price=close,
        price_vs_ma20=round(close / ma["20"] - 1, 6) if ma.get("20") else None,
        method=["I01", "I02"],
    )


def _d_b02(data) -> Dict[str, Any]:
    res = _call("I07", data)
    if res["gate"] != "ok":
        return _block("insufficient_history", method="I07")
    return _block("ok", rsi14=res["result"]["rsi"], zone=res["result"]["zone"], method="I07")


def _d_b03(data) -> Dict[str, Any]:
    res = _call("I09", data)
    if res["gate"] != "ok":
        return _block("insufficient_history", method="I09")
    r = res["result"]
    return _block("ok", dif=r["dif"], dea=r["dea"], hist=r["hist"], cross=r["cross"], method="I09")


def _d_b04(data, has_ohlc: bool) -> Dict[str, Any]:
    if not has_ohlc:
        return _block("insufficient_history", reason="no_ohlc", method="I12")
    res = _call("I12", data)
    if res["gate"] != "ok":
        return _block("insufficient_history", method="I12")
    return _block("ok", atr14=res["result"]["atr"], atr_pct=res["result"]["atr_pct"], method="I12")


def _d_b05(data) -> Dict[str, Any]:
    boll = _call("I14", data)
    pctb = _call("I15", data)
    if boll["gate"] != "ok" or pctb["gate"] != "ok":
        return _block("insufficient_history", method=["I14", "I15"])
    r = boll["result"]
    return _block(
        "ok",
        upper=r["upper"],
        mid=r["mid"],
        lower=r["lower"],
        boll_pos=pctb["result"]["pctb"],
        method=["I14", "I15"],
    )


def _d_b06(data, has_volume: bool) -> Dict[str, Any]:
    if not has_volume:
        return _block("insufficient_history", reason="no_volume", method="I17")
    res = _call("I17", data)
    if res["gate"] != "ok":
        return _block("insufficient_history", method="I17")
    return _block(
        "ok", vol_ratio=res["result"]["vol_ratio"], base_vol=res["result"]["base_vol"], method="I17"
    )


def _d_b07(data, candles: CandleSet, close: float) -> Dict[str, Any]:
    if not candles.has_ohlc:
        return _block("insufficient_history", reason="no_ohlc", method=["I20", "I21", "I22", "I23"])
    high, low = candles.high, candles.low
    sup = _call("I20", data)
    res_levels = _call("I21", data)
    if sup["gate"] != "ok" or res_levels["gate"] != "ok":
        return _block("insufficient_history", method=["I20", "I21"])

    supports = [lv for lv in sup["result"]["levels"] if lv["price"] <= close]
    resistances = [lv for lv in res_levels["result"]["levels"] if lv["price"] >= close]
    window_low = min(low[-LEVEL_WINDOW:])
    window_high = max(high[-LEVEL_WINDOW:])
    level_source = "pivot"
    if supports:
        support = max(supports, key=lambda lv: lv["price"])["price"]
    else:
        support, level_source = window_low, "fallback_extreme"
    if resistances:
        resistance = min(resistances, key=lambda lv: lv["price"])["price"]
    else:
        resistance, level_source = window_high, "fallback_extreme"

    touches = {
        "support": _call("I22", data, level=support)["result"],
        "resistance": _call("I22", data, level=resistance)["result"],
    }
    dist = _call("I23", data, support=support, resistance=resistance)
    if dist["gate"] != "ok":
        return _block("insufficient_history", method="I23")
    return _block(
        "ok",
        support=support,
        resistance=resistance,
        support_touches=touches["support"]["touches"],
        resistance_touches=touches["resistance"]["touches"],
        support_dist=dist["result"]["support_dist"],
        resistance_dist=dist["result"]["resistance_dist"],
        level_source=level_source,
        window=LEVEL_WINDOW,
        method=["I20", "I21", "I22", "I23"],
    )


def analyze(candles: CandleSet, *, now_ts: Optional[int] = None) -> Dict[str, Any]:
    """D-B00–B07 一次性编排，返回带门禁与降级的 CapabilityResult 信封。"""
    now = _now(now_ts)
    stale_days, is_stale = _stale(candles, now)
    base: Dict[str, Any] = {
        "intent": INTENT,
        "symbol": candles.symbol,
        "bar": candles.bar,
        "sample_n": candles.sample_n,
        "span": candles.span,
        "timezone": TIMEZONE,
        "align_method": str(candles.meta.get("align_method") or ALIGN_METHOD),
        "has_ohlc": candles.has_ohlc,
        "source": candles.source,
        "is_stale": is_stale,
        "stale_days": stale_days,
        "params": {"min_bars": MIN_BARS, "level_window": LEVEL_WINDOW},
        "caveat": CAVEAT,
    }

    if candles.sample_n == 0:
        return {
            **base,
            "gate": "empty",
            "capabilities": {"D-B00": _b00(candles, stale_days, is_stale)},
            "degraded": ["D-B00:empty"],
        }

    if candles.sample_n < MIN_BARS:
        return {
            **base,
            "gate": "insufficient_history",
            "capabilities": {"D-B00": _b00(candles, stale_days, is_stale)},
            "degraded": [f"sample_n<{MIN_BARS}"],
        }

    data = candles.to_method_data()
    close = candles.close[-1]
    capabilities: Dict[str, Any] = {
        "D-B00": _b00(candles, stale_days, is_stale),
        "D-B01": _d_b01(data, close),
        "D-B02": _d_b02(data),
        "D-B03": _d_b03(data),
        "D-B04": _d_b04(data, candles.has_ohlc),
        "D-B05": _d_b05(data),
        "D-B06": _d_b06(data, bool(candles.volume)),
        "D-B07": _d_b07(data, candles, close),
    }
    degraded: List[str] = [cid for cid, block in capabilities.items() if block["gate"] != "ok"]
    return {**base, "gate": "ok", "capabilities": capabilities, "degraded": degraded}


def _b00(candles: CandleSet, stale_days: int, is_stale: bool) -> Dict[str, Any]:
    return _block(
        "ok",
        symbol=candles.symbol,
        bar=candles.bar,
        sample_n=candles.sample_n,
        span=candles.span,
        has_ohlc=candles.has_ohlc,
        has_volume=bool(candles.volume),
        source=candles.source,
        stale_days=stale_days,
        is_stale=is_stale,
    )
