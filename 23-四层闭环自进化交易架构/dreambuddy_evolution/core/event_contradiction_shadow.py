"""B-04: 事件主矛盾 shadow 包装（只读诊断）.

调用 PrimaryContradictionDetector 的 force 模式，绕过生产开关但保持 FAIL-OPEN；
结果作为独立字段返回，不改变 production `primary_contradiction` 或任何裁决。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

METHOD_VERSION = "event-contradiction-shadow-v1"

_DETECTOR: Any = None


def _get_detector() -> Any:
    global _DETECTOR
    if _DETECTOR is None:
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )

        _DETECTOR = PrimaryContradictionDetector()
    return _DETECTOR


def compute_event_contradiction_shadow(
    kline_data: Any,
    *,
    enabled: bool = False,
) -> dict | None:
    """按开关计算事件主矛盾 shadow；关闭返回 None；异常 FAIL-OPEN。"""
    if not enabled:
        return None
    if not isinstance(kline_data, dict):
        return {
            "available": False,
            "shadow_only": True,
            "method": METHOD_VERSION,
            "reason": "no_kline_data",
        }
    try:
        info = _get_detector().detect(kline_data, force=True)
        payload = info.to_dict()
        payload.update(
            {
                "available": True,
                "shadow_only": True,
                "method": METHOD_VERSION,
            }
        )
        return payload
    except Exception as exc:  # noqa: BLE001 — shadow 层 FAIL-OPEN
        logger.debug("[EventContradictionShadow] fail-open: %s", exc)
        return {
            "available": False,
            "shadow_only": True,
            "method": METHOD_VERSION,
            "reason": f"{type(exc).__name__}: {exc}",
        }
