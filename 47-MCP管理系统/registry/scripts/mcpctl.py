#!/usr/bin/env python3
"""mcpctl — L0 MCP 通用接入控制面（P0）

子命令：
  doctor                    环境体检：Python / 注册表 / 壳路径 / 宿主配置
  profile --role <role>     按角色生成 MCP 宿主配置（默认输出到 stdout）
  install --role <role>     安装配置到宿主（默认 --host all，自动备份）
  new-shell                 生成新壳骨架 + 契约测试 + registry 片段
  verify                    注册表 ↔ 壳代码 tools/list 漂移检查
  list-roles                列出角色及其工具集
  list-shells               列出壳与工具面

设计边界（P0）：
  - 角色包是**壳级**的：MCP 配置只能按 server 粒度挂载，工具级最小权限
    待 P1 `l0-gateway --role` 落地后由网关注入。
  - 默认只读：cognition 壳显式注入 COGNITIVE_MCP_WRITE_ENABLED=false。
  - 不修改注册表、不拉起常驻进程；profile 只产出配置文本。

用法示例：
  python "47-MCP管理系统/registry/scripts/mcpctl.py" doctor --deep
  python .../mcpctl.py profile --role research
  python .../mcpctl.py profile --role research --out .mcp.json
  python .../mcpctl.py profile --role verifier --host claude-project --install
  python .../mcpctl.py verify --strict
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

from check_mcp_tool_drift import load_registry, probe_shell, run as drift_run
from validate_mcp_registry import validate as validate_registry


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = Path(
    os.environ.get(
        "DREAMBUDDY_MCP_REGISTRY",
        str(REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"),
    )
)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


LAUNCHABLE_STATUS = ("available", "degraded")

# 宿主配置文件模板；needs_project=True 时相对仓库根，否则相对 home
HOST_CONFIGS: Dict[str, Dict[str, Any]] = {
    "json": {"name": "标准输出", "path": "-", "needs_project": False, "writable": False},
    "claude-project": {
        "name": "Claude Code（项目级）",
        "path": "{project}/.mcp.json",
        "needs_project": True,
        "writable": True,
    },
    "trae": {
        "name": "TRAE",
        "path": "{project}/.trae/mcp.json",
        "needs_project": True,
        "writable": True,
    },
    "claude": {
        "name": "Claude Code（用户级）",
        "path": "{home}/.claude.json",
        "needs_project": False,
        "writable": True,
    },
    "cursor": {
        "name": "Cursor",
        "path": "{home}/.cursor/mcp.json",
        "needs_project": False,
        "writable": True,
    },
    "windsurf": {
        "name": "Windsurf",
        "path": "{home}/.codeium/windsurf/mcp_config.json",
        "needs_project": False,
        "writable": True,
    },
    "continue": {
        "name": "Continue.dev",
        "path": "{home}/.continue/config.json",
        "needs_project": False,
        "writable": True,
    },
}


# ── 公共辅助 ──────────────────────────────────────────────────────────


def host_config_path(host: str, repo_root: Path = REPO_ROOT) -> Optional[Path]:
    cfg = HOST_CONFIGS.get(host)
    if not cfg or not cfg.get("writable"):
        return None
    return Path(cfg["path"].format(project=str(repo_root), home=str(Path.home())))


def server_name(shell_id: str) -> str:
    s = shell_id
    if s.startswith("l0."):
        s = s[3:]
    if s.endswith(".mcp"):
        s = s[:-4]
    return s.replace(".", "-")


def shell_index(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        s["shell_id"]: s
        for s in (doc.get("shells") or [])
        if isinstance(s, dict) and s.get("shell_id")
    }


def _local_entry(
    shell: Dict[str, Any],
    repo_root: Path,
    python_exe: str,
) -> Dict[str, Any]:
    env: Dict[str, str] = {
        "PYTHONPATH": str(repo_root),
        "PYTHONIOENCODING": "utf-8",
    }
    if shell["shell_id"] == "l0.cognition.mcp":
        # P0 默认只读；写工具需显式改配置并由宿主授予 Mandate
        env["COGNITIVE_MCP_MODE"] = "local"
        env["COGNITIVE_MCP_WRITE_ENABLED"] = "false"
    return {
        "command": python_exe,
        "args": [str(repo_root / str(shell["shell_path"]))],
        "env": env,
    }


def _ssh_entry(
    shell: Dict[str, Any],
    ssh_host: str,
    remote_repo: str,
    remote_python: str,
    remote_user: Optional[str],
) -> Dict[str, Any]:
    remote_path = f"{remote_repo.rstrip('/')}/{shell['shell_path']}"
    cmd = f"{remote_python} {remote_path}"
    remote_env = f"PYTHONPATH={remote_repo} PYTHONIOENCODING=utf-8"
    if remote_user:
        cmd = f"sudo -n -u {remote_user} -H env {remote_env} {cmd}"
    else:
        cmd = f"env {remote_env} {cmd}"
    return {
        "command": "ssh",
        "args": ["-o", "BatchMode=yes", ssh_host, cmd],
        "env": {},
    }


def build_profile(
    doc: Dict[str, Any],
    role: str,
    *,
    repo_root: Path = REPO_ROOT,
    python_exe: Optional[str] = None,
    ssh_host: Optional[str] = None,
    remote_repo: str = "/home/luke/dreambuddy",
    remote_python: str = "python3",
    remote_user: Optional[str] = "luke",
    gateway: bool = False,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """生成角色配置。返回 (config, warnings, errors)。

    gateway=True 时输出单条 `l0-<role>` 网关配置（工具级最小权限）；
    否则输出壳级多条目配置（P0 兼容模式）。
    """
    warnings: List[str] = []
    errors: List[str] = []

    roles = doc.get("worker_roles") or {}
    spec = roles.get(role)
    if not isinstance(spec, dict):
        available = ", ".join(sorted(roles)) or "（无）"
        return {}, [], [f"未知角色 {role!r}；可用角色: {available}"]

    shells = shell_index(doc)
    role_shells = [str(s) for s in (spec.get("shells") or [])]
    role_tools = [str(t) for t in (spec.get("tools") or [])]
    python_exe = python_exe or sys.executable

    if gateway:
        covered: set[str] = set()
        write_in_role: List[str] = []
        for sid in role_shells:
            shell = shells.get(sid)
            if shell is None:
                errors.append(f"角色引用的壳未登记: {sid}")
                continue
            for tool in shell.get("tools") or []:
                if not isinstance(tool, dict) or not tool.get("name"):
                    continue
                name = str(tool["name"])
                if name in role_tools:
                    covered.add(name)
                    if tool.get("requires_mandate") is True:
                        write_in_role.append(name)

        missing = sorted(set(role_tools) - covered)
        if missing:
            errors.append(f"角色工具未包含在已挂载壳中: {missing}")
        if write_in_role:
            errors.append(
                f"角色含写工具，网关将拒绝（Worker 只读）: {sorted(set(write_in_role))}"
            )
        if errors:
            return {}, warnings, errors

        gateway_path = repo_root / "mcp_shells" / "l0_gateway" / "server.py"
        args = [str(gateway_path), "--role", role]
        if ssh_host:
            args += ["--ssh-host", ssh_host]
        return {
            "mcpServers": {
                f"l0-{role}": {
                    "command": python_exe,
                    "args": args,
                    "env": {
                        "PYTHONPATH": str(repo_root),
                        "PYTHONIOENCODING": "utf-8",
                    },
                }
            }
        }, warnings, errors

    servers: Dict[str, Any] = {}
    covered_tools: set[str] = set()
    as_ssh = bool(ssh_host)

    for sid in role_shells:
        shell = shells.get(sid)
        if shell is None:
            errors.append(f"角色引用的壳未登记: {sid}")
            continue
        status = shell.get("status")
        if status not in LAUNCHABLE_STATUS:
            warnings.append(f"跳过 {sid}：status={status}")
            continue
        if not shell.get("shell_path"):
            warnings.append(f"跳过 {sid}：无 shell_path")
            continue

        if as_ssh and shell.get("transport") == "ssh-stdio":
            entry = _ssh_entry(shell, ssh_host, remote_repo, remote_python, remote_user)
        else:
            entry = _local_entry(shell, repo_root, python_exe)
        servers[server_name(sid)] = entry
        covered_tools.update(
            t.get("name") for t in (shell.get("tools") or []) if t.get("name")
        )

    missing_tools = sorted(set(role_tools) - covered_tools)
    if missing_tools:
        errors.append(f"角色工具未包含在已挂载壳中: {missing_tools}")

    exposed_extra = sorted(covered_tools - set(role_tools))
    if exposed_extra:
        warnings.append(
            "P0 为壳级角色包，以下工具会随壳额外暴露（P1 网关后按角色裁剪）: "
            + ", ".join(exposed_extra)
        )

    return {"mcpServers": servers}, warnings, errors


def _protocol_versions() -> List[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from mcp_shells._shared.shell_runtime import SUPPORTED_PROTOCOL_VERSIONS

    return list(SUPPORTED_PROTOCOL_VERSIONS)


def build_agent_card(
    doc: Dict[str, Any],
    role: str,
    *,
    repo_root: Path = REPO_ROOT,
    python_exe: Optional[str] = None,
    ssh_host: Optional[str] = None,
    portable: bool = False,
) -> Dict[str, Any]:
    """按角色生成 Agent Card（P3b，机读能力发现）。

    portable=True 时 server/env 使用 <PYTHON> / <REPO_ROOT> 占位符，
    使静态索引可跨机器/CI 校验；单角色输出默认给真实绝对路径。
    """
    roles = doc.get("worker_roles") or {}
    spec = roles.get(role)
    if not isinstance(spec, dict):
        available = ", ".join(sorted(roles)) or "（无）"
        raise ValueError(f"未知角色 {role!r}；可用角色: {available}")

    shells = shell_index(doc)
    role_tools = [str(t) for t in (spec.get("tools") or [])]
    order = {name: idx for idx, name in enumerate(role_tools)}
    tools: List[Dict[str, Any]] = []
    for sid in spec.get("shells") or []:
        shell = shells.get(str(sid)) or {}
        for tool in shell.get("tools") or []:
            if isinstance(tool, dict) and tool.get("name") in order:
                tools.append(
                    {
                        "name": tool["name"],
                        "read_only": bool(
                            (tool.get("annotations") or {}).get("readOnlyHint", True)
                        ),
                    }
                )
    tools.sort(key=lambda item: order[item["name"]])
    missing = sorted(set(role_tools) - {t["name"] for t in tools})
    if missing:
        raise ValueError(f"角色 {role!r} 的工具未映射到壳: {missing}")

    gateway_path = repo_root / "mcp_shells" / "l0_gateway" / "server.py"
    if portable:
        command = "<PYTHON>"
        args = ["<REPO_ROOT>/mcp_shells/l0_gateway/server.py", "--role", role]
        env = {"PYTHONPATH": "<REPO_ROOT>", "PYTHONIOENCODING": "utf-8"}
    else:
        command = python_exe or sys.executable
        args = [str(gateway_path), "--role", role]
        env = {"PYTHONPATH": str(repo_root), "PYTHONIOENCODING": "utf-8"}
    if ssh_host:
        args += ["--ssh-host", ssh_host]

    return {
        "schema_version": "1.0-agent-card",
        "name": f"l0-{role}",
        "display_name": f"L0 {role} capability gateway",
        "description": str(spec.get("description", "")),
        "version": "0.1",
        "protocol": {
            "name": "mcp",
            "versions": _protocol_versions(),
            "transport": "stdio",
        },
        "server": {
            "command": command,
            "args": args,
            "env": env,
        },
        "capabilities": {
            "tools": tools,
            "tool_count": len(tools),
            "read_only": True,
        },
        "registry": {
            "schema_version": doc.get("schema_version"),
            "registry_version": doc.get("registry_version"),
        },
        "security": {
            "worker_read_only": True,
            "write_tools_require_mandate": True,
        },
    }


def _merge_config(existing: Dict[str, Any], new_servers: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing) if existing else {}
    merged.setdefault("mcpServers", {})
    if not isinstance(merged["mcpServers"], dict):
        merged["mcpServers"] = {}
    merged["mcpServers"].update(new_servers)
    return merged


def write_config(path: Path, servers: Dict[str, Any]) -> Optional[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            backup = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
            shutil.copy2(path, backup)
        except Exception:
            existing = {}
    merged = _merge_config(existing, servers)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


# ── 子命令 ────────────────────────────────────────────────────────────


def cmd_doctor(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry_path = Path(args.registry)
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, level: str = "ERR") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, "level": level})

    py_ok = sys.version_info >= (3, 10)
    add("python>=3.10", py_ok, sys.version.replace("\n", " "), "ERR")

    if not registry_path.exists():
        add("registry", False, f"不存在: {registry_path}", "ERR")
        return _emit_doctor(checks, args)

    try:
        doc = load_registry(registry_path)
        add(
            "registry",
            doc.get("schema_version") == "1.1-mcp",
            f"schema={doc.get('schema_version')} registry={doc.get('registry_version')}",
        )
    except Exception as exc:
        add("registry", False, f"解析失败: {exc}", "ERR")
        return _emit_doctor(checks, args)

    registry_rc = validate_registry(registry_path, quiet=True)
    add("registry-schema", registry_rc == 0, f"validate_mcp_registry rc={registry_rc}")

    shells = [s for s in (doc.get("shells") or []) if isinstance(s, dict)]
    active = [s for s in shells if s.get("status") in LAUNCHABLE_STATUS]
    total_tools = sum(len(s.get("tools") or []) for s in active)
    cap = (doc.get("enums") or {}).get("max_total_tools", 80)
    budget_level = "ERR" if total_tools > cap else "WARN" if total_tools >= cap * 0.9 else "INFO"
    add(
        "tool-budget",
        total_tools <= cap,
        f"{total_tools}/{cap} active 工具（全局软上限）",
        budget_level,
    )
    role_count = len(doc.get("worker_roles") or {})
    add("roles", bool(role_count), f"{role_count} 个角色", "WARN")

    missing = []
    for shell in active:
        sp = shell.get("shell_path")
        if sp and not (repo_root / sp).exists():
            missing.append(f"{shell.get('shell_id')} → {sp}")
    add(
        "shell-paths",
        not missing,
        "全部存在" if not missing else "; ".join(missing),
        "ERR",
    )

    gateway_path = repo_root / "mcp_shells" / "l0_gateway" / "server.py"
    add("gateway", gateway_path.exists(), str(gateway_path), "WARN")

    project_mcp = repo_root / ".mcp.json"
    mcp_json_detail = (
        str(project_mcp) if project_mcp.exists() else "未生成（mcpctl profile --out .mcp.json）"
    )
    add("project-mcp-json", project_mcp.exists(), mcp_json_detail, "WARN")

    for host, cfg in HOST_CONFIGS.items():
        path = host_config_path(host, repo_root)
        if path is None:
            continue
        add(f"host:{host}", path.exists(), str(path), "INFO")

    if args.deep:
        for shell in active:
            if shell.get("transport") == "http" or not shell.get("shell_path"):
                continue
            ok, tools, error = probe_shell(shell, repo_root=repo_root, timeout=args.timeout)
            detail = f"{len(tools)} 工具" if ok else error
            add(f"probe:{shell.get('shell_id')}", ok, detail, "ERR")

    return _emit_doctor(checks, args)


def _emit_doctor(checks: List[Dict[str, Any]], args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("mcpctl doctor")
        for c in checks:
            if c["ok"]:
                mark = "OK  "
            elif c["level"] == "INFO":
                mark = "info"
            elif c["level"] == "WARN":
                mark = "WARN"
            else:
                mark = "FAIL"
            print(f"  [{mark}] {c['check']:<22} {c['detail']}")
    errors = [c for c in checks if not c["ok"] and c["level"] == "ERR"]
    return 1 if errors else 0


def cmd_profile(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    doc = load_registry(Path(args.registry))
    config, warnings, errors = build_profile(
        doc,
        args.role,
        repo_root=repo_root,
        python_exe=args.python,
        ssh_host=args.ssh_host,
        remote_repo=args.remote_repo,
        remote_python=args.remote_python,
        remote_user=args.remote_user,
        gateway=args.gateway,
    )
    for w in warnings:
        print(f"⚠ {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERR: {e}", file=sys.stderr)
        return 1

    servers = config.get("mcpServers") or {}

    if args.install:
        if args.host == "json":
            print("ERR: --install 需要具体 host，不能用 json", file=sys.stderr)
            return 1
        targets = (
            [h for h, c in HOST_CONFIGS.items() if c.get("writable")]
            if args.host == "all"
            else [args.host]
        )
        for host in targets:
            path = host_config_path(host, repo_root)
            if path is None:
                print(f"⚠ 跳过未知/不可写 host: {host}", file=sys.stderr)
                continue
            backup = write_config(path, servers)
            note = f"（备份 {backup.name}）" if backup else "（新建）"
            print(f"✅ {HOST_CONFIGS[host]['name']}: {path} {note}")
        return 0

    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if args.out and args.out != "-":
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"✅ 已写入 {path}（{len(servers)} 个壳）")
    else:
        sys.stdout.write(text)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """安装角色配置到宿主（等价 profile --install；默认 --host all）。"""
    args.install = True
    return cmd_profile(args)


def cmd_card(args: argparse.Namespace) -> int:
    doc = load_registry(Path(args.registry))
    try:
        card = build_agent_card(
            doc,
            args.role,
            repo_root=Path(args.repo_root).resolve(),
            python_exe=args.python,
            ssh_host=args.ssh_host,
            portable=args.portable,
        )
    except ValueError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(card, ensure_ascii=False, indent=2) + "\n"
    if args.out and args.out != "-":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"✅ {out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_cards(args: argparse.Namespace) -> int:
    doc = load_registry(Path(args.registry))
    roles = doc.get("worker_roles") or {}
    cards: Dict[str, Any] = {}
    for role in roles:
        try:
            cards[role] = build_agent_card(
                doc,
                role,
                repo_root=Path(args.repo_root).resolve(),
                python_exe=args.python,
                ssh_host=args.ssh_host,
                portable=True,
            )
        except ValueError as exc:
            print(f"ERR: {exc}", file=sys.stderr)
            return 1

    index = {
        "schema_version": "1.0-agent-card-index",
        "generated_by": "mcpctl cards",
        "registry": {
            "schema_version": doc.get("schema_version"),
            "registry_version": doc.get("registry_version"),
        },
        "cards": cards,
    }
    text = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    out = Path(args.out)
    if args.check:
        if not out.exists():
            print(f"ERR: {out} 不存在；运行 mcpctl cards --out {out}", file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8").strip() != text.strip():
            print(
                f"ERR: {out} 与 registry 不一致；运行 mcpctl cards --out {out}",
                file=sys.stderr,
            )
            return 1
        print(f"✅ {out} 与 registry 一致（{len(cards)} cards）")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"✅ {out}（{len(cards)} cards）")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    return drift_run(
        Path(args.registry),
        quiet=args.quiet,
        json_output=args.json,
        strict=args.strict,
        only_shells=args.shell,
        timeout=args.timeout,
    )


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_SERVER_TEMPLATE = Template(
    '''#!/usr/bin/env python3
"""mcp_shells/$name/server.py — $shell_id（mcpctl new-shell 生成）

