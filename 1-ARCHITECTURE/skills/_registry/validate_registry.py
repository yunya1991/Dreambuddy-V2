#!/usr/bin/env python3
"""registry.json schema 1.1 校验（SPEC P0-1 / §3.3 治理规则）。

硬错误（exit 1）：
  E1 schema_version != "1.1"
  E2 total_count 与实际条数不符
  E3 缺 name / content_hash
  E4 role 不在枚举内
  E5 tier 为空或含非法端
  E6 category 不在白名单

软告警（不影响退出码，列入人工复核清单）：
  W1 name 重复（同 category+role 下多路径同名）
  W2 path 在本机不存在（历史路径漂移，多为 /home/luke 旧绝对路径）
  W3 同一 base name 同时存在多版本（-v2 等），需确认互斥性

用法：
    python3 1-ARCHITECTURE/skills/_registry/validate_registry.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REGISTRY = Path(__file__).with_name("registry.json")

ROLE_ENUM = {"researcher", "trader", "risk", "operator", "coordinator"}
TIER_ENUM = {"local", "github", "cloud"}
CATEGORY_ENUM = {
    "trading",
    "research",
    "tooling",
    "orchestration",
    "cognition",
    "knowledge",
    "memory",
    "meta",
    "core",
    "governance",
    "support",
    "trigger",
    "collaboration",
}

VERSION_SUFFIX = re.compile(r"-v\d+$")


def main() -> int:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    skills = data.get("skills", [])
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "1.1":
        errors.append(f"E1 schema_version={data.get('schema_version')!r}，应为 '1.1'")
    if data.get("total_count") != len(skills):
        errors.append(f"E2 total_count={data.get('total_count')} 与实际 {len(skills)} 不符")

    for skill in skills:
        name = skill.get("name", "<unnamed>")
        role = skill.get("role")
        tier = skill.get("tier")
        category = skill.get("category")

        if not name or not skill.get("content_hash"):
            errors.append(f"E3 {name}: 缺 name 或 content_hash")
        if role not in ROLE_ENUM:
            errors.append(f"E4 {name}: role={role!r} 不在 {sorted(ROLE_ENUM)}")
        if not isinstance(tier, list) or not tier or not set(tier) <= TIER_ENUM:
            errors.append(f"E5 {name}: tier={tier!r} 非 {sorted(TIER_ENUM)} 的非空子集")
        if category not in CATEGORY_ENUM:
            errors.append(f"E6 {name}: category={category!r} 不在白名单")

    # W1 duplicate name
    name_counts = Counter(s.get("name") for s in skills)
    for name, count in name_counts.items():
        if count > 1:
            paths = [s.get("path", "") for s in skills if s.get("name") == name]
            warnings.append(f"W1 重复 name {name} x{count}: {paths}")

    # W2 path missing locally
    missing = [s.get("path", "") for s in skills if not Path(s.get("path", "")).is_file()]
    if missing:
        warnings.append(f"W2 {len(missing)}/{len(skills)} 条 path 在本机不存在（历史绝对路径漂移）")

    # W3 base name 多版本共存（只在 base 对应 ≥2 个不同 name 时才报，避免与 W1 重复）
    base_names: dict[str, set[str]] = {}
    for s in skills:
        base = VERSION_SUFFIX.sub("", s.get("name", ""))
        if base:
            base_names.setdefault(base, set()).add(s.get("name", ""))
    for base, names in base_names.items():
        if len(names) > 1:
            warnings.append(f"W3 base={base} 存在 {len(names)} 个版本共存: {sorted(names)}")

    print(f"校验对象: {REGISTRY}  条数={len(skills)}  schema={data.get('schema_version')}")
    print("role 分布:", dict(Counter(s.get("role") for s in skills)))
    print("tier 分布:", dict(Counter("+".join(s.get("tier", [])) for s in skills)))

    if warnings:
        print(f"\n软告警 {len(warnings)} 条（不影响通过）:")
        for item in warnings:
            print("  " + item)
    if errors:
        print(f"\n硬错误 {len(errors)} 条:")
        for item in errors:
            print("  " + item)
        return 1

    print("\n✅ registry schema 1.1 校验通过（0 硬错误）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
