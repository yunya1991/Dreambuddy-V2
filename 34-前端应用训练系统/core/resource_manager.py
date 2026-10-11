"""资源配额管理器。

管理主动训练和被动训练的资源配额，确保双模式不超出资源限制。

SPEC §2.4 资源分配:
  - 主动训练: CPU≤30%, 内存≤2GB, 超时8h, 优先级低, 失败重试(次日)
  - 被动训练: CPU≤50%, 内存≤4GB, 超时30min, 优先级中, 不重试
"""
import os
import psutil
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ResourceQuota:
    """资源配额配置。"""
    cpu_percent: int = 30           # CPU使用率上限(%)
    memory_mb: int = 2048           # 内存使用上限(MB)
    timeout_hours: float = 8.0      # 超时(小时)
    timeout_minutes: float = 0.0   # 超时(分钟, 与timeout_hours二选一)
    max_retries: int = 3            # 最大重试次数(0=不重试)


# SPEC §2.4 预设配额
ACTIVE_QUOTA = ResourceQuota(
    cpu_percent=30,
    memory_mb=2048,
    timeout_hours=8.0,
    max_retries=3,
)

PASSIVE_QUOTA = ResourceQuota(
    cpu_percent=50,
    memory_mb=4096,
    timeout_minutes=30.0,
    max_retries=0,  # 被动训练不重试
)


class ResourceManager:
    """资源使用监控与配额检查。"""

    def __init__(self, quota: ResourceQuota):
        self._quota = quota

    def _get_current_usage(self) -> Dict[str, float]:
        """获取当前系统资源使用情况。"""
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            return {"cpu": cpu, "memory_mb": mem.used / (1024 * 1024)}
        except Exception:
            return {"cpu": 0, "memory_mb": 0}

    def check_available(self) -> bool:
        """检查当前资源是否在配额内。"""
        usage = self._get_current_usage()
        if usage["cpu"] > self._quota.cpu_percent:
            return False
        if usage["memory_mb"] > self._quota.memory_mb:
            return False
        return True

    def get_usage_report(self) -> Dict[str, object]:
        """获取资源使用报告。"""
        usage = self._get_current_usage()
        return {
            "current_cpu": round(usage["cpu"], 1),
            "current_memory_mb": round(usage["memory_mb"], 1),
            "quota_cpu": self._quota.cpu_percent,
            "quota_memory_mb": self._quota.memory_mb,
            "within_quota": self.check_available(),
        }
