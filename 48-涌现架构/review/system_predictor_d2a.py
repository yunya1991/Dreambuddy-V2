#!/usr/bin/env python3
"""D2-A 系统预测器：AST 导入复原（architecture recovery from evidence）。

契约（与 run_d2a.py `_run_system` 对齐）：
  - stdin: snapshot JSON（含 module, kept_nodes）
  - stdout: JSONL，每行 {"src": str, "dst": str, "kind": "import"}

策略：对每个保留的 python_file，解析 AST 收集 import 模块名，
按架构图构建器相同的解析逻辑（相对/全仓路径匹配）映射为仓库内路径；
若解析路径落在扣留模块前缀下，则输出预测边。

比 B0/B1（文本相似度）更精确：直接依据 import 语句而非词频。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


def module_to_rel(module: str, py_set: set[str], anchor: str) -> str | None:
    """把 import 模块名映射为仓库内文件相对路径（复刻 build_d2_architecture_graph）。"""
    parts = module.split(".")
    anchor_parts = Path(anchor).parent.parts
    for up in range(len(anchor_parts) + 1):
        prefix = anchor_parts[: len(anchor_parts) - up] if up else anchor_parts
        cand = Path(*prefix, *parts) if prefix else Path(*parts)
        for suffix in (".py", "/__init__.py"):
            rel = cand.as_posix() + suffix
            if rel in py_set:
                return rel
    cand = Path(*parts)
    for suffix in (".py", "/__init__.py"):
        rel = cand.as_posix() + suffix
        if rel in py_set:
            return rel
    return None


def collect_imports(tree: ast.AST) -> list[str]:
    """收集 AST 中所有 import 模块名（含 from ... import ... 的 from 部分）。"""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def module_of(path: str) -> str:
    """复刻 holdout.module_of：二级目录粒度。"""
    parts = path.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="仓库根目录绝对路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snap = json.loads(sys.stdin.read())
    module = snap["module"]
    kept_py = [n["id"] for n in snap.get("kept_nodes", []) if n.get("type") == "python_file"]

    # 全仓 .py 相对路径集（用于 import 解析；扣留模块文件虽不在快照，但物理存在）
    all_py: set[str] = set()
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        # 跳过常见排除目录
        if any(
            seg in {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
            for seg in rel.split("/")
        ):
            continue
        all_py.add(rel)

    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for rel in kept_py:
        full = root / rel
        if not full.exists():
            continue
        try:
            tree = ast.parse(full.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, ValueError):
            continue
        for imp in collect_imports(tree):
            resolved = module_to_rel(imp, all_py, rel)
            if resolved is None:
                continue
            if module_of(resolved) == module:
                key = (rel, resolved)
                if key not in seen:
                    seen.add(key)
                    edges.append(key)

    for src, dst in sorted(edges):
        sys.stdout.write(json.dumps({"src": src, "dst": dst, "kind": "import"}) + "\n")


if __name__ == "__main__":
    main()
