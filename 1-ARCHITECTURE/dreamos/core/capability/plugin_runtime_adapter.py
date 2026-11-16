"""A3 运行时 adapter 接缝：把 install/unload 落到 DSH CLI，并采集副作用快照。

设计
----
- **默认 dry-run**：`apply=False` 时只产出命令计划，绝不执行、绝不伪造安装。
- **可注入 runner**：生产用 `SubprocessRunner` 调 `dsh`；测试注入 fake runner，
  因此全流程可在临时 profile 上验证，不触碰真实运行时。
- **退出码不等于成功**：`dsh plugin add/remove` 返回 0 后还要回读 profile
  `package.json` 确认登记/移除，避免假成功。
- **快照可插拔**：四类副作用由运行时 probe 命令输出 JSON；未配置 probe 直接拒绝，
  不凭空编造订阅/连接/句柄/定时器。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .plugin_inspect import DEFAULT_PACKAGES_DIR, dsh_home


class AdapterError(RuntimeError):
    """adapter 执行/校验失败（不得向上伪装成安装成功）"""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class SubprocessRunner:
    """真实命令执行器；仅在显式 apply=True 时被调用。"""

    def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


class DSHCommandAdapter:
    """通过 `dsh plugin add/remove` 安装/卸载，并读回 profile 确认结果。"""

    def __init__(
        self,
        profile: str,
        *,
        home: Optional[Path] = None,
        packages_dir: Optional[Path] = None,
        runner: Optional[Any] = None,
        apply: bool = False,
        snapshot_command: Optional[Sequence[str]] = None,
        timeout: float = 120.0,
        dsh_bin: str = "dsh",
    ) -> None:
        self.profile = profile
        self.home = dsh_home(home)
        self.packages_dir = Path(packages_dir) if packages_dir else DEFAULT_PACKAGES_DIR
        self.runner = runner or SubprocessRunner()
        self.apply = apply
        self.snapshot_command = list(snapshot_command) if snapshot_command else None
        self.timeout = timeout
        self.dsh_bin = dsh_bin

    # ---------- 命令计划 ----------

    @property
    def _profile_dir(self) -> Path:
        return self.home / "profiles" / self.profile

    def _local_package_dir(self, plugin_id: str) -> Optional[Path]:
        """按包名解析本地包（目录名可能不等于 package.json 的 name）。"""
        direct = self.packages_dir / plugin_id
        if (direct / "package.json").is_file():
            return direct
        for manifest in sorted(self.packages_dir.glob("*/package.json")):
            try:
                doc = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict) and doc.get("name") == plugin_id:
                return manifest.parent
        return None

    def _spec(self, plugin_id: str) -> str:
        local = self._local_package_dir(plugin_id)
        if local is not None:
            # 绝对路径：dsh/pnpm 在不同 cwd 下解析 file: 的结果必须一致
            return f"file:{local.resolve()}"
        return plugin_id

    def plan_install(self, manifest: Dict[str, Any]) -> List[str]:
        return [
            self.dsh_bin,
            "plugin",
            "add",
            self._spec(str(manifest.get("plugin_id") or "")),
            "--profile",
            self.profile,
        ]

    def plan_remove(self, plugin_id: str) -> List[str]:
        return [
            self.dsh_bin,
            "plugin",
            "remove",
            plugin_id,
            "--profile",
            self.profile,
        ]

    # ---------- 执行 ----------

    def _run(self, argv: Sequence[str]) -> CommandResult:
        try:
            return self.runner.run(argv, self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"命令超时（{self.timeout}s）: {' '.join(argv)}") from exc
        except OSError as exc:
            raise AdapterError(f"命令执行失败: {exc}") from exc

    def _deps(self) -> Dict[str, Any]:
        path = self._profile_dir / "package.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError(f"无法读取 profile 清单: {path}（{exc}）") from exc
        deps = doc.get("dependencies") or {}
        if not isinstance(deps, dict):
            raise AdapterError(f"profile 清单 dependencies 非对象: {path}")
        return deps

    def install(self, manifest: Dict[str, Any]) -> None:
        if not self.apply:
            raise AdapterError("dry-run：安装未执行（apply=False，需显式开启）")
        plugin_id = str(manifest.get("plugin_id") or "")
        if not plugin_id:
            raise AdapterError("manifest.plugin_id 缺失")

        argv = self.plan_install(manifest)
        result = self._run(argv)
        if result.returncode != 0:
            raise AdapterError(
                f"dsh plugin add 失败（{result.returncode}）: {result.stderr.strip()}"
            )
        if plugin_id not in self._deps():
            raise AdapterError(f"dsh plugin add 返回成功但 profile 未登记插件: {plugin_id}")

    def remove(self, plugin_id: str) -> None:
        if not self.apply:
            raise AdapterError("dry-run：卸载未执行（apply=False，需显式开启）")
        argv = self.plan_remove(plugin_id)
        result = self._run(argv)
        if result.returncode != 0:
            raise AdapterError(
                f"dsh plugin remove 失败（{result.returncode}）: {result.stderr.strip()}"
            )
        if plugin_id in self._deps():
            raise AdapterError(f"卸载后 profile 仍登记插件: {plugin_id}")

    # ---------- 副作用快照 ----------

    def capture_snapshot(self) -> Dict[str, Any]:
        if not self.snapshot_command:
            raise AdapterError(
                "未配置运行时快照 probe 命令（snapshot_command），拒绝编造四类副作用"
            )
        result = self._run(self.snapshot_command)
        if result.returncode != 0:
            raise AdapterError(f"快照 probe 失败（{result.returncode}）: {result.stderr.strip()}")
        try:
            snapshot = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"快照 probe 输出非 JSON: {exc}") from exc
        if not isinstance(snapshot, dict):
            raise AdapterError("快照 probe 输出必须是对象")
        return snapshot
