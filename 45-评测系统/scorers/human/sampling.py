# -*- coding: utf-8 -*-
"""
sampling.py — 人工抽评分层抽样（P2-6，SPEC §10）
=================================================
按层（stratum）比例分配名额：每层至少 1 个，其余按比例取整，余数给小数部分最大的层
（同分按层名排序）。抽样用固定 seed 打乱后用 id 升序确定性选取，便于复算。
"""

from __future__ import annotations

import random
from dataclasses import dataclass


class SamplingError(ValueError):
    """抽样参数非法（样本不足/层数多于名额）。"""


@dataclass(frozen=True)
class SamplingPlan:
    items: tuple[str, ...]
    per_stratum: dict[str, int]
    seed: int


def stratified_sample(population: list[tuple[str, str]], n: int, seed: int = 0) -> SamplingPlan:
    """population 为 (item_id, stratum)；返回抽样计划（每层名额 + 选中 id）。"""
    if not population:
        raise SamplingError("抽样总体为空")
    if n < 1:
        raise SamplingError(f"抽样名额必须 ≥ 1，收到 {n}")
    if n > len(population):
        raise SamplingError(f"抽样名额 {n} 超过总体 {len(population)}")

    grouped: dict[str, list[str]] = {}
    for item_id, stratum in population:
        if not isinstance(item_id, str) or not item_id or not stratum:
            raise SamplingError("item_id 与 stratum 必须为非空字符串")
        grouped.setdefault(stratum, []).append(item_id)

    strata = sorted(grouped)
    if n < len(strata):
        raise SamplingError(f"名额 {n} 少于层数 {len(strata)}，无法保证每层抽到")

    total = len(population)
    quotas = dict.fromkeys(strata, 1)
    remaining = n - len(strata)
    shares = {stratum: len(grouped[stratum]) / total * remaining for stratum in strata}
    for stratum in strata:
        quota = min(int(shares[stratum]), len(grouped[stratum]) - 1)
        quotas[stratum] += quota
        shares[stratum] -= quota

    leftover = n - sum(quotas.values())
    for stratum in sorted(strata, key=lambda s: (-shares[s], s)):
        if leftover <= 0:
            break
        capacity = len(grouped[stratum]) - quotas[stratum]
        take = min(leftover, capacity)
        quotas[stratum] += take
        leftover -= take
    if leftover > 0:
        raise SamplingError("名额分配失败：层容量不足")

    rng = random.Random(seed)
    selected: list[str] = []
    for stratum in strata:
        pool = sorted(grouped[stratum])
        rng.shuffle(pool)
        selected.extend(sorted(pool[: quotas[stratum]]))
    return SamplingPlan(items=tuple(sorted(selected)), per_stratum=quotas, seed=seed)
