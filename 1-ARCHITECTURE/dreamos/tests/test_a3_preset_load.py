"""GAP-16: preset 一键加载（导出侧已在 P08 完成）

覆盖:
  - dry-run 只出计划，不调用 adapter
  - apply 只安装缺失插件，已安装的跳过
  - 单个插件失败被收集，ok=false
  - preset 被篡改 → 拒绝
  - Mandate scope / 过期 → 拒绝
  - experiment / 回滚证据不全 → 拒绝
  - preset 内插件绕过白名单 → 拒绝
  - 真实 headless preset dry-run（读取 /tmp 不存在则跳过）
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.capability.preset_export import (  # noqa: E402
    _compute_hash,
    build_preset,
)
from dreamos.core.capability.preset_load import (  # noqa: E402
    PresetLoadError,
    load_preset,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
MANDATE = {
    "mandate_id": "mand-001",
    "granted_by": "user",
    "scope": "plugin.install",
    "expires_at": "2026-11-18T00:00:00+00:00",
}
EVIDENCE = {
    "ok": True,
    "unloaded": True,
    "side_effects_reverted": ["subscription", "connection", "handle", "timer"],
}
EXPERIMENT = {"ok": True, "loaded": True, "disk_writes": 0}


class RecordingAdapter:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def install(self, manifest):
        pid = manifest["plugin_id"]
        if pid in self.fail:
            raise RuntimeError(f"boom:{pid}")
        self.calls.append(pid)


def _whitelist(tmp_path, ids):
    path = tmp_path / "plugin_whitelist.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": pid,
                        "status": "approved",
                        "risk_level": "low",
                        "permitted_profiles": ["sandbox"],
                    }
                    for pid in ids
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def _graph(*ids):
    return {
        "plugins": [
            {"plugin_id": pid, "version": "0.1.0", "source": f"file:{pid}", "dependencies": []}
            for pid in ids
        ]
    }


def _preset(tmp_path, ids=("p-a", "p-b"), installed=("p-a",)):
    wl = _whitelist(tmp_path, ids)
    return (
        build_preset(_graph(*ids), name="meta-main", profile="sandbox", whitelist_path=wl, now=NOW),
        wl,
    )


def _load(tmp_path, preset, wl, *, adapter=None, apply=False, mandate=None):
    return load_preset(
        preset,
        mandate=mandate or MANDATE,
        evidence=EVIDENCE,
        experiment=EXPERIMENT,
        adapter=adapter,
        profile="sandbox",
        whitelist_path=wl,
        installed={"p-a"},
        apply=apply,
        now=NOW,
    )


def test_dry_run_plans_without_adapter(tmp_path):
    preset, wl = _preset(tmp_path)
    report = _load(tmp_path, preset, wl, adapter=None, apply=False)

    assert report["ok"] is True
    assert report["applied"] is False
    assert [p["plugin_id"] for p in report["to_install"]] == ["p-b"]
    assert [p["plugin_id"] for p in report["already_installed"]] == ["p-a"]


def test_apply_installs_only_missing(tmp_path):
    preset, wl = _preset(tmp_path)
    adapter = RecordingAdapter()
    report = _load(tmp_path, preset, wl, adapter=adapter, apply=True)

    assert report["ok"] is True
    assert adapter.calls == ["p-b"]
    assert report["installed"] == ["p-b"]


def test_apply_collects_failures(tmp_path):
    preset, wl = _preset(tmp_path)
    adapter = RecordingAdapter(fail={"p-b"})
    report = _load(tmp_path, preset, wl, adapter=adapter, apply=True)

    assert report["ok"] is False
    assert report["failed"][0]["plugin_id"] == "p-b"
    assert "boom" in report["failed"][0]["error"]


def test_tampered_preset_is_rejected(tmp_path):
    preset, wl = _preset(tmp_path)
    preset["plugins"][0]["version"] = "9.9.9"

    with pytest.raises(PresetLoadError) as exc:
        _load(tmp_path, preset, wl)
    assert "hash" in str(exc.value)


def test_expired_mandate_is_rejected(tmp_path):
    preset, wl = _preset(tmp_path)
    expired = dict(MANDATE, expires_at="2026-11-17T09:00:00+00:00")

    with pytest.raises(PresetLoadError) as exc:
        _load(tmp_path, preset, wl, mandate=expired)
    assert "过期" in str(exc.value)


def test_incomplete_evidence_is_rejected(tmp_path):
    preset, wl = _preset(tmp_path)
    with pytest.raises(PresetLoadError) as exc:
        load_preset(
            preset,
            mandate=MANDATE,
            evidence={"ok": True, "unloaded": True, "side_effects_reverted": ["timer"]},
            experiment=EXPERIMENT,
            adapter=RecordingAdapter(),
            profile="sandbox",
            whitelist_path=wl,
            installed=set(),
            apply=True,
            now=NOW,
        )
    assert "回滚证据" in str(exc.value)


def test_preset_plugin_outside_whitelist_is_rejected(tmp_path):
    preset, wl = _preset(tmp_path, ids=("p-a", "p-b"))
    # 伪造一个白名单外插件并重算 hash，模拟「preset 夹带私货」
    preset["plugins"].append(
        {"plugin_id": "p-evil", "version": "0.1.0", "source": "file:p-evil", "dependencies": []}
    )
    preset["preset_hash"] = _compute_hash(preset["name"], preset["version"], preset["plugins"])

    with pytest.raises(PresetLoadError) as exc:
        _load(tmp_path, preset, wl, adapter=RecordingAdapter(), apply=True)
    assert "白名单" in str(exc.value)


def test_real_headless_preset_dry_run(tmp_path):
    real = Path(__file__).parent / "fixtures" / "preset_headless.json"
    if not real.exists():
        pytest.skip("无真实 preset 样本（fixtures/preset_headless.json）")
    preset = json.loads(real.read_text(encoding="utf-8"))
    wl = Path(BASE).parent / "53-DSH插件模块" / "plugin_whitelist.yaml"

    report = load_preset(
        preset,
        mandate=MANDATE,
        evidence=EVIDENCE,
        experiment=EXPERIMENT,
        adapter=None,
        profile="headless",
        whitelist_path=wl,
        installed={p["plugin_id"] for p in preset["plugins"]},
        apply=False,
        now=NOW,
    )
    assert report["ok"] is True
    assert report["applied"] is False
