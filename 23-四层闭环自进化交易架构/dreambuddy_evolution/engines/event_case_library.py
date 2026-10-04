"""兼容层（向后兼容）：事件案例库已迁移至 29-事件驱动策略系统。

真实实现：29-事件驱动策略系统/event_driven/event_case_library.py
迁移日期：2026-10-04
"""
from __future__ import annotations

import sys
from pathlib import Path

_29_dir = str(Path(__file__).resolve().parents[3] / "29-事件驱动策略系统")
if _29_dir not in sys.path:
    sys.path.insert(0, _29_dir)

from event_driven.event_case_library import *  # noqa: F401,F403
from event_driven.event_case_library import (  # noqa: F401
    EventCase,
    EventCaseLibrary,
)
