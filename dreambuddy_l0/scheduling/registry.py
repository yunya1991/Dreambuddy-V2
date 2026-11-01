"""声明式任务注册表（C9）：job_registry.yaml 的加载、校验与查询。

硬约束：本文件是任务清单的机器可读事实源；窗口统一 UTC，迟到容忍 5min，
job_runs 保留 90 天。只纳管非实盘链路（实盘进程只走 C13 只读旁路）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import yaml

CARRIER_ENUM = {"systemd", "systemd-timer", "launchd", "crontab"}
REQUIRED_FIELDS = (
    "task_key",
    "carrier",
    "unit",
    "schedule",
    "window_sec",
    "timeout_sec",
    "max_concurrency",
    "retry",
    "enabled",
    "fallback",
)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_REGISTRY_PATH = os.path.join(_REPO_ROOT, "0-系统文档管理", "job_registry.yaml")


@dataclass(frozen=True)
class TaskSpec:
    task_key: str
    carrier: str
    unit: str
    schedule: str
    window_sec: int
    timeout_sec: int
    max_concurrency: int
    retry: int
    enabled: bool
    fallback: str
    host: str = ""
    alias_units: Tuple[str, ...] = ()
    legacy_carrier: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TaskSpec":
        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            raise ValueError(f"{raw.get('task_key')} 缺字段 {missing}")
        if raw["carrier"] not in CARRIER_ENUM:
            raise ValueError(
                f"{raw['task_key']} carrier={raw['carrier']} 非法（允许 {sorted(CARRIER_ENUM)}）"
            )
        window_sec = int(raw["window_sec"])
        if window_sec <= 0 or window_sec > 86400:
            raise ValueError(f"{raw['task_key']} window_sec={window_sec} 超出 (0, 86400]")
        if int(raw["max_concurrency"]) < 1:
            raise ValueError(f"{raw['task_key']} max_concurrency 必须 >= 1")
        if int(raw["retry"]) < 0:
            raise ValueError(f"{raw['task_key']} retry 必须 >= 0")
        return cls(
            task_key=str(raw["task_key"]),
            carrier=str(raw["carrier"]),
            unit=str(raw["unit"]),
            schedule=str(raw["schedule"]),
            window_sec=window_sec,
            timeout_sec=int(raw["timeout_sec"]),
            max_concurrency=int(raw["max_concurrency"]),
            retry=int(raw["retry"]),
            enabled=bool(raw["enabled"]),
            fallback=str(raw["fallback"]),
            host=str(raw.get("host", "")),
            alias_units=tuple(raw.get("alias_units") or ()),
            legacy_carrier=str(raw.get("legacy_carrier", "")),
        )


class TaskRegistry:
    """任务注册表：只做查询与校验，不加载任何运行时注册表。"""

    def __init__(
        self,
        specs: List[TaskSpec],
        *,
        late_tolerance_sec: int = 300,
        retention_days: int = 90,
        missed_streak_alert: int = 3,
        window_timezone: str = "UTC",
        schema_version: str = "1.0",
    ) -> None:
        self._specs = {s.task_key: s for s in specs}
        self.late_tolerance_sec = int(late_tolerance_sec)
        self.retention_days = int(retention_days)
        self.missed_streak_alert = int(missed_streak_alert)
        self.window_timezone = window_timezone
        self.schema_version = schema_version

    @classmethod
    def from_dicts(cls, rows: List[Dict[str, Any]]) -> "TaskRegistry":
        specs: List[TaskSpec] = []
        seen: set = set()
        for raw in rows:
            spec = TaskSpec.from_dict(raw)
            if spec.task_key in seen:
                raise ValueError(f"duplicate task_key: {spec.task_key}")
            seen.add(spec.task_key)
            specs.append(spec)
        return cls(specs)

    def get(self, task_key: str) -> Optional[TaskSpec]:
        return self._specs.get(task_key)

    def list(self, *, enabled_only: bool = False) -> List[TaskSpec]:
        items = list(self._specs.values())
        return [s for s in items if s.enabled] if enabled_only else items

    def task_keys(self) -> List[str]:
        return sorted(self._specs)


def load_registry(path: Optional[str] = None) -> TaskRegistry:
    """加载并校验 job_registry.yaml；文件缺失/损坏时抛 ValueError（调用方 FAIL-OPEN 兜底）。"""
    path = path or DEFAULT_REGISTRY_PATH
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list) or not doc["tasks"]:
        raise ValueError(f"{path} 缺少非空 tasks 列表")
    reg = TaskRegistry.from_dicts(doc["tasks"])
    reg.late_tolerance_sec = int(doc.get("late_tolerance_sec", 300))
    reg.retention_days = int(doc.get("retention_days", 90))
    reg.missed_streak_alert = int(doc.get("missed_streak_alert", 3))
    reg.window_timezone = str(doc.get("window_timezone", "UTC"))
    reg.schema_version = str(doc.get("schema_version", "1.0"))
    return reg
