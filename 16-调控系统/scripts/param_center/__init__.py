"""参数中心（Param Center）— 16-调控系统

三层混合架构（SPEC: param-center-arch-20261007）的 Layer 2：
  - ParamRepository: 3D 参数表 + 5min 缓存 + FAIL-OPEN（P0 已实现）
  - StatAggregator: BMA + KL散度加权聚合 6 算法输出（P1 待实现）
  - BayesianVerifier: bayes_opt + 回测四条件门禁（P2 待实现）
  - ShadowLogger 增强: 参数中心推荐值 vs 子系统实际值偏差（P3 待实现）

对外只读 API：
    from param_center.api import get_sltp_params
    params = get_sltp_params("BTC", market_regime="chop")
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# 路径设置：让包内模块能导入 11-易经推理系统/scripts 下的依赖
_THIS = _Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent                  # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent          # dreambuddy-v2
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for _p in [_YIJING_SCRIPTS, _SCRIPTS_16]:
    _sp = str(_p)
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)

from .api import get_sltp_params
from .repository import ParamRepository, get_repository
from .aggregator import StatAggregator, AlgoObservation, ParamProposal, trigger_recompute
from .verifier import BayesianVerifier, VerificationResult
from .shadow_integration import ParamCenterShadowLogger, get_shadow_logger

__all__ = [
    "get_sltp_params",
    "ParamRepository",
    "get_repository",
    "StatAggregator",
    "AlgoObservation",
    "ParamProposal",
    "trigger_recompute",
    "BayesianVerifier",
    "VerificationResult",
    "ParamCenterShadowLogger",
    "get_shadow_logger",
]
