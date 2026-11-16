"""A3 运行时 adapter 接缝（DSHCommandAdapter）

覆盖:
  - 命令计划：本地包解析为 `file:../../packages/<id>`，未知包按 registry 名
  - apply=False → dry-run 拒绝执行（不伪造安装）
  - runner 失败 / 超时 → AdapterError
  - 命令成功但 profile 未登记 → AdapterError（不信任退出码）
  - unload 同样校验 profile 已移除
  - 快照采集：未配置 probe → 拒绝；配置后解析 JSON
  - 端到端：A3-4 install 签发 token → 模拟 unload → A3-3 四类验收通过
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
sys.path.insert(0, str(BASE))

from dreamos.core.capability.plugin_install import (  # noqa: E402
    build_install_request,
    handle_install,
)
from dreamos.core.capability.plugin_runtime_adapter import (  # noqa: E402
    AdapterError,
    CommandResult,
    DSHCommandAdapter,
)
from dreamos.core.capability.plugin_unload import unload_plugin  # noqa: E402

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
PLUGIN = "p-new"
MANIFEST = {
    "plugin_id": PLUGIN,
    "version": "0.1.0",
    "entry": "lib/index.js",
    "permissions": ["fs.read"],
}
EVIDENCE = {
    "ok": True,
    "unloaded": True,
    "side_effects_reverted": ["subscription", "connection", "handle", "timer"],
}
EXPERIMENT = {"ok": True, "loaded": True, "disk_writes": 0}
TOKEN = {
    "token_id": "rbk-p-new-20261117100000",
    "expires_at": "2026-11-18T10:00:00+00:00",
    "idempotency_key": "idem-p-new-20261117100000",
}
UNLOAD_MANDATE = {
    "mandate_id": "mand-u-001",
    "granted_by": "user",
    "scope": "plugin.unload",
    "expires_at": "2026-11-18T00:00:00+00:00",
}
INSTALL_MANDATE = {
    "mandate_id": "mand-i-001",
    "granted_by": "user",
    "scope": "plugin.install",
    "expires_at": "2026-11-18T00:00:00+00:00",
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _runtime(tmp_path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    packages = tmp_path / "packages"
    _write_json(
        packages / PLUGIN / "package.json",
        {"name": PLUGIN, "version": "0.1.0", "dependencies": {}},
    )
    _write_json(
        home / "profiles" / "sandbox" / "package.json",
        {"name": "dsh-profile-sandbox", "dependencies": {}},
    )
    return home, packages


def _profile_deps(home: Path) -> dict:
    doc = json.loads((home / "profiles" / "sandbox" / "package.json").read_text(encoding="utf-8"))
    return doc.get("dependencies") or {}


class FakeDSH:
    """模拟 dsh plugin add/remove：真实改动临时 profile，不碰系统。"""

    def __init__(self, home: Path, packages: Path, *, mutate: bool = True):
        self.home = home
        self.packages = packages
        self.mutate = mutate
        self.calls = []
        self.snapshot = {"plugins": ["p-host"], "effects": {}}

    def run(self, argv, timeout):
        self.calls.append(list(argv))
        action = argv[1:3]
        if action == ["plugin", "add"] and len(argv) >= 5:
            spec = argv[3]
            if self.mutate:
                path = self.home / "profiles" / "sandbox" / "package.json"
                doc = json.loads(path.read_text(encoding="utf-8"))
                doc.setdefault("dependencies", {})[PLUGIN] = spec
                _write_json(path, doc)
            return CommandResult(0, "added", "")
        if action == ["plugin", "remove"] and len(argv) >= 4:
            if self.mutate:
                path = self.home / "profiles" / "sandbox" / "package.json"
                doc = json.loads(path.read_text(encoding="utf-8"))
                (doc.get("dependencies") or {}).pop(argv[3], None)
                _write_json(path, doc)
            return CommandResult(0, "removed", "")
        if action == ["plugin", "snapshot"]:
            return CommandResult(0, json.dumps(self.snapshot), "")
        return CommandResult(1, "", "unexpected argv")


def _adapter(home, packages, runner, *, apply=True, probe=True) -> DSHCommandAdapter:
    return DSHCommandAdapter(
        profile="sandbox",
        home=home,
        packages_dir=packages,
        runner=runner,
        apply=apply,
        snapshot_command=["dsh", "plugin", "snapshot", "--profile", "sandbox"] if probe else None,
        timeout=5,
    )


def test_plan_install_uses_file_spec_for_local_package(tmp_path):
    home, packages = _runtime(tmp_path)
    adapter = _adapter(home, packages, FakeDSH(home, packages))

    argv = adapter.plan_install(MANIFEST)
    assert argv == [
        "dsh",
        "plugin",
        "add",
        f"file:{(packages / PLUGIN).resolve()}",
        "--profile",
        "sandbox",
    ]


def test_plan_install_uses_registry_name_for_unknown_package(tmp_path):
    home, packages = _runtime(tmp_path)
    adapter = _adapter(home, packages, FakeDSH(home, packages))

    argv = adapter.plan_install({"plugin_id": "dreambuddy-remote"})
    assert argv[3] == "dreambuddy-remote"


def test_plan_install_matches_local_package_by_manifest_name(tmp_path):
    home, packages = _runtime(tmp_path)
    _write_json(
        packages / "cordis-plugin-renamed" / "package.json",
        {"name": "dreambuddy-renamed", "version": "0.1.0", "dependencies": {}},
    )
    adapter = _adapter(home, packages, FakeDSH(home, packages))

    argv = adapter.plan_install({"plugin_id": "dreambuddy-renamed"})
    assert argv[3] == f"file:{(packages / 'cordis-plugin-renamed').resolve()}"


def test_dry_run_refuses_to_execute(tmp_path):
    home, packages = _runtime(tmp_path)
    runner = FakeDSH(home, packages)
    adapter = _adapter(home, packages, runner, apply=False)

    with pytest.raises(AdapterError) as exc:
        adapter.install(MANIFEST)
    assert "dry-run" in str(exc.value)
    assert runner.calls == []


def test_install_failure_from_runner(tmp_path):
    home, packages = _runtime(tmp_path)
    adapter = _adapter(home, packages, FakeDSH(home, packages, mutate=False))

    with pytest.raises(AdapterError) as exc:
        adapter.install(MANIFEST)
    assert "未登记" in str(exc.value)


def test_install_success_registers_profile(tmp_path):
    home, packages = _runtime(tmp_path)
    adapter = _adapter(home, packages, FakeDSH(home, packages))

    adapter.install(MANIFEST)
    assert _profile_deps(home)[PLUGIN] == f"file:{(packages / PLUGIN).resolve()}"


def test_unload_removes_from_profile(tmp_path):
    home, packages = _runtime(tmp_path)
    runner = FakeDSH(home, packages)
    adapter = _adapter(home, packages, runner)
    adapter.install(MANIFEST)

    adapter.remove(PLUGIN)
    assert PLUGIN not in _profile_deps(home)
    assert runner.calls[-1] == ["dsh", "plugin", "remove", PLUGIN, "--profile", "sandbox"]


def test_snapshot_requires_probe(tmp_path):
    home, packages = _runtime(tmp_path)
    adapter = _adapter(home, packages, FakeDSH(home, packages), probe=False)

    with pytest.raises(AdapterError) as exc:
        adapter.capture_snapshot()
    assert "probe" in str(exc.value)


def test_timeout_is_wrapped(tmp_path):
    home, packages = _runtime(tmp_path)

    class SlowRunner:
        def run(self, argv, timeout):
            raise subprocess.TimeoutExpired(argv, timeout)

    adapter = _adapter(home, packages, SlowRunner())

    with pytest.raises(AdapterError) as exc:
        adapter.install(MANIFEST)
    assert "超时" in str(exc.value)


def test_end_to_end_install_then_verified_unload(tmp_path):
    home, packages = _runtime(tmp_path)
    runner = FakeDSH(home, packages)
    adapter = _adapter(home, packages, runner)

    whitelist = tmp_path / "plugin_whitelist.yaml"
    whitelist.write_text(
        yaml.safe_dump(
            {
                "policies": {"production_profiles": ["headless"]},
                "entries": [
                    {
                        "id": PLUGIN,
                        "status": "approved",
                        "risk_level": "low",
                        "permitted_profiles": ["sandbox"],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    runner.snapshot = {
        "plugins": ["p-host", PLUGIN],
        "effects": {
            "subscription": [{"id": "sub:p-new", "owner": PLUGIN}],
            "connection": [{"id": "conn:p-new", "owner": PLUGIN}],
            "handle": [{"id": "fd:p-new", "owner": PLUGIN}],
            "timer": [{"id": "timer:p-new", "owner": PLUGIN}],
        },
    }

    response = handle_install(
        build_install_request(MANIFEST, INSTALL_MANDATE, "install-e2e-001"),
        evidence=EVIDENCE,
        experiment=EXPERIMENT,
        adapter=adapter,
        whitelist_path=whitelist,
        profile="sandbox",
        now=NOW,
    )
    assert response["installed"] is True
    token = response["rollback_token"]
    assert token["token_id"].startswith("rbk-p-new-")

    # 安装后、卸载前：插件已在图中并带四类副作用
    before = adapter.capture_snapshot()

    adapter.remove(PLUGIN)
    runner.snapshot = {"plugins": ["p-host"], "effects": {}}
    after = adapter.capture_snapshot()

    verdict = unload_plugin(
        PLUGIN,
        rollback_token=token,
        mandate=UNLOAD_MANDATE,
        before=before,
        after=after,
        request_id="unload-e2e-001",
        now=NOW,
    )
    assert verdict["ok"] is True
    assert verdict["unloaded"] is True
    assert verdict["side_effects_reverted"] == [
        "subscription",
        "connection",
        "handle",
        "timer",
    ]
