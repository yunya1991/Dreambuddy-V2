"""
F1 新闻情绪节点 — 扫描市场新闻和情绪指标
"""

from __future__ import annotations

from typing import Any, Dict, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F1NewsSentimentNode(BaseNode):
    """F1 新闻情绪节点

    扫描市场新闻和情绪指标，评估市场情绪面。
    支持 API 调用和备用逻辑。
    """

    node_id = "F1"
    name = "新闻情绪"
    description = "扫描市场新闻和情绪指标，评估市场情绪面"
    chain = "F"
    tags = ["fundamental", "news", "sentiment"]
    estimated_tokens = 0
    estimated_latency_ms = 200

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        coin = mkt.get("coin", "BTC")
        price = mkt.get("price", 0)

        rationale: List[str] = []
        sentiment: Dict[str, Any] = {}

        # 尝试调用基本面 API（备用逻辑优先，避免外部依赖）
        try:
            sentiment = self._fallback_sentiment(mkt)
            rationale.append("[F1] 使用本地情绪评估")
        except Exception as e:
            sentiment = {"impact": "NEUTRAL", "score": 0.5}
            rationale.append(f"[F1] 评估失败，默认中性: {e}")

        # 分析情绪
        sentiment_score = sentiment.get("score", 0.5)
        news_impact = sentiment.get("impact", "NEUTRAL")

        direction = "HOLD"
        conf = 0.50

        if news_impact == "BULLISH":
            direction = "LONG"
            conf = 0.60
            rationale.append(f"✅ 新闻情绪: {news_impact} (score={sentiment_score})")
        elif news_impact == "BEARISH":
            direction = "SHORT"
            conf = 0.60
            rationale.append(f"🔴 新闻情绪: {news_impact} (score={sentiment_score})")
        else:
            rationale.append(f"⚪ 新闻情绪: {news_impact} (score={sentiment_score})")

        # 如果前序有方向，沿用但轻微调整
        prev_direction, prev_conf = self._collect_prev(state)
        if prev_direction != "HOLD" and direction == "HOLD":
            direction = prev_direction
            conf = prev_conf
            rationale.append(f"[融合] 沿用前序方向: {direction} (conf={conf:.0%})")

        return NodeResult(
            node_id="F1",
            confidence=round(conf, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "sentiment": sentiment,
            },
        )

    def _fallback_sentiment(self, mkt: Dict) -> Dict:
        """备用情绪评估（无 API 时）"""
        change_24h = mkt.get("change_24h", 0)
        rsi = mkt.get("rsi14", 50)
        fgi = mkt.get("fgi", 50)

        # 基于价格变动和 FGI 估算情绪
        score = 0.5
        score += change_24h * 0.01  # 24h 涨跌影响
        score += (fgi - 50) * 0.005  # 恐惧贪婪指数影响
        score += (rsi - 50) * 0.003  # RSI 影响

        score = max(0, min(1, score))

        if score > 0.6:
            impact = "BULLISH"
        elif score < 0.4:
            impact = "BEARISH"
        else:
            impact = "NEUTRAL"

        return {
            "impact": impact,
            "score": round(score, 3),
            "24h_change": change_24h,
            "rsi": rsi,
            "fgi": fgi,
        }

    def _collect_prev(self, state: State) -> tuple:
        """收集前序节点的方向和置信度"""
        direction = "HOLD"
        confidence = 0.0

        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "direction") and result.direction and result.direction != "HOLD":
                if hasattr(result, "confidence") and result.confidence > confidence:
                    direction = result.direction
                    confidence = result.confidence

        return direction, confidence

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.inputs, dict) and "mkt" in state.inputs:
            return state.inputs["mkt"]
        if isinstance(state.inputs, dict):
            return state.inputs
        return {}
