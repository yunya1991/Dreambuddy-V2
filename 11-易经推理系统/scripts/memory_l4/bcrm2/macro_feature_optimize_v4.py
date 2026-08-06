#!/usr/bin/env python3
"""宏观特征优化 v4 — 前向贪心选择（两阶段加速）

修正 v3 的根本问题：
  v3 用 importance ranking 的不同截断（K=3/5/8）测试，不是真正的特征搜索
  v4 从 K=0 开始逐步添加边际贡献最大的特征，直到加入不再提升得分

两阶段加速：
  Stage 0 (预筛选, ~40min): 单特征评估（K=1 for each），选 Top-8 候选
  Stage 1 (前向选择, ~60min): 在 Top-8 上做前向贪心选择，产出 K-vs-得分曲线
  Stage 2 (验证, ~60min): 9 币种 × 5 折完整验证

与 v3 的核心区别：
  - 不依赖 LightGBM importance ranking
  - 每步考虑已选特征集的交互效应
  - 相关特征加入时不会提升得分，自动跳过（自然去冗余）
  - 产出真实的边际贡献曲线，而非预设 K 值的对比

评估参数：
  预筛选 + 前向选择：3 币种 × 2 折 × 3000 bars（快速）
  验证：9 币种 × 5 折 × 6000 bars（严格）

评分函数（与 v3 一致）：
  score = sharpe*1.0 + win_rate*2.0 + return*0.01 - dd*0.05 + pf*0.3

落地标准：
  1. 平均得分 > K=0 基线
  2. 9 币种中 ≥6 个币种得分优于 K=0
  3. 无严重退化（任一币种得分降幅 < 30%）
"""
import sys
import os
import json
import time
import logging
import importlib
from pathlib import Path
from datetime import datetime

import numpy as np

# 设置路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]  # 11-易经推理系统/
sys.path.insert(0, str(PROJECT_ROOT))

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================
# BTC-only 模式：宏观特征本质是市场级信号，BTC 最具代表性，排除小币种噪声
ALL_COINS = ["BTC"]
SELECT_COINS = ["BTC"]
TIMEFRAME = "1H"

# 选择阶段参数（单币种需提高折数保证统计显著性）— 1币种×3折×4000bars ≈ 30s/次
SELECT_FOLDS = 3
SELECT_BARS = 4000
# 预筛选保留的候选数
PREFILTER_TOP_K = 8

# 验证阶段参数（严格）
VALIDATE_FOLDS = 5
VALIDATE_BARS = 6000

CONF_THRESHOLD = 0.40
TP_ATR = 3.0
SL_ATR = 2.0
MAX_HOLD_BARS = 60
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.001
FEATURE_SELECTION = True

# 早停：连续 N 步无提升则停止
EARLY_STOP_PATIENCE = 3

OUTPUT_DIR = PROJECT_ROOT / "data" / "baseline"


# ============================================================
# 数据缓存
# ============================================================
_KLINE_CACHE = {}
_REF_DF_CACHE = None


def load_klines(symbol, max_bars=None):
    """加载 K 线数据，支持不同 max_bars"""
    if max_bars is None:
        max_bars = VALIDATE_BARS
    cache_key = f"{symbol}_{max_bars}"
    if cache_key not in _KLINE_CACHE:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _KLINE_CACHE[cache_key] = get_klines(symbol, TIMEFRAME, max_bars=max_bars)
    return _KLINE_CACHE[cache_key]


def get_ref_df():
    global _REF_DF_CACHE
    if _REF_DF_CACHE is None:
        from scripts.memory_l4.bcrm2.data_fetcher import get_klines
        _REF_DF_CACHE = get_klines("BTC", TIMEFRAME, max_bars=VALIDATE_BARS + 200)
    return _REF_DF_CACHE


# ============================================================
# 评分
# ============================================================

