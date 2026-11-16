"""A3-3: 插件卸载回滚验收（IF-6 unload / ADR-10 / G-L2-9）

覆盖:
  - 授权校验：rollback_token / mandate 未过期且 scope=plugin.unload
  - 四类副作用（subscription/connection/handle/timer）全部清干净 → ok/unloaded=true
  - 任一类残留 → ok=false，且该类别不出现在 side_effects_reverted
  - 误删其他插件副作用（回滚过度）→ 该类不算回滚成功
  - 插件仍在 after.plugins → unloaded=false
  - 未知插件 / token 过期 / mandate scope 错 → 拒绝
  - 幂等：同一 token 重复验收结果一致
  - 响应经 56 官方校验器 `--plugin` 0 violation
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from dreamos.core.capability.plugin_unload import (  # noqa: E402
    PluginUnloadError,
    build_unload_request,
    handle_unload,
    unload_plugin,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
REQUEST_ID = "unload-test-001"
PLUGIN = "p-new"
TOKEN = {
    "token_id": "rbk-00000001",
    "expires_at": "2026-11-18T00:00:00+00:00",
    "idempotency_key": "idem-unload-001",
}
MANDATE = {
    "mandate_id": "mand-001",
    "granted_by": "user",
    "scope": "plugin.unload",
    "expires_at": "2026-11-18T00:00:00+00:00",
}


def _effect(eid: str, owner: str) -> dict:
    return {"id": eid, "owner": owner}


def _snapshot(plugins, *, with_new_effects: bool = True) -> dict:
    """构造副作用快照；with_new_effects=False 表示新插件副作用已清空。"""

    def owned(prefix: str, suffix: str) -> dict:
        return _effect(prefix, suffix)

    effects = {
        "subscription": [owned("sub:local-a:agent/pre-step", "local-a")],
        "connection": [owned("conn:local-a:db", "local-a")],
        "handle": [owned("fd:local-a", "local-a")],
        "timer": [owned("timer:local-a", "local-a")],
    }
    if with_new_effects:
        effects["subscription"].append(owned("sub:p-new:agent/pre-step", PLUGIN))
        effects["connection"].append(owned("conn:p-new:redis", PLUGIN))
        effects["handle"].append(owned("fd:p-new", PLUGIN))
        effects["timer"].append(owned("timer:p-new", PLUGIN))
    return {"plugins": list(plugins), "effects": effects}


@pytest.fixture()
def before():
    return _snapshot(["local-a", PLUGIN])


@pytest.fixture()
def after():
    return _snapshot(["local-a"], with_new_effects=False)


def test_clean_unload_reverts_all_four(before, after, tmp_path):
    response = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=after,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert response["op"] == "unload"
    assert response["direction"] == "response"
    assert response["request_id"] == REQUEST_ID
    assert response["ok"] is True
    assert response["unloaded"] is True
    assert response["side_effects_reverted"] == [
        "subscription",
        "connection",
        "handle",
        "timer",
    ]

    target = tmp_path / "unload.response.json"
    target.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "56-L2架构能力聚合层" / "scripts" / "validate_contracts.py"),
            "--plugin",
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_residual_timer_blocks_rollback(before, after):
    leaked = copy.deepcopy(after)
    leaked["effects"]["timer"].append(_effect("timer:p-new", PLUGIN))

    response = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=leaked,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert response["ok"] is False
    assert response["unloaded"] is True
    assert "timer" not in response["side_effects_reverted"]
    assert set(response["side_effects_reverted"]) == {"subscription", "connection", "handle"}


def test_over_revert_blocks_rollback(before, after):
    over = copy.deepcopy(after)
    over["effects"]["subscription"] = [
        item for item in over["effects"]["subscription"] if item["owner"] != "local-a"
    ]

    response = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=over,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert response["ok"] is False
    assert "subscription" not in response["side_effects_reverted"]


def test_plugin_still_present_is_not_unloaded(before):
    still_there = _snapshot(["local-a", PLUGIN], with_new_effects=True)

    response = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=still_there,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert response["ok"] is False
    assert response["unloaded"] is False


def test_unknown_plugin_is_rejected(before, after):
    response = unload_plugin(
        "ghost",
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=after,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert response["ok"] is False
    assert response["unloaded"] is False
    assert response["side_effects_reverted"] == []


def test_expired_token_is_rejected(before, after):
    expired = dict(TOKEN, expires_at="2026-11-17T09:00:00+00:00")

    with pytest.raises(PluginUnloadError) as exc:
        unload_plugin(
            PLUGIN,
            rollback_token=expired,
            mandate=MANDATE,
            before=before,
            after=after,
            request_id=REQUEST_ID,
            now=NOW,
        )
    assert "过期" in str(exc.value)


def test_wrong_mandate_scope_is_rejected(before, after):
    wrong = dict(MANDATE, scope="plugin.install")

    with pytest.raises(PluginUnloadError) as exc:
        unload_plugin(
            PLUGIN,
            rollback_token=TOKEN,
            mandate=wrong,
            before=before,
            after=after,
            request_id=REQUEST_ID,
            now=NOW,
        )
    assert "scope" in str(exc.value)


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"op": "install"}, "op"),
        ({"direction": "response"}, "direction"),
        ({"request_id": "x"}, "request_id"),
    ],
)
def test_request_shape_fail_closed(bad, message, before, after):
    request = build_unload_request(PLUGIN, TOKEN, MANDATE, REQUEST_ID)
    request.update(bad)

    with pytest.raises(PluginUnloadError) as exc:
        handle_unload(request, before=before, after=after, now=NOW)
    assert message in str(exc.value)


def test_handle_unload_accepts_valid_request(before, after):
    request = build_unload_request(PLUGIN, TOKEN, MANDATE, REQUEST_ID)
    response = handle_unload(request, before=before, after=after, now=NOW)

    assert response["request_id"] == REQUEST_ID
    assert response["ok"] is True


def test_repeat_unload_is_idempotent(before, after):
    first = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=after,
        request_id=REQUEST_ID,
        now=NOW,
    )
    second = unload_plugin(
        PLUGIN,
        rollback_token=TOKEN,
        mandate=MANDATE,
        before=before,
        after=after,
        request_id=REQUEST_ID,
        now=NOW,
    )

    assert first == second
