"""F4: 统一降级事件审计流。

所有层（42/50/43/40）的降级事件统一写入 42/runtime/degraded_events.jsonl。
格式：{"ts": ISO8601, "layer": "42"|"50"|"43"|"40", "source": str, "reason": str, "detail": str}

设计原则：
- fail-open：写入失败静默忽略，不影响主流程
- 跨层可用：通过 DREAMBUDDY_ROOT 定位输出路径，不依赖跨模块 import
- 追加写：jsonl 一行一事件，支持 >24h 滚动告警
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
DEGRADED_EVENTS_PATH = Path(_ROOT) / "42-神经网络交易协调层" / "runtime" / "degraded_events.jsonl"

# 已知降级原因枚举（便于下游告警聚合）
REASON_BRIDGE_DEFAULTS = "bridge_closed_using_defaults"
REASON_SOURCE_STALE = "source_stale"
REASON_RESONANCE_FALLBACK = "resonance_fallback"
REASON_TRIGGER_FLAP = "trigger_flap"
REASON_DISPATCHER_DOWN = "dispatcher_down"
REASON_WASHOUT_UNKNOWN = "washout_unknown_fallback"
REASON_DIRECTION_LEAK = "direction_leak_check"
REASON_ADAPTER_ERROR = "adapter_error"
REASON_DATA_FETCH_FAIL = "data_fetch_failed"


def record_degraded_event(layer: str, source: str, reason: str, detail: str = "") -> None:
    """追加一条降级事件到审计流。

    Args:
        layer: 产生降级的层（"42"/"50"/"43"/"40"）
        source: 数据源/模块名（如 "43-strategic", "washout", "constraint_loader"）
        reason: 降级原因（使用 REASON_* 常量或自定义）
        detail: 详细信息（截断至 500 字符）
    """
    try:
        DEGRADED_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "layer": layer,
            "source": source,
            "reason": reason,
            "detail": str(detail)[:500],
        }
        with open(DEGRADED_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  审计写入失败不影响主流程
        pass


def load_recent_events(hours: float = 24.0) -> list[dict]:
    """读取最近 hours 小时的降级事件（用于 >24h 告警）。"""
    from datetime import timedelta

    if not DEGRADED_EVENTS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = []
    try:
        with open(DEGRADED_EVENTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    ts = datetime.fromisoformat(evt["ts"])
                    if ts >= cutoff:
                        events.append(evt)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except Exception:  # noqa: BLE001
        return []
    return events