def compute_score(metrics):
    if metrics is None or metrics["total_trades"] == 0:
        return -10.0
    sharpe = metrics["sharpe_ratio"]
    win_rate = metrics["win_rate"]
    total_ret = metrics["total_return_pct"]
    max_dd = metrics["max_drawdown_pct"]
    pf = min(metrics["profit_factor"], 5.0)
    return 1.0 * sharpe + 2.0 * win_rate + 0.01 * total_ret - 0.05 * max_dd + 0.3 * pf


def get_git_commit():
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT)
        ).decode().strip()
    except Exception:
        return "unknown"


# ============================================================
# 回测
# ============================================================

def build_macro_config(enabled_features):
    from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
    cfg = {}
    if enabled_features is None or enabled_features == []:
        for feat in MacroFeatures.ALL_FEATURES:
            cfg[f"macro_feat_{feat}"] = False
        return cfg
    if enabled_features == "all":
        return {}
    enabled_set = set(enabled_features)
    for feat in MacroFeatures.ALL_FEATURES:
        cfg[f"macro_feat_{feat}"] = feat in enabled_set
    return cfg


def run_single_backtest(symbol, df, macro_config, n_folds):
    from scripts.memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester
    ref_df = get_ref_df()
    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=n_folds,
        conf_threshold=CONF_THRESHOLD,
        tp_atr=TP_ATR,
        sl_atr=SL_ATR,
        max_hold_bars=MAX_HOLD_BARS,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        feature_selection=FEATURE_SELECTION,
        macro_config=macro_config if macro_config else None,
    )
    result = bt.run(df, ref_df=ref_df, verbose=False)
    return {
        "total_trades": result.total_trades,
        "win_rate": round(result.overall_win_rate, 4),
        "total_return_pct": round(result.total_return, 4),
        "max_drawdown_pct": round(result.max_drawdown, 4),
        "profit_factor": round(result.profit_factor, 4),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "avg_hold_bars": round(result.avg_hold_bars, 2),
    }


def evaluate_config(enabled_features, coins, n_folds, max_bars):
    """评估一组特征配置在多币种上的平均得分"""
    macro_config = build_macro_config(enabled_features)
    per_coin = {}
    scores = []
    for coin in coins:
        df = load_klines(coin, max_bars)
        if df is None or len(df) < 500:
            continue
        try:
            metrics = run_single_backtest(coin, df, macro_config, n_folds)
            score = compute_score(metrics)
            metrics["score"] = round(score, 4)
            per_coin[coin] = metrics
            scores.append(score)
        except Exception as e:
            logger.warning(f"  {coin} 回测失败: {e}")
            per_coin[coin] = None
    avg_score = np.mean(scores) if scores else -10.0
    return avg_score, per_coin


# ============================================================
# Stage 0: 预筛选 — 单特征评估
# ============================================================

