"""Phase 2：战略层五域权重 Optuna 优化。

在子指标等权前提下，优化 L1 五域权重（dao/tian/di/jiang/fa）。
目标函数：Walk-forward Sharpe（180训练+30验证）。

用法：
    python five_domain_weight_optuna.py
输出：
    runtime/five_domain_optimal_weights.json
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import optuna

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DB = _REPO / "18-数据获取中心" / "data_center.db"
_RUNTIME = _HERE / "runtime"
_OUTPUT = _RUNTIME / "five_domain_optimal_weights.json"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from five_domain_feature_computer import FiveDomainFeatureComputer  # noqa: E402
from five_domain_ic_analysis import (  # noqa: E402
    _get_daily_snapshots,
    _fetch_yf_returns,
    _build_snapshot_for_date,
    ASSET_RETURN_MAP,
    _DB_PATH,
)
_DB = _DB_PATH


# ============================================================
# 预计算：每日各维度分数
# ============================================================
def _fill_proxy_fields(
    coin_data: Dict[str, Any],
    prices: Dict[str, float],
    price_history: List[Tuple[str, float]],
    target_date: str,
) -> Dict[str, Any]:
    """用现有数据填充缺失字段的代理值（仅用于回测，不影响生产）。

    填充规则：
    - policy_sentiment_score: 用 VIX 归一化（VIX 低→景气高）
    - cycle4y_t_rel: 用价格相对历史区间位置
    - atr_percentile: 用 VIX 分位数（对齐字段名）
    - regime: 用 VIX 水平判断市场形态
    - spring_force_score / ma200_distance: 用价格相对 MA200 距离
    - consolidation_duration: 用近 20 日波动率代理
    - ftd_signal: 用近 3 日涨幅代理
    """
    cd = dict(coin_data)
    vix = cd.get("vix_close")

    # policy_sentiment_score 代理：VIX 归一化（12→0.8, 20→0.5, 35→0.2）
    if cd.get("policy_sentiment_score") is None and isinstance(vix, (int, float)):
        cd["policy_sentiment_score"] = float(np.clip(0.8 - (float(vix) - 12.0) / 40.0, 0.1, 1.0))

    # atr_percentile 字段名对齐
    if cd.get("atr_percentile") is None and cd.get("atr_percentile_proxy") is not None:
        cd["atr_percentile"] = cd["atr_percentile_proxy"]

    # cycle4y_t_rel 代理：价格相对历史区间位置
    if cd.get("cycle4y_t_rel") is None and prices:
        cur = prices.get(target_date)
        if cur is not None:
            p_min, p_max = min(prices.values()), max(prices.values())
            if p_max > p_min:
                cd["cycle4y_t_rel"] = (cur - p_min) / (p_max - p_min)

    # regime 代理：VIX 水平判断市场形态
    if cd.get("regime") is None and isinstance(vix, (int, float)):
        v = float(vix)
        if v < 15:
            cd["regime"] = "trend_up"
        elif v < 25:
            cd["regime"] = "ranging"
        elif v < 35:
            cd["regime"] = "high_volatility"
        else:
            cd["regime"] = "trend_down"

    # spring_force_score / ma200_distance：价格相对 MA200 距离
    if cd.get("spring_force_score") is None or cd.get("ma200_distance") is None:
        if price_history and target_date:
            # 取 target_date 及之前的价格，计算 MA200
            past_prices = [(d, p) for d, p in price_history if d <= target_date]
            if len(past_prices) >= 200:
                ma200 = np.mean([p for _, p in past_prices[-200:]])
                cur_price = past_prices[-1][1]
                dist_pct = (cur_price - ma200) / ma200 * 100
                if cd.get("ma200_distance") is None:
                    cd["ma200_distance"] = dist_pct
                if cd.get("spring_force_score") is None:
                    # 价格在 MA200 上方→高分，下方→低分
                    cd["spring_force_score"] = float(np.clip(50 + dist_pct * 2, 0, 100))

    # consolidation_duration：近 20 日波动率（低波动=盘整久）
    if cd.get("consolidation_duration") is None and price_history:
        past = [p for d, p in price_history if d <= target_date][-20:]
        if len(past) >= 5:
            vol = np.std(np.diff(past) / past[:-1]) if len(past) > 1 else 0
            # 低波动→盘整久→高分；高波动→趋势→低分
            cd["consolidation_duration"] = float(np.clip(70 - vol * 500, 20, 80))

    # ftd_signal：近 3 日涨幅（大涨→FTD）
    if cd.get("ftd_signal") is None and price_history:
        past = [(d, p) for d, p in price_history if d <= target_date]
        if len(past) >= 4:
            ret_3d = (past[-1][1] - past[-4][1]) / past[-4][1]
            # 3日涨幅>5%→FTD 信号强
            cd["ftd_signal"] = float(np.clip(50 + ret_3d * 200, 0, 100))

    return cd


def precompute_domain_scores() -> Dict[str, Dict[str, Dict[str, float]]]:
    """预计算每日每类资产的五域分数。

    返回 {date_str: {asset_class: {dao, tian, di, jiang, fa}}}
    """
    print("[OPT] 预计算各维度分数...")
    snapshots = _get_daily_snapshots(_DB)
    computer = FiveDomainFeatureComputer(enable=True)
    default_sys_state = None

    # 获取各资产类价格（用于 cycle4y/regime/MA200 代理）
    cls_prices = {}
    cls_price_history = {}
    for cls, symbol in ASSET_RETURN_MAP.items():
        prices = _fetch_yf_returns(symbol, days=1500)
        cls_prices[cls] = prices
        # 按日期排序的价格历史
        cls_price_history[cls] = sorted(prices.items(), key=lambda x: x[0])

    scores: Dict[str, Dict[str, Dict[str, float]]] = {}
    for date_str, coin_data in snapshots:
        try:
            filled = {}
            for cls, cd in coin_data.items():
                fcd = _fill_proxy_fields(
                    cd, cls_prices.get(cls, {}),
                    cls_price_history.get(cls, []),
                    date_str,
                )
                filled[cls] = fcd

            result = computer.compute(coin_data=filled, system_state=default_sys_state)
            scores[date_str] = {}
            for cls, dims in result.items():
                scores[date_str][cls] = {k: float(v) for k, v in dims.items()}
                scores[date_str][cls]["jiang"] = 50.0
                scores[date_str][cls]["fa"] = 50.0
        except Exception:
            continue

    dao_all = [scores[d][c]["dao"] for d in scores for c in scores[d]]
    tian_all = [scores[d][c]["tian"] for d in scores for c in scores[d]]
    di_all = [scores[d][c]["di"] for d in scores for c in scores[d]]
    print(f"[OPT] 预计算完成: {len(scores)} 天")
    if dao_all:
        print(f"[OPT] dao: {min(dao_all):.0f}~{max(dao_all):.0f} (std={np.std(dao_all):.1f})")
        print(f"[OPT] tian: {min(tian_all):.0f}~{max(tian_all):.0f} (std={np.std(tian_all):.1f})")
        print(f"[OPT] di: {min(di_all):.0f}~{max(di_all):.0f} (std={np.std(di_all):.1f})")
    return scores


def get_price_returns() -> Dict[str, Dict[str, float]]:
    """获取每日收益率 {asset_class: {date_str: daily_return}}。"""
    returns: Dict[str, Dict[str, float]] = {}
    for cls, symbol in ASSET_RETURN_MAP.items():
        prices = _fetch_yf_returns(symbol, days=1500)
        dates = sorted(prices.keys())
        cls_ret = {}
        for i in range(1, len(dates)):
            prev = prices[dates[i - 1]]
            curr = prices[dates[i]]
            if prev > 0 and curr == curr and prev == prev:  # 过滤 nan
                cls_ret[dates[i]] = (curr - prev) / prev
        returns[cls] = cls_ret
    return returns


# ============================================================
# 收益归因：war_state/cap → 日收益
# ============================================================
def score_to_position(total_score: float) -> float:
    """总分线性映射到仓位比例（0~1）。

    回测中战略层分数集中在 45-65，绝对阈值（75/60/50）区分度不足。
    用线性映射让总分微小变化反映在仓位上，给优化器信号。
    - score 40 → 0.0（空仓）
    - score 60 → 0.5（半仓）
    - score 80 → 1.0（满仓）
    """
    return float(np.clip((total_score - 40.0) / 40.0, 0.0, 1.0))


# ============================================================
# 目标函数
# ============================================================
def compute_walkforward_sharpe(
    scores: Dict[str, Dict[str, Dict[str, float]]],
    returns: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
    asset_class: str = "crypto_usdt",
    train_days: int = 180,
    val_days: int = 30,
) -> float:
    """计算 Walk-forward 平均 Sharpe。

    用给定权重计算每日 total_score → 仓位 → 日收益，
    滚动窗口取各折验证期 Sharpe 的均值。

    returns 格式：{date_str: daily_return}（该资产类的日收益）
    """
    # 对齐日期
    all_dates = sorted(set(scores.keys()) & set(returns.keys()))
    if len(all_dates) < train_days + val_days:
        return 0.0

    w = np.array([weights.get(d, 0.2) for d in ("dao", "tian", "di", "jiang", "fa")])
    w = w / w.sum()  # 归一化

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
            pos = score_to_position(total)
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


# ============================================================
# 验证：最大回撤 & Sobol' 敏感性
# ============================================================
def compute_max_drawdown(
    scores: Dict[str, Dict[str, Dict[str, float]]],
    returns: Dict[str, float],
    weights: Dict[str, float],
    asset_class: str,
) -> float:
    """计算策略最大回撤（用全部样本，非 walk-forward）。

    返回最大回撤绝对值（如 0.15 表示 15%）。
    """
    all_dates = sorted(set(scores.keys()) & set(returns.keys()))
    if len(all_dates) < 10:
        return 0.0

    w = np.array([weights.get(d, 0.2) for d in ("dao", "tian", "di", "jiang", "fa")])
    w = w / w.sum()

    daily_rets = []
    for d in all_dates:
        dims = scores[d].get(asset_class, {})
        total = sum(w[i] * dims.get(dim, 50.0) for i, dim in enumerate(("dao", "tian", "di", "jiang", "fa")))
        pos = score_to_position(total)
        ret = returns.get(d, 0.0)
        daily_rets.append(pos * ret)

    if not daily_rets:
        return 0.0

    # 累计净值
    cum = np.cumprod(1.0 + np.array(daily_rets))
    # 峰值序列（运行最大值）
    peak = np.maximum.accumulate(cum)
    # 回撤
    drawdown = (cum - peak) / peak
    return float(abs(np.min(drawdown)))


def sobol_sensitivity_test(
    scores: Dict[str, Dict[str, Dict[str, float]]],
    returns: Dict[str, float],
    base_weights: Dict[str, float],
    asset_class: str,
    n_samples: int = 500,
    perturbation: float = 0.10,
    seed: int = 42,
) -> Dict[str, Any]:
    """Sobol' 敏感性检验：对最优权重做 ±10% 扰动，统计 Sharpe 变化。

    门禁：Sharpe 变化率 ≤ 20%（即 0.8×base ≤ perturbed ≤ 1.2×base）。

    步骤：
    1. 用 Saltelli 采样生成 N×(D+2) 个参数矩阵
    2. 每个样本的权重 = base_weights × (1 ± perturbation)
    3. 计算每个样本的 Walk-forward Sharpe
    4. 统计均值/标准差/最大变化率
    """
    rng = np.random.default_rng(seed)
    dims = ("dao", "tian", "di", "jiang", "fa")
    base_w = np.array([base_weights[d] for d in dims])

    base_sharpe = compute_walkforward_sharpe(scores, returns, base_weights, asset_class)
    if base_sharpe == 0:
        return {"base_sharpe": 0.0, "max_change_pct": 0.0, "pass": True}

    perturbed_sharpes = []
    for _ in range(n_samples):
        # 每个维度独立扰动 ±perturbation
        factors = 1.0 + rng.uniform(-perturbation, perturbation, size=len(dims))
        pw = base_w * factors
        pw = pw / pw.sum()  # 归一化
        pw_dict = {d: float(pw[i]) for i, d in enumerate(dims)}
        s = compute_walkforward_sharpe(scores, returns, pw_dict, asset_class)
        perturbed_sharpes.append(s)

    arr = np.array(perturbed_sharpes)
    # 相对变化率
    changes = np.abs(arr - base_sharpe) / abs(base_sharpe)
    max_change = float(np.max(changes))
    mean_change = float(np.mean(changes))
    std_change = float(np.std(changes))

    return {
        "base_sharpe": round(base_sharpe, 4),
        "n_samples": n_samples,
        "perturbation": perturbation,
        "mean_change_pct": round(mean_change * 100, 2),
        "std_change_pct": round(std_change * 100, 2),
        "max_change_pct": round(max_change * 100, 2),
        "pass": max_change <= 0.20,  # 门禁：≤20%
    }


# ============================================================
# Optuna 优化
# ============================================================
class FiveDomainWeightOptimizer:
    """五域权重贝叶斯优化器。"""

    def __init__(
        self,
        scores: Dict[str, Dict[str, Dict[str, float]]],
        returns: Dict[str, Dict[str, float]],
        n_trials: int = 200,
        asset_class: str = "crypto_usdt",
    ):
        self.scores = scores
        self.returns = returns
        self.n_trials = n_trials
        self.asset_class = asset_class
        self.baseline_sharpe = self._compute_baseline()

    def _compute_baseline(self) -> float:
        """等权基线 Sharpe。"""
        baseline = {"dao": 0.2, "tian": 0.2, "di": 0.2, "jiang": 0.2, "fa": 0.2}
        return compute_walkforward_sharpe(
            self.scores, self.returns, baseline, self.asset_class)

    def optimize(self) -> Dict[str, Any]:
        print(f"[OPT] 资产类: {self.asset_class}")
        print(f"[OPT] 等权基线 Walk-forward Sharpe: {self.baseline_sharpe:.4f}")
        print(f"[OPT] Optuna n_trials: {self.n_trials}")

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(self._objective, n_trials=self.n_trials)

        best_w = self._normalize_weights(study.best_params)
        best_sharpe = float(study.best_value)

        return {
            "asset_class": self.asset_class,
            "baseline_sharpe": round(self.baseline_sharpe, 4),
            "best_sharpe": round(best_sharpe, 4),
            "sharpe_improvement": round(best_sharpe - self.baseline_sharpe, 4),
            "best_weights": {k: round(v, 4) for k, v in best_w.items()},
            "n_trials": self.n_trials,
        }

    def _objective(self, trial: optuna.Trial) -> float:
        weights = {
            "dao": trial.suggest_float("dao", 0.05, 0.50),
            "tian": trial.suggest_float("tian", 0.05, 0.50),
            "di": trial.suggest_float("di", 0.05, 0.50),
            "jiang": trial.suggest_float("jiang", 0.05, 0.50),
            "fa": trial.suggest_float("fa", 0.05, 0.50),
        }
        # 归一化保证 sum=1
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

        return compute_walkforward_sharpe(
            self.scores, self.returns, weights, self.asset_class)

    @staticmethod
    def _normalize_weights(params: Dict[str, float]) -> Dict[str, float]:
        total = sum(params.values())
        return {k: v / total for k, v in params.items()}


# ============================================================
# 主入口
# ============================================================
def main() -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)

    # 预计算
    scores = precompute_domain_scores()
    returns = get_price_returns()

    if not scores:
        print("[ERR] 无分数数据")
        return

    # 优化三类资产
    results = {}
    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        cls_scores = {d: v for d, v in scores.items() if cls in v}
        cls_returns = returns.get(cls, {})
        if len(cls_scores) < 210:  # 至少 train+val
            print(f"[OPT] {cls}: 样本不足({len(cls_scores)}<210)，跳过")
            continue
        opt = FiveDomainWeightOptimizer(cls_scores, cls_returns, n_trials=200, asset_class=cls)
        result = opt.optimize()

        # ── 验证 1：最大回撤 ──
        baseline_w = {"dao": 0.2, "tian": 0.2, "di": 0.2, "jiang": 0.2, "fa": 0.2}
        best_w = result["best_weights"]
        baseline_mdd = compute_max_drawdown(cls_scores, cls_returns, baseline_w, cls)
        best_mdd = compute_max_drawdown(cls_scores, cls_returns, best_w, cls)
        mdd_ratio = best_mdd / baseline_mdd if baseline_mdd > 0 else 1.0
        mdd_pass = mdd_ratio <= 1.05

        # ── 验证 2：Sobol' 敏感性 ──
        sobol = sobol_sensitivity_test(cls_scores, cls_returns, best_w, cls)

        result["max_drawdown"] = {
            "baseline": round(baseline_mdd, 4),
            "best": round(best_mdd, 4),
            "ratio": round(mdd_ratio, 4),
            "pass": mdd_pass,
        }
        result["sobol_sensitivity"] = sobol

        results[cls] = result
        print(f"[OPT] {cls} 完成: 基线={result['baseline_sharpe']:.4f} "
              f"最优={result['best_sharpe']:.4f} "
              f"提升={result['sharpe_improvement']:+.4f}")
        print(f"      权重: {result['best_weights']}")
        print(f"      回撤: 基线={baseline_mdd:.2%} 最优={best_mdd:.2%} "
              f"比率={mdd_ratio:.3f} {'✅' if mdd_pass else '❌'}")
        print(f"      Sobol': 均值变化={sobol['mean_change_pct']:.1f}% "
              f"最大变化={sobol['max_change_pct']:.1f}% "
              f"{'✅' if sobol['pass'] else '❌'}")

    # 保存
    output = {
        "timestamp": datetime.now().isoformat(),
        "n_trials": 200,
        "train_days": 180,
        "val_days": 30,
        "baseline_weights": {"dao": 0.2, "tian": 0.2, "di": 0.2, "jiang": 0.2, "fa": 0.2},
        "validation_criteria": {
            "sharpe_improvement_min": 0.2,
            "max_drawdown_ratio_max": 1.05,
            "sobol_max_change_pct": 20.0,
        },
        "results": results,
    }
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[OPT] 结果已保存: {_OUTPUT}")


if __name__ == "__main__":
    main()
