"""33-REA/interface_signature_extractor.py — 公开接口签名提取。

设计依据：架构图仅记录 import 边，不记录接口签名/参数契约，需提取公开
函数签名（name + args + return annotation）写入节点的 interface_signature
字段，供 interface_mismatch 检测。

FAIL-OPEN：parse 失败文件跳过，不抛异常。仅依赖 stdlib。
"""

import ast
from pathlib import Path


def _parse(py_path):
    """FAIL-OPEN 解析：失败返回 None。"""
    try:
        return ast.parse(Path(py_path).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


def _unparse(node):
    return ast.unparse(node) if node is not None else None


def _extract_args(a):
    """提取参数列表：每个含 name/annotation/default/kind。"""

    def _entry(arg, default, kind):
        return {
            "name": arg.arg,
            "annotation": _unparse(arg.annotation),
            "default": _unparse(default),
            "kind": kind,
        }

    out = []
    pos = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, default in zip(pos, defaults, strict=True):
        out.append(_entry(arg, default, "positional"))
    if a.vararg:
        out.append(_entry(a.vararg, None, "vararg"))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        out.append(_entry(arg, default, "kwonly"))
    if a.kwarg:
        out.append(_entry(a.kwarg, None, "kwargs"))
    return out


def _signatures_from_tree(tree):
    """从 AST 提取公开函数（非 _ 开头）签名；方法含 class 前缀。"""

    def _visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not child.name.startswith("_"):
                    signatures.append(
                        {
                            "name": f"{prefix}{child.name}",
                            "args": _extract_args(child.args),
                            "returns": _unparse(child.returns),
                            "lineno": child.lineno,
                        }
                    )
                _visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                _visit(child, f"{prefix}{child.name}.")
            else:
                _visit(child, prefix)

    signatures = []
    _visit(tree, "")
    return signatures


def extract_signatures(py_path):
    """提取公开函数签名：name、args（name/annotation/default）、return annotation。

    parse 失败返回空列表（FAIL-OPEN）。
    """
    tree = _parse(py_path)
    if tree is None:
        return []
    return _signatures_from_tree(tree)


def extract_graph_signatures(graph):
    """对每个 python_file 节点写 interface_signature 字段，返回更新后的 graph。

    parse 失败的节点跳过（不写字段）。
    """
    for node in graph.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "python_file" or not node.get("id"):
            continue
        tree = _parse(node["id"])
        if tree is None:
            continue
        node["interface_signature"] = _signatures_from_tree(tree)
    return graph


def check_call_compat(call_site_args, signature):
    """比较调用点参数与签名兼容性（考虑默认值与 *args/**kwargs）。

    call_site_args 为位置参数列表，或 dict {"args": [...], "kwargs": [...]}。
    兼容返回 None，否则返回 mismatch 描述字符串。
    """
    if isinstance(call_site_args, dict):
        pos = list(call_site_args.get("args", []) or [])
        kws = set(call_site_args.get("kwargs", []) or [])
    else:
        pos = list(call_site_args or [])
        kws = set()
    params = (signature or {}).get("args", []) or []

    positional = [p for p in params if p.get("kind") == "positional"]
    kwonly = [p for p in params if p.get("kind") == "kwonly"]
    has_vararg = any(p.get("kind") == "vararg" for p in params)
    has_kwargs = any(p.get("kind") == "kwargs" for p in params)
    required_pos = [p for p in positional if p.get("default") is None]
    required_kwonly = [p for p in kwonly if p.get("default") is None]

    n = len(pos)
    if n < len(required_pos):
        return f"参数不足：需要至少 {len(required_pos)} 个位置参数，实际 {n} 个"
    if not has_vararg and n > len(positional):
        return f"参数过多：最多 {len(positional)} 个位置参数，实际 {n} 个"

    valid_kw_names = {p["name"] for p in params if p.get("kind") in ("positional", "kwonly")}
    bound = {positional[i]["name"] for i in range(min(n, len(positional)))}
    for kw in sorted(kws):
        if kw in bound:
            return f"参数 {kw} 同时被位置与关键字传入"
        if kw not in valid_kw_names and not has_kwargs:
            return f"未知关键字参数：{kw}"
    for p in required_kwonly:
        if p["name"] not in kws:
            return f"缺少必需关键字参数：{p['name']}"
    return None


def _dotted_name(node):
    """把 Name/Attribute 链还原成点分名，失败返回 None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        parts.reverse()
        return ".".join(parts)
    return None


def _extract_call_sites(py_path):
    """提取调用点：caller 上下文 + callee 点分名 + 位置/关键字参数 + 行号。"""

    def _visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                _visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.Call):
                callee = _dotted_name(child.func)
                if callee:
                    sites.append(
                        {
                            "caller": prefix[:-1] if prefix else "<module>",
                            "callee": callee,
                            "args": len(child.args),
                            "kwargs": [kw.arg for kw in child.keywords if kw.arg],
                            "lineno": child.lineno,
                        }
                    )
                _visit(child, prefix)
            else:
                _visit(child, prefix)

    tree = _parse(py_path)
    if tree is None:
        return []
    sites = []
    _visit(tree, "")
    return sites


def find_mismatches(graph):
    """比较 call 边两端签名兼容性，返回 mismatch 清单（caller/callee/原因）。

    parse 失败的文件跳过（FAIL-OPEN）。
    """
    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
    py_ids = [
        n.get("id")
        for n in nodes
        if isinstance(n, dict) and n.get("type") == "python_file" and n.get("id")
    ]

    sigs_by_file = {}
    sites_by_file = {}
    for fid in py_ids:
        tree = _parse(fid)
        if tree is None:
            continue
        sigs_by_file[fid] = _signatures_from_tree(tree)
        sites_by_file[fid] = _extract_call_sites(fid)

    mismatches = []
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("kind") != "call":
            continue
        src, dst = edge.get("src"), edge.get("dst")
        dst_sigs = sigs_by_file.get(dst)
        if not dst_sigs:
            continue
        by_qual = {}
        by_simple = {}
        for sig in dst_sigs:
            by_qual.setdefault(sig["name"], sig)
            by_simple.setdefault(sig["name"].split(".")[-1], sig)
        for site in sites_by_file.get(src, []):
            sig = by_qual.get(site["callee"]) or by_simple.get(site["callee"].split(".")[-1])
            if sig is None:
                continue
            reason = check_call_compat(
                {"args": [None] * site["args"], "kwargs": site["kwargs"]}, sig
            )
            if reason:
                mismatches.append(
                    {
                        "caller": f"{src}::{site['caller']}",
                        "callee": f"{dst}::{sig['name']}",
                        "lineno": site["lineno"],
                        "reason": reason,
                    }
                )
    return mismatches
