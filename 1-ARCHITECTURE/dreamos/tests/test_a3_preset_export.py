"""P08: preset 导出（GAP-16 最后一项）

覆盖:
  - 插件按 plugin_id 排序，hash 与输入顺序无关
  - generated_at 不参与 hash（同内容不同时间 → 同 hash）
  - 未登记 / 未批准 / forbidden / profile 不允许 → 进 skipped，不进 plugins
  - 版本变化 → hash 变化
  - verify_preset 能发现篡改与未排序
  - export 落盘后可 round-trip 校验
  - 真实 headless 图导出（含 skipped 统计）
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

from dreamos.core.capability.preset_export import (  # noqa: E402
    PresetError,
    build_preset,
    export_preset,
    verify_preset,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def _graph(plugins: list) -> dict:
    return {"plugins": plugins}


def _plugin(pid: str, version: str = "0.1.0") -> dict:
    return {
        "plugin_id": pid,
        "version": version,
        "source": f"file:packages/{pid}",
        "dependencies": [],
    }


def _whitelist(tmp_path: Path, entries: list) -> Path:
    path = tmp_path / "plugin_whitelist.yaml"
    path.write_text(yaml.safe_dump({"entries": entries}, allow_unicode=True), encoding="utf-8")
    return path


def _entry(pid: str, *, status="approved", risk="low", profiles=("sandbox", "headless")):
    return {
        "id": pid,
        "status": status,
        "risk_level": risk,
        "permitted_profiles": list(profiles),
    }


def _build(tmp_path, graph, *, profile="headless", now=NOW, name="meta-main"):
    wl = _whitelist(
        tmp_path,
        [
            _entry("p-a"),
            _entry("p-b"),
            _entry("p-forbidden", risk="forbidden"),
            _entry("p-pending", status="pending"),
            _entry("p-sandbox-only", profiles=("sandbox",)),
        ],
    )
    return build_preset(graph, name=name, profile=profile, whitelist_path=wl, now=now)


def test_plugins_sorted_and_hash_is_order_independent(tmp_path):
    graph = _graph([_plugin("p-b"), _plugin("p-a")])
    first = _build(tmp_path, graph)
    second = _build(tmp_path, _graph([_plugin("p-a"), _plugin("p-b")]))

    assert [p["plugin_id"] for p in first["plugins"]] == ["p-a", "p-b"]
    assert first["preset_hash"] == second["preset_hash"]


def test_generated_at_does_not_affect_hash(tmp_path):
    graph = _graph([_plugin("p-a")])
    first = _build(tmp_path, graph, now=NOW)
    second = _build(tmp_path, graph, now=datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc))

    assert first["generated_at"] != second["generated_at"]
    assert first["preset_hash"] == second["preset_hash"]


def test_non_deployable_plugins_are_skipped(tmp_path):
    graph = _graph(
        [
            _plugin("p-a"),
            _plugin("p-forbidden"),
            _plugin("p-pending"),
            _plugin("p-sandbox-only"),
            _plugin("p-unknown"),
        ]
    )
    preset = _build(tmp_path, graph)

    assert [p["plugin_id"] for p in preset["plugins"]] == ["p-a"]
    reasons = {item["plugin_id"]: item["reason"] for item in preset["skipped"]}
    assert reasons == {
        "p-forbidden": "forbidden",
        "p-pending": "not_approved",
        "p-sandbox-only": "profile_not_permitted",
        "p-unknown": "unregistered",
    }


def test_version_change_changes_hash(tmp_path):
    first = _build(tmp_path, _graph([_plugin("p-a", "0.1.0")]))
    second = _build(tmp_path, _graph([_plugin("p-a", "0.2.0")]))
    assert first["preset_hash"] != second["preset_hash"]


def test_verify_detects_tampering(tmp_path):
    preset = _build(tmp_path, _graph([_plugin("p-a")]))
    preset["plugins"][0]["version"] = "9.9.9"

    with pytest.raises(PresetError) as exc:
        verify_preset(preset)
    assert "hash" in str(exc.value)


def test_verify_requires_sorted_plugins(tmp_path):
    preset = _build(tmp_path, _graph([_plugin("p-a"), _plugin("p-b")]))
    preset["plugins"].reverse()
    # 重算 hash 以隔离「排序」检查
    from dreamos.core.capability.preset_export import _compute_hash  # noqa: PLC0415

    preset["preset_hash"] = _compute_hash(preset["name"], preset["version"], preset["plugins"])

    with pytest.raises(PresetError) as exc:
        verify_preset(preset)
    assert "排序" in str(exc.value)


def test_export_roundtrip(tmp_path):
    preset = _build(tmp_path, _graph([_plugin("p-a")]))
    out = tmp_path / "preset.json"
    export_preset(preset, out)

    loaded = json.loads(out.read_text(encoding="utf-8"))
    verify_preset(loaded)
    assert loaded["preset_hash"] == preset["preset_hash"]


def test_real_headless_export(tmp_path):
    out = tmp_path / "headless_preset.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dreamos.core.capability.preset_export",
            "--profile",
            "headless",
            "--name",
            "meta-main",
            "--out",
            str(out),
        ],
        cwd=str(BASE),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    preset = json.loads(out.read_text(encoding="utf-8"))
    verify_preset(preset)
    assert preset["plugins"], "headless 至少应导出一个白名单插件"
    ids = [item["plugin_id"] for item in preset["plugins"]]
    assert ids == sorted(ids)
    assert isinstance(preset["skipped"], list)


def test_missing_whitelist_fails_closed(tmp_path):
    with pytest.raises(PresetError) as exc:
        build_preset(
            _graph([_plugin("p-a")]),
            name="meta-main",
            profile="headless",
            whitelist_path=tmp_path / "nope.yaml",
            now=NOW,
        )
    assert "白名单" in str(exc.value)


def test_empty_name_is_rejected(tmp_path):
    wl = _whitelist(tmp_path, [_entry("p-a")])
    with pytest.raises(PresetError) as exc:
        build_preset(
            _graph([_plugin("p-a")]),
            name="",
            profile="headless",
            whitelist_path=wl,
            now=NOW,
        )
    assert "name" in str(exc.value)
