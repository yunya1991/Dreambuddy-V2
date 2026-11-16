# -*- coding: utf-8 -*-
"""算法注册表校验（TASKS-20261116 T3-3）。

判定项（任一失败即退出 1）：
  1. registry.source.space_version == discovery_space.version；
  2. relation_type 恰好为 R1–R6，id 唯一；
  3. package.id 唯一；relation_type 必须存在且 enabled（或显式 blocked 且包未启用）；
  4. package.methods ⊆ discovery_space.methods；
  5. package.transforms ⊆ discovery_space.transforms；
  6. package.horizons ⊆ discovery_space.targets.horizons；
  7. package.min_n ≥ 250（与 MERS 门禁一致）；
  8. method_roles 覆盖 discovery_space 的全部方法（无孤儿），且角色 ∈ R1–R6；
  9. R6 未启用时不允许存在 enabled 的 R6 包。

用法：
    python3 scripts/validate_algorithm_registry.py
    python3 scripts/validate_algorithm_registry.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import yaml  # noqa: E402

CONFIG_DIR = os.path.join(_MODULE_ROOT, "config")
REGISTRY_PATH = os.path.join(CONFIG_DIR, "algorithm_registry.yaml")
SPACE_PATH = os.path.join(CONFIG_DIR, "discovery_space.yaml")

RELATION_IDS = ("R1", "R2", "R3", "R4", "R5", "R6")
MIN_SAMPLE = 250


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def validate(registry: Dict[str, Any], space: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    source = registry.get("source") or {}
    if int(source.get("space_version", -1)) != int(space.get("version", -2)):
        errors.append(
            f"space_version 不一致: registry={source.get('space_version')} space={space.get('version')}"
        )

    relations = registry.get("relation_types") or []
    ids = [str(item.get("id")) for item in relations]
    if sorted(ids) != sorted(RELATION_IDS):
        errors.append(f"relation_types 必须恰好覆盖 {RELATION_IDS}，实际 {ids}")
    if len(set(ids)) != len(ids):
        errors.append("relation_type id 重复")

    enabled_relations = {
        str(item.get("id")) for item in relations if bool(item.get("enabled", True))
    }
    blocked_relations = {
        str(item.get("id")) for item in relations if not bool(item.get("enabled", True))
    }

    space_methods = [str(item) for item in (space.get("methods") or [])]
    space_transforms = [str(item) for item in (space.get("transforms") or [])]
    space_horizons = [int(item) for item in ((space.get("targets") or {}).get("horizons") or [])]

    packages = registry.get("packages") or []
    package_ids = [str(item.get("id")) for item in packages]
    if len(set(package_ids)) != len(package_ids):
        errors.append("package.id 重复")

    for package in packages:
        pid = str(package.get("id"))
        relation = str(package.get("relation_type"))
        if relation not in ids:
            errors.append(f"{pid}: 未知 relation_type {relation}")
        elif relation in blocked_relations:
            if str(package.get("status", "enabled")) == "enabled":
                errors.append(f"{pid}: {relation} 未启用却存在 enabled 包")
        elif relation not in enabled_relations:
            errors.append(f"{pid}: relation_type {relation} 不可用")

        for method in package.get("methods") or []:
            if str(method) not in space_methods:
                errors.append(f"{pid}: 方法 {method} 不在预注册空间")
        for transform in package.get("transforms") or []:
            if str(transform) not in space_transforms:
                errors.append(f"{pid}: 变换 {transform} 不在预注册空间")
        horizons = [int(item) for item in (package.get("horizons") or [])]
        if not horizons:
            errors.append(f"{pid}: horizons 为空")
        for horizon in horizons:
            if horizon not in space_horizons:
                errors.append(f"{pid}: 期限 {horizon} 不在预注册空间")
        if int(package.get("min_n") or 0) < MIN_SAMPLE:
            errors.append(f"{pid}: min_n < {MIN_SAMPLE}")

    roles = registry.get("method_roles") or {}
    for method in space_methods:
        if method not in roles:
            errors.append(f"method_roles 缺 {method}（发现空间方法必须有归类）")
    for method, mapped in roles.items():
        if str(method) not in space_methods:
            errors.append(f"method_roles 出现空间外方法 {method}")
        if not isinstance(mapped, list) or not mapped:
            errors.append(f"method_roles.{method} 必须是非空列表")
            continue
        for relation in mapped:
            if str(relation) not in RELATION_IDS:
                errors.append(f"method_roles.{method}: 未知关系 {relation}")

    return errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验统计算法注册表")
    parser.add_argument("--registry", default=REGISTRY_PATH)
    parser.add_argument("--space", default=SPACE_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    registry = _load(args.registry)
    space = _load(args.space)
    errors = validate(registry, space)

    summary = {
        "ok": not errors,
        "registry_version": registry.get("version"),
        "space_version": space.get("version"),
        "relation_types": len(registry.get("relation_types") or []),
        "packages": len(registry.get("packages") or []),
        "mapped_methods": len(registry.get("method_roles") or {}),
        "space_methods": len(space.get("methods") or []),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    elif errors:
        print(f"FAIL: {len(errors)} 项")
        for item in errors:
            print(f"  - {item}")
    else:
        print(
            f"ok: {summary['packages']} 包 / {summary['mapped_methods']} 方法 / "
            f"space v{summary['space_version']}"
        )
    return 0 if not errors else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
