"""ASIL VaR 第三门 — 三重漂移检测的 VaR 分量。

Phase 2：在已有 PSI + KS 之上加 VaR 第三门。
SR 11-7 贝叶斯 VaR 回测方法（比交通灯测试好）。
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np


def compute_var_violation(
    returns: Sequence[float],
    var_threshold: float = -0.02,  # 2% 单日损失阈值
    confidence_level: float = 0.95,
) -> Tuple[bool, int, float]:
    """贝叶斯 VaR 第三门。

    Args:
        returns: 日收益率序列（正数=盈利，负数=亏损）
        var_threshold: VaR 阈值（如 -0.02 = 单日亏损 2%）
        confidence_level: 置信水平（默认 95%）

    Returns:
        (violated, n_violations, violation_ratio)
        - violated: 是否超过预期违反次数
        - n_violations: 实际违反次数
        - violation_ratio: 违反次数 / 期望违反次数
    """
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    if n == 0:
        return False, 0, 0.0

    # 违反次数（收益 < VaR 阈值）
    n_violations = int(np.sum(arr < var_threshold))

    # 期望违反次数（二项分布）
    expected = n * (1.0 - confidence_level)

    violation_ratio = n_violations / max(expected, 1)

    # 违反比率 > 2 视为异常（严重尾部风险）
    violated = violation_ratio > 2.0 and n_violations > 0

    return violated, n_violations, float(violation_ratio)
