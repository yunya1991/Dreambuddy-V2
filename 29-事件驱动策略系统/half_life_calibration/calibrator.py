"""半衰期校准器 — Optuna 贝叶斯优化。

SPEC-Phase2 §5.2 (M4): 4 个半衰期为经验假设 v0，待 Phase 3 回测校准。

校准逻辑：
  1. 对单个事件类型，在 τ ∈ [tau_min, tau_max] 范围内搜索
  2. 目标函数：最大化事件后 mean_car（事件研究法）
  3. 采样器：TPE（Optuna 默认，适合小样本单峰优化）
  4. FAIL-OPEN：事件不足时返回 v0 先验值 + 低置信度标记

输出 CalibrationResult:
  - event_type: 事件类型
  - half_life: 最优半衰期
  - mean_car: 最优 CAR
  - win_rate: 胜率
  - n_events: 有效事件数
  - confidence: 置信度（high/medium/low）
  - v0_prior: 原始经验假设值
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from half_life_calibration.event_study import compute_car

logger = logging.getLogger(__name__)

# 经验假设 v0 先验值（SPEC §5.2 M4）
V0_PRIORS = {
    "fomc": 3.0,
    "cpi": 2.0,
    "nfp": 1.5,
    "ppi": 1.0,
    "tech_upgrade": 1.0,
    "fed_speech": 2.0,
    "sec_deadline": 1.5,
    "congressional_hearing": 2.5,
}

_MIN_EVENTS_FOR_CALIBRATION = 5


def calibrate_half_life(
    event_type: str,
    events: list[dict],
    prices: pd.DataFrame,
    tau_range: tuple[float, float] = (0.5, 5.0),
    n_trials: int = 50,
    hold_days_mult: float = 2.0,
) -> dict[str, Any]:
    """贝叶斯优化单个事件类型的半衰期 τ。

    Args:
        event_type: 事件类型（用于查 v0 先验）
        events: 事件列表
        prices: K 线数据
        tau_range: τ 搜索范围 (min, max)
        n_trials: Optuna 试验次数
        hold_days_mult: 持有期倍数

    Returns:
        CalibrationResult dict
    """
    v0_prior = V0_PRIORS.get(event_type, 2.0)
    tau_min, tau_max = tau_range

    # FAIL-OPEN: 事件不足返回 v0 + 低置信度
    non_neutral = [e for e in events if e.get("direction") != "neutral"]
    if len(non_neutral) < _MIN_EVENTS_FOR_CALIBRATION:
        return {
            "event_type": event_type,
            "half_life": v0_prior,
            "mean_car": 0.0,
            "win_rate": 0.0,
            "n_events": len(non_neutral),
            "confidence": "low",
            "v0_prior": v0_prior,
            "note": f"事件数不足({len(non_neutral)}<{_MIN_EVENTS_FOR_CALIBRATION})，返回 v0 先验",
        }

    try:
        import optuna
        from optuna.samplers import TPESampler
    except ImportError:
        logger.warning("Optuna 未安装，回退到网格搜索")
        return _grid_search(
            event_type, events, prices, tau_range, hold_days_mult, v0_prior
        )

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        tau = trial.suggest_float("tau", tau_min, tau_max)
        result = compute_car(events, prices, half_life=tau, hold_days_mult=hold_days_mult)
        return result["mean_car"]

    sampler = TPESampler(seed=42)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_tau = study.best_params["tau"]
    best_result = compute_car(events, prices, half_life=best_tau, hold_days_mult=hold_days_mult)

    # 置信度：基于事件数和 CAR 显著性
    n = best_result["n_events"]
    if n >= 30:
        confidence = "high"
    elif n >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "event_type": event_type,
        "half_life": round(best_tau, 3),
        "mean_car": round(best_result["mean_car"], 6),
        "win_rate": round(best_result["win_rate"], 3),
        "n_events": n,
        "confidence": confidence,
        "v0_prior": v0_prior,
        "note": "合成数据校准结果，真实数据到位后需重跑",
    }


def _grid_search(
    event_type: str,
    events: list[dict],
    prices: pd.DataFrame,
    tau_range: tuple[float, float],
    hold_days_mult: float,
    v0_prior: float,
) -> dict[str, Any]:
    """Optuna 不可用时的回退方案：网格搜索。"""
    tau_min, tau_max = tau_range
    taus = [tau_min + i * (tau_max - tau_min) / 20 for i in range(21)]

    best_tau = v0_prior
    best_car = -float("inf")
    best_result = {"mean_car": 0.0, "win_rate": 0.0, "n_events": 0}

    for tau in taus:
        result = compute_car(events, prices, half_life=tau, hold_days_mult=hold_days_mult)
        if result["mean_car"] > best_car and result["n_events"] > 0:
            best_car = result["mean_car"]
            best_tau = tau
            best_result = result

    n = best_result["n_events"]
    confidence = "high" if n >= 30 else ("medium" if n >= 10 else "low")

    return {
        "event_type": event_type,
        "half_life": round(best_tau, 3),
        "mean_car": round(best_result["mean_car"], 6),
        "win_rate": round(best_result["win_rate"], 3),
        "n_events": n,
        "confidence": confidence,
        "v0_prior": v0_prior,
        "note": "网格搜索（Optuna 不可用），合成数据校准结果",
    }
