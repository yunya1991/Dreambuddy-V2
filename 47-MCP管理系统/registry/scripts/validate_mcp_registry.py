#!/usr/bin/env python3
"""validate_mcp_registry — 47-MCP registry/mcp_capabilities.yaml 校验器

校验项：
  1. schema_version = 1.1-mcp
  2. shell_id 全局唯一 + 合法枚举 transport/port/domain/read_write/status
  3. tools[].name 在同一 shell 内不重复
  4. 存量壳（status!=planned）shell_path 存在
  5. 每 shell 工具数 ≤ max_tools_per_shell (默认 15)
  6. 聚合 available+degraded 壳总工具数 ≤ max_total_tools (默认 80) — R1 工具面膨胀门禁
  7. write 工具 requires_mandate 必须为 true
  8. annotations.readOnlyHint 与 read_write=write 不冲突
  9. worker_roles（若存在）：引用的 shell_id/tool 必须存在；每角色工具数 ≤
     max_tools_per_shell；Worker 只读（ADR-9/H7）——角色工具集禁止含
     requires_mandate=true 的写工具

用法：
  python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py
  python3 scripts/validate_mcp_registry.py --quiet (CI 模式)
  python3 scripts/validate_mcp_registry.py --registry PATH (非默认路径)
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

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"


class Violation:
    def __init__(self, level: str, path: str, msg: str):
        self.level = level  # "ERR" / "WARN"
        self.path = path
        self.msg = msg

    def __str__(self):
        return f"  [{self.level}] {self.path}: {self.msg}"


def _check(ok: bool, level: str, path: str, msg: str, violations: list[Violation]):
    if not ok:
        violations.append(Violation(level, path, msg))


def validate(registry_path: Path, quiet: bool = False) -> int:
    violations: list[Violation] = []

    if not registry_path.exists():
        print(f"ERR: 注册表文件不存在 {registry_path}")
        return 2

    with open(registry_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        violations.append(Violation("ERR", "root", "YAML 根不是 dict"))
    else:
        # 1. schema_version
        _check(
            data.get("schema_version") == "1.1-mcp",
            "ERR",
            "schema_version",
            f"必须是 1.1-mcp，当前 {data.get('schema_version')!r}",
            violations,
        )

        enums = data.get("enums", {})
        shells = data.get("shells", []) or []
        planned = data.get("planned_shells", []) or []
        all_shells = shells + planned

        # 2. shell_id 全局唯一
        seen_ids = set()
        for s in all_shells:
            sid = s.get("shell_id")
            _check(
                sid and sid not in seen_ids,
                "ERR",
                f"shell_id={sid}",
                f"全局唯一冲突（{sid!r}）" if sid else "缺少 shell_id",
                violations,
            )
            if sid:
                seen_ids.add(sid)

        transport_enum = set(enums.get("transport", []))
        port_enum = set(enums.get("port", []))
        domain_enum = set(enums.get("domain", []))
        rw_enum = set(enums.get("read_write", []))
        status_enum = set(enums.get("status", []))
        env_enum = set(enums.get("envelope_version", []))
        max_tools_per_shell = enums.get("max_tools_per_shell", 10)
        max_total_tools = enums.get("max_total_tools", 80)

        total_active_tools = 0

        for shell in all_shells:
            sid = shell.get("shell_id", "<missing>")
            status = shell.get("status")

            _check(
                status in status_enum,
                "ERR",
                f"{sid}.status",
                f"{status!r} 不在枚举 {status_enum}",
                violations,
            )
            _check(
                shell.get("transport") in transport_enum,
                "ERR",
                f"{sid}.transport",
                f"{shell.get('transport')!r} 不在枚举 {transport_enum}",
                violations,
            )
            _check(
                shell.get("envelope_version") in env_enum,
                "ERR",
                f"{sid}.envelope_version",
                f"{shell.get('envelope_version')!r} 不在枚举 {env_enum}",
                violations,
            )

            # 3. tools[] 同 shell 内 name 不重复
            tools = shell.get("tools", []) or []
            _check(
                len(tools) <= max_tools_per_shell,
                "ERR",
                f"{sid}.tools",
                f"{len(tools)} 超过单壳工具上限 {max_tools_per_shell}（R1 治理）",
                violations,
            )

            seen_names = set()
            for t in tools:
                name = t.get("name")
                _check(
                    name and name not in seen_names,
                    "ERR",
                    f"{sid}.tools.{name}",
                    f"name 重复（{name!r}）" if name else "缺少 name",
                    violations,
                )
                if name:
                    seen_names.add(name)

                _check(
                    t.get("port") in port_enum,
                    "ERR",
                    f"{sid}.tools.{name}.port",
                    f"{t.get('port')!r} 不在枚举 {port_enum}",
                    violations,
                )
                _check(
                    t.get("domain") in domain_enum,
                    "ERR",
                    f"{sid}.tools.{name}.domain",
                    f"{t.get('domain')!r} 不在枚举 {domain_enum}",
                    violations,
                )
                _check(
                    t.get("read_write") in rw_enum,
                    "ERR",
                    f"{sid}.tools.{name}.read_write",
                    f"{t.get('read_write')!r} 不在枚举 {rw_enum}",
                    violations,
                )

                rw = t.get("read_write")
                if rw == "write":
                    _check(
                        t.get("requires_mandate") is True,
                        "ERR",
                        f"{sid}.tools.{name}.requires_mandate",
                        "write 工具必须 requires_mandate=true",
                        violations,
                    )

                ann = t.get("annotations") or {}
                if ann.get("readOnlyHint") is True and rw == "write":
                    violations.append(
                        Violation(
                            "ERR",
                            f"{sid}.tools.{name}.annotations",
                            "readOnlyHint=true 与 read_write=write 冲突",
                        )
                    )

            # 4. 存量壳 path 存在（planned 跳）
            if status != "planned":
                sp = shell.get("shell_path")
                if sp:
                    full_path = REPO_ROOT / sp
                    _check(
                        full_path.exists(),
                        "ERR",
                        f"{sid}.shell_path",
                        f"{sp} 不存在（{full_path}）",
                        violations,
                    )

            if status in ("available", "degraded"):
                total_active_tools += len(tools)

        # 6. 聚合 active 壳总工具数
        _check(
            total_active_tools <= max_total_tools,
            "ERR",
            "total_active_tools",
            f"{total_active_tools} 超过全局软上限 {max_total_tools}（R1 工具面膨胀）",
            violations,
        )

        # B4：单一载体声明
        if data.get("single_source_of_truth") is not True:
            violations.append(
                Violation("WARN", "single_source_of_truth", "建议显式声明 true（B4 单一载体）")
            )

        # 9. worker_roles（46-DSH ADR-4：角色→能力标签唯一载体）
        # 同名工具可能存在于多个壳（如 get_positions：l0.trade-exec / l1.trading），
        # 按角色 shells 解析到正确的壳，而不是让后登记的壳覆盖前者。
        tool_index: dict[str, list[dict]] = {}
        for shell in all_shells:
            for t in shell.get("tools", []) or []:
                if t.get("name"):
                    tool_index.setdefault(t["name"], []).append(
                        {
                            "shell": shell.get("shell_id"),
                            "requires_mandate": t.get("requires_mandate") is True,
                        }
                    )

        for role, spec in (data.get("worker_roles", {}) or {}).items():
            path = f"worker_roles.{role}"
            _check(isinstance(spec, dict), "ERR", path, "角色定义必须是 dict", violations)
            if not isinstance(spec, dict):
                continue
            role_shells = spec.get("shells", []) or []
            role_tools = spec.get("tools", []) or []
            for sid in role_shells:
                _check(
                    sid in seen_ids,
                    "ERR",
                    f"{path}.shells",
                    f"引用的 shell {sid!r} 不存在",
                    violations,
                )
            _check(
                0 < len(role_tools) <= max_tools_per_shell,
                "ERR",
                f"{path}.tools",
                (
                    f"{len(role_tools)} 工具超出每角色上限 {max_tools_per_shell}（ADR-4）"
                    if role_tools
                    else "角色工具集为空"
                ),
                violations,
            )
            for tname in role_tools:
                infos = tool_index.get(tname, [])
                info = next(
                    (i for i in infos if i["shell"] in role_shells),
                    infos[0] if infos else None,
                )
                _check(
                    info is not None,
                    "ERR",
                    f"{path}.tools.{tname}",
                    "工具未在任何 shell 登记",
                    violations,
                )
                if info is None:
                    continue
                _check(
                    info["shell"] in role_shells,
                    "ERR",
                    f"{path}.tools.{tname}",
                    f"工具隶属壳 {info['shell']!r} 未列入角色 shells",
                    violations,
                )
                _check(
                    not info["requires_mandate"],
                    "ERR",
                    f"{path}.tools.{tname}",
                    "Worker 只读（ADR-9/H7）：禁止纳入 requires_mandate=true 写工具",
                    violations,
                )

    # 输出
    if violations:
        errs = [v for v in violations if v.level == "ERR"]
        warns = [v for v in violations if v.level == "WARN"]
        if not quiet:
            print(f"\n注册表校验：{len(errs)} ERR / {len(warns)} WARN")
            for v in violations:
                print(v)
        return 1 if errs else 0

    if not quiet:
        print(
            f"✅ 注册表 OK — {len(shells)} 存量壳 + {len(planned)} 规划壳 / "
            f"{total_active_tools} active 工具 / 上限 {max_total_tools}"
        )
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="校验 47-MCP 契约注册表")
    ap.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    ap.add_argument("--quiet", action="store_true", help="CI 模式，只输出错误摘要")
    args = ap.parse_args()
    sys.exit(validate(Path(args.registry), args.quiet))


if __name__ == "__main__":
    main()
