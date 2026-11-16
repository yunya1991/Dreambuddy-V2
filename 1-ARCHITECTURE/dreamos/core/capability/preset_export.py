"""P08: preset 导出（GAP-16 收尾）。

口径
----
- **可部署集合**：只导出白名单中 `approved`、非 `forbidden`、且允许当前 profile 的插件；
  其余写入 `skipped` 并注明原因，不静默丢弃。
- **可复现**：插件按 `plugin_id` 排序；`preset_hash` 只覆盖
  `{name, version, plugins}`，不含 `generated_at`，因此同一图可在任意时间复算。
- **可校验**：`verify_preset` 重算 hash 并检查排序，篡改/乱序都会被拒。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from .plugin_inspect import (
    DEFAULT_PACKAGES_DIR,
    PluginInspectError,
    dsh_home,
    inspect_plugins,
)

SCHEMA_VERSION = "1.0"
DEFAULT_WHITELIST_PATH = (
    Path(__file__).resolve().parents[4] / "53-DSH插件模块" / "plugin_whitelist.yaml"
)


class PresetError(ValueError):
    """preset 构建/校验失败（不产出不可信清单）"""


def _compute_hash(name: str, version: str, plugins: List[Dict[str, Any]]) -> str:
    payload = {"name": name, "version": version, "plugins": plugins}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_entries(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PresetError(f"白名单无法读取/解析: {path}（{exc}）") from exc
    entries = (doc or {}).get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        raise PresetError("白名单 entries 必须是数组")
    return {
        item["id"]: item
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _normalize(plugin: Dict[str, Any]) -> Dict[str, Any]:
    deps = plugin.get("dependencies") or []
    return {
        "plugin_id": str(plugin.get("plugin_id")),
        "version": str(plugin.get("version") or "0.0.0"),
        "source": str(plugin.get("source") or ""),
        "dependencies": sorted(str(dep) for dep in deps),
    }


def _skip_reason(
    plugin_id: str, entry: Optional[Dict[str, Any]], profile: Optional[str]
) -> Optional[str]:
    if entry is None:
        return "unregistered"
    if entry.get("status") != "approved":
        return "not_approved"
    if entry.get("risk_level") == "forbidden":
        return "forbidden"
    permitted = entry.get("permitted_profiles") or []
    if profile and permitted and profile not in permitted:
        return "profile_not_permitted"
    return None


def build_preset(
    graph: Dict[str, Any],
    *,
    name: str,
    version: str = "1.0.0",
    profile: Optional[str] = None,
    whitelist_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise PresetError("name 必填")
    if not isinstance(version, str) or not version.strip():
        raise PresetError("version 必填")
    plugins_raw = graph.get("plugins")
    if not isinstance(plugins_raw, list):
        raise PresetError("graph.plugins 必须是数组")

    entries = _load_entries(Path(whitelist_path) if whitelist_path else DEFAULT_WHITELIST_PATH)

    plugins: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for raw in plugins_raw:
        if not isinstance(raw, dict) or not raw.get("plugin_id"):
            continue
        pid = str(raw["plugin_id"])
        reason = _skip_reason(pid, entries.get(pid), profile)
        if reason:
            skipped.append({"plugin_id": pid, "reason": reason})
        else:
            plugins.append(_normalize(raw))

    plugins.sort(key=lambda item: item["plugin_id"])
    skipped.sort(key=lambda item: item["plugin_id"])
    stamp = (now or datetime.now(timezone.utc)).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "version": version,
        "generated_at": stamp,
        "profile": profile,
        "plugins": plugins,
        "skipped": skipped,
        "preset_hash": _compute_hash(name, version, plugins),
    }


def verify_preset(preset: Any) -> None:
    if not isinstance(preset, dict):
        raise PresetError("preset 必须是对象")
    if preset.get("schema_version") != SCHEMA_VERSION:
        raise PresetError(f"schema_version 必须为 {SCHEMA_VERSION}")
    name = preset.get("name")
    version = preset.get("version")
    plugins = preset.get("plugins")
    if not isinstance(name, str) or not name:
        raise PresetError("preset.name 缺失")
    if not isinstance(version, str) or not version:
        raise PresetError("preset.version 缺失")
    if not isinstance(plugins, list) or any(not isinstance(p, dict) for p in plugins):
        raise PresetError("preset.plugins 必须是对象数组")

    ids = [p.get("plugin_id") for p in plugins]
    if ids != sorted(ids):
        raise PresetError("preset.plugins 未按 plugin_id 排序（破坏可复现性）")

    expected = _compute_hash(name, version, plugins)
    if preset.get("preset_hash") != expected:
        raise PresetError(f"preset_hash 不匹配：期望 {expected}，实际 {preset.get('preset_hash')}")


def export_preset(preset: Dict[str, Any], out_path: Path) -> Path:
    verify_preset(preset)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ============================================================
# CLI
# ============================================================


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preset_export.py", description="P08 preset 导出（白名单可部署集合）"
    )
    parser.add_argument("--profile", default=None, help="DSH profile（缺省 headless）")
    parser.add_argument("--name", required=True)
    parser.add_argument("--preset-version", default="1.0.0")
    parser.add_argument("--whitelist", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--packages-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        graph = inspect_plugins(
            profile=args.profile,
            home=dsh_home(args.home) if args.home else None,
            packages_dir=Path(args.packages_dir) if args.packages_dir else DEFAULT_PACKAGES_DIR,
        )
        preset = build_preset(
            graph,
            name=args.name,
            version=args.preset_version,
            profile=args.profile or "headless",
            whitelist_path=args.whitelist,
        )
        export_preset(preset, args.out)
    except (PresetError, PluginInspectError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "name": preset["name"],
                "plugins": len(preset["plugins"]),
                "skipped": len(preset["skipped"]),
                "preset_hash": preset["preset_hash"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
