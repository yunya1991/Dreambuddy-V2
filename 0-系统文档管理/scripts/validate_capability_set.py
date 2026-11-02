#!/usr/bin/env python3
"""validate_capability_set — 0-系统文档管理/l0_capability_set.v1.yaml 校验器

校验项：
  1. schema_version = 1.0
  2. worker_roles[].tool_count == len(tools)
  3. 每 role tools ≤ limits.max_tools_per_role (10)
  4. **核心交叉引用**：所有 shell_id.tool_name 必须在 47 mcp_capabilities.yaml 里存在
     （漂移即 ERR —— 防本文件"凭空发明"工具）
  5. registry_ref.path 存在 + registry_version/schema_version 与被引用文件一致

用法：
  python3 0-系统文档管理/scripts/validate_capability_set.py
  python3 scripts/validate_capability_set.py --quiet (CI 模式)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERR: pyyaml 未安装 — pip install pyyaml")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT = REPO_ROOT / "0-系统文档管理" / "l0_capability_set.v1.yaml"


class Violation:
    def __init__(self, level: str, path: str, msg: str):
        self.level = level
        self.path = path
        self.msg = msg

    def __str__(self):
        return f"  [{self.level}] {self.path}: {self.msg}"


def validate(cap_set_path: Path, quiet: bool = False) -> int:
    violations: list[Violation] = []

    if not cap_set_path.exists():
        print(f"ERR: 能力集文件不存在 {cap_set_path}")
        return 2

    with open(cap_set_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        violations.append(Violation("ERR", "root", "YAML 根不是 dict"))
        data = {}

    # 1. schema_version
    if data.get("schema_version") != "1.0":
        violations.append(
            Violation("ERR", "schema_version", f"必须是 1.0，当前 {data.get('schema_version')!r}")
        )

    # 5. registry_ref 存在性 + 版本匹配
    reg_ref = data.get("registry_ref", {}) or {}
    reg_path_rel = reg_ref.get("path")
    reg_expected_ver = reg_ref.get("registry_version")
    reg_expected_schema = reg_ref.get("schema_version")

    if reg_path_rel:
        reg_path = REPO_ROOT / reg_path_rel
        if not reg_path.exists():
            violations.append(
                Violation("ERR", "registry_ref.path", f"47 registry 不存在 {reg_path}")
            )
        else:
            with open(reg_path, encoding="utf-8") as f:
                reg_data = yaml.safe_load(f) or {}

            if reg_data.get("registry_version") != reg_expected_ver:
                violations.append(
                    Violation(
                        "WARN",
                        "registry_ref.registry_version",
                        f"本文件期待 {reg_expected_ver!r}，"
                        f"47 registry 实际 {reg_data.get('registry_version')!r}",
                    )
                )
            if reg_data.get("schema_version") != reg_expected_schema:
                violations.append(
                    Violation(
                        "WARN",
                        "registry_ref.schema_version",
                        f"本文件期待 {reg_expected_schema!r}，"
                        f"47 registry 实际 {reg_data.get('schema_version')!r}",
                    )
                )

            # 构建注册表查找索引：shell_id → {tool_name → ...}
            reg_shell_tools: dict[str, set[str]] = {}
            for shell in reg_data.get("shells", []) or []:
                sid = shell.get("shell_id")
                tools = {t.get("name") for t in (shell.get("tools", []) or []) if t.get("name")}
                if sid:
                    reg_shell_tools[sid] = tools
            for shell in reg_data.get("planned_shells", []) or []:
                sid = shell.get("shell_id")
                tools = {t.get("name") for t in (shell.get("tools", []) or []) if t.get("name")}
                if sid:
                    reg_shell_tools.setdefault(sid, set()).update(tools)
    else:
        reg_shell_tools = {}

    roles = data.get("worker_roles", []) or []
    limits = data.get("limits", {}) or {}
    max_tools_per_role = limits.get("max_tools_per_role", 10)

    all_used_tools: list[tuple[str, str]] = []

    for role in roles:
        rid = role.get("role_id", "<missing>")
        tools = role.get("tools", []) or []
        declared_count = role.get("tool_count")

        # 2. tool_count 声明 = 实际 tools 数
        if declared_count is not None and declared_count != len(tools):
            violations.append(
                Violation(
                    "ERR",
                    f"worker_roles.{rid}.tool_count",
                    f"声明 {declared_count} ≠ 实际 {len(tools)}",
                )
            )

        # 3. 工具上限
        if len(tools) > max_tools_per_role:
            violations.append(
                Violation(
                    "ERR",
                    f"worker_roles.{rid}.tools",
                    f"{len(tools)} 超过单角色上限 {max_tools_per_role}（R1 治理）",
                )
            )

        # 4. 交叉引用
        for idx, t in enumerate(tools):
            sid = t.get("shell")
            tname = t.get("tool")
            key = f"{rid}.tools[{idx}]({sid}.{tname})"

            if not sid or not tname:
                violations.append(Violation("ERR", key, "缺少 shell 或 tool"))
                continue

            all_used_tools.append((sid, tname))

            if reg_shell_tools:
                if sid not in reg_shell_tools:
                    violations.append(
                        Violation("ERR", key, f"shell_id={sid!r} 在 47 registry 不存在")
                    )
                elif tname not in reg_shell_tools[sid]:
                    violations.append(
                        Violation("ERR", key, f"tool={tname!r} 不在 shell {sid!r} 的工具列表")
                    )

        # 同角色内 shell.tool 不重复
        seen = set()
        for t in tools:
            pair = (t.get("shell"), t.get("tool"))
            if pair in seen:
                violations.append(Violation("ERR", f"worker_roles.{rid}.tools", f"工具重复 {pair}"))
            seen.add(pair)

    # 输出
    if violations:
        errs = [v for v in violations if v.level == "ERR"]
        warns = [v for v in violations if v.level == "WARN"]
        if not quiet:
            print(f"\n能力集校验：{len(errs)} ERR / {len(warns)} WARN")
            for v in violations:
                print(v)
        return 1 if errs else 0

    if not quiet:
        total = len(all_used_tools)
        unique = len(set(all_used_tools))
        print(
            f"✅ 能力集 OK — {len(roles)} 角色 / {total} 引用 / {unique} 唯一工具 / "
            f"交叉引用已对齐 47 registry"
        )
    return 0


def main():
    ap = argparse.ArgumentParser(description="校验 L0 能力集（交叉引用 47 registry）")
    ap.add_argument("--cap-set", default=str(DEFAULT))
    ap.add_argument("--quiet", action="store_true", help="CI 模式")
    args = ap.parse_args()
    sys.exit(validate(Path(args.cap_set), args.quiet))


if __name__ == "__main__":
    main()
