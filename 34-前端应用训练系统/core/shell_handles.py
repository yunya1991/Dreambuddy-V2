# -*- coding: utf-8 -*-
"""壳句柄管理器(DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-10 / G2 定稿 + SPEC-DSH-P5 v1.0)。

ADR-10: 宿主=DSH 运行时进程;同一进程内按域共享单壳实例,Worker 会话只持
「工具调用句柄」→ 连接数=聚合后域数(3),而非 Worker 数;跨进程(云端/本地)
才各自拉起。壳内禁止自建连接池(47 SPEC §3.1),连接治理在 19-DAL(conn_limit)。
本模块是宿主侧唯一壳生命周期载体:壳定义只读引用 47 registry(B4 唯一载体),
不重复定义;stdio 拉起细节由 launcher 注入(本模块不含进程逻辑)。

SPEC-DSH-P5 v1.0 新增:
  HC-4 健康检查: get_handle 发现壳 is_alive()==False → 关旧壳 → 重拉起
  HC-5 重拉上限: 每 shell_id 最多重拉 MAX_RESTARTS=3 次;超限 FAIL-OPEN None

硬约束:
  HC-1 FAIL-OPEN(H1): 开关关/注册表缺失/未知壳/壳拉起失败 → None,不崩
  HC-2 开关默认关(H2): enable_shell_handles 缺省 False
  HC-3 单壳语义(ADR-10): 同 shell_id 在 Manager 生命周期内只 launcher 一次(
    除非 HC-4 发现壳死重拉)
  HC-4 壳死自动重拉: is_alive() 被动健康检查,死壳 cleanup + 重拉起
  HC-5 同 id 重拉上限: MAX_RESTARTS=3,超限 FAIL-OPEN
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

import yaml

_SWITCH = "enable_shell_handles"

# 47 registry 默认路径(B4 唯一载体;core/ → 34-前端应用训练系统/ → repo 根)
_DEFAULT_REGISTRY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "47-MCP管理系统",
    "registry",
    "mcp_capabilities.yaml",
)

# 可拉起的壳状态(registry status 枚举: available/degraded/planned/deprecated)
_LAUNCHABLE_STATUS = ("available",)

# SPEC-DSH-P5 HC-5: 每 shell_id 重拉上限
MAX_RESTARTS = 3


class ShellHandle:
    """Worker 持有的工具调用句柄(ADR-10: 句柄 ≠ 壳实例,多句柄共享单壳)。"""

    __slots__ = ("shell_id", "spec", "shell")

    def __init__(self, shell_id: str, spec: Dict[str, Any], shell: Any):
        self.shell_id = shell_id
        self.spec = spec
        self.shell = shell

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Any:
        """经句柄调用壳工具(透传到底层共享壳实例)。"""
        return self.shell.call(tool, args)


class ShellHandleManager:
    """进程级壳生命周期管理:按 shell_id 共享单壳,句柄借还,统一关闭。

    SPEC-DSH-P5 v1.0:
      HC-4 健康检查: get_handle 被动发现 is_alive()==False → 自动重拉
      HC-5 重拉上限: MAX_RESTARTS 次后 FAIL-OPEN None
      force_new=True: 强制清旧壳重拉 (供 try-retry-degrade 用)
    """

    def __init__(
        self,
        registry_path: Optional[str] = None,
        launcher: Optional[Callable[[Dict[str, Any]], Any]] = None,
        flags: Optional[Dict[str, Any]] = None,
    ):
        self._registry_path = registry_path or _DEFAULT_REGISTRY
        self._launcher = launcher
        self._flags = flags
        self._shells: Dict[str, Any] = {}  # shell_id → 壳实例(单例)
        self._specs: Dict[str, Dict[str, Any]] = {}  # shell_id → registry spec
        self._issued: Dict[str, int] = {}
        self._restart_counts: Dict[str, int] = {}  # HC-5

    # -- 内部 ---------------------------------------------------------------

    def _enabled(self) -> bool:
        try:
            return bool(isinstance(self._flags, dict) and self._flags.get(_SWITCH, False))
        except Exception:
            return False

    def _load_specs(self) -> Dict[str, Dict[str, Any]]:
        """读 registry shells 段 → {shell_id: spec};缺失/坏文件/坏结构 → {}。"""
        try:
            with open(self._registry_path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            shells = doc.get("shells") or []
            out: Dict[str, Dict[str, Any]] = {}
            for spec in shells:
                if not isinstance(spec, dict):
                    continue
                sid = spec.get("shell_id")
                if isinstance(sid, str) and sid:
                    out[sid] = spec
            return out
        except Exception:
            return {}

    def _specs_cached(self) -> Dict[str, Dict[str, Any]]:
        if not self._specs:
            self._specs = self._load_specs()
        return self._specs

    def _restart_allowed(self, shell_id: str) -> bool:
        """HC-5: 重拉次数未超限。"""
        return self._restart_counts.get(shell_id, 0) < MAX_RESTARTS

    # -- 对外 ---------------------------------------------------------------

    def get_handle(
        self,
        shell_id: Any,
        force_new: bool = False,
    ) -> Optional[ShellHandle]:
        """取句柄:同 shell_id 共享单壳(HC-3);任一层失败 → None(HC-1)。

        SPEC-DSH-P5 v1.0:
          HC-4: 壳 is_alive()==False → 关旧壳 → launcher(spec) 自动重拉
          HC-5: 重拉次数超 MAX_RESTARTS → FAIL-OPEN 返回 None
          force_new=True: 强制清旧壳重新拉起 (供 call_worker_tool try-retry 用)
        """
        try:
            if not self._enabled():
                return None
            if not isinstance(shell_id, str) or not shell_id:
                return None
            spec = self._specs_cached().get(shell_id)
            if spec is None:
                return None  # 未知壳(deny-by-default)
            if spec.get("status", "available") not in _LAUNCHABLE_STATUS:
                return None

            shell = self._shells.get(shell_id)

            # HC-4: 强制重拉 或 壳死了 → cleanup + 重拉起
            need_restart = force_new or (shell is not None and not shell.is_alive())
            if need_restart and shell is not None:
                if not self._restart_allowed(shell_id) and not force_new:
                    # force_new 是显式请求重拉, 绕过 HC-5 上限
                    return None
                self._restart_counts[shell_id] = self._restart_counts.get(shell_id, 0) + 1
                try:
                    shell.close()
                except Exception:
                    pass
                # 不 del —— 保留 crash 后 shell 对象, 让下次 get_handle 还能拿
                # 到并检查 is_alive()=False 触发 need_restart; close 后壳已死,
                # 但 dict key 还在, 直接覆盖即可
                shell = None

            if shell is None:
                if self._launcher is None:
                    return None
                # HC-5 检查 (非 force_new 路径)
                if not force_new and not self._restart_allowed(shell_id):
                    return None
                shell = self._launcher(spec)  # 单壳拉起(每 id 仅一次, 除非 HC-4)
                self._shells[shell_id] = shell
            self._issued[shell_id] = self._issued.get(shell_id, 0) + 1
            return ShellHandle(shell_id, spec, shell)
        except Exception:
            return None  # HC-1: 壳拉起失败由宿主兜底,不击穿 Worker

    def close_all(self) -> None:
        """关闭全部壳实例;单壳关闭异常不阻塞其余(H1)。"""
        shells = list(self._shells.values())
        self._shells.clear()
        for shell in shells:
            try:
                shell.close()
            except Exception:
                pass

    def stats(self) -> Dict[str, Dict[str, int]]:
        return {sid: {"handles_issued": n} for sid, n in self._issued.items()}


__all__ = ["ShellHandle", "ShellHandleManager"]
