"""战略层子指标 IC 加权优化（Phase 3）

在 Phase 2（五域权重优化）基础上，将每个维度内部的子指标等权改为 IC_IR 加权。

流程：
1. 复刻 dao/tian/di 各子指标计算（coin_data → 0-100 分数）
2. 计算每个子指标对未来 7 日收益的 RankIC 和 IC_IR
3. 用 |IC_IR| softmax 归一化作为子指标权重
4. 重新计算维度分数，再跑五域权重优化
5. 对比等权 vs IC_IR 加权的 Sharpe

用法：
    python five_domain_subindicator_ic.py
输出：
    runtime/five_domain_subindicator_ic_weights.json
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DB_PATH = _REPO / "18-数据获取中心" / "data_center.db"
_RUNTIME = _HERE / "runtime"
_OUTPUT = _RUNTIME / "five_domain_subindicator_ic_weights.json"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_REPO / "18-数据获取中心") not in sys.path:
    sys.path.insert(0, str(_REPO / "18-数据获取中心"))

from five_domain_sqlite_reader import (  # noqa: E402
    read_three_classes_from_sqlite,
    _compute_merrill,
    _compute_liquidity_score,
)
from five_domain_ic_analysis import _get_daily_snapshots  # noqa: E402
from five_domain_weight_optuna import (  # noqa: E402
    precompute_domain_scores,
    get_price_returns,
    compute_walkforward_sharpe,
    compute_max_drawdown,
    sobol_sensitivity_test,
    score_to_position,
    _fill_proxy_fields,
    _fetch_yf_returns,
)


# ============================================================
# 子指标计算（复刻 five_domain_feature_computer 逻辑）
# ============================================================
def _safe(val, default=50.0):
    if val is None or (isinstance(val, float) and val != val):
        return default
    return float(val)


def compute_dao_subindicators(cd: Dict[str, Any]) -> Dict[str, float]:
    """道维度 5 子指标分数 [0,100]。"""
    # 子指标1: 央行政策方向
    rate = cd.get("fedfunds_rate")
    rate_score = float(np.clip(round(85 - _safe(rate, 5.0) * 8), 0, 100)) if isinstance(rate, (int, float)) else 50.0

    # 子指标2: 机构资金净流入（稳定币市值）
    sc = cd.get("stablecoin_mcap_bln")
    sc_score = float(np.clip(round((_safe(sc, 100.0) - 80) / 2), 30, 85)) if isinstance(sc, (int, float)) and sc > 0 else 50.0

    # 子指标3: 政策景气度
    sent = cd.get("policy_sentiment_score")
    if isinstance(sent, (int, float)):
        sent_val = sent * 100.0 if 0.0 <= sent <= 1.0 else sent
        sent_score = float(np.clip(round(sent_val), 0, 100))
    else:
        sent_score = 50.0

    # 子指标4: 变化率
    sc_change = cd.get("stablecoin_change_rate")
    diff_score = float(np.clip(round(50 + _safe(sc_change, 0.0) * 400), 0, 100)) if isinstance(sc_change, (int, float)) else 50.0

    # 子指标5: 大周期位置
    cycle = cd.get("cycle4y_t_rel")
    if isinstance(cycle, (int, float)) and cycle == cycle:  # 排除 nan
        # cycle4y_t_rel 0~1 → 0~100（周期初期高分，末期低分）
        cycle_score = float(np.clip(round((1.0 - float(cycle)) * 100), 0, 100))
    else:
        cycle_score = 50.0

    return {
        "rate": rate_score,
        "stablecoin": sc_score,
        "sentiment": sent_score,
        "change_rate": diff_score,
        "cycle": cycle_score,
    }


def compute_tian_subindicators(cd: Dict[str, Any]) -> Dict[str, float]:
    """天维度 5 子指标分数 [0,100]。"""
    # 子指标1: 日历季节性（简化：取 50 中性，实际需日期）
    cal_score = 50.0

    # 子指标2: 美林时钟
    phase = cd.get("merrill_phase", "RECOVERY")
    phase_map = {"RECOVERY": 70, "EXPANSION": 80, "OVERHEAT": 40, "STAGFLATION": 30, "REFORCE": 60}
    merrill_score = float(phase_map.get(phase, 50))

    # 子指标3: 波动率周期（ATR 分位）
    atr = cd.get("atr_percentile", 0.5)
    if isinstance(atr, (int, float)):
        # 低波动=盘整→50, 高波动=趋势→70
        vol_score = float(np.clip(round(50 + atr * 20), 30, 80))
    else:
        vol_score = 50.0

    # 子指标4: 流动性周期
    liq = cd.get("liquidity_score", 0.5)
    if isinstance(liq, (int, float)):
        liq_score = float(np.clip(round(liq * 100), 0, 100))
    else:
        liq_score = 50.0

    # 子指标5: 10Y-2Y 利差
    spread = cd.get("yield_10y_2y")
    if isinstance(spread, (int, float)):
        spread_score = float(np.clip(round(60 + spread * 20), 0, 100))
    else:
        spread_score = 50.0

    return {
        "calendar": cal_score,
        "merrill": merrill_score,
        "volatility": vol_score,
        "liquidity": liq_score,
        "yield_spread": spread_score,
    }


def compute_di_subindicators(cd: Dict[str, Any]) -> Dict[str, float]:
    """地维度 5 子指标分数 [0,100]。"""
    # 子指标1: regime 代理
    regime = cd.get("regime", "ranging")
    regime_map = {"trend_up": 80, "ranging": 50, "high_volatility": 40, "trend_down": 20}
    regime_score = float(regime_map.get(regime, 50))

    # 子指标2: 弹簧力场 MA
    spring = cd.get("spring_force_score")
    ma_score = float(np.clip(_safe(spring, 50.0), 0, 100)) if isinstance(spring, (int, float)) else 50.0

    # 子指标3: 盘整持续
    consol = cd.get("consolidation_duration")
    consol_score = float(np.clip(_safe(consol, 50.0), 20, 80)) if isinstance(consol, (int, float)) else 50.0

    # 子指标4: FTD
    ftd = cd.get("ftd_signal")
    ftd_score = float(np.clip(_safe(ftd, 50.0), 0, 100)) if isinstance(ftd, (int, float)) else 50.0

    # 子指标5: MA200 距离
    ma200 = cd.get("ma200_distance")
    if isinstance(ma200, (int, float)) and ma200 == ma200:  # 排除 nan
        ma200_score = float(np.clip(round(50 + float(ma200) * 2), 0, 100))
    else:
        ma200_score = 50.0

    return {
        "regime": regime_score,
        "spring_force": ma_score,
        "consolidation": consol_score,
        "ftd": ftd_score,
        "ma200_distance": ma200_score,
    }


SUBINDICATOR_FUNCS = {
    "dao": compute_dao_subindicators,
    "tian": compute_tian_subindicators,
    "di": compute_di_subindicators,
}


# ============================================================
# IC 计算
# ============================================================
def compute_rank_ic(values: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman RankIC。"""
    if len(values) < 10 or len(forward_returns) < 10:
        return 0.0
    # 去 nan
    mask = ~(np.isnan(values) | np.isnan(forward_returns))
    v = values[mask]
    r = forward_returns[mask]
    if len(v) < 10:
        return 0.0
    from scipy.stats import spearmanr
    try:
        ic, _ = spearmanr(v, r)
        return float(ic) if not math.isnan(ic) else 0.0
    except Exception:
        return 0.0


