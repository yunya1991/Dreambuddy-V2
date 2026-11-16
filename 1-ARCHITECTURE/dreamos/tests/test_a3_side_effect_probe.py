"""GAP-21: probe 协议 + 完整性门禁 + unload 接线

覆盖:
  - 合法完整快照通过校验
  - static_probe 只给订阅，connection/handle/timer 显式 unavailable
  - require_complete 拒绝静态/不完整快照
  - 未知类别 / 缺 owner → 拒绝
  - unload 拒绝 probe.complete=false 的快照（即使四类看起来已清空）
  - unload 接受完整快照并正确判定 timer 回滚
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.capability.plugin_unload import (  # noqa: E402
    PluginUnloadError,
    unload_plugin,
)
from dreamos.core.capability.side_effect_probe import (  # noqa: E402
    ProbeError,
    require_complete,
    static_probe,
    validate_snapshot,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
TOKEN = {
    "token_id": "rbk-p-new-20261117100000",
    "expires_at": "2026-11-18T10:00:00+00:00",
    "idempotency_key": "idem-p-new-20261117100000",
}
MANDATE = {
    "mandate_id": "mand-u-001",
    "granted_by": "user",
    "scope": "plugin.unload",
    "expires_at": "2026-11-18T00:00:00+00:00",
}


def _snapshot(*, complete=True, plugins=("p-host", "p-new"), timer_owner=None):
    effects = {cls: [] for cls in ("subscription", "connection", "handle", "timer")}
    if timer_owner:
        effects["timer"] = [{"id": f"timer:{timer_owner}", "owner": timer_owner}]
    return {
        "schema_version": "1.0",
        "plugins": list(plugins),
        "effects": effects,
        "probe": {
            "complete": complete,
            "source": "test",
            "at": NOW.isoformat(),
            "unavailable": [] if complete else ["connection", "handle", "timer"],
        },
    }


def test_validate_accepts_complete_snapshot():
    snapshot = validate_snapshot(_snapshot())
    assert snapshot["probe"]["complete"] is True
    assert set(snapshot["effects"]) == {"subscription", "connection", "handle", "timer"}


def test_static_probe_marks_unavailable_and_extracts_subscriptions():
    graph = {
        "plugins": [
            {
                "plugin_id": "p-new",
                "event_channels": {"subscribe": ["agent/pre-step"], "publish": []},
            }
        ]
    }
    snapshot = static_probe(graph, at=NOW)

    assert snapshot["probe"]["complete"] is False
    assert snapshot["probe"]["unavailable"] == ["connection", "handle", "timer"]
    assert snapshot["effects"]["subscription"] == [
        {"id": "sub:p-new:agent/pre-step", "owner": "p-new"}
    ]


def test_require_complete_rejects_static_probe():
    snapshot = static_probe({"plugins": []}, at=NOW)
    with pytest.raises(ProbeError) as exc:
        require_complete(snapshot)
    assert "不完整" in str(exc.value)


def test_unknown_effect_class_is_rejected():
    snapshot = _snapshot()
    snapshot["effects"]["socket"] = []
    with pytest.raises(ProbeError) as exc:
        validate_snapshot(snapshot)
    assert "未知类别" in str(exc.value)


def test_missing_owner_is_rejected():
    snapshot = _snapshot()
    snapshot["effects"]["timer"] = [{"id": "timer:x"}]
    with pytest.raises(ProbeError) as exc:
        validate_snapshot(snapshot)
    assert "owner" in str(exc.value)


def test_unload_rejects_incomplete_probe_even_if_effects_clean():
    before = _snapshot(complete=False, timer_owner="p-new")
    after = _snapshot(complete=False, plugins=("p-host",))

    with pytest.raises(PluginUnloadError) as exc:
        unload_plugin(
            "p-new", TOKEN, MANDATE, before, after, request_id="unload-probe-001", now=NOW
        )
    assert "不完整" in str(exc.value)


def test_unload_accepts_complete_probe():
    before = _snapshot(timer_owner="p-new")
    after = _snapshot(plugins=("p-host",))

    verdict = unload_plugin(
        "p-new", TOKEN, MANDATE, before, after, request_id="unload-probe-002", now=NOW
    )
    assert verdict["ok"] is True
    assert verdict["unloaded"] is True
    assert verdict["side_effects_reverted"] == [
        "subscription",
        "connection",
        "handle",
        "timer",
    ]
