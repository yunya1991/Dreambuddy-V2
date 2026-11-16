"""GAP-16: preset 一键加载。

边界
----
- **先校验后加载**：preset hash/排序、Mandate（`plugin.install`）、experiment、
  四类回滚证据、白名单逐插件复核，任一不过即拒绝。
- **默认 dry-run**：只返回「待安装/已安装」计划；`apply=True` 且注入 adapter 才执行。
- **失败不吞**：单个插件失败进 `failed` 并置 `ok=false`，不把半成品报成成功。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Set

from .plugin_inspect import (
    DEFAULT_PACKAGES_DIR,
    dsh_home,
    inspect_plugins,
)
from .plugin_install import (
    PluginInstallError,
    _check_experiment_ready,
    _check_mandate,
    _check_rollback_evidence,
    _check_whitelist,
)
from .preset_export import PresetError, verify_preset


class PresetLoadError(ValueError):
    """preset 加载前置条件不满足"""


def _to_preset_load_error(exc: Exception) -> PresetLoadError:
    return PresetLoadError(str(exc))


def load_preset(
    preset: Dict[str, Any],
    *,
    mandate: Any,
    evidence: Any,
    experiment: Any,
    adapter: Optional[Any] = None,
    profile: str = "sandbox",
    whitelist_path: Optional[Path] = None,
    installed: Optional[Set[str]] = None,
    home: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
    apply: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    stamp = now or datetime.now(timezone.utc)
    try:
        verify_preset(preset)
        _check_mandate(mandate, stamp)
        _check_experiment_ready(experiment)
        _check_rollback_evidence(evidence)
    except (PresetError, PluginInstallError) as exc:
        raise _to_preset_load_error(exc) from exc

    whitelist = Path(whitelist_path) if whitelist_path else None
    for plugin in preset.get("plugins", []):
        try:
            _check_whitelist(plugin["plugin_id"], profile, whitelist or _default_whitelist())
        except PluginInstallError as exc:
            raise _to_preset_load_error(exc) from exc

    if installed is None:
        graph = inspect_plugins(
            profile=profile,
            home=dsh_home(home) if home else None,
            packages_dir=Path(packages_dir) if packages_dir else DEFAULT_PACKAGES_DIR,
        )
        installed = {p.get("plugin_id") for p in graph.get("plugins", [])}

    to_install = [p for p in preset.get("plugins", []) if p["plugin_id"] not in installed]
    already = [p for p in preset.get("plugins", []) if p["plugin_id"] in installed]

    report: Dict[str, Any] = {
        "ok": True,
        "applied": False,
        "preset_hash": preset.get("preset_hash"),
        "to_install": to_install,
        "already_installed": already,
        "installed": [],
        "failed": [],
        "skipped": preset.get("skipped", []),
    }
    if not apply:
        return report

    if adapter is None:
        raise PresetLoadError("preset 加载需要注入 InstallAdapter（禁止伪造安装成功）")

    for plugin in to_install:
        pid = plugin["plugin_id"]
        try:
            adapter.install({"plugin_id": pid, "version": plugin.get("version", "0.0.0")})
        except Exception as exc:  # 单点失败不阻断整批，但要上报
            report["failed"].append({"plugin_id": pid, "error": str(exc)})
        else:
            report["installed"].append(pid)

    report["applied"] = True
    report["ok"] = not report["failed"]
    return report


def _default_whitelist() -> Path:
    return Path(__file__).resolve().parents[4] / "53-DSH插件模块" / "plugin_whitelist.yaml"


# ============================================================
# CLI（默认 dry-run）
# ============================================================


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preset_load.py", description="preset 一键加载（默认 dry-run）"
    )
    parser.add_argument("--preset", type=Path, required=True)
    parser.add_argument("--mandate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--profile", default="sandbox")
    parser.add_argument("--whitelist", type=Path, default=None)
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真实执行；需要 DSH 运行时 adapter，CLI 不内置",
    )
    args = parser.parse_args(argv)

    if args.apply:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "CLI 不内置 InstallAdapter，请通过 Python API 注入后 apply",
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        report = load_preset(
            _read_json(args.preset),
            mandate=_read_json(args.mandate),
            evidence=_read_json(args.evidence),
            experiment=_read_json(args.experiment),
            adapter=None,
            profile=args.profile,
            whitelist_path=args.whitelist,
            home=args.home,
            packages_dir=args.packages_dir,
            apply=False,
        )
    except (PresetLoadError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