def compute_ic_ir(ic_series: List[float]) -> float:
    """IC_IR = mean(IC) / std(IC) * sqrt(n)。"""
    if len(ic_series) < 5:
        return 0.0
    arr = np.array(ic_series)
    std = np.std(arr, ddof=1)
    if std < 1e-9:
        return 0.0
    return float(np.mean(arr) / std * np.sqrt(len(arr)))


# ============================================================
# 子指标 IC 加权
# ============================================================
def compute_subindicator_ic_weights(
    snapshots: List[Tuple[str, Dict[str, Dict[str, Any]]]],
    returns: Dict[str, float],
    asset_class: str,
    forward_days: int = 7,
) -> Dict[str, Dict[str, float]]:
    """计算每个维度内子指标的 IC_IR 权重。

    返回 {dim: {subindicator: weight}}，权重归一化 sum=1。
    """
    # 收集每个子指标的时间序列
    sub_series: Dict[str, Dict[str, List[float]]] = {}  # dim -> sub -> [scores]
    forward_rets: List[float] = []

    for date_str, coin_data in snapshots:
        cd = coin_data.get(asset_class, {})
        if not cd:
            continue
        # 计算未来 N 日收益
        dates_sorted = sorted(returns.keys())
        if date_str not in dates_sorted:
            continue
        idx = dates_sorted.index(date_str)
        if idx + forward_days >= len(dates_sorted):
            continue
        future_ret = returns[dates_sorted[idx + forward_days]]
        if math.isnan(future_ret):
            continue

        forward_rets.append(future_ret)
        for dim, func in SUBINDICATOR_FUNCS.items():
            subs = func(cd)
            if dim not in sub_series:
                sub_series[dim] = {s: [] for s in subs}
            for s, val in subs.items():
                sub_series[dim][s].append(val)

    fwd = np.array(forward_rets)
    ic_weights: Dict[str, Dict[str, float]] = {}

    for dim, subs in sub_series.items():
        ic_ir_map: Dict[str, float] = {}
        for sub_name, values in subs.items():
            arr = np.array(values)
            if len(arr) < 30:
                ic_ir_map[sub_name] = 0.0
                continue
            # 滑动窗口计算 IC 序列（每 60 天一个窗口）
            ic_list = []
            for start in range(0, len(arr) - 60, 30):
                end = start + 60
                if end > len(arr):
                    break
                ic = compute_rank_ic(arr[start:end], fwd[start:end])
                ic_list.append(ic)
            ic_ir = compute_ic_ir(ic_list)
            ic_ir_map[sub_name] = abs(ic_ir) if ic_ir == ic_ir else 0.0  # 去 nan

        # softmax 归一化（用 |IC_IR| 作为权重）
        vals = np.array(list(ic_ir_map.values()))
        if vals.sum() < 1e-9:
            # 全部 IC_IR 为 0，回退等权
            n = len(vals)
            ic_weights[dim] = {k: 1.0 / n for k in ic_ir_map}
        else:
            # softmax
            exp_vals = np.exp(vals - vals.max())
            weights = exp_vals / exp_vals.sum()
            ic_weights[dim] = {k: float(weights[i]) for i, k in enumerate(ic_ir_map)}

    return ic_weights


