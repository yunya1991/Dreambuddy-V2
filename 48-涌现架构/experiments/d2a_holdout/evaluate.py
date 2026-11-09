"""D2-A 评估：M-D2-EDGE-F1 + 模块级配对聚类 bootstrap + 四态判定（SPEC v0.4 §4.1）。

关键统计口径（预注册冻结）：
  - 独立实验单元 = 模块；模块内边是相关观测，不作独立样本
  - 主终点唯一 = M-D2-EDGE-F1
  - 判定 = 模块级配对聚类 bootstrap（10k 次，percentile CI）比较 system vs 最佳基线
"""

from __future__ import annotations

import random

PRIMARY_METRIC = "M-D2-EDGE-F1"


def edge_f1(pred: set[tuple[str, str, str]], truth: set[tuple[str, str, str]]) -> dict:
    tp = len(pred & truth)
    fp = len(pred - truth)
    fn = len(truth - pred)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def per_module_delta(
    per_module: dict[str, dict[str, float]], metric: str = PRIMARY_METRIC
) -> list[float]:
    """系统 vs 最佳基线 的模块级配对差值。per_module[mod] = {"system": x, "baseline": y}"""
    return [
        per_module[m][metric + "_system"] - per_module[m][metric + "_baseline"]
        for m in sorted(per_module)
    ]


def cluster_bootstrap_ci(
    deltas: list[float], n_iter: int = 10_000, alpha: float = 0.05, seed: int = 42
) -> dict:
    """模块级聚类 bootstrap：以模块为单元有放回重采样，取均值差的 percentile CI。"""
    if not deltas:
        return {
            "n_modules": 0,
            "mean_delta": None,
            "ci_low": None,
            "ci_high": None,
            "iterations": 0,
            "alpha": alpha,
        }
    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(n_iter):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_iter)]
    hi = means[min(n_iter - 1, int((1 - alpha / 2) * n_iter))]
    return {
        "n_modules": n,
        "mean_delta": round(sum(deltas) / n, 6),
        "ci_low": round(lo, 6),
        "ci_high": round(hi, 6),
        "iterations": n_iter,
        "alpha": alpha,
        "seed": seed,
    }


def decide(
    ci: dict, n_modules: int, min_modules: int = 5, human_rubric: float | None = None
) -> dict:
    """§4.1 四态判定（排他）。"""
    if n_modules < min_modules:
        return {
            "verdict": "insufficient_data",
            "reason": f"模块数 {n_modules} < 预注册最小值 {min_modules}",
        }
    if ci["ci_low"] is None:
        return {"verdict": "insufficient_data", "reason": "无可用配对差值"}
    if ci["ci_low"] > 0 and (human_rubric is None or human_rubric >= 4.0):
        return {
            "verdict": "candidate",
            "reason": f"主终点 {PRIMARY_METRIC} 模块级 95% CI 下界 {ci['ci_low']} > 0",
        }
    if ci["ci_high"] <= 0:
        return {
            "verdict": "falsified",
            "reason": f"主终点 95% CI 上界 {ci['ci_high']} ≤ 0，不优于基线",
        }
    if ci["ci_low"] > 0 and human_rubric is not None and human_rubric < 4.0:
        return {
            "verdict": "inconclusive",
            "reason": f"CI 显著但盲评 {human_rubric} < 4/5，门槛未过",
        }
    return {
        "verdict": "inconclusive",
        "reason": f"主终点 95% CI [{ci['ci_low']}, {ci['ci_high']}] 跨 0",
    }


def evaluate_module(system_pred, baseline_preds: dict[str, set], truth) -> dict:
    """单模块评估：系统与各基线在同一 truth 上打分，取最佳基线作配对对象。"""
    sys_score = edge_f1(system_pred, truth) if system_pred is not None else None
    base_scores = {name: edge_f1(pred, truth) for name, pred in baseline_preds.items()}
    best_name = max(base_scores, key=lambda k: base_scores[k]["f1"]) if base_scores else None
    return {
        "system": sys_score,
        "baselines": base_scores,
        "best_baseline": best_name,
        "best_baseline_f1": base_scores[best_name]["f1"] if best_name else None,
    }
