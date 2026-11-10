"""嵌套 walk-forward 反思选择 — SPEC §2.10 A2 / §2.9.4。

为什么需要它：33-REA `dreaming.py` 的 `dream()` 用
`selection_rule="argmax_v_with_current_in_candidates"`，即**在同一批数据上**
评估全部候选并取最大 V。这个最大值是样本内最优，不能作为适应度上报，
否则"涌现"无法证伪。

本模块把选择拆成两层：
  内层（inner）：在 outer-train 内再做 walk-forward，只用内层验证分挑候选
  外层（outer）：把内层选中的候选放到**未参与选择的** outer-test 上评分
最终适应度只取外层均值；`selection_gap = 内层最优均值 − 外层均值`
用于暴露选择偏差（>0 即过拟合）。

口径（预注册）：
  - 扩张窗（expanding），train 严格早于 test
  - embargo ≥1：test 前丢弃若干日，切断重叠信息
  - 日期去重排序；不足最小训练量 → degraded（不抛）

FAIL-OPEN：任何异常返回 degraded 结果，不阻断主链路。
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

logger = logging.getLogger("emergence.reflection.nested_walk_forward")

DEFAULT_OUTER_FOLDS = 4
DEFAULT_INNER_FOLDS = 3
DEFAULT_EMBARGO = 1
DEFAULT_MIN_TRAIN = 20


@dataclass(frozen=True)
class FoldRecord:
    fold: int
    inner_best_index: int
    inner_score: float
    outer_score: float
    n_inner_folds: int
    n_train: int
    n_test: int


@dataclass(frozen=True)
class NestedResult:
    folds: tuple[FoldRecord, ...]
    mean_outer_score: float | None
    std_outer_score: float | None
    mean_inner_score: float | None
    selection_gap: float | None
    n_outer_folds: int
    leakage_free: bool
    degraded: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _unique_sorted(dates: Sequence[Any]) -> list[str]:
    return sorted({str(d)[:10] for d in dates})


def walk_forward_blocks(
    dates: Sequence[Any],
    n_folds: int,
    *,
    embargo: int = DEFAULT_EMBARGO,
    min_train: int = DEFAULT_MIN_TRAIN,
) -> list[tuple[list[str], list[str]]]:
    """扩张窗切分 → [(train_dates, test_dates), ...]；不足则 []。"""
    ds = _unique_sorted(dates)
    if n_folds < 1 or len(ds) < min_train + n_folds:
        return []
    rest = ds[min_train:]
    size = len(rest) // n_folds
    if size < 1:
        return []
    out: list[tuple[list[str], list[str]]] = []
    for k in range(n_folds):
        start = k * size
        end = len(rest) if k == n_folds - 1 else (k + 1) * size
        test = rest[start:end]
        cutoff = min_train + start
        train_end = cutoff - max(0, embargo)
        if train_end < min_train // 2 or not test:
            continue
        train = ds[:train_end]
        if len(train) < 2:
            continue
        out.append((train, test))
    return out


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _degraded(reason: str) -> NestedResult:
    return NestedResult(
        folds=(),
        mean_outer_score=None,
        std_outer_score=None,
        mean_inner_score=None,
        selection_gap=None,
        n_outer_folds=0,
        leakage_free=False,
        degraded=True,
        reason=reason,
    )


def nested_walk_forward(
    dates: Sequence[Any],
    candidates: Sequence[Any],
    eval_fn: Callable[[Any, Sequence[str], Sequence[str]], float],
    *,
    outer_folds: int = DEFAULT_OUTER_FOLDS,
    inner_folds: int = DEFAULT_INNER_FOLDS,
    embargo: int = DEFAULT_EMBARGO,
    min_train: int = DEFAULT_MIN_TRAIN,
) -> NestedResult:
    """嵌套 walk-forward 选择。

    eval_fn(candidate, train_dates, test_dates) -> float
        约定：只能在 train_dates 上拟合、在 test_dates 上评分。
    """
    try:
        if not candidates:
            return _degraded("no_candidates")
        ds = _unique_sorted(dates)
        outer = walk_forward_blocks(ds, outer_folds, embargo=embargo, min_train=min_train)
        if not outer:
            return _degraded("insufficient_dates")

        folds: list[FoldRecord] = []
        for idx, (train, test) in enumerate(outer):
            inner_min = max(5, min(min_train, len(train) // (inner_folds + 1)))
            inner = walk_forward_blocks(train, inner_folds, embargo=embargo, min_train=inner_min)
            if not inner:
                continue
            inner_scores: list[float] = []
            for cand in candidates:
                scores = [float(eval_fn(cand, tr, te)) for tr, te in inner]
                if not all(math.isfinite(s) for s in scores):
                    inner_scores.append(-math.inf)
                else:
                    inner_scores.append(_mean(scores))
            best_i = max(range(len(candidates)), key=lambda i: inner_scores[i])
            if not math.isfinite(inner_scores[best_i]):
                continue
            outer_score = float(eval_fn(candidates[best_i], train, test))
            if not math.isfinite(outer_score):
                continue
            folds.append(
                FoldRecord(
                    fold=idx,
                    inner_best_index=best_i,
                    inner_score=round(inner_scores[best_i], 6),
                    outer_score=round(outer_score, 6),
                    n_inner_folds=len(inner),
                    n_train=len(train),
                    n_test=len(test),
                )
            )

        if not folds:
            return _degraded("no_valid_fold")

        outer_scores = [f.outer_score for f in folds]
        inner_best = [f.inner_score for f in folds]
        leakage_free = all(max(train) < min(test) for train, test in outer if train and test)
        mean_outer = _mean(outer_scores)
        mean_inner = _mean(inner_best)
        return NestedResult(
            folds=tuple(folds),
            mean_outer_score=round(mean_outer, 6),
            std_outer_score=round(_std(outer_scores), 6),
            mean_inner_score=round(mean_inner, 6),
            selection_gap=round(mean_inner - mean_outer, 6),
            n_outer_folds=len(folds),
            leakage_free=leakage_free,
            degraded=False,
        )
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] nested_walk_forward %s: %s", type(e).__name__, str(e)[:120])
        return _degraded(f"error:{type(e).__name__}")
