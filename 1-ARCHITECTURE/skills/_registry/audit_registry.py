#!/usr/bin/env python3
"""SKILL 注册表季度审计（SPEC P2-4）：只读统计，FAIL-OPEN，不改 registry.json。

统计项：
  总数 / 按 status / 按 category / 按 role / 按 tier
  重复同名（跨路径）/ path 指向不存在
  deprecated / archived 数量
  缺 role 或 tier 的条目 / content_hash 缺失数

输出：
  默认：人类可读摘要 + 写入 audit-report.json（含 generated_at）
  --json-only：仅向 stdout 输出 JSON（报告文件仍会写入）

用法：
    python3 1-ARCHITECTURE/skills/_registry/audit_registry.py
    python3 1-ARCHITECTURE/skills/_registry/audit_registry.py --json-only
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REGISTRY = Path(__file__).with_name("registry.json")
REPORT = Path(__file__).with_name("audit-report.json")
SAMPLE_LIMIT = 10


def sorted_counts(counter: Counter) -> dict[str, int]:
    """按数量降序、同数量按名称升序，保证报告可复现对比。"""
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def collect(data: dict) -> dict:
    """从 registry 数据汇总审计统计（纯计算，无副作用）。"""
    skills = data.get("skills", []) or []

    status_counts = Counter(str(s.get("status")) for s in skills)
    category_counts = Counter(str(s.get("category")) for s in skills)
    role_counts = Counter(str(s.get("role")) for s in skills)
    tier_counts = Counter(
        "+".join(t for t in (s.get("tier") or []) if isinstance(t, str)) or "<empty>"
        for s in skills
    )

    # 重复同名（跨路径）：只统计指向 ≥2 个不同 path 的 name
    paths_by_name: dict[str, list[str]] = {}
    for s in skills:
        name = s.get("name")
        if not isinstance(name, str) or not name:
            continue
        paths_by_name.setdefault(name, []).append(str(s.get("path", "")))
    duplicate_names = []
    for name, paths in paths_by_name.items():
        distinct = sorted(set(paths))
        if len(distinct) > 1:
            duplicate_names.append({"name": name, "path_count": len(distinct), "paths": distinct})
    duplicate_names.sort(key=lambda item: item["name"])
    dup_set = {item["name"] for item in duplicate_names}
    duplicate_entries = sum(1 for s in skills if s.get("name") in dup_set)

    # path 在本机不存在
    missing_paths = []
    for s in skills:
        path = str(s.get("path", ""))
        try:
            exists = bool(path) and Path(path).is_file()
        except OSError:
            exists = False  # FAIL-OPEN：异常路径按不存在处理
        if not exists:
            missing_paths.append(path)

    def names_where(predicate) -> list[str]:
        return [str(s.get("name") or "<unnamed>") for s in skills if predicate(s)]

    missing_role = names_where(lambda s: not s.get("role"))
    missing_tier = names_where(lambda s: not isinstance(s.get("tier"), list) or not s.get("tier"))
    missing_role_or_tier = names_where(
        lambda s: not s.get("role") or not isinstance(s.get("tier"), list) or not s.get("tier")
    )
    missing_hash = names_where(lambda s: not s.get("content_hash"))

    deprecated_names = names_where(lambda s: s.get("status") == "deprecated")
    archived_names = names_where(lambda s: s.get("status") == "archived")

    anomalies = []
    if data.get("total_count") != len(skills):
        anomalies.append(f"total_count={data.get('total_count')} 与实际 {len(skills)} 不符")

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "registry_path": str(REGISTRY),
        "schema_version": data.get("schema_version"),
        "declared_total_count": data.get("total_count"),
        "total": len(skills),
        "status_counts": sorted_counts(status_counts),
        "category_counts": sorted_counts(category_counts),
        "role_counts": sorted_counts(role_counts),
        "tier_counts": sorted_counts(tier_counts),
        "duplicate_names": {
            "count": len(duplicate_names),
            "entry_count": duplicate_entries,
            "entries": duplicate_names,
        },
        "missing_path": {
            "count": len(missing_paths),
            "samples": missing_paths[:SAMPLE_LIMIT],
        },
        "deprecated_archived": {
            "deprecated": status_counts.get("deprecated", 0),
            "archived": status_counts.get("archived", 0),
            "total": status_counts.get("deprecated", 0) + status_counts.get("archived", 0),
            "names": deprecated_names + archived_names,
        },
        "missing_fields": {
            "role": {"count": len(missing_role), "names": missing_role},
            "tier": {"count": len(missing_tier), "names": missing_tier},
            "role_or_tier": {"count": len(missing_role_or_tier), "names": missing_role_or_tier},
            "content_hash": {"count": len(missing_hash), "names": missing_hash},
        },
        "anomalies": anomalies,
    }


def print_summary(report: dict) -> None:
    """打印人类可读摘要（仅编排输出，不参与计算）。"""
    dup = report["duplicate_names"]
    missing_path = report["missing_path"]
    dep_arch = report["deprecated_archived"]
    fields = report["missing_fields"]

    print("=== SKILL Registry 季度审计 ===")
    print(f"生成时间: {report['generated_at']}")
    print(
        f"registry: {report['registry_path']}  schema={report['schema_version']}  "
        f"声明条数={report['declared_total_count']}  实际条数={report['total']}"
    )
    print(f"总数: {report['total']}")
    print("status:", report["status_counts"])
    print("category:", report["category_counts"])
    print("role:", report["role_counts"])
    print("tier:", report["tier_counts"])
    print(f"重复同名(跨路径): {dup['count']} 组 / 涉及 {dup['entry_count']} 条")
    print(f"path 指向不存在: {missing_path['count']} / {report['total']}")
    if missing_path["samples"]:
        print("  样例:", missing_path["samples"][0])
    print(
        f"deprecated/archived: deprecated={dep_arch['deprecated']} "
        f"archived={dep_arch['archived']}（合计 {dep_arch['total']}）"
    )
    print(
        f"缺 role: {fields['role']['count']}  缺 tier: {fields['tier']['count']}  "
        f"缺 role|tier: {fields['role_or_tier']['count']}"
    )
    print(f"content_hash 缺失: {fields['content_hash']['count']}")
    for item in report["anomalies"]:
        print(f"⚠️ {item}")
    print(f"报告已写入: {REPORT}")


def main() -> int:
    json_only = "--json-only" in sys.argv[1:]
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        report = collect(data)
    except Exception as exc:  # FAIL-OPEN：审计失败不阻断流水线
        print(f"[audit] 读取/统计失败: {exc}", file=sys.stderr)
        return 0

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    try:
        REPORT.write_text(payload + "\n", encoding="utf-8")
    except OSError as exc:  # FAIL-OPEN：写报告失败仅提示
        print(f"[audit] 写报告失败: {exc}", file=sys.stderr)

    if json_only:
        print(payload)
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