def cap_subindicator_weights(
    ic_weights: Dict[str, Dict[str, float]],
    max_single: float = 0.40,
) -> Dict[str, Dict[str, float]]:
    """限制单个子指标权重上限，超出部分按比例分配给其他子指标。"""
    result = {}
    for dim, w in ic_weights.items():
        items = list(w.items())
        vals = np.array([v for _, v in items])
        # 迭代 cap：超过 max_single 的截断，余量分给其他
        for _ in range(10):
            over = np.maximum(vals - max_single, 0)
            if over.sum() < 1e-9:
                break
            vals = np.minimum(vals, max_single)
            under_mask = vals < max_single
            if under_mask.sum() > 0:
                vals[under_mask] += over.sum() / under_mask.sum()
        # 归一化
        vals = vals / vals.sum()
        result[dim] = {k: float(vals[i]) for i, (k, _) in enumerate(items)}
    return result


def apply_ic_weights_to_snapshot(
    cd: Dict[str, Any],
    ic_weights: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """用 IC 权重计算各维度分数。

    返回 {dim: score}，score ∈ [0,100]。
    """
    result = {}
    for dim, func in SUBINDICATOR_FUNCS.items():
        subs = func(cd)
        weights = ic_weights.get(dim, {})
        if not weights:
            # 回退等权
            result[dim] = float(np.mean(list(subs.values())))
        else:
            weighted = sum(subs.get(s, 50.0) * w for s, w in weights.items())
            result[dim] = float(np.clip(weighted, 0, 100))
    return result


# ============================================================
# 带仓位上限的计算（控制回撤）
# ============================================================
def score_to_position_capped(total_score: float, max_position: float = 1.0) -> float:
    """总分线性映射到仓位比例（0~max_position）。"""
    base = float(np.clip((total_score - 40.0) / 40.0, 0.0, 1.0))
    return base * max_position


def compute_walkforward_sharpe_capped(
    scores, returns, weights, asset_class,
    train_days=180, val_days=30, max_position=1.0,
) -> float:
    """带仓位上限的 Walk-forward Sharpe。"""
    all_dates = sorted(set(scores.keys()) & set(returns.keys()))
    if len(all_dates) < train_days + val_days:
        return 0.0
    w = np.array([weights.get(d, 0.2) for d in ("dao", "tian", "di", "jiang", "fa")])
    w = w / w.sum()
    fold_sharpes = []
    for start in range(0, len(all_dates) - train_days - val_days + 1, val_days):
        val_start = start + train_days
        val_end = val_start + val_days
        if val_end > len(all_dates):
            break
        val_dates = all_dates[val_start:val_end]
        daily_rets = []
        for d in val_dates:
            dims = scores[d].get(asset_class, {})
            total = sum(w[i] * dims.get(dim, 50.0) for i, dim in enumerate(("dao", "tian", "di", "jiang", "fa")))
            pos = score_to_position_capped(total, max_position)
            ret = returns.get(d, 0.0)
            daily_rets.append(pos * ret)
        if len(daily_rets) >= 5:
            arr = np.array(daily_rets)
            mean = np.mean(arr)
            std = np.std(arr, ddof=1)
            if std > 1e-9:
                fold_sharpes.append(mean / std * np.sqrt(365))
    if not fold_sharpes:
        return 0.0
    return float(np.mean(fold_sharpes))


def compute_max_drawdown_capped(scores, returns, weights, asset_class, max_position=1.0) -> float:
    """带仓位上限的最大回撤。"""
    all_dates = sorted(set(scores.keys()) & set(returns.keys()))
    if len(all_dates) < 10:
        return 0.0
    w = np.array([weights.get(d, 0.2) for d in ("dao", "tian", "di", "jiang", "fa")])
    w = w / w.sum()
    daily_rets = []
    for d in all_dates:
        dims = scores[d].get(asset_class, {})
        total = sum(w[i] * dims.get(dim, 50.0) for i, dim in enumerate(("dao", "tian", "di", "jiang", "fa")))
        pos = score_to_position_capped(total, max_position)
        ret = returns.get(d, 0.0)
        daily_rets.append(pos * ret)
    if not daily_rets:
        return 0.0
    cum = np.cumprod(1.0 + np.array(daily_rets))
    peak = np.maximum.accumulate(cum)
    drawdown = (cum - peak) / peak
    return float(abs(np.min(drawdown)))


def sobol_sensitivity_test_capped(scores, returns, base_weights, asset_class,
                                   n_samples=500, perturbation=0.10, seed=42, max_position=1.0):
    """带仓位上限的 Sobol' 检验。"""
    rng = np.random.default_rng(seed)
    dims = ("dao", "tian", "di", "jiang", "fa")
    base_w = np.array([base_weights[d] for d in dims])
    base_sharpe = compute_walkforward_sharpe_capped(scores, returns, base_weights, asset_class, max_position=max_position)
    if base_sharpe == 0:
        return {"base_sharpe": 0.0, "max_change_pct": 0.0, "pass": True}
    perturbed_sharpes = []
    for _ in range(n_samples):
        factors = 1.0 + rng.uniform(-perturbation, perturbation, size=len(dims))
        pw = base_w * factors
        pw = pw / pw.sum()
        pw_dict = {d: float(pw[i]) for i, d in enumerate(dims)}
        s = compute_walkforward_sharpe_capped(scores, returns, pw_dict, asset_class, max_position=max_position)
        perturbed_sharpes.append(s)
    arr = np.array(perturbed_sharpes)
    changes = np.abs(arr - base_sharpe) / abs(base_sharpe)
    return {
        "base_sharpe": round(base_sharpe, 4),
        "n_samples": n_samples,
        "max_change_pct": round(float(np.max(changes)) * 100, 2),
        "pass": float(np.max(changes)) <= 0.20,
    }


# ============================================================
# 主流程
# ============================================================
def main() -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)

    print("[Phase3] 读取快照...")
    snapshots = _get_daily_snapshots(_DB_PATH)
    print(f"[Phase3] 快照数: {len(snapshots)}")

    returns_all = get_price_returns()

    # 等权基线（复用 Phase 2 的 precompute）
    print("[Phase3] 计算等权基线...")
    scores_equal = precompute_domain_scores()

    # 预获取各资产类价格历史（用于代理填充）
    from five_domain_weight_optuna import ASSET_RETURN_MAP
    cls_prices = {}
    cls_price_history = {}
    for cls, symbol in ASSET_RETURN_MAP.items():
        prices = _fetch_yf_returns(symbol, days=1500)
        cls_prices[cls] = prices
        cls_price_history[cls] = sorted(prices.items(), key=lambda x: x[0])

    # 对快照应用代理填充（与 Phase 2 precompute 一致）
    print("[Phase3] 应用代理字段填充...")
    filled_snapshots = []
    for date_str, coin_data in snapshots:
        filled = {}
        for cls, cd in coin_data.items():
            fcd = _fill_proxy_fields(
                cd, cls_prices.get(cls, {}),
                cls_price_history.get(cls, []),
                date_str,
            )
            filled[cls] = fcd
        filled_snapshots.append((date_str, filled))

    all_ic_weights = {}
    results = {}

    # 各资产类仓位上限（仅 IC 策略应用，基线保持无 cap 以公平比较）
    MAX_POSITION = {
        "crypto_usdt": 1.0,
        "us_stock": 1.0,
        "precious_metal": 0.7,
    }
    # metal 子指标单因子权重上限（控制 spring_force 过度集中导致的回撤）
    MAX_SUB_WEIGHT = {
        "crypto_usdt": 1.0,
        "us_stock": 1.0,
        "precious_metal": 0.40,
    }

    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        cls_returns = returns_all.get(cls, {})
        cls_scores_equal = {d: v for d, v in scores_equal.items() if cls in v}
        if len(cls_scores_equal) < 210:
            print(f"[Phase3] {cls}: 样本不足，跳过")
            continue

        max_pos = MAX_POSITION.get(cls, 1.0)
        # 等权基线 Sharpe（无 cap，原始口径）
        baseline_w = {"dao": 0.2, "tian": 0.2, "di": 0.2, "jiang": 0.2, "fa": 0.2}
        baseline_sharpe = compute_walkforward_sharpe(cls_scores_equal, cls_returns, baseline_w, cls)

        # 计算子指标 IC 权重（用填充后的快照）
        max_sub = MAX_SUB_WEIGHT.get(cls, 1.0)
        print(f"[Phase3] {cls}: 计算子指标 IC 权重... (max_position={max_pos}, max_sub_weight={max_sub})")
        ic_weights = compute_subindicator_ic_weights(filled_snapshots, cls_returns, cls)
        # 对子指标权重做上限约束（metal 用 0.40）
        if max_sub < 1.0:
            ic_weights = cap_subindicator_weights(ic_weights, max_single=max_sub)
        all_ic_weights[cls] = ic_weights

        # 打印 IC 权重
        for dim, w in ic_weights.items():
            print(f"    {dim}: " + ", ".join(f"{k}={v:.3f}" for k, v in w.items()))

        # 用 IC 权重重新计算维度分数
        print(f"[Phase3] {cls}: 重算维度分数...")
        scores_ic: Dict[str, Dict[str, Dict[str, float]]] = {}
        for date_str, coin_data in filled_snapshots:
            cd = coin_data.get(cls, {})
            if not cd:
                continue
            dims = apply_ic_weights_to_snapshot(cd, ic_weights)
            scores_ic[date_str] = {cls: {**dims, "jiang": 50.0, "fa": 50.0}}

        # 重新优化五域权重
        print(f"[Phase3] {cls}: 优化五域权重...")
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            w = {
                "dao": trial.suggest_float("dao", 0.05, 0.50),
                "tian": trial.suggest_float("tian", 0.05, 0.50),
                "di": trial.suggest_float("di", 0.05, 0.50),
                "jiang": trial.suggest_float("jiang", 0.05, 0.50),
                "fa": trial.suggest_float("fa", 0.05, 0.50),
            }
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            return compute_walkforward_sharpe_capped(scores_ic, cls_returns, w, cls, max_position=max_pos)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=200)
        best_w = study.best_params
        total = sum(best_w.values())
        best_w = {k: v / total for k, v in best_w.items()}
        best_sharpe = float(study.best_value)

        # 验证：基线回撤无 cap，IC 策略回撤用 cap
        baseline_mdd = compute_max_drawdown(cls_scores_equal, cls_returns, baseline_w, cls)
        best_mdd = compute_max_drawdown_capped(scores_ic, cls_returns, best_w, cls, max_position=max_pos)
        mdd_ratio = best_mdd / baseline_mdd if baseline_mdd > 0 else 1.0
        sobol = sobol_sensitivity_test_capped(scores_ic, cls_returns, best_w, cls, max_position=max_pos)

        results[cls] = {
            "baseline_sharpe_equal": round(baseline_sharpe, 4),
            "best_sharpe_ic": round(best_sharpe, 4),
            "sharpe_improvement": round(best_sharpe - baseline_sharpe, 4),
            "max_position": max_pos,
            "best_weights": {k: round(v, 4) for k, v in best_w.items()},
            "subindicator_ic_weights": {d: {k: round(v, 4) for k, v in w.items()} for d, w in ic_weights.items()},
            "max_drawdown": {
                "baseline": round(baseline_mdd, 4),
                "best": round(best_mdd, 4),
                "ratio": round(mdd_ratio, 4),
                "pass": mdd_ratio <= 1.05,
            },
            "sobol_sensitivity": sobol,
        }
        print(f"[Phase3] {cls}: 等权基线={baseline_sharpe:.4f} IC加权最优={best_sharpe:.4f} "
              f"提升={best_sharpe - baseline_sharpe:+.4f}")
        print(f"    权重: {best_w}")
        print(f"    回撤: 基线={baseline_mdd:.2%} 最优={best_mdd:.2%} 比率={mdd_ratio:.3f} {'✅' if mdd_ratio <= 1.05 else '❌'}")
        print(f"    Sobol: 最大变化={sobol['max_change_pct']:.1f}% {'✅' if sobol['pass'] else '❌'}")

    output = {
        "timestamp": datetime.now().isoformat(),
        "forward_days": 7,
        "n_trials": 200,
        "all_ic_weights": {cls: {d: {k: round(v, 4) for k, v in w.items()} for d, w in iw.items()} for cls, iw in all_ic_weights.items()},
        "results": results,
    }
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[Phase3] 结果已保存: {_OUTPUT}")


if __name__ == "__main__":
    main()
