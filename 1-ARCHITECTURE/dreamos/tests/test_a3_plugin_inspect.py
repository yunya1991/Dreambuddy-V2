"""A3-1: 只读插件图 inspect（IF-6 / ADR-10 前置）

覆盖:
  - inspect.response 满足 `plugin_extension.schema.json`（经 56 官方校验器 `--plugin` 0 violation）
  - 从 DSH profile + 本地插件包静态提取：依赖边 / 事件通道 / 能力面
  - `file:` 指向不存在的包 → graph.unresolved（仍 acyclic=true）
  - 依赖环 fail-closed（契约只允许 acyclic=true，不得伪装成功）
  - request 形状校验（op/direction/request_id）
  - 只读：不创建/修改任何文件
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

from dreamos.core.capability.plugin_inspect import (  # noqa: E402
    PluginInspectError,
    build_inspect_request,
    handle_inspect,
    inspect_plugins,
)

REQUEST_ID = "inspect-test-001"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_pkg(root: Path, name: str, *, version="0.1.0", deps=None, source="") -> Path:
    pkg = root / name
    _write_json(
        pkg / "package.json",
        {
            "name": name,
            "version": version,
            "dependencies": deps or {},
        },
    )
    if source:
        main = pkg / "lib" / "index.js"
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_text(source, encoding="utf-8")
    return pkg


def _make_profile(home: Path, profile: str, deps: dict, bundles=None) -> None:
    _write_json(
        home / "profiles" / profile / "package.json",
        {
            "name": f"dsh-profile-{profile}",
            "dependencies": deps,
            "dsh": {"profile": {"bundles": bundles or ["@deepseek-ai/dsh-base"]}},
        },
    )


@pytest.fixture()
def fake_runtime(tmp_path):
    packages = tmp_path / "packages"
    home = tmp_path / "home"

    plugin_a_source = """
import { defineTool } from "@deepseek-ai/dsh-tools";
export function apply(ctx) {
  ctx.on("agent/pre-step", async () => {});
  ctx.on("agent/pre-step", async () => {});
  ctx.emit("demo/done", {});
  ctx.tools.register(defineTool({ name: "a_scan", description: "scan" }));
}
"""
    _make_pkg(packages, "local-a", deps={"local-b": "*"}, source=plugin_a_source)
    _make_pkg(packages, "local-b", version="0.2.0")

    _make_profile(
        home,
        "alpha",
        {
            "local-a": "file:../../../packages/local-a",
            "local-b": "file:../../../packages/local-b",
        },
    )
    return home, packages


def test_inspect_response_passes_official_contract(tmp_path, fake_runtime):
    home, packages = fake_runtime
    response = inspect_plugins("alpha", home=home, packages_dir=packages, request_id=REQUEST_ID)

    assert response["op"] == "inspect"
    assert response["direction"] == "response"
    assert response["request_id"] == REQUEST_ID
    assert response["ok"] is True
    assert response["graph"]["acyclic"] is True
    assert response["graph"]["unresolved"] == []

    plugins = {item["plugin_id"]: item for item in response["plugins"]}
    assert sorted(plugins) == ["local-a", "local-b"]
    assert plugins["local-a"]["version"] == "0.1.0"
    assert plugins["local-a"]["dependencies"] == ["local-b"]
    assert plugins["local-a"]["event_channels"]["subscribe"] == ["agent/pre-step"]
    assert plugins["local-a"]["event_channels"]["publish"] == ["demo/done"]
    assert plugins["local-a"]["capabilities"] == ["a_scan"]

    target = tmp_path / "inspect.response.json"
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


def test_missing_file_dependency_is_unresolved(tmp_path):
    home = tmp_path / "home"
    packages = tmp_path / "packages"
    _make_profile(
        home,
        "alpha",
        {
            "local-a": "file:../../../packages/local-a",
            "ghost": "file:../../../packages/ghost",
        },
    )
    _make_pkg(packages, "local-a")

    response = inspect_plugins("alpha", home=home, packages_dir=packages, request_id=REQUEST_ID)

    assert response["graph"]["acyclic"] is True
    assert response["graph"]["unresolved"] == ["ghost"]
    assert [item["plugin_id"] for item in response["plugins"]] == ["local-a"]


def test_dependency_cycle_fails_closed(tmp_path):
    home = tmp_path / "home"
    packages = tmp_path / "packages"
    _make_pkg(packages, "local-a", deps={"local-b": "*"})
    _make_pkg(packages, "local-b", deps={"local-a": "*"})
    _make_profile(
        home,
        "alpha",
        {
            "local-a": "file:../../../packages/local-a",
            "local-b": "file:../../../packages/local-b",
        },
    )

    with pytest.raises(PluginInspectError) as exc:
        inspect_plugins("alpha", home=home, packages_dir=packages, request_id=REQUEST_ID)
    assert "依赖环" in str(exc.value)


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
    request = build_inspect_request(REQUEST_ID)
    request.update(bad)

    with pytest.raises(PluginInspectError) as exc:
        handle_inspect(request, profile="alpha", home=home, packages_dir=packages)
    assert message in str(exc.value)


def test_handle_inspect_accepts_valid_request(fake_runtime):
    home, packages = fake_runtime
    request = build_inspect_request(REQUEST_ID)

    response = handle_inspect(request, profile="alpha", home=home, packages_dir=packages)
    assert response["request_id"] == request["request_id"]
    assert response["ok"] is True


def test_missing_profile_fails_closed(tmp_path):
    with pytest.raises(PluginInspectError) as exc:
        inspect_plugins(
            "no-such-profile",
            home=tmp_path / "home",
            packages_dir=tmp_path / "packages",
            request_id=REQUEST_ID,
        )
    assert "profile" in str(exc.value)


def test_inspect_is_read_only(fake_runtime):
    home, packages = fake_runtime

    def snapshot(root: Path) -> list:
        return sorted(
            (str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()
        )

    before = snapshot(home), snapshot(packages)
    inspect_plugins("alpha", home=home, packages_dir=packages, request_id=REQUEST_ID)
    after = snapshot(home), snapshot(packages)

    assert before == after
