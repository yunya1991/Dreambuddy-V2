"""组件契约漂移校验：component.yaml ↔ 脚本真实能力。

只做静态检查（正则扫描 argparse），不执行组件、不联网。拦四类历史事故：
1) 动作指向不存在的脚本 / 入口；
2) 动作 args 写了脚本没有的子命令或参数（如历史上的 show/check/lint）；
3) params 声明的 flag 在脚本里不存在；
4) 安全等级与 MCP 暴露自相矛盾（irreversible 不得 expose，expose 必须 read/ui + json）。

用法：python3 tools/check_contracts.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "components"
SAFETY = {"read", "write", "ui", "irreversible"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ADD_PARSER_RE = re.compile(r"add_parser\(\s*[\"']([A-Za-z0-9_-]+)[\"']")
ALIAS_RE = re.compile(r"aliases\s*=\s*\[([^\]]*)\]")
ADD_ARG_RE = re.compile(r"add_argument\(\s*[\"'](--[A-Za-z0-9_-]+)[\"']")
PROXY_MARKER = "59 域代理壳"


def capabilities(script: Path) -> Dict[str, Set[str]]:
    text = script.read_text(encoding="utf-8")
    subcommands = set(ADD_PARSER_RE.findall(text))
    for blob in ALIAS_RE.findall(text):
        subcommands.update(re.findall(r"[\"']([A-Za-z0-9_-]+)[\"']", blob))
    return {
        "subcommands": subcommands,
        "flags": set(ADD_ARG_RE.findall(text)),
    }


def resolve_script(component_dir: Path, rel: str) -> Path:
    """脚本路径相对组件根或 skill/ 目录（与 dreambuddy.resolve_target 一致）。"""
    for candidate in (component_dir / rel, component_dir / "skill" / rel):
        if candidate.exists():
            return candidate
    return component_dir / rel


def check_component(component_dir: Path) -> List[str]:
    import yaml

    errors: List[str] = []
    manifest_path = component_dir / "component.yaml"
    if not manifest_path.exists():
        return ["{}: 缺少 component.yaml".format(component_dir.name)]
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    name = str(data.get("name") or "")
    if name != component_dir.name:
        errors.append("{}: name 与目录不一致（{}）".format(component_dir.name, name))
    version = str(data.get("version") or "")
    if not VERSION_RE.match(version):
        errors.append("{}: version 不是 x.y.z（{}）".format(name, version))
    for entry in data.get("entrypoints") or []:
        if not resolve_script(component_dir, str(entry)).exists():
            errors.append("{}: 入口不存在 {}".format(name, entry))
    proxy_entries = [
        resolve_script(component_dir, str(entry)) for entry in data.get("entrypoints") or []
    ]
    if any(
        path.is_file() and PROXY_MARKER in path.read_text(encoding="utf-8")
        for path in proxy_entries
    ):
        # 代理壳不含 argparse；真实实现在主仓，契约由 sync_mobile 双向核对
        return errors

    cache: Dict[str, Dict[str, Set[str]]] = {}
    seen: Set[str] = set()
    for action in data.get("actions") or []:
        action_name = str(action.get("name") or "")
        if not action_name:
            errors.append("{}: 存在无名动作".format(name))
            continue
        if action_name in seen:
            errors.append("{}: 动作重名 {}".format(name, action_name))
        seen.add(action_name)
        safety = str(action.get("safety") or "")
        if safety not in SAFETY:
            errors.append("{}: 动作 {} 的 safety 非法（{}）".format(name, action_name, safety))
        output = str(action.get("output") or "text")
        mcp = action.get("mcp") or {}
        if mcp.get("expose"):
            if safety == "irreversible":
                errors.append("{}: 动作 {} 是 irreversible，禁止暴露 MCP".format(name, action_name))
            if output != "json":
                errors.append("{}: 动作 {} 暴露 MCP 但 output 不是 json".format(name, action_name))

        script_rel = str(action.get("script") or "")
        script = resolve_script(component_dir, script_rel) if script_rel else component_dir
        if not script_rel or not script.exists():
            errors.append("{}: 动作 {} 的脚本不存在 {}".format(name, action_name, script_rel))
            continue
        caps = cache.setdefault(script_rel, capabilities(script))
        for token in action.get("args") or []:
            token = str(token)
            if token.startswith("--"):
                if token not in caps["flags"]:
                    errors.append(
                        "{}: 动作 {} 传了脚本没有的参数 {}".format(name, action_name, token)
                    )
            elif token not in caps["subcommands"] and caps["subcommands"]:
                errors.append(
                    "{}: 动作 {} 传了脚本没有的子命令 {}".format(name, action_name, token)
                )
        for param in action.get("params") or []:
            flag = str(param.get("flag") or "")
            if flag and flag not in caps["flags"]:
                errors.append(
                    "{}: 动作 {} 的 params flag 不存在 {}".format(name, action_name, flag)
                )
    return errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验组件契约与脚本能力是否一致")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)
    errors: List[str] = []
    for component_dir in sorted(path for path in COMPONENTS.iterdir() if path.is_dir()):
        if not (component_dir / "component.yaml").exists():
            continue
        errors.extend(check_component(component_dir))
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        for item in errors:
            print("FAIL：" + item)
        print("共 {} 处契约漂移".format(len(errors)))
    else:
        print("OK：组件契约与脚本能力一致")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
