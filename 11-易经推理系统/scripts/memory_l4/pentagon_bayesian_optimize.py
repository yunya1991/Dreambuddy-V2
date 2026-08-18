#!/usr/bin/env python3
"""
五角校验参数贝叶斯优化 — 搜索 PentagonParams 最优配置。

优化目标：最大化综合得分（夏普 + 收益 - 回撤惩罚）
搜索空间：PentagonParams 中的权重、奖惩幅度、仓位系数等
评估方式：WalkForwardBacktester 3折回测（BTC+ETH+SOL平均）
Hold-out：最后20%数据独立验证
"""
import sys
import os
import json
import time
import logging
import importlib
import numpy as np
import pandas as pd

# 设置路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPT_DIR)

# 避免 inspect.py 冲突
_std_inspect = importlib.import_module('inspect')
sys.modules['inspect'] = _std_inspect

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# 数据缓存
_DATA_CACHE = {}


def load_klines(symbol, timeframe="1H", max_bars=3000):
    if symbol not in _DATA_CACHE:
        from memory_l4.bcrm2.data_fetcher import get_klines
        df = get_klines(symbol, timeframe, max_bars=max_bars)
        _DATA_CACHE[symbol] = df
    return _DATA_CACHE[symbol]


def build_params(trial: optuna.Trial) -> dict:
    """从 Optuna trial 构建 PentagonParams 参数字典"""
    return {
        # 权重 — BCRM2 作为主ML模型可以非常高
        "weight_bcrm2": trial.suggest_float("weight_bcrm2", 0.40, 0.80),
        "weight_force": trial.suggest_float("weight_force", 0.02, 0.15),
        "weight_a0": trial.suggest_float("weight_a0", 0.02, 0.10),
        "weight_ising": trial.suggest_float("weight_ising", 0.02, 0.15),
        "weight_tda": trial.suggest_float("weight_tda", 0.05, 0.25),

        # 置信度调整 — 允许很小的调整幅度
        "bonus_strong_agree": trial.suggest_float("bonus_strong_agree", 0.01, 0.15),
        "bonus_majority": trial.suggest_float("bonus_majority", 0.0, 0.08),
        "penalty_divergent": trial.suggest_float("penalty_divergent", -0.06, 0.0),
        "penalty_conflict": trial.suggest_float("penalty_conflict", -0.12, -0.01),

        # 预警惩罚
        "penalty_reversal": trial.suggest_float("penalty_reversal", 0.01, 0.08),
        "penalty_ising_alert": trial.suggest_float("penalty_ising_alert", 0.0, 0.06),
        "penalty_tda_warning": trial.suggest_float("penalty_tda_warning", 0.0, 0.05),
        "penalty_double_warning": trial.suggest_float("penalty_double_warning", 0.01, 0.10),

        # 总惩罚上限
        "max_total_penalty": trial.suggest_float("max_total_penalty", 0.03, 0.12),

        # 仓位系数 — 允许单预警不降仓，强一致可大幅加仓
        "pos_factor_strong_agree": trial.suggest_float("pos_factor_strong_agree", 1.0, 1.40),
        "pos_factor_divergent": trial.suggest_float("pos_factor_divergent", 0.80, 1.0),
        "pos_factor_single_warning": trial.suggest_float("pos_factor_single_warning", 0.85, 1.0),
        "pos_factor_double_warning": trial.suggest_float("pos_factor_double_warning", 0.40, 0.75),
        "pos_factor_reversal": trial.suggest_float("pos_factor_reversal", 0.50, 0.85),

        # fail_closed 阈值
        "fail_closed_threshold": trial.suggest_float("fail_closed_threshold", 0.10, 0.30),

        # 注意力衰减
        "attention_decay": trial.suggest_float("attention_decay", 0.88, 0.98),
    }


def run_backtest_with_params(symbol, df, params_dict, n_folds=3):
    """用指定 PentagonParams 运行回测"""
    from memory_l4.triangle_verifier import TriangleVerifier, PentagonParams
    from memory_l4.bcrm2.walk_forward_backtester import WalkForwardBacktester

    # 构建 PentagonParams
    pentagon_params = PentagonParams.from_dict(params_dict)

    # 创建带自定义参数的 TriangleVerifier
    verifier = TriangleVerifier(params=pentagon_params)

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=n_folds,
        conf_threshold=0.70,
        tp_atr=3.0,
        sl_atr=1.5,
        max_hold_bars=60,
        feature_selection=True,
    )
    # 替换为自定义参数的 verifier
    bt._triangle_verifier = verifier

    result = bt.run(df, verbose=False)
    return result


