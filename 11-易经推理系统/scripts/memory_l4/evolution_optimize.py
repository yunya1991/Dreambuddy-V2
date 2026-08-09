#!/usr/bin/env python3
"""
evolution_optimize.py — PROP-20260809-002: 提案参数值数据驱动化（Optuna）

设计（Z3 规划）:
  - 反思层（A8/做梦部/联网）决定"调哪个参数、往哪个方向调"；
    本模块用 Optuna 在本地 klines walk-forward 上定"调多少"。
  - 搜索空间由方向约束（lower/raise/around），不做全域盲搜。
  - 仅对有真实引擎消费点的参数做寻优（_PARAM_TO_ENGINE_FIELD）；
    影子参数直接返回原值并标注 value_source="shadow_no_consumer"。
  - 失败/超时/无 optuna → 原值 + value_source="default_fallback"（不中断进化）。

数据源: 本地 klines（scripts/data/klines/），不依赖外网（交易所 API 被封锁）。

依赖:
  - optuna（可选，未安装自动降级）
  - evolution_backtest.py（walk-forward 基础设施复用）
"""
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 复用 PROP-001 基础设施
from scripts.memory_l4.evolution_backtest import (   # noqa: E402
    _PARAM_TO_ENGINE_FIELD,
    bars_to_walk_forward_data,
    load_local_bars,
    _run_walk_forward,
    MIN_BARS_FOR_BACKTEST,
)

# ── 寻优配置（Z3 规划: 控成本）────────────────────────────────────────────────
OPTUNA_N_TRIALS   = 30     # 最大试验次数（硬上限）
OPTUNA_TIMEOUT_S  = 120    # 总超时秒数（硬切）
OPTUNA_MAX_BARS   = 150    # 寻优用更小的数据窗口（速度优先）
OPTUNA_MIN_BARS   = 60     # 低于此数直接降级

# 方向 → 搜索空间（相对当前值的比例区间）
_DIRECTION_BOUNDS = {
    "lower":  (0.5, 0.999),   # [current*0.5, current)
    "raise":  (1.001, 1.5),   # (current, current*1.5]
    "around": (0.8, 1.2),     # ±20%
}

# 参数值域绝对上下限（防比例区间越界）
_ABS_BOUNDS = {
    "min_confidence_threshold": (0.05, 0.90),
}


def _resolve_search_space(param_key: str,
                          direction: str,
                          current_value: float
                          ) -> Tuple[float, float]:
    """根据方向约束计算搜索区间 [lo, hi]。"""
    lo_ratio, hi_ratio = _DIRECTION_BOUNDS.get(direction,
                                                _DIRECTION_BOUNDS["around"])
    lo = current_value * lo_ratio
    hi = current_value * hi_ratio

    abs_lo, abs_hi = _ABS_BOUNDS.get(param_key, (0.0, float("inf")))
    lo = max(lo, abs_lo)
    hi = min(hi, abs_hi)

    if lo >= hi:  # 区间退化（current 在边界上）→ 方向感知微调（W1修复 E2审查）
        mid = max(abs_lo, min(current_value, abs_hi))
        if direction == "lower":
            lo = max(abs_lo, mid * 0.90)
            hi = mid                       # 只向下搜
        elif direction == "raise":
            lo = mid                       # 只向上搜
            hi = min(abs_hi, mid * 1.10)
        else:
            lo = max(abs_lo, mid * 0.95)
            hi = min(abs_hi, mid * 1.05)
        if lo >= hi:  # 仍退化（卡死在绝对边界）→ 空区间由调用方回退
            return mid, mid
    return lo, hi


