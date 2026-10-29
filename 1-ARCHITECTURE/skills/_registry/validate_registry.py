#!/usr/bin/env python3
"""registry.json schema 1.1 校验（SPEC P0-1 / §3.3 治理规则）。

硬错误（exit 1）：
  E1 schema_version != "1.1"
  E2 total_count 与实际条数不符
  E3 缺 name / content_hash
  E4 role 不在枚举内
  E5 tier 为空或含非法端
  E6 category 不在白名单
  E7 depends_on 依赖环（按 name/id 建图，DFS 检出并输出环路径）
  E8 互斥组冲突（W4）：同 category+role+mutex_group 的条目不得同时 active
     （任务书中的 E4 编号已被 role 枚举占用，故改记为 E8，规则语义不变）

软告警（不影响退出码，列入人工复核清单）：
  W1 name 重复（同 category+role 下多路径同名）
  W2 path 在本机不存在（历史路径漂移，多为 /home/luke 旧绝对路径）
  W3 同一 base name 同时存在多版本（-v2 等），需确认互斥性
  W4 互斥组（mutex_group）规则，冲突时以硬错误 E8 报出；未声明的条目跳过

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


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """DFS 三色标记检测依赖环，返回规范化后的环路径（最小名字作起点）。

    同一环只报一次（环内旋转视为等价），不追求枚举全部初等环。
    """
    state: dict[str, int] = {}  # 0/缺省=未访问, 1=栈中, 2=已完成
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def canonical(cycle: list[str]) -> tuple[str, ...]:
        pivot = min(range(len(cycle)), key=lambda i: cycle[i])
        return tuple(cycle[pivot:] + cycle[:pivot])

    def dfs(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            st = state.get(nxt, 0)
            if st == 0:
                dfs(nxt)
            elif st == 1:
                # 回边命中栈中节点 → 栈内该节点到当前节点即一个环
                idx = stack.index(nxt)
                key = canonical(stack[idx:])
                if key not in seen:
                    seen.add(key)
                    cycles.append(list(key))
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            dfs(node)
    return cycles


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

    # W4/E8 互斥组：同 category+role+mutex_group 的条目不得同时 active
    mutex_declared = 0
    active_mutex: dict[tuple[str, str, str], list[str]] = {}
    for s in skills:
        group = s.get("mutex_group")
        if not isinstance(group, str) or not group.strip():
            continue  # 未声明 mutex_group 的条目直接跳过，不参与判定（不误报）
        mutex_declared += 1
        if s.get("status") != "active":
            continue
        key = (str(s.get("category")), str(s.get("role")), group.strip())
        active_mutex.setdefault(key, []).append(str(s.get("name", "<unnamed>")))
    for key in sorted(active_mutex, key=str):
        names = active_mutex[key]
        if len(names) > 1:
            errors.append(
                "E8 互斥组冲突 category={} role={} mutex_group={}: {} 同时 active".format(
                    key[0], key[1], key[2], names
                )
            )

    # E7 依赖环：depends_on 可为字符串或数组，元素可能是 name 或 id
    name_index = {s.get("name") for s in skills if isinstance(s.get("name"), str) and s.get("name")}
    id_to_name: dict[str, str] = {}
    for s in skills:
        sid, name = s.get("id"), s.get("name")
        if isinstance(sid, str) and sid and isinstance(name, str) and name:
            id_to_name[sid] = name
    graph: dict[str, list[str]] = {}
    unresolved = 0
    for s in skills:
        name = s.get("name")
        if not isinstance(name, str) or not name:
            continue
        deps = s.get("depends_on")
        if isinstance(deps, str):
            deps = [deps]
        elif not isinstance(deps, list):
            deps = []
        targets = []
        for dep in deps:
            if not isinstance(dep, str) or not dep.strip():
                continue
            dep = dep.strip()
            target = dep if dep in name_index else id_to_name.get(dep)
            if target is None:
                unresolved += 1  # registry 外的依赖（如 bsk/hermes-*），不参与环检测
                continue
            targets.append(target)
        if targets:
            graph.setdefault(name, []).extend(targets)
    # 同名多路径条目共用同一节点，去重保序
    for node in graph:
        graph[node] = list(dict.fromkeys(graph[node]))
    cycles = find_cycles(graph)
    for cycle in cycles:
        errors.append("E7 依赖环: " + " -> ".join(cycle + [cycle[0]]))

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
    print(
        f"依赖图: {len(graph)} 个节点 / {sum(len(v) for v in graph.values())} 条边，未解析外部依赖 {unresolved} 个"
    )
    print(f"互斥组: {mutex_declared} 条声明 mutex_group")

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