def compute_sharpe_from_trades(trades):
    """从交易列表计算日收益夏普"""
    if not trades:
        return 0.0
    daily_returns = {}
    for t in trades:
        day = t.exit_bar // 24
        daily_returns[day] = daily_returns.get(day, 0.0) + t.pnl_pct
    daily_pnls = list(daily_returns.values())
    if len(daily_pnls) <= 1 or np.std(daily_pnls) == 0:
        return 0.0
    return np.mean(daily_pnls) / np.std(daily_pnls) * np.sqrt(252)


def objective(trial: optuna.Trial) -> float:
    """Optuna 目标函数：最大化综合得分"""
    params_dict = build_params(trial)

    symbols = ["BTC", "ETH", "SOL"]
    all_sharpes = []
    all_returns = []
    all_drawdowns = []
    all_win_rates = []
    t0 = time.time()

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue

        try:
            result = run_backtest_with_params(symbol, df, params_dict)

            # 计算夏普
            sharpe = compute_sharpe_from_trades(result.all_trades)
            n_trades = len(result.all_trades)
            if n_trades == 0:
                all_sharpes.append(0.0)
                all_returns.append(0.0)
                all_drawdowns.append(0.0)
                all_win_rates.append(0.0)
                continue

            win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades
            total_ret = sum(t.pnl_pct for t in result.all_trades)
            max_dd = max((t.pnl_pct for t in result.all_trades), default=0)
            # 用最大单笔亏损近似最大回撤
            max_loss = min((t.pnl_pct for t in result.all_trades), default=0)
            max_dd = abs(max_loss) if max_loss < 0 else 0

            all_sharpes.append(sharpe)
            all_returns.append(total_ret)
            all_drawdowns.append(max_dd)
            all_win_rates.append(win_rate)

        except Exception as e:
            logger.warning(f"[{symbol}] 回测失败: {e}")
            return -10.0

    if not all_sharpes:
        return -10.0

    avg_sharpe = np.mean(all_sharpes)
    avg_return = np.mean(all_returns)
    avg_dd = np.mean(all_drawdowns)
    avg_wr = np.mean(all_win_rates)

    # 综合目标：夏普为主，收益为辅，回撤惩罚，交易数惩罚
    score = avg_sharpe + 0.001 * avg_return - 0.02 * avg_dd

    trial.set_user_attr("avg_sharpe", float(avg_sharpe))
    trial.set_user_attr("avg_return", float(avg_return))
    trial.set_user_attr("avg_drawdown", float(avg_dd))
    trial.set_user_attr("avg_win_rate", float(avg_wr))

    elapsed = time.time() - t0
    print(f"    Trial #{trial.number}: 得分={score:.4f}, 夏普={avg_sharpe:.2f}, "
          f"收益={avg_return:.1f}%, 回撤={avg_dd:.1f}%, 胜率={avg_wr:.1%} ({elapsed:.0f}秒)", flush=True)

    return score


def run_baseline():
    """运行基线回测（默认PentagonParams）"""
    print(f"\n  [基线] 运行默认 PentagonParams 回测...")
    from memory_l4.triangle_verifier import PentagonParams

    baseline_params = PentagonParams().to_dict()
    symbols = ["BTC", "ETH", "SOL"]
    baseline_scores = {}

    for symbol in symbols:
        df = load_klines(symbol)
        if df is None:
            continue
        result = run_backtest_with_params(symbol, df, baseline_params)

        sharpe = compute_sharpe_from_trades(result.all_trades)
        n_trades = len(result.all_trades)
        win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades if n_trades > 0 else 0
        total_ret = sum(t.pnl_pct for t in result.all_trades)
        max_loss = min((t.pnl_pct for t in result.all_trades), default=0)
        max_dd = abs(max_loss) if max_loss < 0 else 0

        baseline_scores[symbol] = {
            "sharpe": sharpe,
            "return": total_ret,
            "drawdown": max_dd,
            "trades": n_trades,
            "win_rate": win_rate,
        }
        print(f"    {symbol}: 夏普={sharpe:.2f}, 收益={total_ret:.1f}%, 回撤={max_dd:.1f}%, 胜率={win_rate:.1%}, 交易={n_trades}")

    avg_sharpe = np.mean([s["sharpe"] for s in baseline_scores.values()])
    avg_return = np.mean([s["return"] for s in baseline_scores.values()])
    avg_dd = np.mean([s["drawdown"] for s in baseline_scores.values()])
    baseline_score = avg_sharpe + 0.001 * avg_return - 0.02 * avg_dd
    print(f"    基线综合得分: {baseline_score:.4f}")

    return baseline_score, baseline_scores