def prefilter_features(baseline_score):
    """Stage 0: 逐个评估每个特征的单独贡献，选 Top-K 候选

    Args:
        baseline_score: K=0 基线得分

    Returns:
        ranked_features: 按边际贡献降序排列的特征列表
    """
    from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
    all_features = MacroFeatures.ALL_FEATURES

    print(f"\n  逐特征评估（K=1 for each，{len(all_features)} 个特征）")
    print(f"  参数: {SELECT_COINS} × {SELECT_FOLDS} 折 × {SELECT_BARS} bars")
    print(f"  基线得分: {baseline_score:.4f}\n")

    results = []
    t_start = time.time()

    for i, feat in enumerate(all_features, 1):
        t0 = time.time()
        trial_score, per_coin = evaluate_config(
            [feat], SELECT_COINS, SELECT_FOLDS, SELECT_BARS
        )
        elapsed = time.time() - t0
        marginal = trial_score - baseline_score

        results.append({
            "feature": feat,
            "score": round(trial_score, 4),
            "marginal_gain": round(marginal, 4),
            "dim": MacroFeatures.FEATURE_TO_DIM.get(feat, "?"),
        })

        marker = "+" if marginal > 0 else " " if abs(marginal) < 0.01 else "-"
        print(f"    [{i:>2}/{len(all_features)}] {feat:<30} [{MacroFeatures.FEATURE_TO_DIM.get(feat, '?'):<12}] "
              f"得分={trial_score:.3f}  边际={marginal:+.3f} {marker} "
              f"({elapsed:.0f}s)", flush=True)

    # 按边际贡献降序
    results.sort(key=lambda r: r["marginal_gain"], reverse=True)

    total_elapsed = time.time() - t_start
    print(f"\n  预筛选完成 ({total_elapsed/60:.1f} 分钟)")
    print(f"\n  单特征排名（按边际贡献）:")
    print(f"  {'排名':>4}  {'特征':<30}  {'维度':<12}  {'得分':>8}  {'边际':>8}")
    print(f"  {'-'*70}")
    for rank, r in enumerate(results, 1):
        marker = "★" if rank <= PREFILTER_TOP_K else " "
        print(f"  {rank:>3}{marker}  {r['feature']:<30}  {r['dim']:<12}  "
              f"{r['score']:>8.3f}  {r['marginal_gain']:>+8.3f}")

    top_features = [r["feature"] for r in results[:PREFILTER_TOP_K]]
    print(f"\n  Top-{PREFILTER_TOP_K} 候选: {top_features}")
    return top_features, results


# ============================================================
# Stage 1: 前向贪心选择
# ============================================================

def forward_selection(candidate_features, baseline_score):
    """Stage 1: 在候选特征上做前向贪心选择

    Args:
        candidate_features: 预筛选后的候选特征列表
        baseline_score: K=0 基线得分

    Returns:
        selection_history: [{step, k, added_feature, score, marginal_gain, ...}]
    """
    print(f"\n  前向贪心选择（{len(candidate_features)} 个候选）")
    print(f"  参数: {SELECT_COINS} × {SELECT_FOLDS} 折 × {SELECT_BARS} bars")
    print(f"  早停: 连续 {EARLY_STOP_PATIENCE} 步无提升\n")

    selection_history = [{
        "step": 0,
        "k": 0,
        "added_feature": None,
        "selected_features": [],
        "score": round(baseline_score, 4),
        "marginal_gain": 0.0,
    }]

    selected = []
    remaining = list(candidate_features)
    no_improvement_count = 0
    best_score = baseline_score

    step = 0
    while remaining and no_improvement_count < EARLY_STOP_PATIENCE:
        step += 1
        print(f"\n  {'='*60}")
        print(f"  Step {step}: 尝试添加第 {len(selected)+1} 个特征（剩余 {len(remaining)} 个候选）")
        print(f"  {'='*60}")

        candidates = []
        t_step_start = time.time()

        for i, feat in enumerate(remaining, 1):
            trial_features = selected + [feat]
            t0 = time.time()
            trial_score, _ = evaluate_config(
                trial_features, SELECT_COINS, SELECT_FOLDS, SELECT_BARS
            )
            elapsed = time.time() - t0
            marginal = trial_score - best_score

            candidates.append({
                "feature": feat,
                "score": round(trial_score, 4),
                "marginal_gain": round(marginal, 4),
            })

            marker = "+" if marginal > 0 else " " if abs(marginal) < 0.01 else "-"
            print(f"    [{i:>2}/{len(remaining)}] {feat:<30} "
                  f"得分={trial_score:.3f}  边际={marginal:+.3f} {marker} "
                  f"({elapsed:.0f}s)", flush=True)

        candidates.sort(key=lambda c: c["marginal_gain"], reverse=True)
        best_candidate = candidates[0]

        if best_candidate["marginal_gain"] > 0.001:
            selected.append(best_candidate["feature"])
            remaining.remove(best_candidate["feature"])
            best_score = best_candidate["score"]
            no_improvement_count = 0
            print(f"\n  ✓ 选入: {best_candidate['feature']}")
            print(f"    得分: {best_score:.4f} (边际 +{best_candidate['marginal_gain']:.4f})")
            print(f"    当前特征集 ({len(selected)}): {selected}", flush=True)
        else:
            no_improvement_count += 1
            print(f"\n  ✗ 最佳候选 {best_candidate['feature']} 边际={best_candidate['marginal_gain']:+.4f} ≤ 0")
            print(f"    连续无提升: {no_improvement_count}/{EARLY_STOP_PATIENCE}", flush=True)

        step_elapsed = time.time() - t_step_start
        selection_history.append({
            "step": step,
            "k": len(selected),
            "added_feature": best_candidate["feature"] if best_candidate["marginal_gain"] > 0.001 else None,
            "selected_features": list(selected),
            "score": round(best_score, 4),
            "marginal_gain": round(best_candidate["marginal_gain"], 4),
            "all_candidates": candidates,
            "elapsed_s": round(step_elapsed, 1),
        })

        save_intermediate(selection_history, selected, best_score, baseline_score)
        print(f"    本步耗时: {step_elapsed:.0f}s", flush=True)

    return selection_history