def optimize_proposal_value(param_key: str,
                            direction: str,
                            current_value: float,
                            symbol: str = "BTC",
                            timeframe: str = "1H",
                            n_trials: int = OPTUNA_N_TRIALS,
                            timeout_s: int = OPTUNA_TIMEOUT_S
                            ) -> Tuple[float, str]:
    """
    为进化提案的参数值做数据驱动寻优。

    Args:
        param_key: 参数名（self_evolution_engine 白名单内）
        direction: "lower"|"raise"|"around"（反思层意图）
        current_value: 当前值/默认值（寻优起点与搜索空间锚点）
        symbol/timeframe: 本地 K 线选择
        n_trials/timeout_s: Optuna 预算上限

    Returns:
        (best_value, value_source)
        value_source ∈ {"optuna", "shadow_no_consumer", "default_fallback"}
    """
    # ── 影子参数: 无消费点，寻优无意义 ────────────────────────────────────
    if param_key not in _PARAM_TO_ENGINE_FIELD:
        logger.info("影子参数跳过寻优: %s", param_key)
        return current_value, "shadow_no_consumer"

    try:
        current_value = float(current_value)
    except (TypeError, ValueError):
        return current_value, "default_fallback"

    # ── optuna 可用性 ─────────────────────────────────────────────────────
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("optuna 未安装，提案值降级为默认")
        return current_value, "default_fallback"

    # ── 数据准备 ──────────────────────────────────────────────────────────
    bars = load_local_bars(symbol, timeframe, OPTUNA_MAX_BARS)
    if len(bars) < OPTUNA_MIN_BARS:
        logger.warning("寻优降级: bars=%d < %d", len(bars), OPTUNA_MIN_BARS)
        return current_value, "default_fallback"

    data = bars_to_walk_forward_data(bars)
    train_w = min(30, max(20, len(data) // 4))
    test_w  = min(5, max(3, len(data) // 10))
    step    = 15

    lo, hi = _resolve_search_space(param_key, direction, current_value)
    if lo >= hi:  # W1修复: 空区间（卡死在绝对边界）→ 回退默认值
        logger.warning("寻优区间退化为空 [%s] %s: 回退默认值", direction, param_key)
        return current_value, "default_fallback"
    engine_field = _PARAM_TO_ENGINE_FIELD[param_key]

    from scripts.memory_l4.bcrm.engine import BCRMEngine

    def objective(trial: "optuna.Trial") -> float:
        val = trial.suggest_float(param_key, lo, hi)
        try:
            engine = BCRMEngine(**{engine_field: val})
            summary = _run_walk_forward(engine, data, train_w, test_w, step)
        except Exception as e:
            logger.debug("trial 回测失败 val=%r: %s", val, e)
            return -1.0  # 惩罚失败
        # 目标: 方向准确率为主，平均置信度为辅，fail_closed 率惩罚
        fail_rate = (summary["fail_closed_count"]
                     / max(1, summary["total_bars"]))
        score = (summary["direction_accuracy"]
                 + 0.1 * summary["avg_confidence"]
                 - 0.2 * fail_rate)
        trial.set_user_attr("direction_accuracy",
                            summary["direction_accuracy"])
        trial.set_user_attr("fail_rate", round(fail_rate, 3))
        return score

    # ── 寻优 ──────────────────────────────────────────────────────────────
    try:
        sampler = optuna.samplers.TPESampler(seed=42)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        # 锚点: 当前值作为首个 trial（保证不差于现状的基线参考）
        study.enqueue_trial({param_key: max(lo, min(current_value, hi))})
        study.optimize(objective, n_trials=n_trials, timeout=timeout_s)
    except Exception as e:
        logger.warning("Optuna 寻优失败 %s: %s", param_key, e)
        return current_value, "default_fallback"

    # B1修复(E2审查): 直接用 best_params 取参数值
    # （study.best_value 是目标分数而非参数值，禁止混用）
    try:
        best_trial = study.best_trial
    except ValueError:
        return current_value, "default_fallback"
    if best_trial is None or best_trial.value is None:
        return current_value, "default_fallback"
    best_value = float(best_trial.params.get(param_key, current_value))

    logger.info(
        "Optuna 寻优完成 %s: %r → %.4f (score=%.3f, trials=%d, "
        "space=[%.3f, %.3f], direction=%s)",
        param_key, current_value, best_value,
        study.best_trial.value, len(study.trials), lo, hi, direction)
    return best_value, "optuna"
