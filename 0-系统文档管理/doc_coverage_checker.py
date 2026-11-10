"""0-系统文档管理/doc_coverage_checker.py — 文档覆盖率与断链检查。

设计依据：架构图中部分 python_file 节点无对应 markdown_doc，需统计文档
覆盖率与断链清单；核心模块缺文档时生成 markdown 骨架。

FAIL-OPEN：graph 缺字段时按空处理，不抛异常。仅依赖 stdlib。
"""

from collections import defaultdict
from pathlib import Path

DOC_NAMES = ("README.md", "SKILL.md")


def find_doc_for_module(module_path, doc_dirs=None):
    """查找模块对应 markdown：同目录 README.md/SKILL.md/同名 .md，其次 doc_dirs。

    返回命中路径字符串或 None。
    """
    module_path = Path(module_path)
    candidates = [module_path.parent / name for name in DOC_NAMES]
    candidates.append(module_path.with_suffix(".md"))
    for doc_dir in doc_dirs or []:
        doc_dir = Path(doc_dir)
        candidates.append(doc_dir / f"{module_path.stem}.md")
        candidates.append(doc_dir / module_path.parent.name / f"{module_path.stem}.md")
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def check_coverage(graph, core_dirs=None, doc_dirs=None):
    """按目录聚合 python_file 节点，检查核心目录 README.md/SKILL.md 存在性。

    返回 dict：
    - coverage：有文档核心目录数 / 核心目录总数
    - broken_links：无对应 markdown 的 python_file 清单（排序）
    - missing_core：缺文档核心目录清单（排序）
    """
    nodes = (graph or {}).get("nodes", []) or []
    py_files = [
        n.get("id")
        for n in nodes
        if isinstance(n, dict) and n.get("type") == "python_file" and n.get("id")
    ]

    by_dir = defaultdict(list)
    for fid in py_files:
        parts = Path(fid).parts
        top = parts[0] if len(parts) > 1 else "."
        by_dir[top].append(fid)

    core_dirs = list(core_dirs) if core_dirs is not None else sorted(by_dir)
    documented = 0
    missing_core = []
    for d in core_dirs:
        dpath = Path(d)
        if any((dpath / name).is_file() for name in DOC_NAMES):
            documented += 1
        else:
            missing_core.append(d)

    broken_links = sorted(fid for fid in py_files if find_doc_for_module(fid, doc_dirs) is None)

    total = len(core_dirs)
    return {
        "coverage": (documented / total) if total else 0.0,
        "broken_links": broken_links,
        "missing_core": sorted(missing_core),
        "core_total": total,
        "python_file_total": len(py_files),
    }


def generate_doc_skeleton(dir_path, imports=None):
    """生成 markdown 骨架文本（目录名 + import 边摘要），只返回文本不写文件。"""
    dir_path = Path(dir_path)
    imports = [str(imp) for imp in (imports or [])]
    lines = [f"# {dir_path.name}", "", "## 依赖（import 边）", ""]
    if imports:
        lines.extend(f"- `{imp}`" for imp in imports)
    else:
        lines.append("- （无）")
    lines.append("")
    return "\n".join(lines)
