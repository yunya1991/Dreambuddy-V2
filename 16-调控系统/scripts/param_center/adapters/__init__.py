"""P1 T6: 算法观察适配器集合

6 个适配器包装不同算法，统一输出 AlgoObservation：
  - HmmAdapter: HMM 3-state regime detector
  - BaguaAdapter: 8-state Bagua RegimeParams
  - HurstAdapter: Hurst exponent 持续性分类
  - PmapperAdapter: ParameterMapper 6维参数映射
  - ShadowAdapter: ShadowLogger 历史 effective 经验
  - CusumAdapter: CUSUM 结构性突变事件

每个适配器继承 BaseAdapter，实现 _observe_impl()。
FAIL-OPEN: 异常时返回 None，聚合器自动跳过。
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# 路径设置
_THIS = _Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent.parent          # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent          # dreambuddy-v2
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for _p in [_YIJING_SCRIPTS, _SCRIPTS_16]:
    _sp = str(_p)
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)

from .base import BaseAdapter
from .hmm_adapter import HmmAdapter
from .bagua_adapter import BaguaAdapter
from .hurst_adapter import HurstAdapter
from .pmapper_adapter import PmapperAdapter
from .shadow_adapter import ShadowAdapter
from .cusum_adapter import CusumAdapter


def get_all_adapters():
    """返回全部 6 个适配器实例"""
    return [
        HmmAdapter(),
        BaguaAdapter(),
        HurstAdapter(),
        PmapperAdapter(),
        ShadowAdapter(),
        CusumAdapter(),
    ]


__all__ = [
    "BaseAdapter",
    "HmmAdapter",
    "BaguaAdapter",
    "HurstAdapter",
    "PmapperAdapter",
    "ShadowAdapter",
    "CusumAdapter",
    "get_all_adapters",
]
