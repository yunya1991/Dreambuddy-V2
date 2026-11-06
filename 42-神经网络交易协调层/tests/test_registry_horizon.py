#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-02：registry.yaml horizon 必填 + 校验器契约测试。

验收口径（49-SPEC §13.5 P1-02）：
- registry.yaml 每个 subsystem 必须声明 horizon，且取值合法（hours|days|weeks，
  对齐 SignalSchema v1 §2.1 枚举）
- registry_validator.validate_registry() 对缺 horizon / 非法 horizon 报错
- 校验器对合法 registry 返回空错误列表
- 校验器对既有必填字段（name/publisher/publish/enabled）缺失也报错
- CLI：python3 registry_validator.py 对当前仓库 registry.yaml 退出码为 0
"""

import os
import subprocess
import sys

import pytest
import yaml

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

_REGISTRY_PATH = os.path.join(_42_ROOT, "registry.yaml")

_VALID_HORIZONS = ("hours", "days", "weeks")


def _load_registry(path=_REGISTRY_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 1. 当前 registry.yaml：所有 enabled 子系统必须声明合法 horizon ──
def test_registry_all_subsystems_have_valid_horizon():
    reg = _load_registry()
    subs = reg.get("subsystems") or []
    assert subs, "registry.yaml 必须声明 subsystems"
    for sub in subs:
        name = sub.get("name", "<unnamed>")
        assert "horizon" in sub, "subsystem {} 缺少必填字段 horizon".format(name)
        assert (
            sub["horizon"] in _VALID_HORIZONS
        ), "subsystem {} horizon 非法: {}（合法值 {}）".format(
            name, sub.get("horizon"), _VALID_HORIZONS
        )


# ── 2. 校验器存在且对合法 registry 返回空错误 ──
def test_validator_accepts_valid_registry(tmp_path):
    from registry_validator import validate_registry

    reg = {
        "subsystems": [
            {
                "name": "x",
                "publisher": "adapters/x_adapter.py",
                "publish": ["x_sig"],
                "subscribe": [],
                "horizon": "days",
                "enabled": True,
            }
        ]
    }
    # publisher 路径相对 registry 所在目录解析，需真实存在
    (tmp_path / "adapters").mkdir()
    (tmp_path / "adapters" / "x_adapter.py").write_text("# stub", encoding="utf-8")
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(reg, allow_unicode=True), encoding="utf-8")
    assert validate_registry(str(path)) == []


# ── 3. 缺 horizon → 报错 ──
def test_validator_rejects_missing_horizon(tmp_path):
    from registry_validator import validate_registry

    reg = {
        "subsystems": [
            {
                "name": "x",
                "publisher": "adapters/x_adapter.py",
                "publish": ["x_sig"],
                "enabled": True,
            }
        ]
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(reg, allow_unicode=True), encoding="utf-8")
    errors = validate_registry(str(path))
    assert any("horizon" in e and "x" in e for e in errors), "缺 horizon 必须报错，实际: {}".format(
        errors
    )


# ── 4. 非法 horizon 取值 → 报错 ──
def test_validator_rejects_invalid_horizon(tmp_path):
    from registry_validator import validate_registry

    reg = {
        "subsystems": [
            {
                "name": "x",
                "publisher": "adapters/x_adapter.py",
                "publish": ["x_sig"],
                "enabled": True,
                "horizon": "minutes",
            }
        ]
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(reg, allow_unicode=True), encoding="utf-8")
    errors = validate_registry(str(path))
    assert any("horizon" in e for e in errors), "非法 horizon 取值必须报错，实际: {}".format(errors)


# ── 5. 既有必填字段缺失 → 报错（name/publisher/publish/enabled）──
@pytest.mark.parametrize("missing", ["name", "publisher", "publish", "enabled"])
def test_validator_rejects_missing_required_fields(tmp_path, missing):
    from registry_validator import validate_registry

    sub = {
        "name": "x",
        "publisher": "adapters/x_adapter.py",
        "publish": ["x_sig"],
        "enabled": True,
        "horizon": "hours",
    }
    del sub[missing]
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"subsystems": [sub]}, allow_unicode=True), encoding="utf-8")
    errors = validate_registry(str(path))
    assert any(missing in e for e in errors), "缺 {} 必须报错，实际: {}".format(missing, errors)


# ── 6. CLI：当前仓库 registry.yaml 校验退出码为 0（本地即 CI）──
def test_validator_cli_passes_on_repo_registry():
    proc = subprocess.run(
        [sys.executable, os.path.join(_42_ROOT, "registry_validator.py")],
        capture_output=True,
        text=True,
    )
    assert (
        proc.returncode == 0
    ), "registry_validator.py 对当前 registry.yaml 必须通过，stderr: {}".format(proc.stderr)
