"""43 侧 main-nn 埋点薄封装（FAIL-OPEN）。

口径：15-监控告警系统/docs/TECHNICAL_DESIGN.md §14（M3/M4，source=main-nn）。
观测失败不得影响战略信号发布。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHAIN_DIR = _REPO_ROOT / "42-神经网络交易协调层"
_RUNTIME = _REPO_ROOT / "43-战略承接推演层" / "runtime"
_LAST: dict[tuple[str, str], float] = {}


def emit(
    stage: str,
    node: str,
    status: str = "pass",
    *,
    data: dict[str, Any] | None = None,
    reason_category: str | None = None,
    min_interval_sec: float = 0.0,
) -> None:
    try:
        # 同一进程内同一 (stage,node) 去重：build_bridge_inputs 每个资产类各调一次
        if min_interval_sec > 0:
            key = (stage, node)
            now = time.monotonic()
            if now - _LAST.get(key, 0.0) < min_interval_sec:
                return
            _LAST[key] = now
        if str(_CHAIN_DIR) not in sys.path:
            sys.path.insert(0, str(_CHAIN_DIR))
        from chain_events import emit_stage

        emit_stage(
            stage,
            node,
            "MACRO",
            status,
            data=data,
            reason_category=reason_category,
            runtime=_RUNTIME,
        )
    except Exception:  # noqa: BLE001  观测失败不影响战略发布
        pass
