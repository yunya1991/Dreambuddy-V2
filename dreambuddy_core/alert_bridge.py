"""
dreambuddy_core/alert_bridge.py: 统一告警桥（Lark + fallback logging）
Phase 1 MVP：CI/本地 默认为 no-op + logging。生产会注入真实 send_alert 实现。
测试通过 monkeypatch alert_bridge.send_alert 计数。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def send_alert(level: str, message: str, **_kwargs: Any) -> None:
    """统一接口：level ∈ {info, warn, error, critical}. 生产环境注入 Lark 实现。"""
    lvl = str(level).lower()
    py_level = {
        "critical": logging.CRITICAL,
        "fatal":    logging.CRITICAL,
        "error":    logging.ERROR,
        "warn":     logging.WARNING,
        "warning":  logging.WARNING,
        "info":     logging.INFO,
    }.get(lvl, logging.WARNING)
    logger.log(py_level, "[ALERT:%s] %s", lvl, str(message)[:400])
