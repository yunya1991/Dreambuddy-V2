"""A3-4: 插件安装门禁（IF-6 install / ADR-10 / G-L2-9）

覆盖:
  - 四道门禁：request 形状 / Mandate(plugin.install) / 白名单 / A3-2 experiment + A3-3 回滚证据
  - 缺 rollback_verified / 回滚证据不全 → 拒绝
  - 白名单：未登记 / forbidden / profile 不允许 / 生产 profile 未验 sandbox & fail-open → 拒绝
  - 无安装执行器 adapter → fail-closed（禁止伪造 installed=true）
  - 合法安装 → 契约响应 + rollback_token，经 56 官方校验器 0 violation
  - adapter 抛错 → 包装为 PluginInstallError
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from dreamos.core.capability.plugin_install import (  # noqa: E402
    PluginInstallError,
    build_install_request,
    handle_install,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
REQUEST_ID = "install-test-001"
PLUGIN = "p-new"

MANIFEST = {
    "plugin_id": PLUGIN,
    "version": "0.1.0",
    "entry": "lib/index.js",
    "permissions": ["fs.read", "ui"],
}
MANDATE = {
    "mandate_id": "mand-001",
    "granted_by": "user",
    "scope": "plugin.install",
    "expires_at": "2026-11-18T00:00:00+00:00",
}
EVIDENCE = {
    "schema_version": "1.0",
    "op": "unload",
    "direction": "response",
    "request_id": "unload-test-001",
    "ok": True,
    "unloaded": True,
    "side_effects_reverted": ["subscription", "connection", "handle", "timer"],
}
EXPERIMENT = {
    "schema_version": "1.0",
    "op": "experiment",
    "direction": "response",
    "request_id": "experiment-test-001",
    "ok": True,
    "loaded": True,
    "errors": [],
    "rollback_ok": True,
    "disk_writes": 0,
}


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def install(self, manifest):
        self.calls.append(dict(manifest))


def _whitelist(tmp_path: Path, entry: dict | None = None) -> Path:
    data = {
        "version": "v1",
        "default_deny": True,
        "policies": {
            "production_profiles": ["web", "headless"],
            "sandbox_profiles": ["sandbox"],
            "require_sandbox_first": True,
            "require_fail_open": True,
            "max_risk_for_production": "medium",
        },
        "entries": [
            entry
            or {
                "id": PLUGIN,
                "status": "approved",
                "risk_level": "low",
                "sandbox_verified": True,
                "fail_open_verified": True,
                "permitted_profiles": ["sandbox", "headless"],
            }
        ],
    }
    path = tmp_path / "plugin_whitelist.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _install(
    tmp_path,
    *,
    manifest=None,
    mandate=None,
    evidence=None,
    experiment=None,
    adapter=None,
    profile="sandbox",
    rollback_verified=True,
):
    return handle_install(
        build_install_request(
            manifest or MANIFEST,
            mandate or MANDATE,
            REQUEST_ID,
            rollback_verified=rollback_verified,
        ),
        evidence=evidence if evidence is not None else EVIDENCE,
        experiment=experiment if experiment is not None else EXPERIMENT,
        adapter=adapter,
        whitelist_path=_whitelist(tmp_path),
        profile=profile,
        now=NOW,
    )


def test_install_passes_gates_and_returns_contract_response(tmp_path):
    adapter = RecordingAdapter()
    response = _install(tmp_path, adapter=adapter)

    assert adapter.calls == [MANIFEST]
    assert response["op"] == "install"
    assert response["direction"] == "response"
    assert response["request_id"] == REQUEST_ID
    assert response["ok"] is True
    assert response["installed"] is True
    assert response["plugin_id"] == PLUGIN
    token = response["rollback_token"]
    assert len(token["token_id"]) >= 8
    assert len(token["idempotency_key"]) >= 8
    assert token["expires_at"]

    target = tmp_path / "install.response.json"
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


def test_missing_adapter_fails_closed(tmp_path):
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=None)
    assert "执行器" in str(exc.value)


def test_rollback_verified_false_is_rejected(tmp_path):
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=RecordingAdapter(), rollback_verified=False)
    assert "rollback_verified" in str(exc.value)


def test_incomplete_rollback_evidence_is_rejected(tmp_path):
    incomplete = dict(EVIDENCE, side_effects_reverted=["subscription", "connection", "handle"])
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=RecordingAdapter(), evidence=incomplete)
    assert "timer" in str(exc.value)


def test_failed_experiment_is_rejected(tmp_path):
    failed = dict(EXPERIMENT, ok=False, loaded=False)
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=RecordingAdapter(), experiment=failed)
    assert "experiment" in str(exc.value)


def test_wrong_mandate_scope_is_rejected(tmp_path):
    wrong = dict(MANDATE, scope="plugin.unload")
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=RecordingAdapter(), mandate=wrong)
    assert "scope" in str(exc.value)


def test_expired_mandate_is_rejected(tmp_path):
    expired = dict(MANDATE, expires_at="2026-11-17T09:00:00+00:00")
    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=RecordingAdapter(), mandate=expired)
    assert "过期" in str(exc.value)


@pytest.mark.parametrize(
    "entry, message",
    [
        (
            {
                "id": "other",
                "status": "approved",
                "risk_level": "low",
                "permitted_profiles": ["sandbox"],
            },
            "白名单",
        ),
        (
            {
                "id": PLUGIN,
                "status": "pending",
                "risk_level": "low",
                "permitted_profiles": ["sandbox"],
            },
            "approved",
        ),
        (
            {
                "id": PLUGIN,
                "status": "approved",
                "risk_level": "forbidden",
                "permitted_profiles": ["sandbox"],
            },
            "forbidden",
        ),
        (
            {
                "id": PLUGIN,
                "status": "approved",
                "risk_level": "low",
                "permitted_profiles": ["web"],
            },
            "permitted",
        ),
    ],
)
def test_whitelist_gates(entry, message, tmp_path):
    with pytest.raises(PluginInstallError) as exc:
        handle_install(
            build_install_request(MANIFEST, MANDATE, REQUEST_ID),
            evidence=EVIDENCE,
            experiment=EXPERIMENT,
            adapter=RecordingAdapter(),
            whitelist_path=_whitelist(tmp_path, entry),
            profile="sandbox",
            now=NOW,
        )
    assert message in str(exc.value)


def test_production_profile_requires_sandbox_and_fail_open(tmp_path):
    entry = {
        "id": PLUGIN,
        "status": "approved",
        "risk_level": "low",
        "sandbox_verified": False,
        "fail_open_verified": False,
        "permitted_profiles": ["headless"],
    }
    with pytest.raises(PluginInstallError) as exc:
        handle_install(
            build_install_request(MANIFEST, MANDATE, REQUEST_ID),
            evidence=EVIDENCE,
            experiment=EXPERIMENT,
            adapter=RecordingAdapter(),
            whitelist_path=_whitelist(tmp_path, entry),
            profile="headless",
            now=NOW,
        )
    assert "sandbox" in str(exc.value)


def test_adapter_failure_is_wrapped(tmp_path):
    class FailingAdapter:
        def install(self, manifest):
            raise RuntimeError("node_modules not writable")

    with pytest.raises(PluginInstallError) as exc:
        _install(tmp_path, adapter=FailingAdapter())
    assert "安装执行失败" in str(exc.value)


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"op": "unload"}, "op"),
        ({"direction": "response"}, "direction"),
        ({"request_id": "x"}, "request_id"),
    ],
)
def test_request_shape_fail_closed(bad, message, tmp_path):
    request = build_install_request(MANIFEST, MANDATE, REQUEST_ID)
    request.update(bad)

    with pytest.raises(PluginInstallError) as exc:
        handle_install(
            request,
            evidence=EVIDENCE,
            experiment=EXPERIMENT,
            adapter=RecordingAdapter(),
            whitelist_path=_whitelist(tmp_path),
            now=NOW,
        )
    assert message in str(exc.value)
