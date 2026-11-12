#!/usr/bin/env python3
"""生成 D2 统一 ArchitectureGraph 基线（P0-3）。

只读扫描仓库源码与文档，产出：
  - architecture_graph.json : 节点 + 边（确定性排序，可复现 sha256）
  - graph_summary.json      : 规模/类型分布/校验结果
  - manifest.json           : git commit、sha256、字节数、生成参数

设计约束（SPEC-EMERGENCE-3D v0.4 §2.2 / baselines/README）：
  - FAIL-OPEN：单文件解析失败跳过并计数，不中断整体构建
  - Python-only、函数名级调用边、Markdown 链接 doc_ref 边
  - 闭合校验：所有边端点必须在节点集合内（外部依赖建 external 节点吸收）
  - 不改任何既有域代码；产物写入 48-涌现架构/baselines/artifacts/
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "artifacts" / "d2_architecture_graph"

# 不扫描的目录（运行时/依赖/生成物）
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".trae-tmp",
    ".workbuddy",
    ".cognitive",
    "dist",
    "build",
    ".next",
    "artifacts",
    ".bsk-home",
    ".arch-map",  # 架构复盘产物（快照 md/json），非架构节点；否则每轮复盘自造 orphan
    ".runs",  # dreamos-dev run 工作目录（运行产物），非架构节点
}

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")


def _iter_files(root: Path, scopes: list[str]) -> tuple[list[Path], list[Path]]:
    """收集 scope 内的 .py / .md 文件。"""
    py_files: list[Path] = []
    md_files: list[Path] = []
    roots = [root / s for s in scopes] if scopes else [root]
    for base in roots:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                if name.endswith(".py"):
                    py_files.append(p)
                elif name.endswith(".md"):
                    md_files.append(p)
    return sorted(set(py_files)), sorted(set(md_files))


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _module_to_rel(module: str, py_set: set[str], anchor: str) -> str | None:
    """把 import 模块名映射为仓库内文件相对路径；失败返回 None。"""
    parts = module.split(".")
    anchor_parts = Path(anchor).parent.parts
    # 自 anchor 所在包逐级向上尝试（近似相对导入解析）
    for up in range(len(anchor_parts) + 1):
        prefix = anchor_parts[: len(anchor_parts) - up] if up else anchor_parts
        cand = Path(*prefix, *parts) if prefix else Path(*parts)
        for suffix in (".py", "/__init__.py"):
            rel = cand.as_posix() + suffix
            if rel in py_set:
                return rel
    # 全仓顶层匹配
    cand = Path(*parts)
    for suffix in (".py", "/__init__.py"):
        rel = cand.as_posix() + suffix
        if rel in py_set:
            return rel
    return None


def _parse_py(path: Path, py_set: set[str], anchor: str) -> dict:
    """解析单个 py 文件：原始 import 模块名 + 函数定义 + 调用名。FAIL-OPEN。"""
    out: dict = {"raw_imports": [], "defs": set(), "calls": set(), "error": None}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out["raw_imports"].append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out["raw_imports"].append(node.module)
            elif node.level:  # from . import x → 近似为同包模块
                for a in node.names:
                    out["raw_imports"].append(a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["defs"].add(node.name)
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out["calls"].add(f.id)
            elif isinstance(f, ast.Attribute):
                out["calls"].add(f.attr)
    return out


def build_graph(root: Path, scopes: list[str]) -> dict:
    """构建 ArchitectureGraph。返回 dict(nodes/edges/parse_errors/dangling_edges)。"""
    py_files, md_files = _iter_files(root, scopes)
    py_set = {_rel(p, root) for p in py_files}
    md_set = {_rel(p, root) for p in md_files}

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()
    parse_errors: list[dict] = []

    for rel in sorted(py_set):
        nodes[rel] = {"id": rel, "type": "python_file"}
    for rel in sorted(md_set):
        nodes[rel] = {"id": rel, "type": "markdown_doc"}

    # 第一遍：解析所有 py 文件
    parsed: dict[str, dict] = {}
    for rel in sorted(py_set):
        info = _parse_py(root / rel, py_set, rel)
        parsed[rel] = info
        if info["error"]:
            parse_errors.append({"file": rel, "error": info["error"]})

    # 全局函数名 → 定义文件（重名取路径排序首个，保证确定性）
    name_to_file: dict[str, str] = {}
    for rel in sorted(py_set):
        for fn in sorted(parsed[rel]["defs"]):
            name_to_file.setdefault(fn, rel)

    # 第二遍：import / call 边
    for rel in sorted(py_set):
        info = parsed[rel]
        for mod in info["raw_imports"]:
            target = _module_to_rel(mod, py_set, rel)
            if target is not None:
                if target != rel:
                    edges.add((rel, target, "import"))
            else:
                ext_id = f"external:{mod.split('.')[0]}"
                if ext_id not in nodes:
                    nodes[ext_id] = {"id": ext_id, "type": "external"}
                edges.add((rel, ext_id, "import"))
        for call in sorted(info["calls"]):
            target = name_to_file.get(call)
            if target and target != rel:
                edges.add((rel, target, "call"))

    # doc_ref 边（markdown 相对链接 → 仓内 md）
    for rel in sorted(md_set):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        base = (root / rel).parent
        for m in MD_LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "file:")):
                continue
            t = (base / target).resolve()
            try:
                trel = t.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if trel in md_set and trel != rel:
                edges.add((rel, trel, "doc_ref"))

    # 闭合校验：边的端点都必须存在
    dangling = [
        {"src": s, "dst": d, "kind": k}
        for (s, d, k) in sorted(edges)
        if s not in nodes or d not in nodes
    ]

    return {
        "nodes": [nodes[k] for k in sorted(nodes)],
        "edges": [{"src": s, "dst": d, "kind": k} for (s, d, k) in sorted(edges)],
        "parse_errors": parse_errors,
        "dangling_edges": dangling,
    }


def _sha256_json(obj: dict) -> tuple[str, bytes]:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), blob


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def run(root: Path, out_dir: Path, scopes: list[str]) -> dict:
    graph = build_graph(root, scopes)
    generated_at = datetime.now(timezone.utc).isoformat()
    # sha256 只覆盖结构内容（不含时间戳），保证同一代码状态可复现
    payload = {
        "schema": "ArchitectureGraph/v1",
        "scopes": scopes or ["<repo>"],
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }
    sha, blob = _sha256_json(payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 落盘文件带 generated_at（不影响 sha 校验，校验时剔除该字段）
    disk_payload = {"generated_at": generated_at, **payload}
    graph_path = out_dir / "architecture_graph.json"
    graph_path.write_text(
        json.dumps(disk_payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    disk_bytes = graph_path.stat().st_size

    type_dist: dict[str, int] = {}
    for n in graph["nodes"]:
        type_dist[n["type"]] = type_dist.get(n["type"], 0) + 1
    edge_dist: dict[str, int] = {}
    for e in graph["edges"]:
        edge_dist[e["kind"]] = edge_dist.get(e["kind"], 0) + 1

    summary = {
        "generated_at": generated_at,
        "scopes": payload["scopes"],
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "node_type_distribution": type_dist,
        "edge_kind_distribution": edge_dist,
        "parse_error_count": len(graph["parse_errors"]),
        "parse_errors": graph["parse_errors"][:50],
        "dangling_edge_count": len(graph["dangling_edges"]),
        "closed_check": "pass" if not graph["dangling_edges"] else "fail",
        "sha256": sha,
        "bytes": disk_bytes,
    }
    (out_dir / "graph_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    manifest = {
        "generated_at": generated_at,
        "git_commit": _git_commit(root),
        "artifacts": {
            "architecture_graph.json": {
                "sha256": sha,
                "bytes": disk_bytes,
                "sha_note": "sha256 覆盖剔除 generated_at 的结构内容",
            },
        },
        "scopes": payload["scopes"],
        "limits": [
            "Python-only；不含 TS/JS import 与运行时数据流",
            "call 边为函数名级（重名取排序首个），非精确调用图",
            "doc_ref 仅覆盖 Markdown 相对链接",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 D2 ArchitectureGraph 基线")
    ap.add_argument("--scope", action="append", default=[], help="限定扫描目录（可多次）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产物输出目录")
    args = ap.parse_args(argv)
    summary = run(REPO_ROOT, Path(args.out), args.scope)
    print(
        f"[build_d2] nodes={summary['node_count']} edges={summary['edge_count']} "
        f"parse_errors={summary['parse_error_count']} "
        f"dangling={summary['dangling_edge_count']} sha256={summary['sha256'][:12]}..."
    )
    return 0 if summary["closed_check"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
