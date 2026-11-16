"""A3-2: 插件内存/沙箱试跑（IF-6 experiment / ADR-10 / G-L2-9）。

边界
----
- **不执行插件代码**：本阶段做「内存预检 + 图合并」——manifest 合法性、依赖可解析、
  发布通道冲突、权限面；全部通过才 `loaded=true`。不 eval/require 任何第三方代码。
- **零落盘**：不写 profile、不写 package.json、不写缓存；响应恒为 `disk_writes=0`。
- **可回滚**：预检只在内存里构建节点，失败即丢弃，故 `rollback_ok=true`。
- **fail-closed**：任一检查失败 → `ok=false, loaded=false`，错误码来自 IF-6 枚举，
  不用「看起来成功」掩盖（G-L2-9：未验证回滚不得 install）。

依赖 A3-1 的只读插件图（`plugin_inspect`）作为已安装事实源。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .plugin_inspect import (
    DEFAULT_PACKAGES_DIR,
    PluginInspectError,
    inspect_plugins,
)

SCHEMA_VERSION = "1.0"
DEFAULT_REQUEST_ID = "experiment-local"

PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PERMISSIONS = ("fs.read", "fs.write", "net", "exec", "ui")
MANIFEST_KEYS = {
    "plugin_id",
    "version",
    "entry",
    "dependencies",
    "event_channels",
    "permissions",
    "requires_restart",
}
DENIED_PERMISSIONS = ("exec", "fs.write")


class PluginExperimentError(ValueError):
    """experiment 请求本身不合法（不是 manifest 校验结果）"""


def _error(code: str, message: str, field: Optional[str] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"code": code, "message": message}
    if field:
        item["field"] = field
    return item


# ============================================================
# manifest 预检
# ============================================================


def _parse_manifest(manifest: Any) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """返回 (规范化 manifest, errors)；errors 非空即拒绝 loaded。"""
    errors: List[Dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return {}, [_error("E_MANIFEST_INVALID", "manifest 必须是对象", "manifest")]

    unknown = sorted(set(manifest) - MANIFEST_KEYS)
    if unknown:
        errors.append(_error("E_MANIFEST_INVALID", f"manifest 含未知字段: {unknown}", unknown[0]))

    plugin_id = manifest.get("plugin_id")
    if not isinstance(plugin_id, str) or not PLUGIN_ID_RE.match(plugin_id):
        errors.append(
            _error(
                "E_MANIFEST_INVALID",
                "plugin_id 必须匹配 ^[a-z0-9][a-z0-9._-]{2,63}$",
                "plugin_id",
            )
        )

    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        errors.append(_error("E_MANIFEST_INVALID", "version 必须为 x.y.z", "version"))

    entry = manifest.get("entry")
    if not isinstance(entry, str) or len(entry.strip()) < 3:
        errors.append(_error("E_MANIFEST_INVALID", "entry 至少 3 字", "entry"))

    permissions = manifest.get("permissions")
    if not isinstance(permissions, list):
        errors.append(_error("E_MANIFEST_INVALID", "permissions 必须是数组", "permissions"))
        permissions = []
    else:
        invalid = [item for item in permissions if item not in PERMISSIONS]
        if invalid:
            errors.append(
                _error(
                    "E_MANIFEST_INVALID",
                    f"permissions 含非法值: {invalid}（允许 {PERMISSIONS}）",
                    "permissions",
                )
            )

    dependencies = manifest.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or len(item) < 2 for item in dependencies
    ):
        errors.append(
            _error("E_MANIFEST_INVALID", "dependencies 必须是至少 2 字的字符串数组", "dependencies")
        )
        dependencies = []

    channels = manifest.get("event_channels", {})
    if not isinstance(channels, dict):
        errors.append(_error("E_MANIFEST_INVALID", "event_channels 必须是对象", "event_channels"))
        channels = {}
    else:
        unknown_channels = sorted(set(channels) - {"publish", "subscribe"})
        if unknown_channels:
            errors.append(
                _error(
                    "E_MANIFEST_INVALID",
                    f"event_channels 含未知键: {unknown_channels}",
                    "event_channels",
                )
            )
        for key in ("publish", "subscribe"):
            values = channels.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(item, str) or len(item) < 2 for item in values
            ):
                errors.append(
                    _error(
                        "E_MANIFEST_INVALID",
                        f"event_channels.{key} 必须是至少 2 字的字符串数组",
                        "event_channels",
                    )
                )

    requires_restart = manifest.get("requires_restart", False)
    if not isinstance(requires_restart, bool):
        errors.append(
            _error("E_MANIFEST_INVALID", "requires_restart 必须是布尔", "requires_restart")
        )

    normalized = {
        "plugin_id": plugin_id,
        "version": version,
        "entry": entry,
        "dependencies": list(dependencies) if isinstance(dependencies, list) else [],
        "event_channels": {
            "publish": list(channels.get("publish") or []),
            "subscribe": list(channels.get("subscribe") or []),
        },
        "permissions": list(permissions) if isinstance(permissions, list) else [],
        "requires_restart": requires_restart,
    }
    return normalized, errors


def _check_permissions(permissions: Sequence[str]) -> List[Dict[str, Any]]:
    denied = [item for item in permissions if item in DENIED_PERMISSIONS]
    if not denied:
        return []
    return [
        _error(
            "E_PERMISSION_DENIED",
            f"沙箱 experiment 不授予 {denied}（零落盘/不执行第三方代码）",
            "permissions",
        )
    ]


def _check_dependencies(
    dependencies: Sequence[str], installed: set, packages_dir: Path
) -> List[Dict[str, Any]]:
    missing = [
        dep
        for dep in dependencies
        if dep not in installed and not (packages_dir / dep / "package.json").is_file()
    ]
    if not missing:
        return []
    return [_error("E_DEP_MISSING", f"依赖不可解析: {missing}", "dependencies")]


def _check_channel_conflicts(
    declared: Dict[str, List[str]], plugins: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    owners: Dict[str, str] = {}
    for plugin in plugins:
        for channel in (plugin.get("event_channels") or {}).get("publish") or []:
            owners.setdefault(channel, plugin.get("plugin_id", "?"))

    conflicts = sorted(channel for channel in declared.get("publish") or [] if channel in owners)
    if not conflicts:
        return []
    detail = ", ".join(f"{channel}（已由 {owners[channel]} 发布）" for channel in conflicts)
    return [_error("E_CHANNEL_CONFLICT", f"发布通道冲突: {detail}", "event_channels")]


# ============================================================
# 契约入口
# ============================================================


def build_experiment_request(
    manifest: Dict[str, Any], request_id: str = DEFAULT_REQUEST_ID
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "op": "experiment",
        "direction": "request",
        "request_id": request_id,
        "manifest": manifest,
    }


def experiment_plugin(
    manifest: Any,
    profile: Optional[str] = None,
    home: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
    request_id: str = DEFAULT_REQUEST_ID,
) -> Dict[str, Any]:
    """内存预检 manifest，返回 IF-6 experiment.response（不执行、不落盘）。"""
    pkg_root = Path(packages_dir) if packages_dir else DEFAULT_PACKAGES_DIR
    try:
        graph = inspect_plugins(
            profile=profile, home=home, packages_dir=pkg_root, request_id=request_id
        )
    except PluginInspectError as exc:
        raise PluginExperimentError(f"profile 不可用: {exc}") from exc

    installed = {item["plugin_id"] for item in graph.get("plugins") or []}
    normalized, errors = _parse_manifest(manifest)

    if not errors:
        errors += _check_permissions(normalized["permissions"])
        errors += _check_dependencies(normalized["dependencies"], installed, pkg_root)
        errors += _check_channel_conflicts(normalized["event_channels"], graph.get("plugins") or [])

    ok = not errors
    return {
        "schema_version": SCHEMA_VERSION,
        "op": "experiment",
        "direction": "response",
        "request_id": request_id,
        "ok": ok,
        "loaded": ok,
        "errors": errors,
        "rollback_ok": True,
        "disk_writes": 0,
    }


def handle_experiment(
    request: Dict[str, Any],
    profile: Optional[str] = None,
    home: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """校验 IF-6 experiment.request 后返回 experiment.response。"""
    if not isinstance(request, dict):
        raise PluginExperimentError("experiment request 必须是对象")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise PluginExperimentError(f"schema_version 必须为 {SCHEMA_VERSION}")
    if request.get("op") != "experiment":
        raise PluginExperimentError(f"op 必须为 experiment（实际 {request.get('op')!r}）")
    if request.get("direction") != "request":
        raise PluginExperimentError(
            f"direction 必须为 request（实际 {request.get('direction')!r}）"
        )
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or len(request_id) < 6:
        raise PluginExperimentError("request_id 至少 6 字")
    if "manifest" not in request:
        raise PluginExperimentError("缺少 manifest")

    return experiment_plugin(
        request["manifest"],
        profile=profile,
        home=home,
        packages_dir=packages_dir,
        request_id=request_id,
    )


# ============================================================
# CLI
# ============================================================


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_experiment.py", description="A3-2 插件内存/沙箱试跑（IF-6）"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", default=None, help="DSH profile（缺省 headless）")
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        response = handle_experiment(
            build_experiment_request(manifest, args.request_id),
            profile=args.profile,
            home=args.home,
            packages_dir=args.packages_dir,
        )
    except (OSError, json.JSONDecodeError, PluginExperimentError) as exc:
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
