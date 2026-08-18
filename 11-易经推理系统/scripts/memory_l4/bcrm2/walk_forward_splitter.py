"""
§4.3 WalkForward 时间序列滚动分割器（5 折，防时间泄露，gap=20）

与 sklearn TimeSeriesSplit 区别：
- 显式 gap 参数：训练尾部 → 测试开头之间强制空出 gap 条样本
- 每折的训练集可保持相等尺寸（固定窗口），也可扩张（expanding）
- train_ratio / test_ratio 控制每折占比，适用于「5 年日线 → 每折 ~1 年 测试」
"""
from __future__ import annotations

from typing import Generator, List, Tuple

import numpy as np


def walk_forward_time_series_split(
    n_samples: int,
    n_splits: int = 5,
    gap: int = 20,
    train_ratio: float = 0.7,
    test_ratio: float = 0.2,
    expanding: bool = True,
) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
    """Walk-Forward 滚动时间序列分割。

    划分策略（兼容 sklearn TimeSeriesSplit 风格 + 显式 gap）：
      - 将长度 N 视为由「n_splits 段」测试块 + 训练块组成。
      - expanding=True（默认，anchored）：
            将 N 按 (n_splits + 1) 等分 → 每段 base_size = N // (n_splits + 1)
            fold k:
              test_start = (k + 1) * base_size
              test_end   = min((k + 2) * base_size, N)
              train_end  = max(gap, test_start - gap)
              train_start = 0
            训练段随折数「扩张」（首折训练较小，末折训练接近 N*n_splits/(n_splits+1)），
            末折训练占比 ≈ n_splits/(n_splits+1)（5 折时 ≈ 83%），与 train_ratio≈0.7
            同量级。此模式最贴合「滚动回测」。
      - expanding=False（sliding）：
            训练段大小 = min_train（首折训练尺寸），每折前移 base_size。
            fold k:
              test_start = min_train + gap + k * base_size
              test_end   = min_train + gap + k * base_size + base_size
              train_start = k * base_size
              train_end   = train_start + min_train
            其中 base_size 取能容纳 n_splits 折的最大可行值（参考 test_ratio）。
      - 两模式都严格保证：train_idx.max() + gap <= test_idx.min()
    """
    if n_splits < 1:
        raise ValueError("n_splits 必须 ≥ 1")
    if gap < 0:
        raise ValueError("gap 必须 ≥ 0")
    if expanding:
        # ============================================================
        # 「首折足尺 + 扩张」版 expanding：
        #   - 训练集从 0 开始扩张，保证首折训练就有 train_min 尺寸（≈ 0.55~0.7 N），
        #     这样 8 态样本齐全，监督训练稳定。
        #   - 剩余空间（N - train_min - gap）均分给 n_splits 折作为测试段；
        #     每折训练段尾部 = 测试开头 - gap。训练段随 k 增长而扩张。
        # ============================================================
        train_min = int(round(n_samples * max(0.5, train_ratio - 0.05)))
        # 可用测试总长度
        usable = n_samples - train_min - gap
        if usable < n_splits * 4:
            # 退而求其次：base_size = (N // (n_splits + 1)) 等分法（首折训练小）
            base = n_samples // (n_splits + 1)
            if base < 2:
                raise ValueError(f"n_samples={n_samples} 太小，无法产生 {n_splits} 折")
            for k in range(n_splits):
                test_start = (k + 1) * base
                test_end = n_samples if k == n_splits - 1 else (k + 2) * base
                train_end = test_start - gap
                if train_end < 2 or test_end - test_start < 2:
                    break
                yield np.arange(0, train_end), np.arange(test_start, test_end)
            return
        step = usable // n_splits
        for k in range(n_splits):
            test_start = train_min + gap + k * step
            if k == n_splits - 1:
                test_end = n_samples
            else:
                test_end = test_start + step
            train_end = test_start - gap
            if train_end < 2 or test_end - test_start < 2:
                break
            yield np.arange(0, train_end), np.arange(test_start, test_end)
    else:
        # sliding：训练段大小参考 train_ratio * n_samples；每折前移步长参考 test_ratio
        min_train = int(round(n_samples * train_ratio))
        step = max(2, int(round(n_samples * test_ratio)))
        # 最大 k： min_train + gap + (n_splits-1)*step + step <= n_samples
        # => k_max 满足 min_train + gap + k_max*step + step <= n_samples
        max_step_idx = (n_samples - min_train - gap - step) // step
        # 实际折数 = min(n_splits, max_step_idx + 1)
        real_splits = min(n_splits, max_step_idx + 1)
        if real_splits < 1:
            # 退化为 1 折（按 min_train + gap 切）
            train_start, train_end = 0, min_train
            test_start, test_end = min_train + gap, n_samples
            if train_end - train_start >= 2 and test_end - test_start >= 2:
                yield np.arange(train_start, train_end), np.arange(test_start, test_end)
            return
        for k in range(real_splits):
            test_start = min_train + gap + k * step
            test_end = min(test_start + step, n_samples)
            train_start = k * step
            train_end = train_start + min_train
            if train_end - train_start < 2 or test_end - test_start < 2:
                break
            yield np.arange(train_start, train_end), np.arange(test_start, test_end)


def split_sizes(n_samples: int, **kwargs) -> List[Tuple[int, int]]:
    """返回各折的 (train_size, test_size) 序列，用于诊断。"""
    res: List[Tuple[int, int]] = []
    for tr, te in walk_forward_time_series_split(n_samples, **kwargs):
        res.append((len(tr), len(te)))
    return res
