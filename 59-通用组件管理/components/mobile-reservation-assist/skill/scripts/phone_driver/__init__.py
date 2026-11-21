"""本地手机驱动：uiautomator2（adb）通道，与 Auto.js 网关通道并存。

路由约定：只有剪映 / 抖音这类"单次、需要精细点击"的流程走本地 u2；
顺风车、小红书等既有链路仍走网关 + Auto.js，互不影响。
"""

from __future__ import annotations

from .runner import LOCAL_DRIVERS, driver_mode, run_local_job, use_local_driver
from .u2_driver import U2Driver, U2Error, available

__all__ = [
    "LOCAL_DRIVERS",
    "U2Driver",
    "U2Error",
    "available",
    "driver_mode",
    "run_local_job",
    "use_local_driver",
]
