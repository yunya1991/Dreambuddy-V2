"""classic_pipeline → S1/S2 标准化映射层。

将 classic_pipeline 的指标计算结果和信号结果映射为前端
classic-system-bridge.ts 定义的 S1ResearchOutput / S2AnalysisOutput 结构，
供用户对话层直接消费。

字段命名严格对齐前端 TypeScript 接口定义。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# S1 调研映射
# ---------------------------------------------------------------------------

def map_to_s1(
    indicators: Dict[str, Any],
    *,
    symbol: str,
    price: float,
    display_name: Optional[str] = None,
    price_change_24h: Optional[float] = None,
    support: Optional[str] = None,
    resistance: Optional[str] = None,
    sentiment: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    """将 classic_pipeline 指标结果映射为 S1ResearchOutput。

    Args:
        indicators: 指标字典，支持键: rsi, macd{value,signal,histogram}, ema_fast, ema_slow
        symbol: 交易对符号
        price: 当前价格
        display_name: 显示名称（默认 symbol）
        price_change_24h: 24h 涨跌幅
        support: 支撑位
        resistance: 阻力位
        sentiment: 情绪指标 {fearGreedIndex, fundingRate}
        summary: 摘要文本

    Returns:
        符合 S1ResearchOutput 接口的 dict
    """
    ind = indicators or {}

    # RSI
    rsi_val = _safe_float(ind.get("rsi"))

    # MACD
    macd_obj = ind.get("macd") if isinstance(ind.get("macd"), dict) else {}
    macd_value = _safe_float(macd_obj.get("value") or macd_obj.get("macd"))
    macd_signal = _safe_float(macd_obj.get("signal"))
    macd_hist = _safe_float(macd_obj.get("histogram"))

    # 趋势判断：EMA 快慢线 + MACD 柱状
    ema_fast = _safe_float(ind.get("ema_fast"))
    ema_slow = _safe_float(ind.get("ema_slow"))
    trend = _derive_trend(ema_fast=ema_fast, ema_slow=ema_slow, macd_hist=macd_hist)

    out: Dict[str, Any] = {
        "symbol": str(symbol or ""),
        "displayName": str(display_name or symbol or ""),
        "price": float(price or 0.0),
        "priceChange24h": (float(price_change_24h) if price_change_24h is not None else None),
        "support": (str(support) if support is not None else ""),
        "resistance": (str(resistance) if resistance is not None else ""),
        "indicators": {
            "rsi": rsi_val,
            "macd": {
                "value": macd_value,
                "signal": macd_signal,
                "histogram": macd_hist,
            },
            "trend": trend,
        },
        "sentiment": (sentiment if isinstance(sentiment, dict) else {}),
        "summary": (str(summary) if summary else _default_s1_summary(rsi_val, trend)),
    }
    return out


# ---------------------------------------------------------------------------
# S2 分析映射
# ---------------------------------------------------------------------------

def map_to_s2(
    signal_result: Dict[str, Any],
    regime: Optional[Dict[str, Any]] = None,
    *,
    key_levels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """将 classic_pipeline 信号结果映射为 S2AnalysisOutput。

    Args:
        signal_result: quant_signal.compute() 的输出 {signals, dominant_direction, confidence, details}
        regime: 市场环境 {trend, volatility}
        key_levels: 关键位 {entryRange, stopLoss, takeProfit}

    Returns:
        符合 S2AnalysisOutput 接口的 dict
    """
    sig = signal_result or {}
    reg = regime or {}

    dominant = str(sig.get("dominant_direction") or "neutral").strip().lower()
    confidence = _safe_float(sig.get("confidence"), default=0.0)
    confidence = max(0.0, min(1.0, confidence))

    # 短/中/长期趋势：当前信号 + regime 组合
    short_term = _direction_to_trend(dominant)
    med_regime = str(reg.get("trend") or "").strip().lower()
    medium_term = _regime_to_trend(med_regime) if med_regime else short_term
    # 长期默认取中期（缺少长周期数据时）
    long_term = medium_term

    risks: list = []
    details = sig.get("details") if isinstance(sig.get("details"), dict) else {}
    if confidence < 0.5:
        risks.append("信号置信度偏低")
    vol = str(reg.get("volatility") or "").strip().lower()
    if vol in ("high", "elevated"):
        risks.append("市场波动率偏高")
    if not risks:
        risks.append("无显著风险")

    kl = key_levels if isinstance(key_levels, dict) else {}
    conclusion = _default_s2_conclusion(short_term, confidence)

    out: Dict[str, Any] = {
        "trend": {
            "shortTerm": short_term,
            "mediumTerm": medium_term,
            "longTerm": long_term,
        },
        "keyLevels": {
            "entryRange": str(kl.get("entryRange") or ""),
            "stopLoss": str(kl.get("stopLoss") or ""),
            "takeProfit": str(kl.get("takeProfit") or ""),
        },
        "risks": risks,
        "confidence": confidence,
        "conclusion": conclusion,
    }
    return out


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f == f:  # not NaN
            return f
    except Exception:
        pass
    return float(default)


def _derive_trend(*, ema_fast: Optional[float], ema_slow: Optional[float], macd_hist: Optional[float]) -> str:
    """基于 EMA 快慢线和 MACD 柱状推导趋势。"""
    bullish = 0
    bearish = 0
    if ema_fast is not None and ema_slow is not None and ema_slow != 0:
        if ema_fast > ema_slow:
            bullish += 1
        elif ema_fast < ema_slow:
            bearish += 1
    if macd_hist is not None:
        if macd_hist > 0:
            bullish += 1
        elif macd_hist < 0:
            bearish += 1
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def _direction_to_trend(direction: str) -> str:
    d = str(direction or "").strip().lower()
    if d in ("long", "bullish"):
        return "bullish"
    if d in ("short", "bearish"):
        return "bearish"
    return "neutral"


def _regime_to_trend(regime_trend: str) -> str:
    t = str(regime_trend or "").strip().lower()
    if t in ("up", "bull", "bullish"):
        return "bullish"
    if t in ("down", "bear", "bearish"):
        return "bearish"
    return "neutral"


def _default_s1_summary(rsi: Optional[float], trend: str) -> str:
    parts = []
    if rsi is not None:
        if rsi > 70:
            parts.append(f"RSI={rsi:.1f} 超买")
        elif rsi < 30:
            parts.append(f"RSI={rsi:.1f} 超卖")
        else:
            parts.append(f"RSI={rsi:.1f} 中性")
    parts.append(f"趋势={trend}")
    return "；".join(parts)


def _default_s2_conclusion(trend: str, confidence: float) -> str:
    if confidence >= 0.8:
        strength = "强"
    elif confidence >= 0.6:
        strength = "中"
    else:
        strength = "弱"
    return f"短期{trend}，置信度{strength}（{confidence:.2f}）"


__all__ = ["map_to_s1", "map_to_s2"]
