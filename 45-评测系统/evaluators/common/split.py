# -*- coding: utf-8 -*-
"""
split.py — 防泄漏切分组件（P2-2）
==================================
抽象自 walk-forward / time-split（Screen1 训练链路），按 López de Prado 的
purged & embargo 语义实现，供金融回测与 AI 评测复用。

两类切分：
- purged_kfold：全样本 k 折；训练集剔除「标签窗口与测试窗重叠」的样本（purge），
  并剔除测试窗之后一段样本（embargo，抑制序列相关泄漏）
- walk_forward：扩展窗口；训练集严格位于测试窗之前，并按 label_horizon 去掉尾部（purge）

无泄漏验证：`verify_no_leakage(splits, label_horizon, embargo_len)` 返回违规列表，
对合规切分为空列表（PLAN P2-2 验收「给定样例可验证无泄漏」）。

索引语义：样本 i 的标签使用 (i, i + label_horizon] 的前视信息；
若该窗口与测试窗 [s, e) 相交，则 i 不得进入训练集。
"""

from __future__ import annotations

from dataclasses import dataclass


class SplitError(ValueError):
    """切分参数非法或产生空训练/测试集。"""


@dataclass(frozen=True)
class TimeSplit:
    """一折切分结果（索引元组，按时间升序）。"""

    fold: int
    train: tuple[int, ...]
    test: tuple[int, ...]


def embargo_length(n_samples: int, embargo_pct: float) -> int:
    """禁运长度：embargo_pct * n_samples，至少 1 条（pct=0 时为 0）。"""
    if embargo_pct <= 0:
        return 0
    return max(1, int(n_samples * embargo_pct))


def purged_kfold(
    n_samples: int,
    n_splits: int = 5,
    label_horizon: int = 0,
    embargo_pct: float = 0.0,
) -> list[TimeSplit]:
    """purged k-fold：测试块为连续等长分块；训练集按 purge + embargo 剔除。"""
    _validate(n_samples, n_splits, label_horizon, embargo_pct)
    if n_samples // n_splits < 1:
        raise SplitError(f"样本不足：n_samples={n_samples} < n_splits={n_splits}")

    embargo = embargo_length(n_samples, embargo_pct)
    splits: list[TimeSplit] = []
    for fold, (start, end) in enumerate(_blocks(n_samples, n_splits)):
        train = tuple(
            i for i in range(n_samples) if i < start - label_horizon or i >= end + embargo
        )
        if not train:
            raise SplitError(f"fold {fold} 训练集为空（purge/embargo 过强）")
        splits.append(TimeSplit(fold=fold, train=train, test=tuple(range(start, end))))
    return splits


def walk_forward(
    n_samples: int,
    n_splits: int = 5,
    label_horizon: int = 0,
) -> list[TimeSplit]:
    """扩展窗口：把样本切成 n_splits+1 块，首块为初始训练集，其后逐块做测试。"""
    _validate(n_samples, n_splits, label_horizon, embargo_pct=0.0)
    blocks = _blocks(n_samples, n_splits + 1)

    splits: list[TimeSplit] = []
    for fold in range(n_splits):
        start, end = blocks[fold + 1]
        if start >= end:
            raise SplitError(f"fold {fold} 测试集为空（样本不足以切分）")
        train = tuple(range(0, max(0, start - label_horizon)))
        if not train:
            raise SplitError(f"fold {fold} 训练集为空（初始窗口过小）")
        splits.append(TimeSplit(fold=fold, train=train, test=tuple(range(start, end))))
    return splits


def verify_no_leakage(
    splits: list[TimeSplit],
    label_horizon: int = 0,
    embargo_len: int = 0,
) -> list[str]:
    """返回全部泄漏违规（空列表 = 无泄漏），用于单测/报告证据。"""
    violations: list[str] = []
    for split in splits:
        start = min(split.test) if split.test else None
        end = max(split.test) + 1 if split.test else None
        if start is None or end is None:
            continue
        for index in split.train:
            if start - label_horizon <= index < end:
                violations.append(
                    f"fold{split.fold}: train {index} 标签窗口与测试 [{start},{end}) 重叠"
                )
            elif end <= index < end + embargo_len:
                violations.append(f"fold{split.fold}: train {index} 位于测试后禁运期")
    return violations


# ---------- 内部 ----------


def _blocks(n_samples: int, n_blocks: int) -> list[tuple[int, int]]:
    """等长分块；余数全部并入最后一块，保证覆盖完整且连续。"""
    base = n_samples // n_blocks
    remainder = n_samples - base * n_blocks
    blocks: list[tuple[int, int]] = []
    start = 0
    for index in range(n_blocks):
        size = base + (remainder if index == n_blocks - 1 else 0)
        blocks.append((start, start + size))
        start += size
    return blocks


def _validate(n_samples: int, n_splits: int, label_horizon: int, embargo_pct: float) -> None:
    if not isinstance(n_samples, int) or n_samples <= 0:
        raise SplitError(f"n_samples 必须为正整数，收到 {n_samples}")
    if not isinstance(n_splits, int) or n_splits < 2:
        raise SplitError(f"n_splits 必须 ≥ 2，收到 {n_splits}")
    if not isinstance(label_horizon, int) or label_horizon < 0:
        raise SplitError(f"label_horizon 必须 ≥ 0，收到 {label_horizon}")
    if not (0.0 <= embargo_pct < 1.0):
        raise SplitError(f"embargo_pct 必须落在 [0, 1)，收到 {embargo_pct}")
