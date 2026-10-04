"""共享工具函数（纯函数，无全局状态依赖）。

集中存放跨模块复用的数值安全转换与裁剪函数，
消除各业务模块中的重复定义。
"""
from __future__ import annotations

import math
from typing import Any


def _sf0(v: Any, default: float = 0.0) -> float:
    """安全转 float：非有限值或异常时返回 default。"""
    try:
        f = float(v)
        if math.isfinite(f):
            return f
    except Exception:
        pass
    return float(default)


def _clip(v: float, lo: float, hi: float) -> float:
    """将 v 裁剪到 [lo, hi] 区间。"""
    return max(lo, min(hi, v))


__all__ = ["_sf0", "_clip"]
