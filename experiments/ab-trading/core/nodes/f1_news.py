"""
F1 新闻情绪节点
扫描市场新闻和情绪指标

SKILL.md 调用路径: experiments/ab-trading/core/nodes/f1_news
"""

from typing import Dict, Any
import requests


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 F1 新闻情绪扫描

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "sentiment": {...}  # 情绪详情
        }
    """
    coin = mkt.get("coin", "BTC")
    price = mkt.get("price", 0)

    reasoning = []
    sentiment = {}

    # ── 尝试调用基本面 API ──────────────────────────────────────────────
    try:
        resp = requests.get(
            "http://49.233.123.96:3456/sentiment",
            params={"coin": coin},
            timeout=3
        )
        if resp.status_code == 200:
            sentiment_data = resp.json()
            sentiment = sentiment_data if isinstance(sentiment_data, dict) else {}
            reasoning.append(f"[F1 API] 获取到情绪数据")
        else:
            sentiment = _fallback_sentiment(mkt)
            reasoning.append(f"[F1 API] 返回 {resp.status_code}，使用备用逻辑")
    except Exception:
        sentiment = _fallback_sentiment(mkt)
        reasoning.append("[F1] 请求失败，使用备用逻辑")

    # ── 分析情绪 ───────────────────────────────────────────────────────
    sentiment_score = sentiment.get("score", 0)
    news_impact = sentiment.get("news_impact", "NEUTRAL")

    direction = "HOLD"
    conf = 0.50

    if news_impact == "BULLISH":
        direction = "LONG"
        conf = 0.60
        reasoning.append(f"✅ 新闻情绪: {news_impact} (score={sentiment_score})")
    elif news_impact == "BEARISH":
        direction = "SHORT"
        conf = 0.60
        reasoning.append(f"🔴 新闻情绪: {news_impact} (score={sentiment_score})")
    else:
        reasoning.append(f"⚪ 新闻情绪: {news_impact} (score={sentiment_score})")

    # ── 如果前序有方向，沿用但轻微调整 ─────────────────────────────────
    prev_direction = data.get("direction", "HOLD")
    if prev_direction != "HOLD" and direction == "HOLD":
        # 新闻中性但前序有信号，保留前序方向
        direction = prev_direction
        conf = data.get("confidence", 0.50)
        reasoning.append(f"[融合] 沿用前序方向: {direction} (conf={conf:.0%})")

    return {
        "node": "F1_新闻",
        "direction": direction,
        "confidence": round(conf, 3),
        "rationale": reasoning,
        "sentiment": sentiment,
    }


def _fallback_sentiment(mkt: Dict) -> Dict:
    """备用情绪评估（无 API 时）"""
    change_24h = mkt.get("change_24h", 0)
    rsi = mkt.get("rsi14", 50)

    # 基于价格变动估算情绪
    if change_24h > 3:
        impact = "BULLISH"
        score = 0.6
    elif change_24h < -3:
        impact = "BEARISH"
        score = 0.4
    else:
        impact = "NEUTRAL"
        score = 0.5

    return {
        "impact": impact,
        "score": score,
        "24h_change": change_24h,
        "rsi": rsi,
    }


def f1_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
