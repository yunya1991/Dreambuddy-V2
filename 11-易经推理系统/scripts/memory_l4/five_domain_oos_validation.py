"""战略层样本外验证（OOS）

用 2026-01-01 作为分割点：
- 训练集：2026-01-01 之前 → 计算 IC 权重 + 优化五域权重
- 测试集：2026-01-01 至今 → 验证 Sharpe 提升是否持续

用法：
    python five_domain_oos_validation.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DB_PATH = _REPO / "18-数据获取中心" / "data_center.db"
_RUNTIME = _HERE / "runtime"
_OUTPUT = _RUNTIME / "five_domain_oos_validation.json"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from five_domain_ic_analysis import _get_daily_snapshots  # noqa: E402
from five_domain_weight_optuna import (  # noqa: E402
    get_price_returns,
    compute_walkforward_sharpe,
    compute_max_drawdown,
    score_to_position,
    _fill_proxy_fields,
    _fetch_yf_returns,
    ASSET_RETURN_MAP,
)
from five_domain_subindicator_ic import (  # noqa: E402
    compute_subindicator_ic_weights,
    apply_ic_weights_to_snapshot,
    cap_subindicator_weights,
    compute_walkforward_sharpe_capped,
    compute_max_drawdown_capped,
    sobol_sensitivity_test_capped,
)

OOS_SPLIT_DATE = "2026-01-01"
MAX_POSITION = {"crypto_usdt": 1.0, "us_stock": 1.0, "precious_metal": 0.7}
MAX_SUB_WEIGHT = {"crypto_usdt": 1.0, "us_stock": 1.0, "precious_metal": 0.40}


def split_snapshots(snapshots, split_date: str):
    train = [(d, c) for d, c in snapshots if d < split_date]
    test = [(d, c) for d, c in snapshots if d >= split_date]
    return train, test


def split_returns(returns: Dict[str, float], split_date: str):
    train = {d: r for d, r in returns.items() if d < split_date}
    test = {d: r for d, r in returns.items() if d >= split_date}
    return train, test


def main() -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)

    print(f"[OOS] 分割点: {OOS_SPLIT_DATE}")
    snapshots = _get_daily_snapshots(_DB_PATH)
    train_snaps, test_snaps = split_snapshots(snapshots, OOS_SPLIT_DATE)
    print(f"[OOS] 训练样本: {len(train_snaps)}, 测试样本: {len(test_snaps)}")

    if len(test_snaps) < 30:
        print(f"[OOS] 测试样本不足({len(test_snaps)}<30)，无法验证")
        return

    returns_all = get_price_returns()

    # 预获取价格历史用于代理填充
    cls_prices = {}
    cls_price_history = {}
    for cls, symbol in ASSET_RETURN_MAP.items():
        prices = _fetch_yf_returns(symbol, days=1500)
        cls_prices[cls] = prices
        cls_price_history[cls] = sorted(prices.items(), key=lambda x: x[0])

    def fill_snaps(snaps):
        filled = []
        for date_str, coin_data in snaps:
            f = {}
            for cls, cd in coin_data.items():
                f[cls] = _fill_proxy_fields(cd, cls_prices.get(cls, {}),
                                            cls_price_history.get(cls, []), date_str)
            filled.append((date_str, f))
        return filled

    train_filled = fill_snaps(train_snaps)
    test_filled = fill_snaps(test_snaps)

    results = {}

    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        cls_returns_all = returns_all.get(cls, {})
        train_ret, test_ret = split_returns(cls_returns_all, OOS_SPLIT_DATE)

        if len(test_ret) < 30:
            print(f"[OOS] {cls}: 测试收益样本不足({len(test_ret)}<30)，跳过")
            continue

        max_pos = MAX_POSITION.get(cls, 1.0)
        max_sub = MAX_SUB_WEIGHT.get(cls, 1.0)
        baseline_w = {"dao": 0.2, "tian": 0.2, "di": 0.2, "jiang": 0.2, "fa": 0.2}

        # ── 训练集：计算 IC 权重 ──
        print(f"[OOS] {cls}: 训练集计算 IC 权重...")
        ic_weights = compute_subindicator_ic_weights(train_filled, train_ret, cls)
        if max_sub < 1.0:
            ic_weights = cap_subindicator_weights(ic_weights, max_single=max_sub)

        # ── 训练集：优化五域权重 ──
        train_scores_ic = {}
        for date_str, coin_data in train_filled:
            cd = coin_data.get(cls, {})
            if not cd:
                continue
            dims = apply_ic_weights_to_snapshot(cd, ic_weights)
            train_scores_ic[date_str] = {cls: {**dims, "jiang": 50.0, "fa": 50.0}}

        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            w = {k: trial.suggest_float(k, 0.05, 0.50) for k in ("dao", "tian", "di", "jiang", "fa")}
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            return compute_walkforward_sharpe_capped(train_scores_ic, train_ret, w, cls, max_position=max_pos)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=150)
        best_w = study.best_params
        total = sum(best_w.values())
        best_w = {k: v / total for k, v in best_w.items()}

        # ── 测试集：评估 IC 加权策略 ──
        test_scores_ic = {}
        for date_str, coin_data in test_filled:
            cd = coin_data.get(cls, {})
            if not cd:
                continue
            dims = apply_ic_weights_to_snapshot(cd, ic_weights)
            test_scores_ic[date_str] = {cls: {**dims, "jiang": 50.0, "fa": 50.0}}

        # 测试集 Sharpe（直接用全部测试数据，非 walk-forward，因为样本少）
        def full_sharpe(scores, returns, weights, asset_class, max_pos_):
            all_dates = sorted(set(scores.keys()) & set(returns.keys()))
            w = np.array([weights.get(d, 0.2) for d in ("dao", "tian", "di", "jiang", "fa")])
            w = w / w.sum()
            daily_rets = []
            for d in all_dates:
                dims = scores[d].get(asset_class, {})
                total = sum(w[i] * dims.get(dim, 50.0) for i, dim in enumerate(("dao", "tian", "di", "jiang", "fa")))
                pos = score_to_position(total) * max_pos_
                ret = returns.get(d, 0.0)
                daily_rets.append(pos * ret)
            if len(daily_rets) < 10:
                return 0.0
            arr = np.array(daily_rets)
            std = np.std(arr, ddof=1)
            if std < 1e-9:
                return 0.0
            return float(np.mean(arr) / std * np.sqrt(365))

        # 等权基线测试集表现
        test_scores_equal = {}
        for date_str, coin_data in test_filled:
            cd = coin_data.get(cls, {})
            if not cd:
                continue
            # 等权：直接用 precompute 的结果（需要重新计算）
            # 简化：用 5 子指标等权
            from five_domain_subindicator_ic import compute_dao_subindicators, compute_tian_subindicators, compute_di_subindicators
            dao = np.mean(list(compute_dao_subindicators(cd).values()))
            tian = np.mean(list(compute_tian_subindicators(cd).values()))
            di = np.mean(list(compute_di_subindicators(cd).values()))
            test_scores_equal[date_str] = {cls: {"dao": dao, "tian": tian, "di": di, "jiang": 50.0, "fa": 50.0}}

        baseline_test_sharpe = full_sharpe(test_scores_equal, test_ret, baseline_w, cls, 1.0)
        ic_test_sharpe = full_sharpe(test_scores_ic, test_ret, best_w, cls, max_pos)

        baseline_mdd = compute_max_drawdown(test_scores_equal, test_ret, baseline_w, cls)
        ic_mdd = compute_max_drawdown_capped(test_scores_ic, test_ret, best_w, cls, max_position=max_pos)

        results[cls] = {
            "train_samples": len(train_ret),
            "test_samples": len(test_ret),
            "train_best_walkforward_sharpe": round(float(study.best_value), 4),
            "test_baseline_sharpe": round(baseline_test_sharpe, 4),
            "test_ic_sharpe": round(ic_test_sharpe, 4),
            "test_sharpe_improvement": round(ic_test_sharpe - baseline_test_sharpe, 4),
            "test_baseline_mdd": round(baseline_mdd, 4),
            "test_ic_mdd": round(ic_mdd, 4),
            "test_mdd_ratio": round(ic_mdd / baseline_mdd if baseline_mdd > 0 else 1.0, 4),
            "best_weights": {k: round(v, 4) for k, v in best_w.items()},
            "ic_weights": {d: {k: round(v, 4) for k, v in w.items()} for d, w in ic_weights.items()},
            "oos_pass": ic_test_sharpe > baseline_test_sharpe,
        }
        print(f"[OOS] {cls}:")
        print(f"    训练 WF Sharpe: {study.best_value:.4f}")
        print(f"    测试集: 基线={baseline_test_sharpe:.4f} IC={ic_test_sharpe:.4f} 提升={ic_test_sharpe - baseline_test_sharpe:+.4f} {'✅' if ic_test_sharpe > baseline_test_sharpe else '❌'}")
        print(f"    回撤: 基线={baseline_mdd:.2%} IC={ic_mdd:.2%} 比率={ic_mdd / baseline_mdd if baseline_mdd > 0 else 1.0:.3f}")

    output = {
        "timestamp": datetime.now().isoformat(),
        "split_date": OOS_SPLIT_DATE,
        "results": results,
    }
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[OOS] 结果已保存: {_OUTPUT}")


if __name__ == "__main__":
    main()
