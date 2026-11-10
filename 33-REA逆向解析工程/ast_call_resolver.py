"""33-REA/ast_call_resolver.py — call 边 AST 精确解析。

设计依据：架构图 call 边为函数名级解析（重名取路径排序首个），产生大量
重名假依赖。本模块用 ast 对每个 python_file 做精确函数定义/调用解析，
把 call 边升级为 qualified_name 精确匹配，并统计重名假依赖率。

FAIL-OPEN：单文件 parse 失败跳过并计入 skipped 计数，不抛异常。
仅依赖 stdlib：ast / pathlib / collections。
"""

import ast
from collections import defaultdict
from pathlib import Path


def _parse(py_path):
    """FAIL-OPEN 解析：失败返回 None。"""
    try:
        return ast.parse(Path(py_path).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


def _definitions_from_tree(tree, py_path):
    """从 AST 提取 FunctionDef/AsyncFunctionDef 的 qualified name 与行号。"""

    def _visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                defs.append(
                    {
                        "qualified_name": qual,
                        "name": child.name,
                        "lineno": child.lineno,
                        "file": str(py_path),
                    }
                )
                _visit(child, f"{qual}.")
            elif isinstance(child, ast.ClassDef):
                _visit(child, f"{prefix}{child.name}.")
            else:
                _visit(child, prefix)

    defs = []
    _visit(tree, "")
    return defs


def extract_definitions(py_path):
    """提取函数定义：qualified name（含类前缀，如 ``ClassName.method``）与行号。

    parse 失败返回空列表（FAIL-OPEN）。
    """
    tree = _parse(py_path)
    if tree is None:
        return []
    return _definitions_from_tree(tree, py_path)


def _dotted_name(node):
    """把 Name/Attribute 链还原成点分名（如 ``a.b.c``），失败返回 None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        parts.reverse()
        return ".".join(parts)
    return None


def _resolve_callee(call, ctx):
    """把 ast.Call 的 func 尽量解析为 qualified name。"""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "self" and ctx.get("class"):
            return f"{ctx['class']}.{func.attr}"
        dotted = _dotted_name(func)
        return dotted if dotted else func.attr
    return None


def _caller_name(ctx):
    if ctx.get("class") and ctx.get("function"):
        return f"{ctx['class']}.{ctx['function']}"
    return ctx.get("function") or ctx.get("class") or "<module>"


def _calls_from_tree(tree, py_path):
    """从 AST 提取 ast.Call 节点：caller 上下文 + callee 名 + 行号。"""

    def _visit(node, ctx):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                _visit(child, {"class": child.name, "function": None})
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _visit(child, {"class": ctx.get("class"), "function": child.name})
            elif isinstance(child, ast.Call):
                callee = _resolve_callee(child, ctx)
                if callee:
                    calls.append(
                        {
                            "caller": _caller_name(ctx),
                            "callee": callee,
                            "lineno": child.lineno,
                            "file": str(py_path),
                        }
                    )
                _visit(child, ctx)
            else:
                _visit(child, ctx)

    calls = []
    _visit(tree, {"class": None, "function": None})
    return calls


def resolve_calls(py_path):
    """提取调用点：尽量解析为 qualified name（``obj.method()``/``func()``/``module.func()``）。

    返回 call 列表（caller 上下文 + callee 名 + 行号）。parse 失败返回空列表。
    """
    tree = _parse(py_path)
    if tree is None:
        return []
    return _calls_from_tree(tree, py_path)


def compute_false_dependency_rate(edges):
    """重名冲突率 = 有多个候选定义的边数 / 总边数。

    每条边为 dict，含 callee 名与 candidates（候选定义数）。空输入返回 0.0。
    """
    edges = [e for e in (edges or []) if isinstance(e, dict)]
    if not edges:
        return 0.0
    ambiguous = sum(1 for e in edges if int(e.get("candidates") or 0) > 1)
    return ambiguous / len(edges)


def _match_edge(src_calls, dst_defs, name_to_files):
    """在 src 调用中找与 dst 定义精确匹配的 callee；优先 qualified 全等匹配。"""
    if not src_calls or not dst_defs:
        return None, 0
    dst_qual = {d["qualified_name"] for d in dst_defs}
    dst_simple = {d["name"] for d in dst_defs}
    weak = None
    for call in src_calls:
        simple = call["callee"].split(".")[-1]
        if call["callee"] in dst_qual:
            return call, len(name_to_files.get(simple, ()))
        if simple in dst_simple and weak is None:
            weak = call
    if weak is not None:
        simple = weak["callee"].split(".")[-1]
        return weak, len(name_to_files.get(simple, ()))
    return None, 0


def resolve_graph(graph):
    """把架构图 call 边升级为 qualified_name 精确匹配，加 ``ast_resolved`` 标记。

    返回 (更新后的 graph, 统计 dict)。parse 失败的文件跳过并计入 skipped_files。
    """
    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
    py_nodes = [
        n.get("id")
        for n in nodes
        if isinstance(n, dict) and n.get("type") == "python_file" and n.get("id")
    ]

    defs_by_file = {}
    calls_by_file = {}
    name_to_files = defaultdict(set)
    skipped = 0
    for node_id in py_nodes:
        tree = _parse(node_id)
        if tree is None:
            skipped += 1
            continue
        defs = _definitions_from_tree(tree, node_id)
        defs_by_file[node_id] = defs
        calls_by_file[node_id] = _calls_from_tree(tree, node_id)
        for d in defs:
            name_to_files[d["name"]].add(node_id)

    resolved = 0
    unresolved = 0
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("kind") != "call":
            continue
        match, candidates = _match_edge(
            calls_by_file.get(edge.get("src")),
            defs_by_file.get(edge.get("dst")),
            name_to_files,
        )
        if match is not None:
            edge["ast_resolved"] = True
            edge["resolved_callee"] = match["callee"]
            edge["lineno"] = match["lineno"]
            edge["candidates"] = candidates
            resolved += 1
        else:
            edge["ast_resolved"] = False
            edge["candidates"] = 0
            unresolved += 1

    resolved_edges = [
        e
        for e in edges
        if isinstance(e, dict) and e.get("kind") == "call" and e.get("ast_resolved")
    ]
    stats = {
        "total_call_edges": resolved + unresolved,
        "resolved": resolved,
        "unresolved": unresolved,
        "name_collision_rate": compute_false_dependency_rate(resolved_edges),
        "skipped_files": skipped,
        "definitions": sum(len(v) for v in defs_by_file.values()),
    }
    return graph, stats
