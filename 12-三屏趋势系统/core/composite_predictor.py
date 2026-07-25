"""三屏趋势系统 — 综合预测引擎（Path B 增强版）

设计理念：
- 技术面为基线（静态指标 + 三维动态融合）
- 基本面为主要调节因子（方向/速度/加速度三维度）
- 动态算法优先于静态指标
- 基本面信号通过三维度模型影响最终决策

架构：
    输入层: 技术面 + 基本面原始数据
        ↓
    处理层: 
        - 技术面: 三屏趋势一致性检测 + 动态权重
        - 基本面: 三维度(方向/速度/加速度) + SignalEngine + SentimentEngine
        ↓
    融合层: 技术基线 × 基本面调节因子
        ↓
    输出层: 最终方向 + 置信度 + 信号

核心公式:
    final_confidence = tech_confidence × (1 + fundamental_adjustment)
    fundamental_adjustment = f(direction_match, velocity, acceleration, sentiment)
"""

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── 导入9-基本面分析模块 ──
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "9-基本面分析"))
    from engines.least_resistance import compute_composite_score, compute_resistance_3d
    from engines.sentiment_engine import SentimentEngine, create_sentiment_engine
    from engines.signal_engine import SignalEngine, create_signal_engine

    FUNDAMENTAL_ENGINES_AVAILABLE = True
except ImportError:
    FUNDAMENTAL_ENGINES_AVAILABLE = False
    SignalEngine = None
    SentimentEngine = None
    compute_resistance_3d = None
    compute_composite_score = None

# ── 默认权重配置 ──
DEFAULT_WEIGHTS = {
    "technical_base": 0.6,  # 技术面基线权重
    "fundamental_adjust": 0.4,  # 基本面调节权重
    "direction_factor": 0.3,  # 方向匹配因子
    "velocity_factor": 0.3,  # 速度因子
    "acceleration_factor": 0.2,  # 加速度因子
    "sentiment_factor": 0.2,  # 情绪因子
}


