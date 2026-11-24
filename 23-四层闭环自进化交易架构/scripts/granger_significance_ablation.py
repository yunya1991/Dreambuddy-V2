#!/usr/bin/env python3
"""Granger 显著性参数对照实验（方案C·B 步）.

目的：G 侧（Granger 因果）在真实行情上长期 `no_significant_granger`，
导致 23 交叉验证长期停留在单链路降级 / SPRT 中性。本实验对比三种显著性阈值：

  V0_current     : significance=0.05 + Bonferroni（3 维 × 5 lag = 0.00333），旧生产口径
  V1b_per_dim    : significance=0.05，按维度校正（0.0167），2026-11-25 起生产默认
  V1_uncorrected : significance=0.05（不做多重比较校正）
  V2_uncorrected : significance=0.10（不做多重比较校正）

口径尽量与生产一致：
  - 因子派生完全复刻 evolution_pipeline Phase 2.5（收益 / MA20 偏离 / 20 期波动率）
  - G_dim 由真实 GrangerCausalityChecker 检验得出（非相关性代理）
  - A_dim 用与 poc_cv_ablation 相同的 corr-attention 代理（离线无 cross-attn 权重）
  - 下游统一走 CrossValidationGate，逐窗口顺序调用（SPRT/冷却状态保留）

指标：G 可用率、G 维度分布、降级模式分布、双链路一致率、策略 Sharpe/胜率。

用法：
  # 单品种
  python3 scripts/granger_significance_ablation.py \
      --csv "11-易经推理系统/scripts/data/klines/BTC_1H.csv" --window 500 --step 24
  # 多品种 × 多时段（落地前验证用）
  python3 scripts/granger_significance_ablation.py \
      --csvs BTC_1H ETH_1H SOL_1H BTC_1D --folds 3 --window 500 --step 24
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate  # noqa: E402
from dreambuddy_evolution.core.framework_comparison import FrameworkComparison  # noqa: E402
from dreambuddy_evolution.core.granger_causality_checker import (  # noqa: E402
    GrangerCausalityChecker,
)

DIMS = ("technical", "fundamental", "macro")
MAX_LAG = 5

VARIANTS = {
    "V0_current": {"significance": 0.05, "correction": "bonferroni"},
    "V1b_per_dim": {"significance": 0.05, "correction": "per_dim"},
    "V1_uncorrected": {"significance": 0.05, "correction": "none"},
    "V2_uncorrected": {"significance": 0.10, "correction": "none"},
}


def effective_alpha(significance: float, correction: str) -> float:
    if correction == "bonferroni":
        return significance / (len(DIMS) * MAX_LAG)
    if correction == "per_dim":
        return significance / len(DIMS)
    return significance


def load_closes(csv_path: Path) -> np.ndarray:
    rows = csv_path.read_text(encoding="utf-8").splitlines()
    header = rows[0].split(",")
    idx = header.index("close")
    closes = [float(r.split(",")[idx]) for r in rows[1:] if r.strip()]
    return np.asarray(closes, dtype=float)


def production_factors(prices: np.ndarray) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """复刻 evolution_pipeline Phase 2.5 的 3 维因子与对数收益。"""
    price = np.asarray(prices, dtype=float)
    log_ret = np.diff(np.log(price)) if len(price) > 1 else np.array([])
    ret = np.diff(price) / np.maximum(np.abs(price[:-1]), 1e-12)
    ma20 = np.convolve(price, np.ones(20) / 20, mode="same")
    vol20 = np.array(
        [np.std(ret[max(0, i - 20) : i + 1]) if i >= 5 else 0.02 for i in range(len(ret))]
    )
    factors = {
        "technical": ret,
        "fundamental": (price - ma20)[:-1] if len(price) > 1 else np.array([]),
        "macro": vol20,
    }
    return factors, log_ret


def granger_g_dim(
    factors: dict[str, np.ndarray], returns: np.ndarray, significance: float, correction: str
) -> tuple[str | None, dict[str, float], float]:
    """与 GrangerPipelineAdapter 同口径，但可切换多重比较校正方式。"""
    checker = GrangerCausalityChecker(max_lag=MAX_LAG, significance=significance)
    alpha = effective_alpha(significance, correction)
    p_values: dict[str, float] = {}
    for dim in DIMS:
        factor = factors.get(dim)
        if factor is None:
            continue
        factor = np.asarray(factor, dtype=float)
        min_len = min(len(factor), len(returns))
        if min_len < MAX_LAG * 3 + 5:
            continue
        result = checker.check(factor[:min_len], returns[:min_len])
        if result is not None:
            p_values[dim] = float(result["p_value"])
    if not p_values:
        return None, {}, alpha
    g_dim = min(p_values, key=p_values.get)
    if p_values[g_dim] >= alpha:
        return None, p_values, alpha
    return g_dim, p_values, alpha


def attention_proxy(prices: np.ndarray) -> tuple[str, float]:
    """与 poc_cv_ablation 一致的 corr-attention 代理，产出 A_dim/A_strength。"""
    factors, returns = production_factors(prices)
    n = min(len(returns), *(len(v) for v in factors.values()))
    rets = returns[:n]
    span = min(60, n)
    recent_rets = rets[-span:]
    weights = {}
    for dim in DIMS:
        f = factors[dim][:n][-span:]
        w = abs(np.corrcoef(f, recent_rets)[0, 1]) if np.std(f) > 1e-10 else 0.0
        weights[dim] = 0.0 if np.isnan(w) else float(w)
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    else:
        weights = dict.fromkeys(DIMS, 1.0 / len(DIMS))
    a_dim = max(weights, key=weights.get)
    return a_dim, weights[a_dim]


def structural_break(prices: np.ndarray) -> dict[str, bool]:
    factors, returns = production_factors(prices)
    n = len(returns)
    span = min(60, n // 2)
    recent, past = returns[-span:], returns[-2 * span : -span]
    vol_shift = bool(np.std(recent) > np.std(past) * 1.3) if np.std(past) > 1e-10 else False
    ac_recent = np.corrcoef(recent[:-1], recent[1:])[0, 1] if np.std(recent[:-1]) > 1e-10 else 0.0
    ac_past = np.corrcoef(past[:-1], past[1:])[0, 1] if np.std(past[:-1]) > 1e-10 else 0.0
    f = factors["technical"]
    corr_recent = abs(np.corrcoef(f[-span:], recent)[0, 1]) if np.std(f[-span:]) > 1e-10 else 0.0
    corr_past = abs(np.corrcoef(f[-2 * span : -span], past)[0, 1]) if np.std(past) > 1e-10 else 0.0
    return {
        "volatility_regime_shift": vol_shift,
        "correlation_break": bool(abs(corr_recent - corr_past) > 0.3),
        "market_form_shift": bool((ac_recent > 0) != (ac_past > 0)),
    }


def momentum_direction(prices: np.ndarray, dim: str, span: int = 60) -> float:
    factors, _ = production_factors(prices)
    f = factors[dim]
    if len(f) < span + 1:
        return 0.0
    return 1.0 if np.mean(f[-span:]) - f[-span - 1] > 0 else -1.0


def run_variant(prices: np.ndarray, window: int, step: int, significance: float, correction: str):
    gate = CrossValidationGate(
        persistence_threshold=5,
        structural_break_threshold=1.0,
        enable_head_multipliers_mean_reversion=True,
    )
    stats = Counter()
    g_dims: Counter = Counter()
    modes: Counter = Counter()
    min_ps: list[float] = []
    strat_rets: list[float] = []
    n_evals = 0

    for end in range(window, len(prices) - step, step):
        seg = prices[end - window : end]
        factors, returns = production_factors(seg)
        g_dim, p_values, _alpha = granger_g_dim(factors, returns, significance, correction)
        a_dim, a_strength = attention_proxy(seg)

        result = gate.compare(
            G_dim=g_dim,
            G_conf=0.0,
            A_dim=a_dim,
            A_strength=a_strength,
            structural_break=structural_break(seg),
        )
        n_evals += 1
        stats["g_available"] += int(g_dim is not None)
        g_dims[g_dim or "None"] += 1
        modes[str(result.get("degraded_mode") or "both_available")] += 1
        if g_dim is not None and a_dim is not None:
            stats["both_present"] += 1
            stats["agreement"] += int(g_dim == a_dim)
        if p_values:
            min_ps.append(min(p_values.values()))
        stats["boost"] += int(result["confidence_mult"] > 1.0)
        stats["penalty"] += int(result["confidence_mult"] < 1.0)
        stats["quality_change"] += int(bool(result.get("quality_change")))

        direction = momentum_direction(seg, a_dim)
        signal = direction * float(result["confidence_mult"])
        if result.get("quality_change"):
            signal = -signal
        fwd = prices[end + step - 1] / prices[end] - 1.0
        strat_rets.append(signal * fwd)

    pnl = np.asarray(strat_rets, dtype=float)
    comp = FrameworkComparison(prices, window=60)
    sharpe = comp.sharpe_ratio(pnl, periods_per_year=max(1, int(365 * 24 / step)))
    return {
        "n_evals": n_evals,
        "g_available_rate": round(stats["g_available"] / n_evals, 4) if n_evals else 0.0,
        "g_dim_distribution": dict(g_dims),
        "degraded_mode_distribution": dict(modes),
        "agreement_rate": (
            round(stats["agreement"] / stats["both_present"], 4) if stats["both_present"] else None
        ),
        "median_min_p": round(float(np.median(min_ps)), 6) if min_ps else None,
        "p10_min_p": round(float(np.percentile(min_ps, 10)), 6) if min_ps else None,
        "boost_rate": round(stats["boost"] / n_evals, 4) if n_evals else 0.0,
        "penalty_rate": round(stats["penalty"] / n_evals, 4) if n_evals else 0.0,
        "quality_change_count": stats["quality_change"],
        "sharpe": round(float(sharpe), 4),
        "winrate": round(float(np.mean(pnl > 0)), 4) if len(pnl) else 0.0,
        "total_return": round(float(np.sum(pnl)), 6),
    }


def run_matrix(csv_paths: list[Path], window: int, step: int, folds: int) -> dict:
    """多品种 × 多时段矩阵：每个 (csv, fold) 独立跑三变体。"""
    detail = {}
    for csv_path in csv_paths:
        prices = load_closes(csv_path)
        detail[csv_path.stem] = {}
        for fold in range(folds):
            lo = fold * len(prices) // folds
            hi = (fold + 1) * len(prices) // folds
            seg = prices[lo:hi]
            if len(seg) < window + step * 5:
                continue
            detail[csv_path.stem][f"fold{fold + 1}"] = {
                v: {"config": cfg, **run_variant(seg, window, step, **cfg)}
                for v, cfg in VARIANTS.items()
            }
    return detail


def aggregate(detail: dict) -> dict:
    agg: dict[str, dict] = {}
    for variant in VARIANTS:
        rows = [r[variant] for sym in detail.values() for r in sym.values() if variant in r]
        agreements = [r["agreement_rate"] for r in rows if r["agreement_rate"] is not None]
        agg[variant] = {
            "n_cases": len(rows),
            "g_available_rate": (
                round(float(np.mean([r["g_available_rate"] for r in rows])), 4) if rows else 0.0
            ),
            "agreement_rate": round(float(np.mean(agreements)), 4) if agreements else None,
            "sharpe": round(float(np.mean([r["sharpe"] for r in rows])), 4) if rows else 0.0,
            "winrate": round(float(np.mean([r["winrate"] for r in rows])), 4) if rows else 0.0,
        }
    for variant, res in agg.items():
        if variant == "V0_current":
            res["sharpe_win_vs_V0"] = "-"
            continue
        wins = sum(
            1
            for sym in detail.values()
            for r in sym.values()
            if r[variant]["sharpe"] > r["V0_current"]["sharpe"]
        )
        res["sharpe_win_vs_V0"] = f"{wins}/{res['n_cases']}"
    return agg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default=str(ROOT.parent / "11-易经推理系统/scripts/data/klines/BTC_1H.csv"),
    )
    parser.add_argument(
        "--csvs",
        nargs="*",
        default=None,
        help="多品种对照（优先于 --csv），如 BTC_1H ETH_1H SOL_1H BTC_1D",
    )
    parser.add_argument("--window", type=int, default=500)
    parser.add_argument("--step", type=int, default=24, help="评估步长（bar 数）")
    parser.add_argument("--folds", type=int, default=1, help="每个品种按时间切分的独立时段数")
    parser.add_argument("--out", default=str(ROOT / "data/granger_significance_ablation.json"))
    args = parser.parse_args()

    if args.csvs:
        kline_dir = ROOT.parent / "11-易经推理系统/scripts/data/klines"
        csv_paths = [kline_dir / (c if c.endswith(".csv") else f"{c}.csv") for c in args.csvs]
    else:
        csv_paths = [Path(args.csv)]

    print(
        f"数据集: {[p.name for p in csv_paths]} | window={args.window} step={args.step} folds={args.folds}"
    )

    if args.folds > 1 or len(csv_paths) > 1:
        detail = run_matrix(csv_paths, args.window, args.step, args.folds)
        summary = aggregate(detail)
        print("\n=== 多品种/多时段聚合 ===")
        print(
            f"{'variant':<16}{'cases':>6}{'G可用率':>9}{'一致率':>8}{'Sharpe':>8}{'胜率':>7}{'跑赢V0':>9}"
        )
        for name, res in summary.items():
            print(
                f"{name:<16}{res['n_cases']:>6}{res['g_available_rate']:>9.2%}"
                f"{(res['agreement_rate'] or 0):>8.2%}{res['sharpe']:>8.2f}"
                f"{res['winrate']:>7.2%}{res['sharpe_win_vs_V0']:>9}"
            )
        payload = {
            "window": args.window,
            "step": args.step,
            "folds": args.folds,
            "datasets": [p.name for p in csv_paths],
            "aggregate": summary,
            "detail": detail,
        }
    else:
        prices = load_closes(csv_paths[0])
        print(f"数据: {csv_paths[0]} | bars={len(prices)}")
        results = {
            name: {"config": cfg, **run_variant(prices, args.window, args.step, **cfg)}
            for name, cfg in VARIANTS.items()
        }
        print("\n=== Granger 显著性对照 ===")
        print(
            f"{'variant':<16}{'alpha':>9}{'G可用率':>9}{'一致率':>8}"
            f"{'both_none':>10}{'no_rel':>8}{'Sharpe':>8}{'胜率':>7}"
        )
        for name, res in results.items():
            modes = res["degraded_mode_distribution"]
            print(
                f"{name:<16}{effective_alpha(res['config']['significance'], res['config']['correction']):>9.4f}"
                f"{res['g_available_rate']:>9.2%}{(res['agreement_rate'] or 0):>8.2%}"
                f"{modes.get('both_none', 0):>10}{modes.get('no_reliable_link', 0):>8}"
                f"{res['sharpe']:>8.2f}{res['winrate']:>7.2%}"
            )
        payload = {
            "data": str(csv_paths[0]),
            "window": args.window,
            "step": args.step,
            "results": results,
        }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
