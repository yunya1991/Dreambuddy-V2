# -*- coding: utf-8 -*-
"""能力层（54）：把已注册的 154+ 方法接到 L0 scope / L1 意图 / CapabilityResult 信封。

对外只暴露三个入口：
  - `manifest()` / `get_capability(id)`：能力注册表（`capability_manifest.yaml` 为 SSoT）；
  - `run_capability(id, **kwargs)`：按能力 ID 跑编排并返回统一信封；
  - `build/unavailable/quality_for`：供 L1 执行器自行组装信封。
"""

from .envelope import (  # noqa: F401
    STATUS_EMPTY,
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality,
    quality_for,
    unavailable,
)
from .manifest import Capability, ManifestError, get_capability, manifest  # noqa: F401
from .stats import (  # noqa: F401
    conditional_ic,
    correlation,
    drawdown,
    run_capability,
    seasonality,
    state_transition,
    supported,
)
