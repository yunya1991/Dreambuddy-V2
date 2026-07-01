"""
F3 情绪分析节点
调用基本面分析系统获取市场情绪数据
遵循"调用的不重复建设"原则

API 路径: 10-经典指标系统/ml_trade_service.py
- /fundamental/trading/latest - 交易信号（含情绪）
- /fundamental/overview/latest - 概览

模块路径: core.modules.fundamental_api
"""

from typing import Dict, Any
from pathlib import Path

try:
    from core.modules.fundamental_api import FundamentalAPIClient
    _FUND_OK = True
except ImportError:
    _FUND_OK = False
    FundamentalAPIClient = None


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 F3 情绪分析
    
    优先调用基本面分析系统 API，失败时使用本地降级
    
    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据
    
    Returns:
        {
            "node": "F3_情绪",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...情绪详情...},
            "source": "fundamental_api" | "local_fallback"
        }
    """
    reasoning = []
    coin = mkt.get("coin", "BTC")
    rsi = mkt.get("rsi14", 50)
    ch24 = mkt.get("change_24h", 0)
    funding = mkt.get("funding_rate", 0)
    
    # ── 调用基本面 API ─────────────────────────────────────────────
    source = "local_fallback"
    sentiment_data = None
    
    if _FUND_OK:
        try:
            client = FundamentalAPIClient()
            if client.is_available():
                sentiment_data = client.get_sentiment(coin)
                source = "fundamental_api"
                reasoning.append(f"[F3情绪] 数据源: 基本面分析系统 API")
            else:
                reasoning.append(f"[F3情绪] 数据源: 本地计算（基本面系统不可用）")
        except Exception as e:
            reasoning.append(f"[F3情绪] 数据源: 本地计算（{str(e)[:30]}）")
    else:
        reasoning.append(f"[F3情绪] 数据源: 本地计算（模块未加载）")
    
    # ── 情绪计算 ──────────────────────────────────────────────────
    if sentiment_data and sentiment_data.fear_greed != 50.0:
        # 使用 API 数据
        fg_index = sentiment_data.fear_greed
        sentiment_label = sentiment_data.sentiment
        ls_ratio = sentiment_data.long_short_ratio
    else:
        # 本地计算：基于 RSI、涨跌幅、资金费率综合估算
        score = 50.0
        
        # RSI 贡献
        score += (rsi - 50) * 0.5
        
        # 24H 涨跌贡献
        score += ch24 * 2
        
        # 资金费率贡献
        if funding > 0.0005:
            score += 15
        elif funding > 0.0001:
            score += 5
        elif funding < -0.0005:
            score -= 15
        elif funding < -0.0001:
            score -= 5
        
        fg_index = max(0, min(100, score))
        
        if fg_index > 70:
            sentiment_label = "GREED"
        elif fg_index < 30:
            sentiment_label = "FEAR"
        else:
            sentiment_label = "NEUTRAL"
        
        ls_ratio = 1.0
    
    # ── 情绪方向判断 ──────────────────────────────────────────────
    # 逆向思维：极度恐惧是买入机会，极度贪婪是卖出信号
    if sentiment_label == "FEAR" and fg_index < 25:
        direction = "LONG"
        confidence = 0.55
        reasoning.append(f"  🟢 极度恐惧({fg_index:.0f}) → 逆向偏多（抄底机会）")
    elif sentiment_label == "GREED" and fg_index > 75:
        direction = "SHORT"
        confidence = 0.55
        reasoning.append(f"  🔴 极度贪婪({fg_index:.0f}) → 逆向偏空（逃顶信号）")
    elif sentiment_label == "FEAR":
        direction = "LONG"
        confidence = 0.48
        reasoning.append(f"  🟡 恐惧({fg_index:.0f}) → 轻微偏多")
    elif sentiment_label == "GREED":
        direction = "SHORT"
        confidence = 0.48
        reasoning.append(f"  🟡 贪婪({fg_index:.0f}) → 轻微偏空")
    else:
        direction = "HOLD"
        confidence = 0.45
        reasoning.append(f"  ⚖️  情绪中性({fg_index:.0f})")
    
    # ── 多空比（如有数据） ───────────────────────────────────────
    if ls_ratio != 1.0:
        reasoning.append(f"  📊 多空比: {ls_ratio:.2f}")
    
    return {
        "node": "F3_情绪",
        "direction": direction,
        "confidence": round(confidence, 3),
        "rationale": reasoning,
        "source": source,
        "data": {
            "coin": coin,
            "fear_greed_index": round(fg_index, 2),
            "sentiment": sentiment_label,
            "long_short_ratio": round(ls_ratio, 4),
            "source": source,
        }
    }


def f3_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
