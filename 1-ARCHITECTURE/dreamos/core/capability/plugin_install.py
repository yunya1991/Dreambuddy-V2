"""A3-4: 插件安装门禁（IF-6 install / ADR-10 / G-L2-9）。

边界
----
- **门禁优先，执行器后置**：本模块负责四道硬门禁——request 形状、Mandate
  （`scope=plugin.install` 且未过期）、白名单（53 `plugin_whitelist.yaml`）、
  `plugin_ready`（A3-2 experiment 通过 + A3-3 四类回滚证据齐全）。
- **禁止伪造 installed=true**：真正落盘安装必须注入 `InstallAdapter`（DSH 运行时
  adapter）。未注入 adapter 时直接 fail-closed，绝不返回假的安装成功。
- **契约失败不可表达**：`install.response` 的 `ok/installed` 是 const true，所以所有
  门禁失败都以 `PluginInstallError` 抛出，不伪造响应。
- 本模块自身不写盘；是否落盘由 adapter 决定，并通过 `rollback_token` 关联后续 unload。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import yaml

SCHEMA_VERSION = "1.0"
DEFAULT_REQUEST_ID = "install-local"
SIDE_EFFECTS = ("subscription", "connection", "handle", "timer")
DEFAULT_WHITELIST_PATH = (
    Path(__file__).resolve().parents[4] / "53-DSH插件模块" / "plugin_whitelist.yaml"
)
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "forbidden": 3}


class PluginInstallError(ValueError):
    """install 门禁不通过（拒绝安装，不产出成功响应）"""


class InstallAdapter:
    """安装执行器接口：真实落盘安装由 DSH 运行时适配器实现。"""

    def install(self, manifest: Dict[str, Any]) -> None:  # pragma: no cover - 接口
        raise NotImplementedError


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PluginInstallError(f"{field} 必须是 ISO 8601 时间")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PluginInstallError(f"{field} 无法解析: {value!r}") from exc
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _check_request(request: Any) -> Dict[str, Any]:
    if not isinstance(request, dict):
        raise PluginInstallError("install request 必须是对象")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise PluginInstallError(f"schema_version 必须为 {SCHEMA_VERSION}")
    if request.get("op") != "install":
        raise PluginInstallError(f"op 必须为 install（实际 {request.get('op')!r}）")
    if request.get("direction") != "request":
        raise PluginInstallError(f"direction 必须为 request（实际 {request.get('direction')!r}）")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or len(request_id) < 6:
        raise PluginInstallError("request_id 至少 6 字")
    manifest = request.get("manifest")
    if not isinstance(manifest, dict):
        raise PluginInstallError("缺少 manifest")
    if request.get("rollback_verified") is not True:
        raise PluginInstallError("rollback_verified 必须为 true（无回滚不安装，G-L2-9）")
    return manifest


def _check_mandate(mandate: Any, now: datetime) -> None:
    if not isinstance(mandate, dict):
        raise PluginInstallError("缺少 mandate")
    if len(str(mandate.get("mandate_id") or "")) < 4:
        raise PluginInstallError("mandate.mandate_id 至少 4 字")
    if len(str(mandate.get("granted_by") or "")) < 2:
        raise PluginInstallError("mandate.granted_by 至少 2 字")
    if mandate.get("scope") != "plugin.install":
        raise PluginInstallError(
            f"mandate.scope 必须为 plugin.install（实际 {mandate.get('scope')!r}）"
        )
    if _parse_ts(mandate.get("expires_at"), "mandate.expires_at") <= now:
        raise PluginInstallError("mandate 已过期")


def _check_rollback_evidence(evidence: Any) -> None:
    """要求 A3-3 的 unload 验收结果覆盖四类副作用，而不是仅声明 rollback_verified。"""
    if not isinstance(evidence, dict):
        raise PluginInstallError("缺少 A3-3 回滚验收证据（side_effects_reverted）")
    if evidence.get("ok") is not True or evidence.get("unloaded") is not True:
        raise PluginInstallError("A3-3 回滚证据未通过（ok/unloaded 必须为 true）")
    reverted = evidence.get("side_effects_reverted")
    if not isinstance(reverted, list):
        raise PluginInstallError("A3-3 回滚证据缺 side_effects_reverted")
    missing = [cls for cls in SIDE_EFFECTS if cls not in reverted]
    if missing:
        raise PluginInstallError(f"回滚证据未覆盖四类副作用，缺: {missing}")


def _check_experiment_ready(experiment: Any) -> None:
    """plugin_ready 的 experiment 侧：内存预检必须通过且零落盘。"""
    if not isinstance(experiment, dict):
        raise PluginInstallError("缺少 A3-2 experiment 结果（plugin_ready）")
    if experiment.get("ok") is not True or experiment.get("loaded") is not True:
        raise PluginInstallError("A3-2 experiment 未通过（ok/loaded 必须为 true）")
    if experiment.get("disk_writes") != 0:
        raise PluginInstallError("A3-2 experiment 必须零落盘（disk_writes=0）")


def _load_whitelist(path: Path) -> Dict[str, Any]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PluginInstallError(f"白名单无法读取/解析: {exc}") from exc
    if not isinstance(doc, dict):
        raise PluginInstallError("白名单格式非法")
    return doc


def _check_whitelist(plugin_id: str, profile: str, whitelist_path: Path) -> None:
    doc = _load_whitelist(whitelist_path)
    entries = doc.get("entries") or []
    entry = next(
        (item for item in entries if isinstance(item, dict) and item.get("id") == plugin_id),
        None,
    )
    if entry is None:
        raise PluginInstallError(f"白名单未登记: {plugin_id}（deny-by-default）")
    if entry.get("status") != "approved":
        raise PluginInstallError(f"白名单 status={entry.get('status')!r}（需 approved）")
    if entry.get("risk_level") == "forbidden":
        raise PluginInstallError("白名单 risk_level=forbidden，任何 profile 都不许加载")

    permitted = entry.get("permitted_profiles") or []
    if profile not in permitted:
        raise PluginInstallError(f"profile {profile!r} 不在 permitted_profiles={permitted}")

    policies = doc.get("policies") or {}
    if profile in (policies.get("production_profiles") or []):
        if not (entry.get("sandbox_verified") is True and entry.get("fail_open_verified") is True):
            raise PluginInstallError(
                "生产 profile 需 sandbox_verified=true 且 fail_open_verified=true"
            )
        max_risk = policies.get("max_risk_for_production")
        if isinstance(max_risk, str):
            limit = RISK_ORDER.get(max_risk, 1)
            if RISK_ORDER.get(str(entry.get("risk_level")), 2) > limit:
                raise PluginInstallError(
                    f"生产 profile 不允许 risk_level={entry.get('risk_level')!r}（上限 {max_risk}）"
                )


def _issue_rollback_token(plugin_id: str, now: datetime) -> Dict[str, str]:
    stamp = now.strftime("%Y%m%d%H%M%S")
    return {
        "token_id": f"rbk-{plugin_id}-{stamp}",
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "idempotency_key": f"idem-{plugin_id}-{stamp}",
    }


# ============================================================
# 契约入口
# ============================================================


def build_install_request(
    manifest: Dict[str, Any],
    mandate: Dict[str, Any],
    request_id: str = DEFAULT_REQUEST_ID,
    rollback_verified: bool = True,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "op": "install",
        "direction": "request",
        "request_id": request_id,
        "manifest": manifest,
        "mandate": mandate,
        "rollback_verified": rollback_verified,
    }


def handle_install(
    request: Dict[str, Any],
    *,
    evidence: Any,
    experiment: Any,
    adapter: Optional[InstallAdapter] = None,
    whitelist_path: Optional[Path] = None,
    profile: str = "sandbox",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """四道门禁全过且注入 adapter 后，才执行安装并返回 install.response。"""
    stamp = now or datetime.now(timezone.utc)
    manifest = _check_request(request)
    _check_mandate(request.get("mandate"), stamp)
    _check_experiment_ready(experiment)
    _check_rollback_evidence(evidence)

    plugin_id = manifest.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise PluginInstallError("manifest.plugin_id 缺失")
    _check_whitelist(
        plugin_id, profile, Path(whitelist_path) if whitelist_path else DEFAULT_WHITELIST_PATH
    )

    if adapter is None:
        raise PluginInstallError(
            "安装执行器未接通：需注入 DSH 运行时 InstallAdapter（禁止伪造 installed=true）"
        )
    try:
        adapter.install(manifest)
    except Exception as exc:  # adapter 失败不得伪装成功
        raise PluginInstallError(f"安装执行失败: {exc}") from exc

    return {
        "schema_version": SCHEMA_VERSION,
        "op": "install",
        "direction": "response",
        "request_id": request["request_id"],
        "ok": True,
        "installed": True,
        "plugin_id": plugin_id,
        "rollback_token": _issue_rollback_token(plugin_id, stamp),
    }


# ============================================================
# CLI（仅门禁预检，不执行安装）
# ============================================================


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_install.py", description="A3-4 安装门禁预检（不执行安装）"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mandate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="A3-3 unload.response")
    parser.add_argument("--experiment", type=Path, required=True, help="A3-2 experiment.response")
    parser.add_argument("--whitelist", type=Path, default=None)
    parser.add_argument("--profile", default="sandbox")
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    args = parser.parse_args(argv)

    try:
        request = build_install_request(
            _read_json(args.manifest), _read_json(args.mandate), args.request_id
        )
        manifest = _check_request(request)
        _check_mandate(request["mandate"], datetime.now(timezone.utc))
        _check_experiment_ready(_read_json(args.experiment))
        _check_rollback_evidence(_read_json(args.evidence))
        _check_whitelist(
            manifest["plugin_id"],
            args.profile,
            args.whitelist or DEFAULT_WHITELIST_PATH,
        )
    except (OSError, json.JSONDecodeError, PluginInstallError, KeyError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ready": True,
                "plugin_id": manifest["plugin_id"],
                "profile": args.profile,
                "note": "门禁通过；安装需注入 DSH InstallAdapter（本 CLI 不落盘）",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
