#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4 — 47 registry 只读工具集加载器。

唯一事实源：`47-MCP管理系统/registry/mcp_capabilities.yaml`（只读，绝不写回）。
优先使用已安装的 PyYAML；不可用时退化为标准库正则极简解析
（shell_id / tools[].name / tools[].domain）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"

_SHELL_RE = re.compile(r"^\s*-\s*shell_id:\s*[\"']?([A-Za-z0-9._-]+)")
_TOOL_RE = re.compile(r"^\s*-\s*name:\s*[\"']?([A-Za-z0-9_]+)")
_DOMAIN_RE = re.compile(r"^\s*domain:\s*[\"']?([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class ToolInfo:
    shell_id: str
    name: str
    domain: str
    read_write: str

    @property
    def full_name(self) -> str:
        return f"{self.shell_id}.{self.name}"


@dataclass
class RegistryView:
    """registry 只读视图：支持 `tool in view` 与 domain 查询。"""

    tools: dict[str, ToolInfo] = field(default_factory=dict)
    source: str = ""

    @property
    def domains(self) -> dict[str, str]:
        """{tool_full_name: domain}（供 gate G3 判定 tool 所属壳域）。"""
        return {name: info.domain for name, info in self.tools.items()}

    def __contains__(self, tool: Any) -> bool:
        return isinstance(tool, str) and tool in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    def allowed(self) -> set[str]:
        return set(self.tools)

    def domain_of(self, tool: str) -> str | None:
        info = self.tools.get(tool)
        return info.domain if info else None

    def shell_of(self, tool: str) -> str | None:
        info = self.tools.get(tool)
        return info.shell_id if info else None


def _parse_with_yaml(text: str) -> list[ToolInfo] | None:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — 解析失败交由正则兜底
        return None
    if not isinstance(data, dict) or not isinstance(data.get("shells"), list):
        return None

    tools: list[ToolInfo] = []
    for shell in data["shells"]:
        if not isinstance(shell, dict):
            continue
        shell_id = str(shell.get("shell_id") or "").strip()
        if not shell_id:
            continue
        for tool in shell.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            tools.append(
                ToolInfo(
                    shell_id=shell_id,
                    name=name,
                    domain=str(tool.get("domain") or ""),
                    read_write=str(tool.get("read_write") or ""),
                )
            )
    return tools


def _parse_with_regex(text: str) -> list[ToolInfo]:
    tools: list[ToolInfo] = []
    shell_id = ""
    pending: dict[str, str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]
        if not line.strip():
            continue
        shell_match = _SHELL_RE.match(line)
        if shell_match:
            shell_id = shell_match.group(1)
            continue
        tool_match = _TOOL_RE.match(line)
        if tool_match and shell_id:
            if pending is not None:
                tools.append(ToolInfo(**pending))  # type: ignore[arg-type]
            pending = {
                "shell_id": shell_id,
                "name": tool_match.group(1),
                "domain": "",
                "read_write": "",
            }
            continue
        domain_match = _DOMAIN_RE.match(line)
        if domain_match and pending is not None and not pending["domain"]:
            pending["domain"] = domain_match.group(1)

    if pending is not None:
        tools.append(ToolInfo(**pending))  # type: ignore[arg-type]
    return tools


def load_registry(path: str | Path | None = None) -> RegistryView:
    """读取 registry → RegistryView。文件缺失/解析为空 → 空视图（调用方降级）。"""
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    try:
        text = registry_path.read_text(encoding="utf-8")
    except OSError:
        return RegistryView({}, source=str(registry_path))

    parsed = _parse_with_yaml(text)
    if parsed is None:
        parsed = _parse_with_regex(text)
    return RegistryView({info.full_name: info for info in parsed}, source=str(registry_path))
