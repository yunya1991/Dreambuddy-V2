"""
三维度计算引擎 (Least Resistance Analysis)
计算方向(Direction)、速度(Velocity)、加速度(Acceleration)
"""

import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


def compute_resistance_3d(raw_score: float, historical_scores: List[float] = None) -> Dict[str, Any]:
    """
    计算三维度指标
    
    Args:
        raw_score: 原始评分 (-1 to 1)
        historical_scores: 历史评分列表
    
    Returns:
        包含 direction, velocity, acceleration, confidence, data_points 的字典
    """
    if historical_scores is None:
        historical_scores = []
    
    # Direction: 基于 raw_score 判断方向
    if raw_score > 0.3:
        direction = "up"
    elif raw_score < -0.3:
        direction = "down"
    else:
        direction = "neutral"
    
    # Velocity: 计算相对于历史的速率变化
    if historical_scores:
        hist_mean = sum(historical_scores) / len(historical_scores)
        hist_std = _std(historical_scores) if len(historical_scores) > 1 else 0.3
        if hist_std > 0:
            velocity = math.tanh((raw_score - hist_mean) / hist_std)
        else:
            velocity = math.tanh(raw_score)
    else:
        velocity = math.tanh(raw_score)
    
    # Acceleration: 基于速度变化趋势
    if len(historical_scores) >= 2:
        recent_v = velocity
        prev_scores = historical_scores[-3:] if len(historical_scores) >= 3 else historical_scores
        prev_mean = sum(prev_scores) / len(prev_scores)
        acceleration = math.tanh(raw_score - prev_mean)
    else:
        acceleration = 0.0
    
    # Confidence: 置信度
    base_conf = 0.3
    score_conf = abs(raw_score) * 0.5
    history_conf = 0.2 if historical_scores else 0.0
    data_points_conf = min(0.3, len(historical_scores) * 0.02) if historical_scores else 0.0
    confidence = min(1.0, base_conf + score_conf + history_conf + data_points_conf)
    
    # Direction Score: 方向强度 (-1 to 1)
    direction_score = raw_score
    
    return {
        "direction": direction,
        "direction_score": round(direction_score, 4),
        "velocity": round(velocity, 4),
        "acceleration": round(acceleration, 4),
        "confidence": round(confidence, 4),
        "data_points": len(historical_scores) + 1 if historical_scores else 1,
        "trend_summary": summarize_trend(direction, velocity, acceleration)
    }


def generate_signal(resistance_3d: Dict[str, Any], metrics: Dict[str, Any], 
                    stress: str = "normal") -> Dict[str, Any]:
    """
    基于三维度和其他指标生成交易信号
    
    Args:
        resistance_3d: 三维度计算结果
        metrics: 其他指标（包含 sentiment 等）
        stress: 压力状态 (high, normal, low)
    
    Returns:
        信号字典
    """
    direction = resistance_3d.get("direction", "neutral")
    velocity = resistance_3d.get("velocity", 0)
    sentiment = metrics.get("sentiment", 50)  # 0-100 scale
    
    signal_id = f"sig_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    
    # 情绪判断
    sentiment_bullish = sentiment > 55
    sentiment_bearish = sentiment < 45
    sentiment_neutral = 45 <= sentiment <= 55
    
    # 强买入: up + velocity>0.1 + sentiment>55
    if direction == "up" and velocity > 0.1 and sentiment > 55:
        return _build_signal(signal_id, "strong_buy", 0.8, resistance_3d, 
                            "多项利好叠加，趋势强劲", "short", ["趋势强劲", "情绪乐观"])
    
    # 买入: up + sentiment>52
    if direction == "up" and sentiment > 52:
        return _build_signal(signal_id, "buy", 0.6, resistance_3d,
                            "上涨趋势确认", "medium", ["趋势向上", "情绪偏好"])
    
    # 强卖出: down + velocity<-0.1 + sentiment<45
    if direction == "down" and velocity < -0.1 and sentiment < 45:
        return _build_signal(signal_id, "strong_sell", 0.8, resistance_3d,
                            "空头趋势强劲，风险厌恶", "short", ["趋势下行", "情绪悲观"])
    
    # 卖出: down + sentiment<48
    if direction == "down" and sentiment < 48:
        return _build_signal(signal_id, "sell", 0.6, resistance_3d,
                            "下跌趋势确认", "medium", ["趋势向下", "情绪偏弱"])
    
    # 高压状态 -> 减仓
    if stress == "high":
        return _build_signal(signal_id, "reduce", 0.5, resistance_3d,
                            "市场压力较大，建议减仓", "short", ["市场高压", "谨慎操作"])
    
    # 中性 -> 观望
    return _build_signal(signal_id, "hold", 0.3, resistance_3d,
                        "趋势不明确，观望为主", "medium", ["趋势中性", "等待信号"])


def _build_signal(sig_id: str, sig_type: str, strength: float,
                  resistance_3d: Dict, reason: str, horizon: str,
                  factors: List[str]) -> Dict[str, Any]:
    """构建信号字典"""
    return {
        "id": sig_id,
        "type": sig_type,
        "strength": strength,
        "confidence": resistance_3d.get("confidence", 0.5),
        "reason": reason,
        "horizon": horizon,
        "factors": factors,
        "created_at": datetime.now(timezone.utc).isoformat()
    }


def summarize_trend(direction: str, velocity: float, acceleration: float) -> str:
    """
    生成趋势描述文本
    
    Args:
        direction: 方向 (up/down/neutral)
        velocity: 速度
        acceleration: 加速度
    
    Returns:
        中文趋势描述
    """
    if direction == "up":
        if velocity > 0.5 and acceleration > 0:
            return "多方主导，趋势强劲加速中"
        elif velocity > 0.3:
            return "多方主导，趋势增强中"
        elif velocity > 0.1:
            return "多方略占优势"
        else:
            return "上涨意愿不强，谨慎观望"
    
    elif direction == "down":
        if velocity < -0.5 and acceleration < 0:
            return "空方主导，趋势加速下行"
        elif velocity < -0.3:
            return "空方主导，趋势减弱中"
        elif velocity < -0.1:
            return "空方略占优势"
        else:
            return "下跌意愿不强，谨慎观望"
    
    else:
        return "多空僵持，趋势不明"


def _std(data: List[float]) -> float:
    """计算标准差"""
    if len(data) < 2:
        return 0.0
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)
    return math.sqrt(variance)


def compute_composite_score(module_metrics: Dict[str, float]) -> float:
    """
    计算综合评分
    
    Args:
        module_metrics: 各模块的原始评分
    
    Returns:
        综合评分 (-1 to 1)
    """
    if not module_metrics:
        return 0.0
    
    # 简单平均
    raw = sum(module_metrics.values()) / len(module_metrics)
    return max(-1.0, min(1.0, raw))
