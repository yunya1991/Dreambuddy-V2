"""P1-6 评审校准：双裁判一致性校验（Cohen's κ / Krippendorff's α）。

沿用 45-评测系统 §9 校准协议：
  - 校准集 ≥200 条人工标注，覆盖好/中/差三档
  - Cohen's κ ≥ 0.60 且 Krippendorff's α ≥ 0.67（ordinal）

输入：标注 JSONL 文件，每条含 annotator_a.overall 和 annotator_b.overall（1/2/3）。
输出：κ、α、是否达标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple


def load_annotations(path: Path) -> List[Tuple[int, int]]:
    """加载标注文件，返回 [(a_overall, b_overall), ...]。"""
    pairs: List[Tuple[int, int]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            a = rec.get("annotator_a", {}).get("overall")
            b = rec.get("annotator_b", {}).get("overall")
            if a is not None and b is not None:
                pairs.append((int(a), int(b)))
    return pairs


def cohens_kappa(pairs: List[Tuple[int, int]]) -> float:
    """Cohen's κ（适用于两位裁判、定序/定类数据）。"""
    if not pairs:
        return 0.0
    categories = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    n = len(pairs)
    # 观测一致率
    observed = sum(1 for a, b in pairs if a == b) / n
    # 期望一致率（边际概率乘积）
    freq_a = {c: sum(1 for a, _ in pairs if a == c) / n for c in categories}
    freq_b = {c: sum(1 for _, b in pairs if b == c) / n for c in categories}
    expected = sum(freq_a[c] * freq_b[c] for c in categories)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def krippendorffs_alpha(pairs: List[Tuple[int, int]]) -> float:
    """Krippendorff's α（ordinal，使用平方差距离函数）。"""
    if not pairs:
        return 0.0
    # 展平为裁判×样本矩阵：每行一个裁判，每列一个样本
    values = list({v for p in pairs for v in p})
    values.sort()
    n_samples = len(pairs)
    # 观测不一致
    observed_disagree = sum((a - b) ** 2 for a, b in pairs) / n_samples
    # 期望不一致（所有配对的平方差均值）
    all_vals = [v for p in pairs for v in p]
    n_total = len(all_vals)
    expected_disagree = 0.0
    for i in range(n_total):
        for j in range(i + 1, n_total):
            expected_disagree += (all_vals[i] - all_vals[j]) ** 2
    expected_disagree = 2 * expected_disagree / (n_total * (n_total - 1)) if n_total > 1 else 0.0
    if expected_disagree == 0:
        return 1.0
    return 1.0 - observed_disagree / expected_disagree


def check_calibration(path: Path) -> dict:
    """校验校准集是否达标。"""
    pairs = load_annotations(path)
    n = len(pairs)
    kappa = cohens_kappa(pairs)
    alpha = krippendorffs_alpha(pairs)
    return {
        "n_annotated": n,
        "cohens_kappa": round(kappa, 4),
        "krippendorffs_alpha": round(alpha, 4),
        "kappa_pass": kappa >= 0.60,
        "alpha_pass": alpha >= 0.67,
        "n_pass": n >= 200,
        "calibrated": n >= 200 and kappa >= 0.60 and alpha >= 0.67,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python review_calibration.py <annotation.jsonl>")
        sys.exit(1)
    result = check_calibration(Path(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["calibrated"] else 1)
