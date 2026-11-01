# -*- coding: utf-8 -*-
"""
test_sandbox.py — P4-3 gVisor 沙箱运行配置
===========================================
验收（PLAN P4-3 / SPEC §14.3）：
- 逃逸用例被拦：特权容器 / Docker socket / 宿主根挂载 / host 网络 / root 用户 /
  未登记挂载一律拒绝
- 命令构造硬化：runsc + 只读 rootfs + 非 root + cap-drop ALL + no-new-privileges +
  cpu/mem/pids 配额 + 网络 none + tmpfs
- strict 模式下 runsc 缺失 fail-closed；`evalctl sandbox --check` 退出码 0/4
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.sandbox import (  # noqa: E402
    ExecutionRequest,
    SandboxError,
    SandboxPolicy,
    SandboxRequest,
    build_command,
    check_runtime,
    validate_request,
)

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = MODULE_ROOT / "config" / "sandbox.yaml"


@pytest.fixture
def policy() -> SandboxPolicy:
    return SandboxPolicy.load(CONFIG)


def make_request(**overrides) -> ExecutionRequest:
    base = {
        "image": "eval/engineering-runner:1.0",
        "command": ["python", "-m", "pytest"],
    }
    base.update(overrides)
    return ExecutionRequest(**base)


def test_policy_loads_from_yaml(policy: SandboxPolicy):
    assert policy.runtime == "gvisor"
    assert policy.strict is True
    assert policy.network == "none"
    assert policy.read_only_rootfs is True
    assert policy.run_as_non_root is True
    assert policy.cpu == 1.0
    assert policy.memory == "2g"
    assert policy.pids == 256
    assert policy.user == "65534:65534"


def test_policy_missing_file_uses_strict_defaults(tmp_path: Path):
    fallback = SandboxPolicy.load(tmp_path / "absent.yaml")
    assert fallback.runtime == "gvisor"
    assert fallback.strict is True
    assert fallback.network == "none"


def test_safe_request_has_no_violations(policy: SandboxPolicy):
    assert validate_request(make_request(), policy) == []


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"privileged": True}, "privileged"),
        ({"network_mode": "host"}, "network"),
        ({"mounts": [("/var/run/docker.sock", "/var/run/docker.sock", True)]}, "docker_socket"),
        ({"mounts": [("/", "/host", True)]}, "host_root"),
        ({"mounts": [("/proc", "/proc", True)]}, "sensitive_path"),
        ({"user": "0"}, "non_root"),
        ({"user": "root"}, "non_root"),
        ({"mounts": [("/Users/evil", "/work", False)]}, "mount_not_allowed"),
        ({"image": ""}, "missing_image"),
        ({"command": []}, "missing_command"),
    ],
)
def test_escape_cases_blocked(policy: SandboxPolicy, overrides: dict, reason: str):
    violations = validate_request(make_request(**overrides), policy)
    assert any(reason in v for v in violations), violations


def test_allowlisted_workdir_mount_accepted(policy: SandboxPolicy):
    request = make_request(
        mounts=[("/tmp/eval-work/obj-01", "/work/obj-01", True)],
    )
    assert validate_request(request, policy) == []


def test_build_command_hardening_flags(policy: SandboxPolicy, monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: f"/usr/local/bin/{name}")
    cmd = build_command(make_request(), policy)
    joined = " ".join(cmd)

    assert cmd[:2] == ["docker", "run"]
    assert "--runtime=runsc" in cmd
    assert "--read-only" in cmd
    assert "--network=none" in cmd
    assert "--user=65534:65534" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges" in cmd
    assert "--cpus=1.0" in cmd
    assert "--memory=2g" in cmd
    assert "--pids-limit=256" in cmd
    assert "--tmpfs" in joined
    assert cmd[-4:] == ["eval/engineering-runner:1.0", "python", "-m", "pytest"]


def test_build_command_mounts_readonly(policy: SandboxPolicy, monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: f"/usr/local/bin/{name}")
    request = make_request(mounts=[("/tmp/eval-work/obj-01", "/work/obj-01", True)])
    cmd = build_command(request, policy)
    mount_arg = next(part for part in cmd if part.startswith("type=bind"))
    assert "source=/tmp/eval-work/obj-01" in mount_arg
    assert "target=/work/obj-01" in mount_arg
    assert "readonly" in mount_arg


def test_build_command_rejects_violations(policy: SandboxPolicy, monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: f"/usr/local/bin/{name}")
    with pytest.raises(SandboxError) as exc:
        build_command(make_request(privileged=True), policy)
    assert "privileged" in str(exc.value)


def test_build_command_strict_gvisor_missing_fails_closed(policy: SandboxPolicy, monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: None)
    with pytest.raises(SandboxError) as exc:
        build_command(make_request(), policy)
    assert "runtime_unavailable" in str(exc.value)


def test_build_command_non_strict_allows_fallback(policy: SandboxPolicy, monkeypatch):
    relaxed = SandboxPolicy(
        runtime="gvisor",
        strict=False,
        network="none",
        read_only_rootfs=True,
        run_as_non_root=True,
        cpu=1.0,
        memory="2g",
        pids=256,
        user="65534:65534",
        mount_allowlist=["/tmp/eval-work"],
    )
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: None)
    cmd = build_command(make_request(), relaxed)
    assert "--runtime=runsc" not in cmd


def test_check_runtime_ok_when_runsc_present(monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: f"/usr/local/bin/{name}")
    result = check_runtime(SandboxPolicy.load(CONFIG))
    assert result["ok"] is True
    assert result["runtime"] == "gvisor"
    assert result["available"] is True
    assert result["reasons"] == []


def test_check_runtime_reports_missing_runsc(monkeypatch):
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: None)
    result = check_runtime(SandboxPolicy.load(CONFIG))
    assert result["ok"] is False
    assert any("runsc" in r for r in result["reasons"])


def test_check_runtime_rejects_none_runtime_in_strict():
    strict_none = SandboxPolicy(
        runtime="none",
        strict=True,
        network="none",
        read_only_rootfs=True,
        run_as_non_root=True,
        cpu=1.0,
        memory="2g",
        pids=256,
        user="65534:65534",
        mount_allowlist=[],
    )
    result = check_runtime(strict_none)
    assert result["ok"] is False
    assert any("none" in r for r in result["reasons"])


def test_runtime_docker_mode_checks_docker_binary(monkeypatch):
    docker_policy = SandboxPolicy(
        runtime="docker",
        strict=True,
        network="none",
        read_only_rootfs=True,
        run_as_non_root=True,
        cpu=1.0,
        memory="2g",
        pids=256,
        user="65534:65534",
        mount_allowlist=["/tmp/eval-work"],
    )
    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: "/usr/bin/docker")
    assert check_runtime(docker_policy)["ok"] is True
    cmd = build_command(make_request(), docker_policy)
    assert "--runtime=runsc" not in cmd


def test_unknown_runtime_rejected():
    with pytest.raises(SandboxError) as exc:
        check_runtime(
            SandboxPolicy(
                runtime="firecracker",
                strict=False,
                network="none",
                read_only_rootfs=True,
                run_as_non_root=True,
                cpu=1.0,
                memory="2g",
                pids=256,
                user="65534:65534",
                mount_allowlist=[],
            )
        )
    assert "unknown_runtime" in str(exc.value)


# ---------- CLI ----------


def test_cli_sandbox_check_ok(monkeypatch):
    from api.cli import main

    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: f"/usr/local/bin/{name}")
    out = io.StringIO()
    assert main(["sandbox", "--check"], out=out) == 0
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True


def test_cli_sandbox_check_missing_runtime_is_error(monkeypatch):
    from api.cli import EXIT_ERROR, main

    monkeypatch.setattr("core.sandbox.shutil.which", lambda name: None)
    out = io.StringIO()
    assert main(["sandbox", "--check"], out=out) == EXIT_ERROR
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False


def test_cli_sandbox_unknown_mode_is_error(tmp_path: Path, monkeypatch):
    from api.cli import EXIT_ERROR, main

    config = tmp_path / "sandbox.yaml"
    config.write_text("runtime: firecracker\nstrict: false\n", encoding="utf-8")
    monkeypatch.setenv("EVAL_SANDBOX_CONFIG", str(config))
    out = io.StringIO()
    assert main(["sandbox", "--check"], out=out) == EXIT_ERROR
    assert "error" in json.loads(out.getvalue())


# ---------- 配额 / 策略数值 ----------


def test_policy_accepts_network_allowlist_mode():
    allowlist = SandboxPolicy(
        runtime="gvisor",
        strict=True,
        network="allowlist",
        read_only_rootfs=True,
        run_as_non_root=True,
        cpu=1.0,
        memory="2g",
        pids=256,
        user="65534:65534",
        mount_allowlist=[],
        network_allowlist=["api.internal:443"],
    )
    assert allowlist.network_allowlist == ["api.internal:443"]


def test_sandbox_request_is_exported():
    """对外契约：SandboxRequest 协议可被评测器实现使用（P2-7 接入点）。"""
    assert hasattr(SandboxRequest, "image")
    assert hasattr(SandboxRequest, "command")
