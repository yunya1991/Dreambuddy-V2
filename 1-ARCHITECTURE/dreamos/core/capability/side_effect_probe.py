"""GAP-21: 四类副作用 probe 协议与完整性门禁。

约定
----
运行时 probe 输出（Node 采集器或 harness）::

    {
      "schema_version": "1.0",
      "plugins": ["p-host", "p-new"],
      "effects": {
        "subscription": [{"id": "sub:p-new:agent/pre-step", "owner": "p-new"}],
        "connection":   [{"id": "conn:p-new:1", "owner": "p-new"}],
        "handle":       [{"id": "handle:p-new:1", "owner": "p-new"}],
        "timer":        [{"id": "timer:p-new:1", "owner": "p-new"}]
      },
      "probe": {"complete": true, "source": "dsh-node-instrument", "at": "..."}
    }

- `complete=false` 的快照只能用于规划，**不能**作为 unload 验收证据（fail-closed）。
- `static_probe` 仅从 A3-1 插件图推导订阅关系，并显式把 connection/handle/timer
  标为 unavailable——它永远不是完整的运行时证据。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
SIDE_EFFECTS = ("subscription", "connection", "handle", "timer")


class ProbeError(ValueError):
    """probe 快照不合法或不完整"""


def validate_snapshot(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProbeError("probe 快照必须是对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProbeError(f"schema_version 必须为 {SCHEMA_VERSION}")
    plugins = payload.get("plugins")
    if not isinstance(plugins, list) or any(not isinstance(p, str) for p in plugins):
        raise ProbeError("plugins 必须是字符串数组")

    effects = payload.get("effects")
    if not isinstance(effects, dict):
        raise ProbeError("effects 必须是对象")
    unknown = sorted(set(effects) - set(SIDE_EFFECTS))
    if unknown:
        raise ProbeError(f"effects 含未知类别: {unknown}")

    normalized: Dict[str, List[Dict[str, str]]] = {}
    for cls in SIDE_EFFECTS:
        items = effects.get(cls, [])
        if not isinstance(items, list):
            raise ProbeError(f"effects.{cls} 必须是数组")
        bucket: List[Dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ProbeError(f"effects.{cls} 元素必须是对象")
            eid, owner = item.get("id"), item.get("owner")
            if not isinstance(eid, str) or not eid:
                raise ProbeError(f"effects.{cls} 缺 id")
            if not isinstance(owner, str) or not owner:
                raise ProbeError(f"effects.{cls} 缺 owner")
            bucket.append({"id": eid, "owner": owner})
        normalized[cls] = bucket

    probe = payload.get("probe")
    if not isinstance(probe, dict) or not isinstance(probe.get("complete"), bool):
        raise ProbeError("probe.complete 必须是布尔值")

    return {
        "schema_version": SCHEMA_VERSION,
        "plugins": list(plugins),
        "effects": normalized,
        "probe": probe,
    }


def require_complete(payload: Any) -> Dict[str, Any]:
    snapshot = validate_snapshot(payload)
    if snapshot["probe"]["complete"] is not True:
        raise ProbeError(
            "probe 不完整（complete != true），拒绝作为卸载证据；"
            f"unavailable={snapshot['probe'].get('unavailable')}"
        )
    return snapshot


def static_probe(graph: Dict[str, Any], *, at: Optional[datetime] = None) -> Dict[str, Any]:
    """从 A3-1 插件图推导订阅；其余三类显式标记 unavailable。"""
    subscriptions: List[Dict[str, str]] = []
    plugins: List[str] = []
    for plugin in graph.get("plugins", []):
        if not isinstance(plugin, dict) or not plugin.get("plugin_id"):
            continue
        pid = str(plugin["plugin_id"])
        plugins.append(pid)
        channels = (plugin.get("event_channels") or {}).get("subscribe") or []
        for channel in channels:
            subscriptions.append({"id": f"sub:{pid}:{channel}", "owner": pid})

    stamp = (at or datetime.now(timezone.utc)).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "plugins": sorted(plugins),
        "effects": {
            "subscription": subscriptions,
            "connection": [],
            "handle": [],
            "timer": [],
        },
        "probe": {
            "complete": False,
            "source": "static-graph",
            "at": stamp,
            "unavailable": ["connection", "handle", "timer"],
        },
    }
