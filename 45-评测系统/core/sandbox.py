# -*- coding: utf-8 -*-
"""
sandbox.py — gVisor 沙箱运行配置与逃逸校验（P4-3）
==================================================
职责（PLAN P4-3 / SPEC §14.3）：
- 策略加载：`config/sandbox.yaml`（runtime/strict/cpu/memory/pids/timeout/network/
  read_only_rootfs/run_as_non_root/user/mount_allowlist）
- 逃逸用例拦截（fail-closed）：特权容器、Docker socket、宿主根/敏感路径挂载、
  host 网络、root 用户、未登记挂载、缺镜像/命令
- 命令构造硬化：Docker + runsc、只读 rootfs、非 root、cap-drop ALL、
  no-new-privileges、cpu/mem/pids 配额、network=none、tmpfs
- strict 模式 runtime 缺失即拒绝执行（不静默降级）

边界：
- 本层只产出运行配置与命令，不负责拉取 object_ref / 编排（P2-7 评测器接入）
- 编译类评测 gVisor 开销 ≤20% 属云端实测门（见 CHANGELOG P4-3 运维说明）
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import yaml

logger = logging.getLogger(__name__)

MODULE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = MODULE_ROOT / "config" / "sandbox.yaml"

RUNTIMES = ("gvisor", "docker", "none")
NETWORKS = ("none", "allowlist")
SENSITIVE_PREFIXES = ("/proc", "/sys", "/dev")
DOCKER_SOCKET = "/var/run/docker.sock"


class SandboxError(Exception):
    """沙箱策略或运行环境不满足（fail-closed）。"""


class SandboxRequest(Protocol):
    """评测器执行请求的最小契约（P2-7 接入点）。"""

    image: str = ""
    command: Sequence[str] = ()
    mounts: Sequence[tuple[str, str, bool]]
    privileged: bool
    network_mode: str | None
    user: str | None
    env: Mapping[str, str]


@dataclass(frozen=True)
class ExecutionRequest:
    """一次沙箱执行请求。"""

    image: str = ""
    command: Sequence[str] = ()
    mounts: Sequence[tuple[str, str, bool]] = ()
    privileged: bool = False
    network_mode: str | None = None
    user: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxPolicy:
    """沙箱运行策略（配置即策略，缺失字段取严格默认）。"""

    runtime: str = "gvisor"
    strict: bool = True
    cpu: float = 1.0
    memory: str = "2g"
    pids: int = 256
    timeout_s: int = 1800
    network: str = "none"
    network_allowlist: Sequence[str] = ()
    read_only_rootfs: bool = True
    run_as_non_root: bool = True
    user: str = "65534:65534"
    mount_allowlist: Sequence[str] = ()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SandboxPolicy":
        """加载策略；文件缺失回退严格默认（fail-closed）。"""
        config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not config_path.is_file():
            return cls()
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        policy = cls(**payload)
        policy._validate()
        return policy

    def _validate(self) -> None:
        if self.runtime not in RUNTIMES:
            raise SandboxError(f"unknown_runtime:{self.runtime}")
        if self.network not in NETWORKS:
            raise SandboxError(f"unknown_network:{self.network}")
        if self.strict and self.runtime == "none":
            raise SandboxError("runtime_unavailable:none_in_strict")


# ---------- 逃逸校验 ----------


def _mount_source_allowed(source: str, policy: SandboxPolicy) -> bool:
    return any(source.startswith(prefix) for prefix in policy.mount_allowlist)


def validate_request(request: ExecutionRequest, policy: SandboxPolicy) -> list[str]:
    """返回逃逸/违规清单；空列表即放行。"""
    violations: list[str] = []

    if not request.image:
        violations.append("missing_image")
    if not request.command:
        violations.append("missing_command")
    if request.privileged:
        violations.append("privileged")

    mode = request.network_mode
    if mode is not None and mode != policy.network:
        violations.append(f"network_not_allowed:{mode}")

    if policy.run_as_non_root:
        user = (request.user or policy.user).split(":")[0]
        if user in ("0", "root", ""):
            violations.append("non_root_required")

    for source, target, readonly in request.mounts:
        if source == "/":
            violations.append("host_root")
            continue
        if DOCKER_SOCKET in source:
            violations.append("docker_socket")
            continue
        if source.startswith(SENSITIVE_PREFIXES):
            violations.append(f"sensitive_path:{source}")
            continue
        if not _mount_source_allowed(source, policy):
            violations.append(f"mount_not_allowed:{source}")
        if not readonly:
            violations.append(f"mount_not_readonly:{source}")
        if not target.startswith("/") or target == "/":
            violations.append(f"bad_mount_target:{target}")

    return violations


# ---------- 运行环境检查 ----------


def _binary_for(runtime: str) -> str:
    return {"gvisor": "runsc", "docker": "docker"}.get(runtime, "")


def check_runtime(policy: SandboxPolicy, which: Any = None) -> dict[str, Any]:
    """检查策略要求的 runtime 是否可用；strict 缺失即不可用。"""
    if policy.runtime not in RUNTIMES:
        raise SandboxError(f"unknown_runtime:{policy.runtime}")

    which = which or shutil.which
    reasons: list[str] = []
    binary = _binary_for(policy.runtime)
    available = bool(binary and which(binary))

    if policy.runtime == "none":
        if policy.strict:
            reasons.append("runtime_unavailable:none_in_strict")
            return {"ok": False, "runtime": "none", "available": False, "reasons": reasons}
        return {"ok": True, "runtime": "none", "available": False, "reasons": reasons}

    if not available:
        reasons.append(f"runtime_unavailable:{binary}")
        if policy.strict:
            return {
                "ok": False,
                "runtime": policy.runtime,
                "available": False,
                "reasons": reasons,
            }
    return {
        "ok": True,
        "runtime": policy.runtime,
        "available": available,
        "reasons": reasons,
    }


# ---------- 命令构造 ----------


def build_command(request: ExecutionRequest, policy: SandboxPolicy, which: Any = None) -> list[str]:
    """构造硬化后的 docker run 命令；策略违规或 runtime 缺失即 SandboxError。"""
    violations = validate_request(request, policy)
    if violations:
        raise SandboxError(";".join(violations))

    availability = check_runtime(policy, which=which)
    if not availability["ok"]:
        raise SandboxError(";".join(availability["reasons"]) or "runtime_unavailable")

    cmd = ["docker", "run", "--rm"]
    if policy.runtime == "gvisor" and availability["available"]:
        cmd.append("--runtime=runsc")
    if policy.read_only_rootfs:
        cmd.append("--read-only")
    if policy.network in ("none", "allowlist"):
        cmd.append("--network=none")
    if policy.run_as_non_root:
        cmd.append(f"--user={request.user or policy.user}")
        cmd.append("--security-opt=no-new-privileges")
    cmd.extend(
        [
            "--cap-drop=ALL",
            f"--cpus={policy.cpu}",
            f"--memory={policy.memory}",
            f"--pids-limit={policy.pids}",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=512m",
        ]
    )

    for source, target, readonly in request.mounts:
        mount = f"type=bind,source={source},target={target}"
        if readonly:
            mount += ",readonly"
        cmd.extend(["--mount", mount])

    for key, value in request.env.items():
        cmd.extend(["--env", f"{key}={value}"])

    cmd.extend([request.image, *request.command])
    return cmd
