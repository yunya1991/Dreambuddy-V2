"""运行时辅助函数（从 ml_trade_service.py 抽取）

包含：
- _now_ms：可注入固定时间（便于测试），默认返回当前毫秒时间戳
- characterization 排他状态管理：_CHARACTERIZATION_EXCLUSIVE_STATE + inc/dec/is_running

依赖 classic_pipeline.core.locks 中的 _CHARACTERIZATION_EXCLUSIVE_LOCK 和 _RUNTIME_CTX。
"""

import time
from typing import Any, Dict

from .locks import _CHARACTERIZATION_EXCLUSIVE_LOCK, _RUNTIME_CTX

# === characterization 排他状态 ===
_CHARACTERIZATION_EXCLUSIVE_STATE: Dict[str, Any] = {
    "running": 0,
    "since_ms": 0,
    "last_end_ms": 0,
}


def _characterization_exclusive_is_running() -> bool:
    try:
        return int(_CHARACTERIZATION_EXCLUSIVE_STATE.get("running") or 0) > 0
    except Exception:
        return False


def _characterization_exclusive_inc() -> None:
    with _CHARACTERIZATION_EXCLUSIVE_LOCK:
        _CHARACTERIZATION_EXCLUSIVE_STATE["running"] = (
            int(_CHARACTERIZATION_EXCLUSIVE_STATE.get("running") or 0) + 1
        )
        if int(_CHARACTERIZATION_EXCLUSIVE_STATE.get("since_ms") or 0) <= 0:
            _CHARACTERIZATION_EXCLUSIVE_STATE["since_ms"] = int(time.time() * 1000)


def _characterization_exclusive_dec() -> None:
    with _CHARACTERIZATION_EXCLUSIVE_LOCK:
        _CHARACTERIZATION_EXCLUSIVE_STATE["running"] = max(
            0, int(_CHARACTERIZATION_EXCLUSIVE_STATE.get("running") or 0) - 1
        )
        if int(_CHARACTERIZATION_EXCLUSIVE_STATE.get("running") or 0) <= 0:
            _CHARACTERIZATION_EXCLUSIVE_STATE["last_end_ms"] = int(time.time() * 1000)
            _CHARACTERIZATION_EXCLUSIVE_STATE["since_ms"] = 0


def _now_ms() -> int:
    try:
        v = getattr(_RUNTIME_CTX, "fixed_now_ms", None)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return int(time.time() * 1000)


__all__ = [
    "_CHARACTERIZATION_EXCLUSIVE_STATE",
    "_characterization_exclusive_is_running",
    "_characterization_exclusive_inc",
    "_characterization_exclusive_dec",
    "_now_ms",
]