class CompositePredictor:
    """综合预测引擎"""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or DEFAULT_WEIGHTS
        self.signal_engine = None
        self.sentiment_engine = None
        if FUNDAMENTAL_ENGINES_AVAILABLE:
            self.signal_engine = create_signal_engine()
            self.sentiment_engine = create_sentiment_engine()

    def _normalize_weights(self):
        total = self.weights.get("technical_base", 0.6) + self.weights.get(
            "fundamental_adjust", 0.4
        )
        if total != 1.0:
            self.weights["technical_base"] /= total
            self.weights["fundamental_adjust"] /= total

    def compute_fundamental_3d(
        self, fundamental_data: Dict[str, Any], historical_scores: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        计算基本面三维度（方向/速度/加速度）

        参数:
            fundamental_data: 基本面原始数据
            historical_scores: 历史评分列表

        返回:
            三维度分析结果
        """
        if not FUNDAMENTAL_ENGINES_AVAILABLE or not fundamental_data:
            return {
                "available": False,
                "direction": "neutral",
                "direction_score": 0.0,
                "velocity": 0.0,
                "acceleration": 0.0,
                "confidence": 0.0,
                "error": "基本面引擎不可用",
            }

        try:
            raw_score = 0.0
            score_sources = []

            if "score" in fundamental_data:
                raw_score += float(fundamental_data["score"]) * 0.3
                score_sources.append("fundamental_score")

            if "direction" in fundamental_data:
                dir_map = {"BULL": 0.5, "BEAR": -0.5, "NEUTRAL": 0}
                raw_score += dir_map.get(fundamental_data["direction"], 0) * 0.3
                score_sources.append("direction")

            if "confidence" in fundamental_data:
                conf_score = (float(fundamental_data["confidence"]) / 100) * 0.2
                raw_score += conf_score * (1 if raw_score >= 0 else -1)
                score_sources.append("confidence")

            if "dimensions" in fundamental_data:
                dims = fundamental_data["dimensions"]
                for dim_name, dim_data in dims.items():
                    if dim_data.get("available", False):
                        dim_score = float(dim_data.get("score", 0)) / 20
                        raw_score += dim_score * 0.05
                        score_sources.append(dim_name)

            raw_score = max(-1.0, min(1.0, raw_score))

            result = compute_resistance_3d(raw_score, historical_scores)
            result["available"] = True
            result["score_sources"] = score_sources

            return result

        except Exception as e:
            return {
                "available": False,
                "direction": "neutral",
                "direction_score": 0.0,
                "velocity": 0.0,
                "acceleration": 0.0,
                "confidence": 0.0,
                "error": f"三维度计算失败: {str(e)[:50]}",
            }

    def analyze_sentiment(self, texts: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        分析情绪（来自9-基本面分析的SentimentEngine）

        参数:
            texts: 文本列表

        返回:
            情绪分析结果
        """
        if not self.sentiment_engine or not texts:
            return {
                "available": False,
                "sentiment": "neutral",
                "sentiment_index": 50,
                "score": 0.0,
            }

        try:
            result = self.sentiment_engine.analyze_batch(texts)
            return {
                "available": True,
                "sentiment": result["sentiment"],
                "sentiment_index": result["sentiment_index"],
                "score": result["score"],
                "count": result["count"],
                "positive_count": result["positive_count"],
                "negative_count": result["negative_count"],
                "category_distribution": result["category_distribution"],
                "fear_greed": self.sentiment_engine.get_fear_greed_estimate(
                    result["sentiment_index"]
                ),
            }
        except Exception as e:
            return {
                "available": False,
                "sentiment": "neutral",
                "sentiment_index": 50,
                "score": 0.0,
                "error": f"情绪分析失败: {str(e)[:50]}",
            }

    def generate_signals(
        self,
        resistance_3d: Dict[str, Any],
        metrics: Dict[str, Any],
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        生成交易信号（来自9-基本面分析的SignalEngine）

        参数:
            resistance_3d: 三维度计算结果
            metrics: 指标数据
            events: 事件列表

        返回:
            信号列表
        """
        if not self.signal_engine or not resistance_3d.get("available", False):
            return []

        try:
            signals = self.signal_engine.generate_signals(resistance_3d, metrics, events)
            return self.signal_engine.rank_signals(signals)
        except Exception:
            return []

    def compute_fundamental_adjustment(
        self,
        tech_direction: str,
        fundamental_3d: Dict[str, Any],
        sentiment_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        计算基本面调节因子

        参数:
            tech_direction: 技术面方向 "BULL"/"BEAR"/"NEUTRAL"
            fundamental_3d: 基本面三维度分析结果
            sentiment_result: 情绪分析结果

        返回:
            调节因子分析结果
        """
        if not fundamental_3d.get("available", False):
            return {
                "adjustment": 0.0,
                "adjustment_type": "none",
                "reason": "基本面不可用，不调整",
                "breakdown": {},
            }

        direction_factor = self.weights.get("direction_factor", 0.3)
        velocity_factor = self.weights.get("velocity_factor", 0.3)
        acceleration_factor = self.weights.get("acceleration_factor", 0.2)
        sentiment_factor = self.weights.get("sentiment_factor", 0.2)

        fund_dir = fundamental_3d.get("direction", "neutral")
        fund_dir_score = fundamental_3d.get("direction_score", 0.0)
        velocity = fundamental_3d.get("velocity", 0.0)
        acceleration = fundamental_3d.get("acceleration", 0.0)

        tech_core = tech_direction
        if tech_core.startswith("REVERSAL_"):
            tech_core = "BULL" if tech_core == "REVERSAL_BULL" else "BEAR"

        dir_match = 0.0
        if tech_core != "NEUTRAL":
            if fund_dir == "up" and tech_core == "BULL":
                dir_match = 1.0
            elif fund_dir == "down" and tech_core == "BEAR":
                dir_match = 1.0
            elif fund_dir == "up" and tech_core == "BEAR":
                dir_match = -1.0
            elif fund_dir == "down" and tech_core == "BULL":
                dir_match = -1.0

        sentiment_score = 0.0
        if sentiment_result.get("available", False):
            sentiment_score = sentiment_result.get("score", 0.0)

        adj_direction = dir_match * direction_factor
        adj_velocity = velocity * velocity_factor
        adj_acceleration = acceleration * acceleration_factor
        adj_sentiment = sentiment_score * sentiment_factor

        total_adjustment = adj_direction + adj_velocity + adj_acceleration + adj_sentiment

        adjustment_type = "none"
        if total_adjustment > 0.15:
            adjustment_type = "enhance"
        elif total_adjustment < -0.15:
            adjustment_type = "weaken"
        elif total_adjustment != 0:
            adjustment_type = "fine_tune"

        reasons = []
        if abs(adj_direction) > 0.05:
            reasons.append(
                f"方向{'一致增强' if adj_direction > 0 else '矛盾减弱'}({adj_direction:+.2f})"
            )
        if abs(adj_velocity) > 0.05:
            reasons.append(f"速度{'正向' if adj_velocity > 0 else '负向'}({adj_velocity:+.2f})")
        if abs(adj_acceleration) > 0.05:
            reasons.append(
                f"加速度{'正向' if adj_acceleration > 0 else '负向'}({adj_acceleration:+.2f})"
            )
        if abs(adj_sentiment) > 0.05:
            reasons.append(f"情绪{'偏多' if adj_sentiment > 0 else '偏空'}({adj_sentiment:+.2f})")

        reason = "; ".join(reasons) if reasons else "基本面调节因子较小"

        return {
            "adjustment": round(total_adjustment, 4),
            "adjustment_type": adjustment_type,
            "reason": reason,
            "breakdown": {
                "direction": round(adj_direction, 4),
                "velocity": round(adj_velocity, 4),
                "acceleration": round(adj_acceleration, 4),
                "sentiment": round(adj_sentiment, 4),
            },
            "fundamental_direction": fund_dir,
            "fundamental_direction_score": fund_dir_score,
            "velocity": velocity,
            "acceleration": acceleration,
            "sentiment_score": sentiment_score,
        }

    def predict(
        self,
        tech_result: Dict[str, Any],
        fundamental_data: Dict[str, Any],
        sentiment_texts: Optional[List[str]] = None,
        historical_scores: Optional[List[float]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        综合预测主入口

        参数:
            tech_result: 技术面分析结果
                {"direction": str, "confidence": float}
            fundamental_data: 基本面数据
                calc_fundamental_screen1() 返回的结果或类似结构
            sentiment_texts: 情绪分析文本列表
            historical_scores: 历史评分列表（用于三维度计算）
            events: 事件列表

        返回:
            综合预测结果
        """
        tech_direction = tech_result.get("direction", "NEUTRAL")
        tech_confidence = float(tech_result.get("confidence", 0.0))

        fundamental_3d = self.compute_fundamental_3d(fundamental_data, historical_scores)

        sentiment_result = self.analyze_sentiment(sentiment_texts)

        signals = []
        if fundamental_3d.get("available", False):
            metrics = {}
            if sentiment_result.get("available", False):
                metrics["sentiment"] = sentiment_result.get("sentiment_index", 50)
                metrics["fear_greed_index"] = sentiment_result.get("sentiment_index", 50)
            if fundamental_data.get("dimensions"):
                for dim_name, dim_data in fundamental_data["dimensions"].items():
                    if dim_data.get("available", False):
                        metrics[dim_name] = dim_data.get("score", 0)
            signals = self.generate_signals(fundamental_3d, metrics, events)

        adjustment = self.compute_fundamental_adjustment(
            tech_direction, fundamental_3d, sentiment_result
        )

        tech_weight = self.weights.get("technical_base", 0.6)
        fund_weight = self.weights.get("fundamental_adjust", 0.4)

        final_confidence = tech_confidence * (1 + adjustment["adjustment"] * fund_weight)
        final_confidence = max(0.0, min(100.0, final_confidence))

        final_direction = tech_direction
        if adjustment["adjustment_type"] == "weaken" and final_confidence < 20:
            final_direction = "NEUTRAL"

        signal_summary = ""
        if signals:
            signal_summary = (
                self.signal_engine.generate_summary(signals, top_n=3) if self.signal_engine else ""
            )

        return {
            "direction": final_direction,
            "confidence": round(final_confidence, 2),
            "technical": {
                "direction": tech_direction,
                "confidence": tech_confidence,
            },
            "fundamental": {
                "3d": fundamental_3d,
                "adjustment": adjustment,
                "sentiment": sentiment_result,
                "signals": signals,
                "signal_summary": signal_summary,
            },
            "weights": {
                "technical_base": tech_weight,
                "fundamental_adjust": fund_weight,
                "direction_factor": self.weights.get("direction_factor"),
                "velocity_factor": self.weights.get("velocity_factor"),
                "acceleration_factor": self.weights.get("acceleration_factor"),
                "sentiment_factor": self.weights.get("sentiment_factor"),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def create_composite_predictor(weights: Optional[Dict[str, float]] = None) -> CompositePredictor:
    """创建综合预测引擎实例"""
    return CompositePredictor(weights)


def predict_from_dataframes(
    weekly_df,
    daily_df,
    fundamental_data: Optional[Dict[str, Any]] = None,
    sentiment_texts: Optional[List[str]] = None,
    historical_scores: Optional[List[float]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    从DataFrame计算综合预测（便捷函数）

    参数:
        weekly_df: 周线DataFrame
        daily_df: 日线DataFrame
        fundamental_data: 基本面数据
        sentiment_texts: 情绪文本列表
        historical_scores: 历史评分
        weights: 权重配置

    返回:
        综合预测结果
    """
    try:
        from .config import FUNDAMENTAL_SCREEN1_ENABLED
        from .trend_consistency import calc_trend_consistency

        trend_consistency = calc_trend_consistency(
            weekly_df, daily_df, use_fundamental=FUNDAMENTAL_SCREEN1_ENABLED
        )

        tech_result = {
            "direction": trend_consistency.get("overall_direction", "NEUTRAL"),
            "confidence": trend_consistency.get("consistency_confidence", 0.0),
            "consistency_level": trend_consistency.get("consistency_level", "STRONG_CONSISTENT"),
        }

        predictor = create_composite_predictor(weights)
        return predictor.predict(
            tech_result=tech_result,
            fundamental_data=fundamental_data or {},
            sentiment_texts=sentiment_texts,
            historical_scores=historical_scores,
        )

    except ImportError:
        from config import FUNDAMENTAL_SCREEN1_ENABLED
        from trend_consistency import calc_trend_consistency

        trend_consistency = calc_trend_consistency(
            weekly_df, daily_df, use_fundamental=FUNDAMENTAL_SCREEN1_ENABLED
        )

        tech_result = {
            "direction": trend_consistency.get("overall_direction", "NEUTRAL"),
            "confidence": trend_consistency.get("consistency_confidence", 0.0),
            "consistency_level": trend_consistency.get("consistency_level", "STRONG_CONSISTENT"),
        }

        predictor = create_composite_predictor(weights)
        return predictor.predict(
            tech_result=tech_result,
            fundamental_data=fundamental_data or {},
            sentiment_texts=sentiment_texts,
            historical_scores=historical_scores,
        )

    except Exception as e:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "error": f"综合预测失败: {str(e)[:100]}",
        }
