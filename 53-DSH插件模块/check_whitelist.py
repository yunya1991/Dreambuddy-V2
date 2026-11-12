#!/usr/bin/env python3
"""P1-2 DSH 插件白名单校验器。

用法:
    python3 53-DSH插件模块/check_whitelist.py --profile sandbox
    python3 53-DSH插件模块/check_whitelist.py --profile headless --json

校验对象: 指定 dsh profile 的 package.json dependencies + cordis.patch.yml 插入条目,
与 plugin_whitelist.yaml 对齐。deny-by-default:
  - 未登记插件 → 违规
  - risk_level=forbidden / 命中 forbidden 通配 → 违规
  - profile 不在 permitted_profiles → 违规
  - 生产 profile 加载未在 sandbox 实测过 / 未验证 FAIL-OPEN 的插件 → 违规

退出码: 0 通过 / 1 存在违规 / 2 配置错误
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from typing import Any, Dict, List

import yaml

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_WHITELIST = os.path.join(_MODULE_DIR, "plugin_whitelist.yaml")
_DEFAULT_DSH_HOME = os.path.join(
    _MODULE_DIR, "..", "1-ARCHITECTURE", "dream-harness-bridge", ".dsh-home"
)

# 官方包与 dsh 内置能力不纳入第三方白名单校验
_CORE_PREFIXES = ("@deepseek-ai/",)


def _is_core(name: str) -> bool:
    return name.startswith(_CORE_PREFIXES)


def _load_whitelist(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError("whitelist 必须是 YAML 映射")
    return doc


def _profile_plugins(profile_dir: str) -> List[str]:
    """收集 profile 实际挂载的第三方插件名(package.json deps ∪ patch insert)。"""
    names: set[str] = set()

    pkg_path = os.path.join(profile_dir, "package.json")
    if os.path.isfile(pkg_path):
        with open(pkg_path, encoding="utf-8") as f:
            pkg = json.load(f)
        for name in pkg.get("dependencies") or {}:
            if not _is_core(name):
                names.add(name)

    patch_path = os.path.join(profile_dir, "cordis.patch.yml")
    if os.path.isfile(patch_path):
        with open(patch_path, encoding="utf-8") as f:
            patches = yaml.safe_load(f) or []
        if isinstance(patches, list):
            for entry in patches:
                if not isinstance(entry, dict):
                    continue
                for item in entry.get("insert") or []:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("id")
                    if isinstance(name, str) and not _is_core(name):
                        names.add(name)
    return sorted(names)


def _match_entry(name: str, entries: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    exact: Dict[str, Any] | None = None
    for entry in entries:
        eid = entry.get("id")
        if not isinstance(eid, str):
            continue
        if eid == name:
            exact = entry
        elif "*" in eid and fnmatch.fnmatch(name, eid) and exact is None:
            exact = entry
    return exact


def check(profile: str, whitelist: Dict[str, Any], plugins: List[str]) -> List[str]:
    entries = whitelist.get("entries") or []
    policies = whitelist.get("policies") or {}
    production = set(policies.get("production_profiles") or [])
    require_sandbox_first = bool(policies.get("require_sandbox_first", False))
    require_fail_open = bool(policies.get("require_fail_open", False))
    default_deny = bool(whitelist.get("default_deny", True))

    violations: List[str] = []
    for name in plugins:
        entry = _match_entry(name, entries)
        if entry is None:
            if default_deny:
                violations.append(f"{name}: 未在白名单登记（default_deny=true）")
            continue

        status = entry.get("status")
        risk = entry.get("risk_level")
        permitted = entry.get("permitted_profiles") or []

        if risk == "forbidden" or status == "forbidden":
            violations.append(f"{name}: risk_level=forbidden，任何 profile 禁止加载")
            continue

        if profile not in permitted:
            violations.append(f"{name}: 不允许加载到 profile={profile}（permitted={permitted}）")
            continue

        if profile in production:
            if require_sandbox_first and not entry.get("sandbox_verified", False):
                violations.append(f"{name}: 未在 sandbox 实测（sandbox_verified=false）")
            if require_fail_open and not entry.get("fail_open_verified", False):
                violations.append(f"{name}: 未验证 FAIL-OPEN（fail_open_verified=false）")
            if status != "approved":
                violations.append(f"{name}: 生产 profile 要求 status=approved，当前={status}")
    return violations


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSH 插件白名单校验")
    parser.add_argument("--profile", required=True, help="dsh profile 名（如 sandbox/headless）")
    parser.add_argument("--dsh-home", default=_DEFAULT_DSH_HOME, help="DSH_HOME 路径")
    parser.add_argument("--whitelist", default=_DEFAULT_WHITELIST, help="白名单 YAML 路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    profile_dir = os.path.join(args.dsh_home, "profiles", args.profile)
    if not os.path.isdir(profile_dir):
        print(f"[whitelist] profile 目录不存在: {profile_dir}", file=sys.stderr)
        return 2

    try:
        whitelist = _load_whitelist(args.whitelist)
    except Exception as e:  # noqa: BLE001
        print(f"[whitelist] 白名单加载失败: {e}", file=sys.stderr)
        return 2

    plugins = _profile_plugins(profile_dir)
    violations = check(args.profile, whitelist, plugins)

    if args.json:
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "plugins": plugins,
                    "violations": violations,
                    "ok": not violations,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"[whitelist] profile={args.profile} 第三方插件 {len(plugins)} 个")
        for name in plugins:
            print(f"  - {name}")
        if violations:
            print(f"[whitelist] ❌ {len(violations)} 项违规:")
            for v in violations:
                print(f"  ! {v}")
        else:
            print("[whitelist] ✅ 全部通过")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
