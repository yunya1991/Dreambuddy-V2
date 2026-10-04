"""Skill Index Generator — 从 registry.json 自动生成 SKILL_INDEX.md。

替代手写版，保证与 registry.json 同步。
FAIL-OPEN：异常时不崩溃。

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def generate_skill_index(registry_path: Path | str, output_path: Path | str) -> Path:
    """从 registry.json 生成人类可读的 SKILL_INDEX.md。

    Args:
        registry_path: registry.json 路径
        output_path: 输出 SKILL_INDEX.md 路径

    Returns:
        输出文件路径
    """
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    skills = registry.get("skills", [])
    total = registry.get("total_count", len(skills))

    by_category: dict[str, list[dict]] = defaultdict(list)
    status_counts: dict[str, int] = defaultdict(int)
    for s in skills:
        cat = s.get("category", "uncategorized")
        by_category[cat].append(s)
        status_counts[s.get("status", "unknown")] += 1

    lines: list[str] = []
    lines.append("# SKILL Index")
    lines.append("")
    lines.append(f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 总数量: {total} SKILL")
    lines.append("")

    # 概览表
    lines.append("## 概览")
    lines.append("")
    lines.append("| 分类 | 数量 |")
    lines.append("|------|------|")
    for cat, items in sorted(by_category.items()):
        lines.append(f"| {cat} | {len(items)} |")
    lines.append("")

    # 状态分布
    lines.append("## 状态分布")
    lines.append("")
    lines.append("| 状态 | 数量 |")
    lines.append("|------|------|")
    for st, cnt in sorted(status_counts.items()):
        lines.append(f"| {st} | {cnt} |")
    lines.append("")

    # 按分类列出
    for cat, items in sorted(by_category.items()):
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| 名称 | 版本 | 状态 | 描述 |")
        lines.append("|------|------|------|------|")
        for s in sorted(items, key=lambda x: x.get("name", "")):
            desc = s.get("description", "").replace("|", "\\|")
            lines.append(
                f"| {s.get('name', '')} | {s.get('version', '')} | "
                f"{s.get('status', '')} | {desc} |"
            )
        lines.append("")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
