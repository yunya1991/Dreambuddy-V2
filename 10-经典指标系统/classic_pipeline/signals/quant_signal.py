"""Quant 信号生成（纯函数）。

从单体提取 quant 信号决策逻辑：
- signal_confidence: 基于规则的置信度计算（bias + 权重*特征 + tag_bias）
- strategy_weight: 策略权重调整（基于 PF/最大回撤）
- compute: 多策略投票 + 风险门控

所有函数为纯函数，不依赖全局状态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from classic_pipeline.core.utils import _clip, _sf0


# ---------------------------------------------------------------------------
# 置信度计算
# ---------------------------------------------------------------------------

def signal_confidence(
    strategy_id: str,
    group_id: str,
    tag: Any,
    features: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
) -> float:
    """基于规则的信号置信度计算。

    从单体 _signal_confidence 提取的纯函数版本。

    Args:
        strategy_id: 策略 ID
        group_id: 规则组 ID
        tag: 信号标签
        features: 特征字典
        rules: 置信度规则（替代全局 CONFIG["signal_confidence_rules"]）

    Returns:
        置信度 [0, 1]
    """
    gid = str(group_id or "").strip()
    if not isinstance(rules, dict):
        return 1.0
    rule = rules.get(gid)
    if not isinstance(rule, dict):
        return 1.0

    bias = _sf0(rule.get("bias"), 1.0)

    # 特征权重加权
    w = rule.get("w")
    if isinstance(w, dict):
        for k, wk in w.items():
            bias += _sf0(wk, 0.0) * _sf0((features or {}).get(k), 0.0)

    # tag 偏差
    tb = rule.get("tag_bias")
    if isinstance(tb, dict):
        t = "" if tag is None else str(tag)
        bias += _sf0(tb.get(t), 0.0)

    return float(_clip(float(bias), 0.0, 1.0))


# ---------------------------------------------------------------------------
# 策略权重
# ---------------------------------------------------------------------------

def strategy_weight(
    current: float,
    perf: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> float:
    """基于绩效的策略权重调整。

    从单体 _strategy_weight_get + _strategy_reward_apply 提取。

    Args:
        current: 当前权重
        perf: 绩效 {"pf": 盈亏比, "maxdd": 最大回撤}
        config: 配置

    Returns:
        调整后的权重 [floor, cap]
    """
    cfg = config or {}
    floor = float(cfg.get("weight_floor", 0.25))
    cap = float(cfg.get("weight_cap", 2.0))
    v = _clip(_sf0(current, 1.0), floor, cap)

    if not perf:
        return v

    enabled = bool(cfg.get("reward_enabled", True))
    if not enabled:
        return v

    pf = _sf0(perf.get("pf"), 0.0)
    maxdd = _sf0(perf.get("maxdd"), 0.0)
    pf_up = float(cfg.get("reward_pf_up", 1.2))
    pf_down = float(cfg.get("reward_pf_down", 0.9))
    dd_up = float(cfg.get("reward_maxdd_up", 0.12))
    dd_down = float(cfg.get("reward_maxdd_down", 0.20))
    step_up = float(cfg.get("reward_step_up", 0.05))
    step_down = float(cfg.get("reward_step_down", 0.07))

    if pf >= pf_up and maxdd <= dd_up:
        v = _clip(v * (1.0 + step_up), floor, cap)
    elif pf <= pf_down or maxdd >= dd_down:
        v = _clip(v * (1.0 - step_down), floor, cap)

    return v


# ---------------------------------------------------------------------------
# 策略绩效计算
# ---------------------------------------------------------------------------

def strategy_perf(rets: List[float], config: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """从收益率序列计算策略绩效。

    Returns:
        {"pf": 盈亏比, "maxdd": 最大回撤, "n": 样本数}
    """
    cfg = config or {}
    eps = float(cfg.get("loss_eps", 1e-6))
    if not rets:
        return {"pf": 0.0, "maxdd": 0.0, "n": 0}

    gp = 0.0
    gl = 0.0
    eq = 1.0
    peak = 1.0
    maxdd = 0.0
    for r in rets:
        rr = float(r)
        if rr >= 0:
            gp += rr
        else:
            gl += -rr
        eq *= (1.0 + rr)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0.0 else 0.0
        if dd > maxdd:
            maxdd = dd

    pf = gp / max(gl, eps)
    return {"pf": float(pf), "maxdd": float(maxdd), "n": len(rets)}


# ---------------------------------------------------------------------------
# 多策略投票
# ---------------------------------------------------------------------------

def vote(
    strategy_signals: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """多策略信号投票。

    Args:
        strategy_signals: 各策略信号 [{direction, confidence, weight, strategy_id}]
        config: 配置

    Returns:
        {dominant_direction, confidence, votes}
    """
    cfg = config or {}
    if not strategy_signals:
        return {"dominant_direction": "neutral", "confidence": 0.0, "votes": {}}

    long_score = 0.0
    short_score = 0.0
    total_weight = 0.0

    for sig in strategy_signals:
        direction = str(sig.get("direction") or "neutral").strip().lower()
        conf = _sf0(sig.get("confidence"), 0.0)
        weight = _sf0(sig.get("weight"), 1.0)
        score = conf * weight
        total_weight += weight
        if direction == "long":
            long_score += score
        elif direction == "short":
            short_score += score

    if total_weight <= 0:
        return {"dominant_direction": "neutral", "confidence": 0.0, "votes": {}}

    dominant = "neutral"
    confidence = 0.0
    if long_score > short_score and long_score > 0:
        dominant = "long"
        confidence = long_score / total_weight
    elif short_score > long_score and short_score > 0:
        dominant = "short"
        confidence = short_score / total_weight

    return {
        "dominant_direction": dominant,
        "confidence": _clip(confidence, 0.0, 1.0),
        "votes": {"long": long_score, "short": short_score, "total_weight": total_weight},
    }


# ---------------------------------------------------------------------------
# 风险门控
# ---------------------------------------------------------------------------

def risk_gate(
    signal: Dict[str, Any],
    portfolio_state: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """风险门控（参考传统金融 Risk Gatekeeper 设计）。

    Args:
        signal: 信号 {direction, confidence}
        portfolio_state: 组合状态 {equity, positions, ...}
        config: 配置

    Returns:
        {approved, position_size, stop_loss, take_profit, reason}
    """
    cfg = config or {}
    ps = portfolio_state or {}

    direction = str(signal.get("direction") or "neutral").strip().lower()
    if direction not in ("long", "short"):
        return {"approved": False, "position_size": 0.0, "reason": "no_direction"}

    equity = _sf0(ps.get("equity"), 0.0)
    if equity <= 0:
        return {"approved": False, "position_size": 0.0, "reason": "no_equity"}

    # 单笔最大风险 2%
    max_risk_pct = float(cfg.get("max_risk_pct", 0.02))
    risk_amount = equity * max_risk_pct

    # 止损距离（基于 ATR 或固定比例）
    atr_pct = float(cfg.get("atr_pct", 0.02))
    stop_distance = atr_pct

    # 仓位大小
    if stop_distance > 0:
        position_size = risk_amount / (equity * stop_distance)
    else:
        position_size = float(cfg.get("default_position_pct", 0.1))

    # 最大仓位限制
    max_position_pct = float(cfg.get("max_position_pct", 0.1))
    position_size = _clip(position_size, 0.0, max_position_pct)

    return {
        "approved": True,
        "position_size": position_size,
        "stop_loss": stop_distance,
        "take_profit": stop_distance * float(cfg.get("reward_risk_ratio", 2.0)),
        "reason": "",
    }


# ---------------------------------------------------------------------------
# 最终信号计算
# ---------------------------------------------------------------------------

def compute(
    df: Optional[pd.DataFrame],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Quant 信号最终计算。

    简化版本：基于趋势指标生成多策略信号并投票。

    Args:
        df: OHLCV DataFrame
        config: 配置

    Returns:
        {signals, dominant_direction, confidence, details}
    """
    cfg = config or {}
    if df is None or len(df) < 20:
        return {"signals": [], "dominant_direction": "neutral", "confidence": 0.0, "details": {}}

    try:
        from classic_pipeline.indicators.trend import ema, macd
        from classic_pipeline.indicators.momentum import rsi

        close = df["close"]
        ema_fast = ema(df, period=int(cfg.get("ema_fast", 12)))
        ema_slow = ema(df, period=int(cfg.get("ema_slow", 26)))
        rsi_val = rsi(df, period=14)
        macd_val = macd(df)

        signals: List[Dict[str, Any]] = []

        # 策略1: EMA 交叉
        ema_dir = "neutral"
        if len(ema_fast) > 0 and len(ema_slow) > 0:
            if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
                ema_dir = "long"
            elif ema_fast.iloc[-1] < ema_slow.iloc[-1]:
                ema_dir = "short"
        if ema_dir != "neutral":
            signals.append({
                "strategy_id": "ema_cross",
                "direction": ema_dir,
                "confidence": 0.6,
                "weight": 1.0,
            })

        # 策略2: RSI 超买超卖
        rsi_dir = "neutral"
        if len(rsi_val) > 0:
            r = float(rsi_val.iloc[-1])
            if r < 30:
                rsi_dir = "long"
            elif r > 70:
                rsi_dir = "short"
        if rsi_dir != "neutral":
            signals.append({
                "strategy_id": "rsi_reversal",
                "direction": rsi_dir,
                "confidence": 0.5,
                "weight": 0.8,
            })

        # 策略3: MACD 柱状
        macd_dir = "neutral"
        if len(macd_val) > 0:
            hist = float(macd_val["histogram"].iloc[-1])
            if hist > 0:
                macd_dir = "long"
            elif hist < 0:
                macd_dir = "short"
        if macd_dir != "neutral":
            signals.append({
                "strategy_id": "macd_hist",
                "direction": macd_dir,
                "confidence": 0.55,
                "weight": 0.9,
            })

        # 多策略投票
        vote_result = vote(signals, cfg)

        return {
            "signals": signals,
            "dominant_direction": vote_result["dominant_direction"],
            "confidence": vote_result["confidence"],
            "details": {"votes": vote_result["votes"]},
        }
    except Exception:
        return {"signals": [], "dominant_direction": "neutral", "confidence": 0.0, "details": {}}
