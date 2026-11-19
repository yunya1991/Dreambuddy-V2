# -*- coding: utf-8 -*-
"""P0-D3D: Hermes 运行时隔离契约（B1 关闭项）。

只校验配置，不实际改系统；部署层据此生成 systemd/网络策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


@dataclass(frozen=True)
class RuntimeIsolation:
    runtime_id: str = "hermes"
    os_user: str = "hermes-runtime"
    no_new_privileges: bool = True
    protect_system: str = "strict"
    private_tmp: bool = True
    protect_home: bool = True
    read_only_paths: Tuple[str, ...] = ()
    writable_paths: Tuple[str, ...] = ()
    dsh_credentials: bool = False
    dsh_internal_reachable: bool = False
    allowed_egress: Tuple[str, ...] = ()
    max_memory_mb: int = 4096
    max_cpu_quota: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_only_paths", _as_tuple(self.read_only_paths))
        object.__setattr__(self, "writable_paths", _as_tuple(self.writable_paths))
        object.__setattr__(self, "allowed_egress", _as_tuple(self.allowed_egress))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.runtime_id != "hermes":
            errors.append("invalid_runtime_id")
        if self.os_user != "hermes-runtime":
            errors.append("dedicated_user_required")
        if not self.no_new_privileges:
            errors.append("no_new_privileges_required")
        if self.protect_system != "strict":
            errors.append("protect_system_strict_required")
        if not self.private_tmp:
            errors.append("private_tmp_required")
        if not self.protect_home:
            errors.append("protect_home_required")
        if self.dsh_credentials:
            errors.append("dsh_credentials_forbidden")
        if self.dsh_internal_reachable:
            errors.append("dsh_internal_network_forbidden")
        if not self.allowed_egress:
            errors.append("egress_allowlist_required")
        if self.max_memory_mb <= 0:
            errors.append("memory_limit_required")
        if self.max_cpu_quota <= 0:
            errors.append("cpu_limit_required")
        if any(
            token in path
            for path in self.writable_paths
            for token in ("34-前端应用训练系统", "47-MCP管理系统", "22-执行引擎中心")
        ):
            errors.append("dsh_path_writable_forbidden")
        return errors
