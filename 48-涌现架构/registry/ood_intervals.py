"""OOD (out-of-sample) 区间 registry 加载与命中判定。

P0-1 强制点的共享数据通路：案例入库与记忆升级两条路径都消费同一份 OOS 区间定义，
保证 OOS 隔离纪律一致。区间左闭右开 [start, end)。

调用方：
    from registry.ood_intervals import load_oos_intervals, in_oos_interval
    intervals = load_oos_intervals()  # List[(datetime, datetime)]
    if in_oos_interval(ts, intervals):
        ...  # fail-closed：拒绝入库 / 拒绝记忆升级

向后兼容：oos_intervals=None 时不强制隔离（旧行为）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Tuple

Interval = Tuple[datetime, datetime]

_REGISTRY_PATH = Path(__file__).resolve().parent / "ood_intervals.json"


def _parse_ts(value: object) -> Optional[datetime]:
    """宽容解析 ISO 时间戳（Z / 带时区 / 无时区按 UTC 处理）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def load_oos_intervals(registry_path: Optional[Path] = None) -> list[Interval]:
    """从 registry JSON 加载 OOS 区间列表。

    失败（文件不存在 / JSON 损坏）返回空列表 —— 调用方据此决定是否 fail-closed。
    """
    path = registry_path or _REGISTRY_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[Interval] = []
    for item in data.get("intervals", []):
        if not isinstance(item, dict):
            continue
        start = _parse_ts(item.get("start"))
        end = _parse_ts(item.get("end"))
        if start is None or end is None:
            continue
        if start >= end:
            continue
        out.append((start, end))
    return out


def in_oos_interval(ts: Optional[datetime], intervals: Optional[Sequence[Interval]]) -> bool:
    """判定 ts 是否落在任一 OOS 区间内（左闭右开 [start, end)）。

    - ts=None 或 intervals 为空 → 返回 False（不命中，由调用方决定缺时间戳策略）。
    - 无时区的 ts 视为 UTC；区间端点统一转换到 ts 的时区比较。
    """
    if ts is None or not intervals:
        return False
    ts_tz = ts.tzinfo or timezone.utc
    ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=ts_tz)
    for start, end in intervals:
        s = start.astimezone(ts_tz) if start.tzinfo else start.replace(tzinfo=ts_tz)
        e = end.astimezone(ts_tz) if end.tzinfo else end.replace(tzinfo=ts_tz)
        if s <= ts_aware < e:
            return True
    return False


__all__ = ["Interval", "load_oos_intervals", "in_oos_interval", "_parse_ts"]
