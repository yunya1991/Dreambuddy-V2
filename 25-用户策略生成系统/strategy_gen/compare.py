"""
25-用户策略生成系统 - 基线对比机制

对比用户策略与基线策略的回测指标，综合评分后给出推荐。
推荐但不强制 - 用户可自主选择。
"""
from typing import Any, Dict, Optional

# 综合评分权重
_WEIGHT_PF = 0.3
_WEIGHT_DD = 0.2
_WEIGHT_WR = 0.2
_WEIGHT_SHARPE = 0.3

# 最低交易次数阈值
MIN_TRADES = 80


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def compute_score(metrics: Dict[str, Any]) -> float:
    """计算综合评分: score = pf*0.3 + (1-dd)*0.2 + wr*0.2 + sharpe*0.3"""
    pf = _safe_float(metrics.get("profit_factor"))
    dd = _safe_float(metrics.get("max_drawdown_pct")) / 100.0  # 转为 0-1
    wr = _safe_float(metrics.get("winrate")) / 100.0  # 转为 0-1
    sharpe = _safe_float(metrics.get("sharpe_ratio"))
    # 限制范围避免极端值
    pf = min(max(pf, 0.0), 5.0) / 5.0  # 归一化到 0-1
    dd = min(max(dd, 0.0), 1.0)
    wr = min(max(wr, 0.0), 1.0)
    sharpe = min(max(sharpe, 0.0), 5.0) / 5.0  # 归一化到 0-1
    return pf * _WEIGHT_PF + (1 - dd) * _WEIGHT_DD + wr * _WEIGHT_WR + sharpe * _WEIGHT_SHARPE


def _is_valid(metrics: Dict[str, Any]) -> bool:
    """检查回测结果是否有效（交易次数 >= 阈值）"""
    trades = int(_safe_float(metrics.get("trades"), 0))
    return trades >= MIN_TRADES


def compare_with_baseline(
    user_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    对比用户策略与基线策略。

    返回:
        winner: "user" | "baseline"
        user_score, baseline_score: 综合评分
        delta: 各维度差值
        recommendation: "adopt_user" | "recommend_baseline"
    """
    user_valid = _is_valid(user_metrics)
    baseline_valid = _is_valid(baseline_metrics)

    if not user_valid and not baseline_valid:
        return {
            "winner": "baseline",
            "user_score": 0.0,
            "baseline_score": 0.0,
            "delta": {},
            "recommendation": "recommend_baseline",
            "reason": "两者交易次数均不足",
        }
    if not user_valid:
        return {
            "winner": "baseline",
            "user_score": 0.0,
            "baseline_score": compute_score(baseline_metrics),
            "delta": {},
            "recommendation": "recommend_baseline",
            "reason": "用户策略交易次数不足",
        }
    if not baseline_valid:
        return {
            "winner": "user",
            "user_score": compute_score(user_metrics),
            "baseline_score": 0.0,
            "delta": {},
            "recommendation": "adopt_user",
            "reason": "基线策略交易次数不足",
        }

    user_score = compute_score(user_metrics)
    baseline_score = compute_score(baseline_metrics)

    delta = {
        "profit_factor": _safe_float(user_metrics.get("profit_factor")) - _safe_float(baseline_metrics.get("profit_factor")),
        "max_drawdown_pct": _safe_float(user_metrics.get("max_drawdown_pct")) - _safe_float(baseline_metrics.get("max_drawdown_pct")),
        "winrate": _safe_float(user_metrics.get("winrate")) - _safe_float(baseline_metrics.get("winrate")),
        "sharpe_ratio": _safe_float(user_metrics.get("sharpe_ratio")) - _safe_float(baseline_metrics.get("sharpe_ratio")),
    }

    if user_score >= baseline_score:
        winner = "user"
        recommendation = "adopt_user"
        reason = "用户策略综合评分优于基线"
    else:
        winner = "baseline"
        recommendation = "recommend_baseline"
        reason = "用户策略综合评分低于基线，建议采用基线策略"

    return {
        "winner": winner,
        "user_score": round(user_score, 4),
        "baseline_score": round(baseline_score, 4),
        "delta": {k: round(v, 4) for k, v in delta.items()},
        "recommendation": recommendation,
        "reason": reason,
    }
