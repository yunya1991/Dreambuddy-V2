# -*- coding: utf-8 -*-
"""
calibration.py — 裁判校准指标（P2-5，SPEC §5.2 A-H4 / §9）
============================================================
- Cohen's κ：两名标注者按类别一致度（扣除随机一致）
- Krippendorff's α（nominal）：多标注者，不完备性下的名义一致性
阈值：κ≥0.60、α≥0.67、校准集≥200（判定见 evaluators/ai/judge.py）
"""

from __future__ import annotations

from collections import Counter


class CalibrationError(ValueError):
    """校准输入非法（长度不一致/样本不足/空标签）。"""


def cohen_kappa(human: list[str], judge: list[str]) -> float:
    """κ = (po - pe) / (1 - pe)；pe 为随机一致概率。"""
    _validate(human, judge)
    n = len(human)
    po = sum(1 for h, j in zip(human, judge, strict=True) if h == j) / n
    human_counts = Counter(human)
    judge_counts = Counter(judge)
    pe = sum((human_counts[label] / n) * (judge_counts.get(label, 0) / n) for label in human_counts)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def krippendorff_alpha(coders: list[list[str]]) -> float:
    """名义 α = 1 - (1 - P_o)/D_e，适用于完整标注（每单元标注者数一致）。"""
    if len(coders) < 2:
        raise CalibrationError("Krippendorff α 至少需要 2 名标注者")
    lengths = {len(row) for row in coders}
    if len(lengths) != 1:
        raise CalibrationError("标注者样本长度必须一致")
    n_units = lengths.pop()
    if n_units < 2:
        raise CalibrationError(f"样本数必须 ≥ 2，收到 {n_units}")

    for row in coders:
        if any(not isinstance(label, str) or not label for label in row):
            raise CalibrationError("标签必须为非空字符串")

    n_coders = len(coders)
    total = Counter(label for row in coders for label in row)
    value_count = sum(total.values())
    expected_disagreement = 1 - sum((count / value_count) ** 2 for count in total.values())

    observed_agreement = 0.0
    for unit in range(n_units):
        counts = Counter(row[unit] for row in coders)
        numerator = sum(count * (count - 1) for count in counts.values())
        observed_agreement += numerator / (n_coders * (n_coders - 1))
    observed_agreement /= n_units

    if expected_disagreement == 0:
        return 1.0
    return 1 - (1 - observed_agreement) / expected_disagreement


def krippendorff_alpha_ordinal(coders: list[list[str]], labels: tuple[str, ...]) -> float:
    """序数 α：标签按 labels 顺序视为有序等级，相邻分歧惩罚小于跨级分歧（SPEC §10.2）。"""
    if not labels or len(set(labels)) != len(labels):
        raise CalibrationError("ordinal α 需要无重复的等级标签序列")
    if len(coders) < 2:
        raise CalibrationError("Krippendorff α 至少需要 2 名标注者")
    lengths = {len(row) for row in coders}
    if len(lengths) != 1:
        raise CalibrationError("标注者样本长度必须一致")
    n_units = lengths.pop()
    if n_units < 2:
        raise CalibrationError(f"样本数必须 ≥ 2，收到 {n_units}")

    rank = {label: index for index, label in enumerate(labels)}
    for row in coders:
        for label in row:
            if not isinstance(label, str) or label not in rank:
                raise CalibrationError(f"标签 {label!r} 不在 ordinal 等级序列中")

    total = Counter(label for row in coders for label in row)
    if len(total) == 1:
        return 1.0
    n_values = sum(total.values())

    def delta_squared(left: str, right: str) -> float:
        low, high = sorted((rank[left], rank[right]))
        span = sum(total[labels[index]] for index in range(low, high + 1))
        return (span - (total[left] + total[right]) / 2) ** 2

    expected_numerator = sum(
        total[left] * total[right] * delta_squared(left, right)
        for left in total
        for right in total
        if left != right
    )
    expected_disagreement = expected_numerator / (n_values * (n_values - 1))
    if expected_disagreement == 0:
        return 1.0

    observed = 0.0
    n_coders = len(coders)
    for unit in range(n_units):
        counts = Counter(row[unit] for row in coders)
        numerator = sum(
            counts[left] * counts[right] * delta_squared(left, right)
            for left in counts
            for right in counts
            if left != right
        )
        observed += numerator / (n_coders * (n_coders - 1))
    observed /= n_units
    return 1 - observed / expected_disagreement


def _validate(human: list[str], judge: list[str]) -> None:
    if len(human) != len(judge):
        raise CalibrationError(f"标注长度不一致：human={len(human)} judge={len(judge)}")
    if len(human) < 2:
        raise CalibrationError(f"样本数必须 ≥ 2，收到 {len(human)}")
    for row in (human, judge):
        if any(not isinstance(label, str) or not label for label in row):
            raise CalibrationError("标签必须为非空字符串")