def save_intermediate(history, selected, best_score, baseline_score):
    output = {
        "version": "v4-forward-selection",
        "timestamp": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "config": {
            "select_coins": SELECT_COINS,
            "select_folds": SELECT_FOLDS,
            "select_bars": SELECT_BARS,
            "early_stop_patience": EARLY_STOP_PATIENCE,
        },
        "baseline_score": round(baseline_score, 4),
        "current_best_score": round(best_score, 4),
        "selected_features": selected,
        "k": len(selected),
        "history": history,
    }
    output_path = OUTPUT_DIR / "macro_optimize_v4_intermediate.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))


# ============================================================
# 分析
# ============================================================

def print_k_vs_score_curve(history):
    print(f"\n{'='*70}")
    print(f"  K-vs-得分曲线（前向贪心选择）")
    print(f"{'='*70}")
    print(f"\n  {'K':>3}  {'得分':>8}  {'边际':>8}  {'加入特征':<30}")
    print(f"  {'-'*60}")
    for h in history:
        k = h["k"]
        score = h["score"]
        marginal = h["marginal_gain"]
        feat = h.get("added_feature") or "(基线)"
        print(f"  {k:>3}  {score:>8.3f}  {marginal:>+8.3f}  {feat:<30}")

    best_entry = max(history, key=lambda h: h["score"])
    print(f"\n  最优 K = {best_entry['k']} (得分={best_entry['score']:.3f})")
    if best_entry["k"] > 0:
        print(f"  最优特征集: {best_entry['selected_features']}")
    else:
        print(f"  最优 K=0（无宏观特征）")


# ============================================================
# Stage 2: 验证
# ============================================================