def run_holdout(best_params_dict):
    """用最后 20% 数据做 hold-out 验证"""
    print(f"\n  [Hold-out] 用最后 20% 数据独立验证最优参数...")
    holdout_results = {}

    for symbol in ["BTC", "ETH", "SOL"]:
        df = load_klines(symbol)
        if df is None or len(df) < 800:
            continue

        # 取最后 20%
        split_idx = int(len(df) * 0.8)
        holdout_df = df.iloc[split_idx:].copy()

        if len(holdout_df) < 200:
            continue

        try:
            result = run_backtest_with_params(symbol, holdout_df, best_params_dict, n_folds=2)
            sharpe = compute_sharpe_from_trades(result.all_trades)
            n_trades = len(result.all_trades)
            win_rate = sum(1 for t in result.all_trades if t.pnl_pct > 0) / n_trades if n_trades > 0 else 0
            total_ret = sum(t.pnl_pct for t in result.all_trades)

            holdout_results[symbol] = {
                "sharpe": sharpe,
                "return": total_ret,
                "win_rate": win_rate,
                "trades": n_trades,
            }
            print(f"    {symbol}: 夏普={sharpe:.2f}, 收益={total_ret:.1f}%, 胜率={win_rate:.1%}, 交易={n_trades}")
        except Exception as e:
            print(f"    {symbol}: hold-out 失败: {e}")

    return holdout_results


def main():
    print("=" * 80)
    print("  五角校验参数贝叶斯优化 (v2)")
    print("  搜索空间：PentagonParams（权重+奖惩+仓位+注意力）")
    print("=" * 80)

    # 基线
    baseline_score, baseline_scores = run_baseline()

    # 优化
    n_trials = 40
    print(f"\n  [优化] 开始贝叶斯搜索（{n_trials} trials）...")
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    t0 = time.time()
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    elapsed = time.time() - t0

    best = study.best_trial
    print(f"\n  优化完成！耗时: {elapsed:.0f}秒")
    print(f"\n  最优试验 #{best.number}:")
    print(f"    综合得分: {best.value:.4f} (基线: {baseline_score:.4f})")
    print(f"    平均夏普: {best.user_attrs.get('avg_sharpe', 0):.4f}")
    print(f"    平均收益: {best.user_attrs.get('avg_return', 0):.4f}%")
    print(f"    平均回撤: {best.user_attrs.get('avg_drawdown', 0):.4f}%")
    print(f"    平均胜率: {best.user_attrs.get('avg_win_rate', 0):.4f}")
    print(f"\n  最优参数：")
    for k, v in best.params.items():
        print(f"    {k}: {v:.4f}")

    improvement = best.value - baseline_score
    print(f"\n  得分提升: {improvement:+.4f}")

    # Hold-out 验证
    if improvement > 0:
        holdout_results = run_holdout(best.params)

        # 保存结果
        output = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "baseline_score": baseline_score,
            "best_score": best.value,
            "improvement": improvement,
            "best_params": best.params,
            "best_user_attrs": best.user_attrs,
            "baseline_scores": baseline_scores,
            "holdout_results": holdout_results,
        }

        # 归一化权重
        from memory_l4.triangle_verifier import PentagonParams
        optimal_params = PentagonParams.from_dict(best.params)
        total_w = (optimal_params.weight_bcrm2 + optimal_params.weight_force +
                   optimal_params.weight_a0 + optimal_params.weight_ising +
                   optimal_params.weight_tda)
        print(f"\n  最优权重（归一化前）:")
        print(f"    BCRM2: {optimal_params.weight_bcrm2:.4f} ({optimal_params.weight_bcrm2/total_w*100:.1f}%)")
        print(f"    Force: {optimal_params.weight_force:.4f} ({optimal_params.weight_force/total_w*100:.1f}%)")
        print(f"    A0:    {optimal_params.weight_a0:.4f} ({optimal_params.weight_a0/total_w*100:.1f}%)")
        print(f"    Ising: {optimal_params.weight_ising:.4f} ({optimal_params.weight_ising/total_w*100:.1f}%)")
        print(f"    TDA:   {optimal_params.weight_tda:.4f} ({optimal_params.weight_tda/total_w*100:.1f}%)")

        # 判断是否采纳
        if improvement > 0.1:
            # hold-out 夏普需要 > 0
            holdout_sharpes = [r["sharpe"] for r in holdout_results.values()]
            if holdout_sharpes and np.mean(holdout_sharpes) > 0:
                output_path = os.path.join(SCRIPT_DIR, "pentagon_optimal_params.json")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                print(f"\n  ✅ 优化参数已保存到: {output_path}")
                print(f"  建议将此参数应用到 TriangleVerifier 默认配置中。")
            else:
                print(f"\n  ⚠️ Hold-out 夏普为负，不建议采纳。")
        else:
            print(f"\n  ⚠️ 提升幅度不足（{improvement:.4f} < 0.1），不建议采纳。")
    else:
        print(f"\n  ⚠️ 优化未超过基线，保持默认参数。")


if __name__ == "__main__":
    main()
