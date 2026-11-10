"""D3-A 评估：M-D3-TOP1 + ECE + session 级配对 bootstrap + 四态判定（SPEC v0.4 §4.3）。

关键统计口径（预注册冻结）：
  - 独立实验单元 = session（时序切分，train/test 不重叠）
  - 主终点 = M-D3-TOP1（session 级 task_type 预测命中率）
  - 校准门槛 = ECE ≤ 0.1
  - 判定 = session 级配对 bootstrap（10k 次）比较 system vs 最佳基线
"""

from __future__ import annotations

import random

PRIMARY_METRIC = "M-D3-TOP1"
ECE_THRESHOLD = 0.1
N_BINS = 10


def top1_acc(preds: list[str], truths: list[str]) -> float:
    if not preds:
        return 0.0
    return sum(p == t for p, t in zip(preds, truths, strict=True)) / len(preds)


def expected_calibration_error(
    probs_list: list[dict[str, float]], preds: list[str], truths: list[str]
) -> float:
    """ECE：按预测概率分箱，|acc - conf| 的加权平均。"""
    if not preds:
        return 0.0
    bins: list[list[tuple[float, float]]] = [[] for _ in range(N_BINS)]
    for probs, pred, truth in zip(probs_list, preds, truths, strict=True):
        conf = probs.get(pred, 0.0)
        acc = 1.0 if pred == truth else 0.0
        idx = min(int(conf * N_BINS), N_BINS - 1)
        bins[idx].append((conf, acc))
    total = len(preds)
    ece = 0.0
    for b in bins:
        if not b:
            continue
        avg_conf = sum(c for c, _ in b) / len(b)
        avg_acc = sum(a for _, a in b) / len(b)
        ece += len(b) / total * abs(avg_acc - avg_conf)
    return round(ece, 6)


def session_bootstrap_ci(
    deltas: list[float], n_iter: int = 10_000, alpha: float = 0.05, seed: int = 42
) -> dict:
    """session 级配对 bootstrap：以 session 为单元有放回重采样。"""
    if not deltas:
        return {"n": 0, "mean_delta": None, "ci_low": None, "ci_high": None}
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
        "n": n,
        "mean_delta": round(sum(deltas) / n, 6),
        "ci_low": round(lo, 6),
        "ci_high": round(hi, 6),
    }


def decide(ci: dict, ece: float, n_sessions: int, min_sessions: int = 200) -> dict:
    """§4.3 四态判定（排他）。"""
    if n_sessions < min_sessions:
        return {
            "verdict": "insufficient_data",
            "reason": f"测试 session 数 {n_sessions} < 预注册最小值 {min_sessions}",
        }
    if ci["ci_low"] is None:
        return {"verdict": "insufficient_data", "reason": "无可用配对差值"}
    if ece > ECE_THRESHOLD:
        return {
            "verdict": "inconclusive",
            "reason": f"ECE={ece} > {ECE_THRESHOLD}，校准未过门槛",
        }
    if ci["ci_low"] > 0:
        return {
            "verdict": "candidate",
            "reason": (
                f"主终点 {PRIMARY_METRIC} 95% CI 下界 {ci['ci_low']} > 0"
                f" 且 ECE={ece} ≤ {ECE_THRESHOLD}"
            ),
        }
    if ci["ci_high"] <= 0:
        return {
            "verdict": "falsified",
            "reason": f"主终点 95% CI 上界 {ci['ci_high']} ≤ 0，不优于基线",
        }
    return {
        "verdict": "inconclusive",
        "reason": f"主终点 95% CI [{ci['ci_low']}, {ci['ci_high']}] 跨 0",
    }
