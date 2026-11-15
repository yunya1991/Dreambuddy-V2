# -*- coding: utf-8 -*-
"""L1 方法层：注册表 + 已实现方法（导入即完成登记）。"""

from __future__ import annotations

# 注册顺序属于运行时契约：保持 correlation 先于 conditional，禁止 import sorter 重排。
# ruff: noqa: I001
from . import correlation  # noqa: F401  # 触发 S2 批次登记
from . import conditional  # noqa: F401  # 触发 S3 批次（条件收益/IC/分组）登记
from . import descriptive  # noqa: F401  # 触发 S/D 批次（描述统计/分布形态）登记
from . import fed_methods  # noqa: F401  # 触发 I35–I39（美联储调研方法）登记
from . import inference  # noqa: F401  # 触发 H/B/M/R 批次（检验/状态/表达）登记
from . import research  # noqa: F401  # 调研族编号表（X/O/P/Q/SC 元数据）
from . import research_pq  # noqa: F401  # 触发 P/Q 批次（风险组合/研究协议）登记
from . import research_sc_a  # noqa: F401  # 触发 SC01–SC46（科研统计前半）登记
from . import research_sc_b  # noqa: F401  # 触发 SC47–SC92（科研统计后半）登记
from . import research_xo  # noqa: F401  # 触发 X/O 批次（横截面/时序算子）登记
from . import seasonal  # noqa: F401  # 触发 C 组（季节性与日历效应）登记
from . import technical  # noqa: F401  # 触发 D-B01–B07（I 组）登记
from . import timeseries  # noqa: F401  # 触发 T/F 批次（时序结构与金融指标）登记
from .registry import (  # noqa: F401
    GROUP_CAPACITY,
    REGISTRY,
    MethodChecks,
    MethodSpec,
    MethodUnavailable,
    RegistryError,
    all_specs,
    get,
    register,
    register_unavailable,
    run,
)

__all__ = [
    "GROUP_CAPACITY",
    "REGISTRY",
    "MethodChecks",
    "MethodSpec",
    "MethodUnavailable",
    "RegistryError",
    "all_specs",
    "get",
    "register",
    "register_unavailable",
    "run",
]
