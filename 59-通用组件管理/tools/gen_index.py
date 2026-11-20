#!/usr/bin/env python3
"""由 components/*/component.yaml 生成 INDEX.md 的组件登记表（SPEC §2.1 第 6 条）。

用法:
    python3 tools/gen_index.py --check   # 默认：只比对，有漂移退出 1
    python3 tools/gen_index.py --write   # 原地重写生成块

P2 迁移前 components/ 不存在时直接跳过（退出 0）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：需要 PyYAML（python3 -m pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
INDEX = ROOT / "INDEX.md"
MARK_BEGIN = "<!-- GEN:COMPONENT-REGISTRY:BEGIN -->"
MARK_END = "<!-- GEN:COMPONENT-REGISTRY:END -->"
HEADER = [
    "| 组件 | 目录 | 版本 | 生命周期 | 分发变体 | 入口 |",
    "|---|---|---|---|---|---|",
]


def load_components() -> list[tuple[str, dict]]:
    if not COMPONENTS.is_dir():
        return []
    items = []
    for path in sorted(COMPONENTS.iterdir()):
        manifest = path / "component.yaml"
        if not path.is_dir() or not manifest.is_file():
            continue
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        items.append((path.name, data if isinstance(data, dict) else {}))
    return items


def build_block(items: list[tuple[str, dict]]) -> str:
    lines = [MARK_BEGIN, *HEADER]
    for name, manifest in items:
        display = manifest.get("display_name") or name
        products = "、".join(manifest.get("products") or []) or "—"
        entries = len(manifest.get("entrypoints") or [])
        lines.append(
            "| {} `{}` | components/{}/ | v{} | {} | {} | {} 个 |".format(
                display,
                name,
                name,
                manifest.get("version") or "0.0.0",
                manifest.get("lifecycle") or "draft",
                products,
                entries,
            )
        )
    lines.append(MARK_END)
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    start = text.find(MARK_BEGIN)
    end = text.find(MARK_END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(
            "E_INDEX：INDEX.md 缺少生成块标记，请先插入 {} 与 {}".format(MARK_BEGIN, MARK_END)
        )
    return text[:start] + block + text[end + len(MARK_END) :]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 INDEX 组件登记表")
    parser.add_argument("--write", action="store_true", help="原地写入 INDEX.md")
    parser.add_argument("--check", action="store_true", help="只比对（默认行为）")
    args = parser.parse_args(argv)

    items = load_components()
    if not items:
        print("提示：components/ 尚未迁移（P2），暂无可生成的组件登记项。")
        return 0
    if not INDEX.is_file():
        print("E_INDEX：缺少 INDEX.md", file=sys.stderr)
        return 2

    current = INDEX.read_text(encoding="utf-8")
    updated = replace_block(current, build_block(items))

    if args.write:
        INDEX.write_text(updated, encoding="utf-8")
        print("已更新 INDEX.md 组件登记表：{} 个组件".format(len(items)))
        return 0

    if updated == current:
        print("INDEX.md 组件登记表已同步（{} 个组件）".format(len(items)))
        return 0
    print("INDEX.md 组件登记表存在漂移，运行 --write 重新生成。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