def validate_on_all_coins(selected_features, baseline_score):
    print(f"\n{'='*70}")
    print(f"  Stage 2: 验证（9 币种 × {VALIDATE_FOLDS} 折 × {VALIDATE_BARS} bars）")
    print(f"{'='*70}")

    print(f"\n  [1/2] 验证最优配置 (K={len(selected_features)})")
    if selected_features:
        print(f"  特征集: {selected_features}")
    else:
        print(f"  (无宏观特征)")

    optimal_score, optimal_per_coin = evaluate_config(
        selected_features if selected_features else None,
        ALL_COINS, VALIDATE_FOLDS, VALIDATE_BARS
    )
    print(f"\n  最优配置平均得分: {optimal_score:.4f}")

    print(f"\n  [2/2] 验证基线 K=0")
    validate_baseline_score, baseline_per_coin = evaluate_config(
        None, ALL_COINS, VALIDATE_FOLDS, VALIDATE_BARS
    )
    print(f"  基线平均得分: {validate_baseline_score:.4f}")

    print(f"\n  逐币种对比:")
    print(f"  {'币种':<8} {'K=0得分':>8} {'最优得分':>8} {'变化':>8} {'判定':>6}")
    print(f"  {'-'*45}")

    improved = 0
    severe_degrade = []
    for coin in ALL_COINS:
        k0 = baseline_per_coin.get(coin)
        opt = optimal_per_coin.get(coin)
        if k0 is None or opt is None:
            print(f"  {coin:<8} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>6}")
            continue
        change = opt["score"] - k0["score"]
        verdict = "✓" if change > 0 else "✗"
        if change > 0:
            improved += 1
        if k0["score"] > 0 and change < 0:
            degrade = -change / k0["score"]
            if degrade > 0.30:
                severe_degrade.append((coin, degrade))
        print(f"  {coin:<8} {k0['score']:>8.3f} {opt['score']:>8.3f} {change:>+8.3f} {verdict:>6}")

    print(f"\n  改善币种: {improved}/{len(ALL_COINS)}")

    print(f"\n{'='*70}")
    print(f"  落地标准检查")
    print(f"{'='*70}")

    crit1 = optimal_score > validate_baseline_score
    print(f"\n  标准1: 平均得分 > K=0 基线")
    print(f"    {optimal_score:.3f} > {validate_baseline_score:.3f} → {'✓ 通过' if crit1 else '✗ 未通过'}")

    crit2 = improved >= 6
    print(f"\n  标准2: ≥6/9 币种得分优于 K=0")
    print(f"    {improved}/9 改善 → {'✓ 通过' if crit2 else '✗ 未通过'}")

    crit3 = len(severe_degrade) == 0
    print(f"\n  标准3: 无严重退化（降幅 < 30%）")
    if severe_degrade:
        for coin, deg in severe_degrade:
            print(f"    {coin}: 退化 {deg:.1%}")
        print(f"    → ✗ 未通过")
    else:
        print(f"    → ✓ 通过")

    all_pass = crit1 and crit2 and crit3
    print(f"\n  总结: {'✓ 全部通过，可落地' if all_pass else '✗ 未全部通过，不可落地'}")

    return {
        "optimal_score": round(optimal_score, 4),
        "baseline_score": round(validate_baseline_score, 4),
        "improved_coins": improved,
        "total_coins": len(ALL_COINS),
        "severe_degrade": severe_degrade,
        "can_land": all_pass,
        "optimal_per_coin": optimal_per_coin,
        "baseline_per_coin": baseline_per_coin,
    }


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 80)
    print("  宏观特征优化 v4 — 前向贪心选择（两阶段加速）")
    print("=" * 80)
    print(f"  Stage 0: 预筛选（单特征评估 → Top-{PREFILTER_TOP_K}）")
    print(f"    {SELECT_COINS} × {SELECT_FOLDS} 折 × {SELECT_BARS} bars")
    print(f"  Stage 1: 前向贪心选择")
    print(f"    {SELECT_COINS} × {SELECT_FOLDS} 折 × {SELECT_BARS} bars, 早停={EARLY_STOP_PATIENCE}")
    print(f"  Stage 2: 验证")
    print(f"    {ALL_COINS} × {VALIDATE_FOLDS} 折 × {VALIDATE_BARS} bars")

    # 预加载数据
    print(f"\n  [准备] 预加载 K 线数据...")
    for coin in ALL_COINS:
        df = load_klines(coin, VALIDATE_BARS)
        if df is not None:
            print(f"    {coin}: {len(df)} bars")
    get_ref_df()

    t_start = time.time()

    # Step 0: 评估基线
    print(f"\n{'='*80}")
    print(f"  Step 0: 评估基线 K=0")
    print(f"{'='*80}")
    t0 = time.time()
    baseline_score, baseline_per_coin = evaluate_config(
        None, SELECT_COINS, SELECT_FOLDS, SELECT_BARS
    )
    baseline_elapsed = time.time() - t0
    print(f"  基线得分: {baseline_score:.4f} ({baseline_elapsed:.0f}s)", flush=True)
    for coin, m in baseline_per_coin.items():
        if m:
            print(f"    {coin}: 得分={m['score']:.3f}  胜率={m['win_rate']:.1%}  "
                  f"收益={m['total_return_pct']:+.1f}%  夏普={m['sharpe_ratio']:.2f}")

    # Stage 0: 预筛选
    print(f"\n{'='*80}")
    print(f"  Stage 0: 预筛选")
    print(f"{'='*80}")
    top_features, prefilter_results = prefilter_features(baseline_score)

    # Stage 1: 前向选择
    print(f"\n{'='*80}")
    print(f"  Stage 1: 前向贪心选择")
    print(f"{'='*80}")
    history = forward_selection(top_features, baseline_score)

    print_k_vs_score_curve(history)

    best_entry = max(history, key=lambda h: h["score"])
    selected_features = best_entry["selected_features"]
    best_select_score = best_entry["score"]

    select_elapsed = time.time() - t_start
    print(f"\n  选择阶段总耗时: {select_elapsed/60:.1f} 分钟")
    print(f"  基线得分: {baseline_score:.4f} → 最优得分: {best_select_score:.4f} (K={len(selected_features)})")

    # Stage 2: 验证
    validation = validate_on_all_coins(selected_features, baseline_score)

    # 保存最终结果
    output = {
        "version": "v4-forward-selection",
        "created_at": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "config": {
            "select_coins": SELECT_COINS,
            "select_folds": SELECT_FOLDS,
            "select_bars": SELECT_BARS,
            "validate_coins": ALL_COINS,
            "validate_folds": VALIDATE_FOLDS,
            "validate_bars": VALIDATE_BARS,
            "prefilter_top_k": PREFILTER_TOP_K,
            "early_stop_patience": EARLY_STOP_PATIENCE,
            "conf_threshold": CONF_THRESHOLD,
            "tp_atr": TP_ATR,
            "sl_atr": SL_ATR,
            "max_hold_bars": MAX_HOLD_BARS,
            "fee_rate": FEE_RATE,
            "slippage_rate": SLIPPAGE_RATE,
        },
        "baseline_score": round(baseline_score, 4),
        "best_select_score": round(best_select_score, 4),
        "optimal_k": len(selected_features),
        "optimal_features": selected_features,
        "prefilter_results": prefilter_results,
        "selection_history": history,
        "validation": validation,
        "total_elapsed_min": round((time.time() - t_start) / 60, 1),
    }

    output_path = OUTPUT_DIR / "macro_optimize_v4.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n  结果已保存: {output_path}")

    # 最终结论
    print(f"\n{'='*80}")
    print(f"  最终结论")
    print(f"{'='*80}")
    if selected_features:
        print(f"  最优 K = {len(selected_features)}")
        print(f"  最优特征集: {selected_features}")
        print(f"  选择阶段: {baseline_score:.4f} → {best_select_score:.4f} "
              f"(+{best_select_score - baseline_score:.4f})")
        print(f"  验证阶段: {validation['baseline_score']:.4f} → {validation['optimal_score']:.4f} "
              f"(+{validation['optimal_score'] - validation['baseline_score']:.4f})")
        print(f"  改善币种: {validation['improved_coins']}/{validation['total_coins']}")
        print(f"  落地判定: {'✓ 可落地' if validation['can_land'] else '✗ 不可落地'}")
    else:
        print(f"  最优 K = 0（无宏观特征）")
        print(f"  结论: 宏观特征在当前数据质量下不带来稳定收益")
        print(f"  建议: 维持 baseline-v1，待宏观数据源补齐后再优化")
    print(f"\n{'='*80}")


if __name__ == "__main__":
    main()
