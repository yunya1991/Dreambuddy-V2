"""A3-3: 插件卸载回滚验收（IF-6 unload / ADR-10 / G-L2-9）。

边界
----
- **只做验收，不执行卸载**：真正的 unload 由 DSH 运行时完成；本模块校验授权凭证，
  并对「卸载前 / 卸载后」副作用快照做证据化比对。
- **四类副作用**：`subscription` / `connection` / `handle` / `timer`。
  判定标准（逐类）：
    1) 该插件拥有的副作用在 after 中全部消失；
    2) 其他插件的副作用未被误删（防回滚过度）。
  两类都满足才算该类回滚成功；全部成功且插件已从 after 消失才 `ok=true`。
- **fail-closed**：缺 token/mandate、过期、scope 不符、快照畸形一律拒绝；
  有残留时 `side_effects_reverted` 只列真正干净的类别，不把失败写成成功。

副作用快照格式（由运行时 harness 采集）::

    {
      "plugins": ["local-a", "p-new"],
      "effects": {
        "subscription": [{"id": "sub:p-new:agent/pre-step", "owner": "p-new"}],
        "connection":   [{"id": "conn:p-new:redis", "owner": "p-new"}],
        "handle":       [{"id": "fd:p-new", "owner": "p-new"}],
        "timer":        [{"id": "timer:p-new", "owner": "p-new"}]
      }
    }
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "1.0"
DEFAULT_REQUEST_ID = "unload-local"
SIDE_EFFECTS = ("subscription", "connection", "handle", "timer")


class PluginUnloadError(ValueError):
    """unload 请求/授权/快照不合法（拒绝验收）"""


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PluginUnloadError(f"{field} 必须是 ISO 8601 时间")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PluginUnloadError(f"{field} 无法解析: {value!r}") from exc
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _check_authorization(rollback_token: Any, mandate: Any, now: datetime) -> None:
    """G-L2-9：无有效 rollback_token + plugin.unload Mandate 不得验收。"""
    if not isinstance(rollback_token, dict):
        raise PluginUnloadError("缺少 rollback_token")
    token_id = rollback_token.get("token_id")
    if not isinstance(token_id, str) or len(token_id) < 8:
        raise PluginUnloadError("rollback_token.token_id 至少 8 字")
    idem = rollback_token.get("idempotency_key")
    if not isinstance(idem, str) or len(idem) < 8:
        raise PluginUnloadError("rollback_token.idempotency_key 至少 8 字")
    if _parse_ts(rollback_token.get("expires_at"), "rollback_token.expires_at") <= now:
        raise PluginUnloadError("rollback_token 已过期")

    if not isinstance(mandate, dict):
        raise PluginUnloadError("缺少 mandate")
    if len(str(mandate.get("mandate_id") or "")) < 4:
        raise PluginUnloadError("mandate.mandate_id 至少 4 字")
    if len(str(mandate.get("granted_by") or "")) < 2:
        raise PluginUnloadError("mandate.granted_by 至少 2 字")
    if mandate.get("scope") != "plugin.unload":
        raise PluginUnloadError(
            f"mandate.scope 必须为 plugin.unload（实际 {mandate.get('scope')!r}）"
        )
    if _parse_ts(mandate.get("expires_at"), "mandate.expires_at") <= now:
        raise PluginUnloadError("mandate 已过期")


def _parse_snapshot(raw: Any, label: str) -> Tuple[Set[str], Dict[str, Dict[str, str]]]:
    if not isinstance(raw, dict):
        raise PluginUnloadError(f"{label} 快照必须是对象")
    plugins = raw.get("plugins")
    if not isinstance(plugins, list) or any(not isinstance(item, str) for item in plugins):
        raise PluginUnloadError(f"{label}.plugins 必须是字符串数组")

    effects = raw.get("effects")
    if not isinstance(effects, dict):
        raise PluginUnloadError(f"{label}.effects 必须是对象")
    unknown = sorted(set(effects) - set(SIDE_EFFECTS))
    if unknown:
        raise PluginUnloadError(f"{label}.effects 含未知类别: {unknown}")

    parsed: Dict[str, Dict[str, str]] = {}
    for cls in SIDE_EFFECTS:
        items = effects.get(cls, [])
        if not isinstance(items, list):
            raise PluginUnloadError(f"{label}.effects.{cls} 必须是数组")
        bucket: Dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                raise PluginUnloadError(f"{label}.effects.{cls} 元素必须是对象")
            eid = item.get("id")
            owner = item.get("owner")
            if not isinstance(eid, str) or not eid:
                raise PluginUnloadError(f"{label}.effects.{cls} 缺 id")
            if not isinstance(owner, str) or not owner:
                raise PluginUnloadError(f"{label}.effects.{cls} 缺 owner")
            bucket[eid] = owner
        parsed[cls] = bucket

    # 带 probe 元信息的快照必须完整；静态推导的快照（complete=false）不能用于验收
    if "probe" in raw:
        probe = raw["probe"]
        if not isinstance(probe, dict):
            raise PluginUnloadError(f"{label}.probe 必须是对象")
        if probe.get("complete") is not True:
            raise PluginUnloadError(
                f"{label}.probe 不完整（complete != true），拒绝验收；"
                f"unavailable={probe.get('unavailable')}"
            )
    return set(plugins), parsed


def _reverted_classes(
    plugin_id: str,
    before: Dict[str, Dict[str, str]],
    after: Dict[str, Dict[str, str]],
) -> List[str]:
    reverted: List[str] = []
    for cls in SIDE_EFFECTS:
        owned_before = {eid for eid, owner in before[cls].items() if owner == plugin_id}
        host_before = {eid for eid, owner in before[cls].items() if owner != plugin_id}
        after_ids = set(after[cls])
        after_owned = {eid for eid, owner in after[cls].items() if owner == plugin_id}

        residue = (owned_before & after_ids) | after_owned
        host_lost = host_before - after_ids
        if not residue and not host_lost:
            reverted.append(cls)
    return reverted


def unload_plugin(
    plugin_id: str,
    rollback_token: Any,
    mandate: Any,
    before: Any,
    after: Any,
    request_id: str = DEFAULT_REQUEST_ID,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """验收一次卸载：授权 + 四类副作用 before/after 比对（不执行卸载）。"""
    stamp = now or datetime.now(timezone.utc)
    _check_authorization(rollback_token, mandate, stamp)

    before_plugins, before_effects = _parse_snapshot(before, "before")
    after_plugins, after_effects = _parse_snapshot(after, "after")

    if plugin_id not in before_plugins:
        # 未加载的插件没有可验收的卸载：不伪造成功
        return {
            "schema_version": SCHEMA_VERSION,
            "op": "unload",
            "direction": "response",
            "request_id": request_id,
            "ok": False,
            "unloaded": False,
            "side_effects_reverted": [],
        }

    unloaded = plugin_id not in after_plugins
    reverted = _reverted_classes(plugin_id, before_effects, after_effects)

    return {
        "schema_version": SCHEMA_VERSION,
        "op": "unload",
        "direction": "response",
        "request_id": request_id,
        "ok": unloaded and len(reverted) == len(SIDE_EFFECTS),
        "unloaded": unloaded,
        "side_effects_reverted": reverted,
    }


# ============================================================
# 契约入口
# ============================================================


def build_unload_request(
    plugin_id: str,
    rollback_token: Dict[str, Any],
    mandate: Dict[str, Any],
    request_id: str = DEFAULT_REQUEST_ID,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "op": "unload",
        "direction": "request",
        "request_id": request_id,
        "plugin_id": plugin_id,
        "rollback_token": rollback_token,
        "mandate": mandate,
    }


def handle_unload(
    request: Dict[str, Any],
    before: Any,
    after: Any,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """校验 IF-6 unload.request 后返回 unload.response。"""
    if not isinstance(request, dict):
        raise PluginUnloadError("unload request 必须是对象")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise PluginUnloadError(f"schema_version 必须为 {SCHEMA_VERSION}")
    if request.get("op") != "unload":
        raise PluginUnloadError(f"op 必须为 unload（实际 {request.get('op')!r}）")
    if request.get("direction") != "request":
        raise PluginUnloadError(f"direction 必须为 request（实际 {request.get('direction')!r}）")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or len(request_id) < 6:
        raise PluginUnloadError("request_id 至少 6 字")
    plugin_id = request.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise PluginUnloadError("缺少 plugin_id")
    if "rollback_token" not in request:
        raise PluginUnloadError("缺少 rollback_token")
    if "mandate" not in request:
        raise PluginUnloadError("缺少 mandate")

    return unload_plugin(
        plugin_id,
        rollback_token=request["rollback_token"],
        mandate=request["mandate"],
        before=before,
        after=after,
        request_id=request_id,
        now=now,
    )


# ============================================================
# CLI
# ============================================================


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_unload.py", description="A3-3 卸载回滚验收（IF-6）"
    )
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--token", type=Path, required=True)
    parser.add_argument("--mandate", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True, help="卸载前副作用快照")
    parser.add_argument("--after", type=Path, required=True, help="卸载后副作用快照")
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        request = build_unload_request(
            args.plugin_id,
            _read_json(args.token),
            _read_json(args.mandate),
            args.request_id,
        )
        response = handle_unload(
            request,
            before=_read_json(args.before),
            after=_read_json(args.after),
        )
    except (OSError, json.JSONDecodeError, PluginUnloadError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    text = json.dumps(response, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if response["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
