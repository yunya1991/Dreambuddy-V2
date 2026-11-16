"""A3-2: 插件内存/沙箱试跑（IF-6 experiment，ADR-10）

覆盖:
  - 合法 manifest → ok/loaded=true、errors=[]、rollback_ok=true、disk_writes=0
  - 响应经 56 官方校验器 `--plugin` 0 violation
  - 非法 manifest → E_MANIFEST_INVALID
  - 依赖缺失 → E_DEP_MISSING
  - 发布通道与已安装插件冲突 → E_CHANNEL_CONFLICT
  - 申请 exec / fs.write → E_PERMISSION_DENIED（沙箱不落盘）
  - 全程只读：profile / packages 文件零变化
  - request 形状校验（op/direction/request_id）
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from dreamos.core.capability.plugin_experiment import (  # noqa: E402
    PluginExperimentError,
    build_experiment_request,
    experiment_plugin,
    handle_experiment,
)

REQUEST_ID = "experiment-test-001"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_pkg(root: Path, name: str, *, version="0.1.0", deps=None, source="") -> Path:
    pkg = root / name
    _write_json(
        pkg / "package.json",
        {"name": name, "version": version, "dependencies": deps or {}},
    )
    if source:
        main = pkg / "lib" / "index.js"
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_text(source, encoding="utf-8")
    return pkg


def _manifest(**overrides) -> dict:
    data = {
        "plugin_id": "dreambuddy-demo",
        "version": "0.1.0",
        "entry": "lib/index.js",
        "permissions": ["fs.read", "ui"],
        "dependencies": [],
        "event_channels": {"publish": [], "subscribe": []},
    }
    data.update(overrides)
    return data


@pytest.fixture()
def fake_runtime(tmp_path):
    packages = tmp_path / "packages"
    home = tmp_path / "home"

    source = """
export function apply(ctx) {
  ctx.on("agent/pre-step", async () => {});
  ctx.emit("demo/done", {});
}
"""
    _make_pkg(packages, "local-a", deps={}, source=source)
    _write_json(
        home / "profiles" / "alpha" / "package.json",
        {
            "name": "dsh-profile-alpha",
            "dependencies": {"local-a": "file:../../../packages/local-a"},
            "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base"]}},
        },
    )
    return home, packages


def test_valid_manifest_is_loaded_in_memory(tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = experiment_plugin(
        _manifest(),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )

    assert response["op"] == "experiment"
    assert response["direction"] == "response"
    assert response["request_id"] == REQUEST_ID
    assert response["ok"] is True
    assert response["loaded"] is True
    assert response["errors"] == []
    assert response["rollback_ok"] is True
    assert response["disk_writes"] == 0

    target = tmp_path / "experiment.response.json"
    _write_json(target, response)
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


@pytest.mark.parametrize(
    "bad, field",
    [
        ({"plugin_id": "Bad_ID"}, "plugin_id"),
        ({"version": "0.1"}, "version"),
        ({"entry": ""}, "entry"),
        ({"permissions": ["root"]}, "permissions"),
        ({"unknown_key": 1}, "unknown_key"),
    ],
)
def test_invalid_manifest_is_rejected(bad, field, tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = experiment_plugin(
        _manifest(**bad),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )

    assert response["ok"] is False
    assert response["loaded"] is False
    assert response["rollback_ok"] is True
    assert response["disk_writes"] == 0
    assert [item["code"] for item in response["errors"]] == ["E_MANIFEST_INVALID"]
    assert response["errors"][0].get("field") == field


def test_missing_dependency_is_rejected(tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = experiment_plugin(
        _manifest(dependencies=["ghost-plugin"]),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )

    assert response["ok"] is False
    assert "E_DEP_MISSING" in [item["code"] for item in response["errors"]]
    missing = next(item for item in response["errors"] if item["code"] == "E_DEP_MISSING")
    assert "ghost-plugin" in missing["message"]


def test_channel_conflict_with_installed_plugin(tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = experiment_plugin(
        _manifest(event_channels={"publish": ["demo/done"], "subscribe": []}),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )

    assert response["ok"] is False
    conflict = next(item for item in response["errors"] if item["code"] == "E_CHANNEL_CONFLICT")
    assert "demo/done" in conflict["message"]


@pytest.mark.parametrize("perm", ["exec", "fs.write"])
def test_write_or_exec_permission_denied(perm, tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = experiment_plugin(
        _manifest(permissions=["fs.read", perm]),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )

    assert response["ok"] is False
    denied = next(item for item in response["errors"] if item["code"] == "E_PERMISSION_DENIED")
    assert perm in denied["message"]
    assert response["disk_writes"] == 0


def test_experiment_is_read_only(tmp_path, fake_runtime):
    home, packages = fake_runtime

    def snapshot(root: Path) -> list:
        return sorted(
            (str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()
        )

    before = snapshot(home), snapshot(packages)
    experiment_plugin(
        _manifest(),
        profile="alpha",
        home=home,
        packages_dir=packages,
        request_id=REQUEST_ID,
    )
    after = snapshot(home), snapshot(packages)

    assert before == after


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"op": "install"}, "op"),
        ({"direction": "response"}, "direction"),
        ({"request_id": "x"}, "request_id"),
    ],
)
def test_request_shape_fail_closed(bad, message, fake_runtime):
    home, packages = fake_runtime
    request = build_experiment_request(_manifest(), REQUEST_ID)
    request.update(bad)

    with pytest.raises(PluginExperimentError) as exc:
        handle_experiment(request, profile="alpha", home=home, packages_dir=packages)
    assert message in str(exc.value)


def test_handle_experiment_accepts_valid_request(fake_runtime):
    home, packages = fake_runtime
    request = build_experiment_request(_manifest(), REQUEST_ID)

    response = handle_experiment(request, profile="alpha", home=home, packages_dir=packages)
    assert response["request_id"] == request["request_id"]
    assert response["ok"] is True
