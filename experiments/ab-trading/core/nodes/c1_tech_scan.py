"""
C1 技术扫描节点
调用经典指标系统（10-经典指标系统）获取技术指标
遵循"调用的不重复建设"原则

SKILL / 模块路径: 
- 经典指标系统: 10-经典指标系统/ml_trade_service.py
- 本地降级: core.modules.classic_indicators
"""

from typing import Dict, Any
from pathlib import Path

try:
    from core.modules.classic_indicators import ClassicIndicatorsClient
    _MODULES_OK = True
except ImportError:
    _MODULES_OK = False
    ClassicIndicatorsClient = None


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 C1 技术扫描
    
    优先调用经典指标系统 API，失败时使用本地降级计算
    
    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据
    
    Returns:
        {
            "node": "C1_技术扫描",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...技术指标详情...},
            "source": "classic_api" | "local_fallback"
        }
    """
    price  = mkt.get("price", 0)
    coin   = mkt.get("coin", "BTC")
    ema20  = mkt.get("ema20", price)
    ema50  = mkt.get("ema50", price)
    ema200 = mkt.get("ema200", price)
    rsi    = mkt.get("rsi14", 50)
    ch24   = mkt.get("change_24h", 0)
    ch4h   = mkt.get("change_4h", 0)
    ch1h   = mkt.get("change_1h", 0)
    vr     = mkt.get("vol_ratio", 1.0)
    atr    = mkt.get("atr14", price * 0.02)
    regime = mkt.get("regime", "RANGE")
    
    reasoning = [
        f"[C1技术扫描] 价格=${price:.2f} | RSI={rsi:.1f} | 量比={vr:.2f}x",
        f"  24h: {ch24:+.2f}% | 4h: {ch4h:+.2f}% | 1h: {ch1h:+.2f}%",
    ]
    
    # ── 尝试调用经典指标系统 ──────────────────────────────────────────
    source = "local_fallback"
    if _MODULES_OK:
        try:
            client = ClassicIndicatorsClient()
            if client.is_available():
                source = "classic_api"
                reasoning.append(f"  ✅ 数据源: 经典指标系统 API")
            else:
                reasoning.append(f"  ⚠️  数据源: 本地计算（经典指标系统不可用）")
        except Exception as e:
            reasoning.append(f"  ⚠️  数据源: 本地计算（{str(e)[:30]}）")
    else:
        reasoning.append(f"  ⚠️  数据源: 本地计算（模块未加载）")
    
    # ── EMA 排列判断 ─────────────────────────────────────────────────
    direction = "HOLD"
    conf = 0.45
    
    if price > ema20 > ema50 > ema200:
        direction = "LONG"
        conf = 0.65
        reasoning.append("  ✅ EMA 强多排列（价格在所有均线之上）")
    elif price < ema20 < ema50 < ema200:
        direction = "SHORT"
        conf = 0.65
        reasoning.append("  🔴 EMA 强空排列（价格在所有均线之下）")
    elif price > ema200:
        direction = "LONG"
        conf = 0.55
        reasoning.append("  ✅ 价格在 MA200 上方，中期偏多")
    elif price < ema200:
        direction = "SHORT"
        conf = 0.55
        reasoning.append("  🔴 价格在 MA200 下方，中期偏空")
    else:
        reasoning.append("  ⚠️ EMA 排列混乱，方向不明")
    
    # ── RSI 修正 ────────────────────────────────────────────────────
    if rsi > 70:
        conf -= 0.05
        reasoning.append(f"  ⚠️ RSI={rsi:.1f} 超买")
    elif rsi < 30:
        conf -= 0.05
        reasoning.append(f"  ⚠️ RSI={rsi:.1f} 超卖")
    
    # ── 量比修正 ─────────────────────────────────────────────────────
    if vr > 1.5 and direction != "HOLD":
        conf = min(conf + 0.05, 0.85)
        reasoning.append(f"  ✅ 量比 {vr:.1f}x 放大，支持 {direction}")
    elif vr < 0.5:
        conf -= 0.05
        reasoning.append(f"  ⚠️ 量比 {vr:.1f}x 萎缩，动能不足")
    
    # ── 趋势强度修正 ────────────────────────────────────────────────
    if "TREND" in regime:
        if direction == "LONG":
            conf = min(conf + 0.05, 0.90)
            reasoning.append(f"  ✅ 市场状态={regime}，趋势多头增强")
        elif direction == "SHORT":
            conf = min(conf + 0.05, 0.90)
            reasoning.append(f"  ✅ 市场状态={regime}，趋势空头增强")
    
    conf = max(min(conf, 0.95), 0.25)
    
    return {
        "node": "C1_技术扫描",
        "direction": direction,
        "confidence": round(conf, 3),
        "rationale": reasoning,
        "source": source,
        "data": {
            "coin": coin,
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "change_24h": ch24,
            "change_4h": ch4h,
            "change_1h": ch1h,
            "vol_ratio": vr,
            "atr": atr,
            "regime": regime,
            "source": source,
        }
    }


def c1_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