TODO: 补充域说明与硬约束。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "$shell_id"


$handlers

TOOL_DEFS = {
$defs
}

TOOL_HANDLERS = {
$handler_map
}


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)
'''
)

_TEST_TEMPLATE = Template(
    '''#!/usr/bin/env python3
"""$shell_id 契约测试（mcpctl new-shell 生成）。"""

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).resolve().parent / "server.py"
EXPECTED = $expected


def _tools_list():
    reqs = (
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        + "\\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    )
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=reqs,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=str(_REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert lines, f"no stdout; stderr={proc.stderr}"
    return json.loads(lines[-1])["result"]["tools"]


def test_tools_list_matches_contract():
    names = [tool["name"] for tool in _tools_list()]
    assert names == EXPECTED
'''
)


def _parse_tools(raw: str) -> List[Tuple[str, str]]:
    tools: List[Tuple[str, str]] = []
    seen = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        name = parts[0].strip()
        read_write = parts[1].strip() if len(parts) > 1 else "read"
        if not _TOOL_RE.match(name):
            raise ValueError(f"非法工具名 {name!r}（需小写字母/数字/下划线）")
        if read_write not in ("read", "write"):
            raise ValueError(f"工具 {name!r} 读写属性必须是 read/write")
        if name in seen:
            raise ValueError(f"工具名重复: {name}")
        seen.add(name)
        tools.append((name, read_write))
    if not tools:
        raise ValueError("至少需要一个工具（--tools name:read[,name2:write]）")
    if len(tools) > 10:
        raise ValueError(f"单壳工具数 {len(tools)} 超过上限 10（ADR-4）")
    return tools


def _registry_snippet(
    shell_id: str,
    capability_id: str,
    name: str,
    domain: str,
    port: str,
    tools: List[Tuple[str, str]],
) -> str:
    lines = [
        f"  - shell_id: {shell_id}",
        f"    capability_id: {capability_id}",
        "    transport: stdio",
        f'    shell_path: "mcp_shells/{name}/server.py"',
        '    shell_cmd: "python3 {path}"',
        '    envelope_version: "0.1"',
        "    status: available",
        "    tools:",
    ]
    for tool, read_write in tools:
        is_write = read_write == "write"
        lines += [
            f"      - name: {tool}",
            f"        port: {port}",
            f"        domain: {domain}",
            f"        read_write: {read_write}",
            f"        requires_mandate: {'true' if is_write else 'false'}",
            "        annotations: { "
            f"readOnlyHint: {'false' if is_write else 'true'}, "
            f"destructiveHint: {'true' if is_write else 'false'} }}",
        ]
    return "\n".join(lines) + "\n"


def _render_server(shell_id: str, name: str, tools: List[Tuple[str, str]]) -> str:
    handlers = []
    defs = []
    handler_map = []
    for tool, _ in tools:
        handlers.append(
            f'def _handle_{tool}(args: Dict[str, Any]) -> str:\n'
            f'    """TODO: implement {tool}."""\n'
            "    return json.dumps(\n"
            "        wrap(\n"
            "            None,\n"
            "            SHELL_SOURCE,\n"
            '            degraded=True,\n'
            '            error_code="not_found",\n'
            f'            meta={{"reason": "{tool} not implemented"}},\n'
            "        ),\n"
            "        ensure_ascii=False,\n"
            "    )\n"
        )
        defs.append(
            f'    "{tool}": {{\n'
            f'        "description": "TODO: describe {tool}",\n'
            '        "inputSchema": {"type": "object", "properties": {}},\n'
            "    },"
        )
        handler_map.append(f'    "{tool}": _handle_{tool},')
    return _SERVER_TEMPLATE.substitute(
        name=name,
        shell_id=shell_id,
        handlers="\n\n".join(handlers),
        defs="\n".join(defs),
        handler_map="\n".join(handler_map),
    )


def cmd_new_shell(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry_path = Path(args.registry)
    doc = load_registry(registry_path)

    name = args.name.strip()
    if not _NAME_RE.match(name):
        print("ERR: --name 需 kebab-case（小写字母/数字/连字符）", file=sys.stderr)
        return 1
    shell_id = args.shell_id or f"l0.{name}.mcp"
    capability_id = args.capability_id or f"l0.{name}"

    enums = doc.get("enums") or {}
    if args.domain not in (enums.get("domain") or []):
        print(
            f"ERR: domain {args.domain!r} 不在枚举 {enums.get('domain')}；"
            "新增域需先更新 registry enums.domain",
            file=sys.stderr,
        )
        return 1
    if args.port not in (enums.get("port") or []):
        print(f"ERR: port {args.port!r} 不在枚举 {enums.get('port')}", file=sys.stderr)
        return 1
    try:
        tools = _parse_tools(args.tools)
    except ValueError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    shell_dir = repo_root / "mcp_shells" / name
    server_path = shell_dir / "server.py"
    test_path = shell_dir / f"test_{name.replace('-', '_')}_server.py"
    if shell_dir.exists() and not args.force:
        print(f"ERR: 目录已存在 {shell_dir}（--force 覆盖）", file=sys.stderr)
        return 1
    shell_dir.mkdir(parents=True, exist_ok=True)
    server_path.write_text(_render_server(shell_id, name, tools), encoding="utf-8")
    test_path.write_text(
        _TEST_TEMPLATE.substitute(
            shell_id=shell_id,
            expected=repr([tool for tool, _ in tools]),
        ),
        encoding="utf-8",
    )
    print(f"✅ {server_path}")
    print(f"✅ {test_path}")

    snippet = _registry_snippet(
        shell_id,
        capability_id,
        name,
        args.domain,
        args.port,
        tools,
    )
    if args.register:
        text = registry_path.read_text(encoding="utf-8")
        marker = "# ── 枚举词典"
        if marker not in text:
            print(f"ERR: registry 缺少插入标记 {marker!r}", file=sys.stderr)
            return 1
        backup = registry_path.with_suffix(registry_path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(registry_path, backup)
        registry_path.write_text(
            text.replace(marker, snippet + "\n" + marker, 1),
            encoding="utf-8",
        )
        rc = validate_registry(registry_path, quiet=True)
        if rc != 0:
            shutil.copy2(backup, registry_path)
            print("ERR: 注册表校验失败，已回滚", file=sys.stderr)
            return 1
        print(f"✅ 已登记到 {registry_path}（备份 {backup.name}）")
    else:
        print("\n将以下片段加入 registry mcp_capabilities.yaml（或使用 --register）：\n")
        print(snippet)

    print("\n下一步：")
    print(f"  1) 实现 mcp_shells/{name}/server.py 的 TODO handler")
    print("  2) 如需给角色使用，把工具加入 worker_roles 对应角色")
    print("  3) python mcpctl.py verify")
    return 0


def cmd_list_roles(args: argparse.Namespace) -> int:
    doc = load_registry(Path(args.registry))
    roles = doc.get("worker_roles") or {}
    if args.json:
        print(json.dumps(roles, ensure_ascii=False, indent=2))
        return 0
    for name, spec in roles.items():
        tools = spec.get("tools") or []
        shells = spec.get("shells") or []
        print(f"{name:<12} {len(tools):>2} 工具 · 壳: {', '.join(shells)}")
        print(f"{'':<12} {', '.join(tools)}")
    return 0


def cmd_list_shells(args: argparse.Namespace) -> int:
    doc = load_registry(Path(args.registry))
    shells = [s for s in (doc.get("shells") or []) if isinstance(s, dict)]
    if args.json:
        print(json.dumps(shells, ensure_ascii=False, indent=2))
        return 0
    for s in shells:
        tools = [t.get("name") for t in (s.get("tools") or []) if isinstance(t, dict)]
        print(
            f"{s.get('shell_id'):<24} {s.get('status'):<11} "
            f"{s.get('transport'):<10} {len(tools):>2} 工具"
        )
        print(f"{'':<24} {', '.join(tools)}")
    return 0


def _add_common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="L0 MCP 通用接入控制面（P0）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="环境体检")
    _add_common(p_doctor)
    p_doctor.add_argument("--deep", action="store_true", help="真实拉起每个壳做握手")
    p_doctor.add_argument("--repo-root", default=str(REPO_ROOT))
    p_doctor.add_argument("--timeout", type=float, default=30.0)
    p_doctor.set_defaults(func=cmd_doctor)

    p_profile = sub.add_parser("profile", help="按角色生成宿主配置")
    _add_common(p_profile)
    p_profile.add_argument("--role", required=True)
    p_profile.add_argument(
        "--host",
        default="json",
        choices=sorted(HOST_CONFIGS),
        help="目标宿主（install 时使用）",
    )
    p_profile.add_argument("--out", default="-", help="输出文件路径，- 表示 stdout")
    p_profile.add_argument("--install", action="store_true", help="写入宿主配置（自动备份）")
    p_profile.add_argument(
        "--gateway",
        action="store_true",
        help="生成单条角色网关配置（工具级最小权限，P1）",
    )
    p_profile.add_argument(
        "--python", default=None, help="解释器路径（默认 sys.executable）"
    )
    p_profile.add_argument("--repo-root", default=str(REPO_ROOT))
    p_profile.add_argument("--ssh-host", default=None, help="ssh-stdio 壳的 SSH 别名")
    p_profile.add_argument("--remote-repo", default="/home/luke/dreambuddy")
    p_profile.add_argument("--remote-python", default="python3")
    p_profile.add_argument("--remote-user", default="luke")
    p_profile.set_defaults(func=cmd_profile)

    p_install = sub.add_parser("install", help="安装角色配置到宿主（默认 all）")
    _add_common(p_install)
    p_install.add_argument("--role", required=True)
    p_install.add_argument(
        "--host",
        default="all",
        choices=sorted(list(HOST_CONFIGS) + ["all"]),
    )
    p_install.add_argument(
        "--gateway",
        action="store_true",
        help="安装单条角色网关配置（工具级最小权限，P1）",
    )
    p_install.add_argument("--python", default=None, help="解释器路径（默认 sys.executable）")
    p_install.add_argument("--repo-root", default=str(REPO_ROOT))
    p_install.add_argument("--ssh-host", default=None)
    p_install.add_argument("--remote-repo", default="/home/luke/dreambuddy")
    p_install.add_argument("--remote-python", default="python3")
    p_install.add_argument("--remote-user", default="luke")
    p_install.set_defaults(func=cmd_install)

    p_cards = sub.add_parser("cards", help="生成 / 校验全部角色 Agent Card")
    _add_common(p_cards)
    p_cards.add_argument(
        "--out",
        default=str(REPO_ROOT / "47-MCP管理系统" / "registry" / "agent_cards.json"),
    )
    p_cards.add_argument("--check", action="store_true", help="只校验不写入")
    p_cards.add_argument("--python", default=None)
    p_cards.add_argument("--repo-root", default=str(REPO_ROOT))
    p_cards.add_argument("--ssh-host", default=None)
    p_cards.set_defaults(func=cmd_cards)

    p_card = sub.add_parser("card", help="生成单个角色 Agent Card")
    _add_common(p_card)
    p_card.add_argument("--role", required=True)
    p_card.add_argument("--out", default="-")
    p_card.add_argument("--python", default=None)
    p_card.add_argument("--repo-root", default=str(REPO_ROOT))
    p_card.add_argument("--ssh-host", default=None)
    p_card.add_argument(
        "--portable",
        action="store_true",
        help="使用 <PYTHON>/<REPO_ROOT> 占位符而非绝对路径",
    )
    p_card.set_defaults(func=cmd_card)

    p_verify = sub.add_parser("verify", help="注册表 ↔ 代码漂移检查")
    _add_common(p_verify)
    p_verify.add_argument("--strict", action="store_true")
    p_verify.add_argument("--shell", action="append")
    p_verify.add_argument("--timeout", type=float, default=30.0)
    p_verify.set_defaults(func=cmd_verify)

    p_new = sub.add_parser("new-shell", help="生成新壳骨架 + 契约测试 + registry 片段")
    _add_common(p_new)
    p_new.add_argument("--name", required=True, help="目录/模块名（kebab-case）")
    p_new.add_argument("--shell-id", default=None)
    p_new.add_argument("--capability-id", default=None)
    p_new.add_argument("--domain", required=True)
    p_new.add_argument("--port", default="analysis")
    p_new.add_argument("--tools", required=True, help="name:read[,name2:write]")
    p_new.add_argument("--repo-root", default=str(REPO_ROOT))
    p_new.add_argument("--register", action="store_true", help="自动插入 registry 并校验")
    p_new.add_argument("--force", action="store_true", help="覆盖已有目录")
    p_new.set_defaults(func=cmd_new_shell)

    p_roles = sub.add_parser("list-roles", help="列出角色")
    _add_common(p_roles)
    p_roles.set_defaults(func=cmd_list_roles)

    p_shells = sub.add_parser("list-shells", help="列出壳")
    _add_common(p_shells)
    p_shells.set_defaults(func=cmd_list_shells)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())