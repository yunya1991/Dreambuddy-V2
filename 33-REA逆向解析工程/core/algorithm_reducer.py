"""关键算法还原 — AST 模式匹配识别常见算法模式。

检测的算法模式：
- 递归（函数自调用）
- 迭代（for/while 循环）
- 累加器（变量 += 循环内）
- 条件分支（if-elif-else 链）
- 分治（函数调用自身处理子问题）
- 动态规划（缓存 + 递归）

每条结论带 Evidence（代码片段 + 推导逻辑 + known_gaps）。
"""

from __future__ import annotations

import ast
import os
from typing import Any

from .evidence import Evidence


def reduce_algorithm(target: str, function_name: str | None = None) -> dict[str, Any]:
    """分析 Python 源码中的算法模式。

    Args:
        target: Python 文件路径
        function_name: 指定函数名分析（可选，不指定则分析全部）

    Returns:
        {
            "functions": [{name, patterns, pseudo_code, line}],
            "patterns": [匹配的模式列表],
            "pseudo_code": [伪代码描述],
            "evidence": [Evidence],
        }
    """
    result: dict[str, Any] = {
        "functions": [],
        "patterns": [],
        "pseudo_code": [],
        "evidence": [],
    }

    if not os.path.isfile(target):
        result["evidence"].append(Evidence(
            result=f"文件不存在: {target}",
            provenance={"target": target},
            confidence=1.0,
            known_gaps=["无法分析不存在的文件"],
            level="observation",
        ))
        return result

    try:
        with open(target, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=target)
    except (SyntaxError, UnicodeDecodeError) as e:
        result["evidence"].append(Evidence(
            result=f"解析失败: {e}",
            provenance={"target": target},
            confidence=1.0,
            known_gaps=["语法错误或编码错误，无法分析"],
            level="observation",
        ))
        return result

    # 收集所有函数定义
    all_funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_funcs.append(node)

    if function_name:
        all_funcs = [f for f in all_funcs if f.name == function_name]

    all_patterns: list[dict[str, Any]] = []
    all_pseudo: list[str] = []

    for func in all_funcs:
        patterns = _detect_patterns(func)
        pseudo = _generate_pseudo_code(func, patterns)

        result["functions"].append({
            "name": func.name,
            "patterns": patterns,
            "pseudo_code": pseudo,
            "line": func.lineno,
        })

        all_patterns.extend(patterns)
        all_pseudo.append(pseudo)

    # 去重 patterns
    seen_types: set[str] = set()
    unique_patterns: list[dict[str, Any]] = []
    for p in all_patterns:
        if p["type"] not in seen_types:
            unique_patterns.append(p)
            seen_types.add(p["type"])
    result["patterns"] = unique_patterns

    result["pseudo_code"] = all_pseudo
    result["evidence"] = _build_evidence(
        len(all_funcs), unique_patterns, target,
    )

    return result


# ---------------------------------------------------------------------------
# 模式检测
# ---------------------------------------------------------------------------

def _detect_patterns(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    """检测函数中的算法模式。"""
    patterns: list[dict[str, Any]] = []

    # 递归检测：函数体内调用自身
    is_recursive = False
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = _call_name(node.func)
            if callee and callee == func.name:
                is_recursive = True
                break
    if is_recursive:
        patterns.append({
            "type": "递归 recursion",
            "description": f"函数 {func.name} 在自身体内调用自身",
            "line": func.lineno,
        })

    # 迭代检测：for/while 循环
    has_loop = False
    for node in ast.walk(func):
        if isinstance(node, (ast.For, ast.While)):
            has_loop = True
            break
    if has_loop:
        patterns.append({
            "type": "迭代 iteration",
            "description": f"函数 {func.name} 包含循环结构",
            "line": func.lineno,
        })

    # 累加器检测：变量 += 循环内
    has_accumulator = False
    for node in ast.walk(func):
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.target, ast.Name):
                has_accumulator = True
                break
    if has_accumulator:
        patterns.append({
            "type": "累加器 accumulator",
            "description": f"函数 {func.name} 使用累加器模式 (var += ...)",
            "line": func.lineno,
        })

    # 条件分支检测：if-elif-else 链（≥2个分支）
    if_count = 0
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            if_count += 1
    if if_count >= 2:
        patterns.append({
            "type": "条件分支 conditional_branch",
            "description": f"函数 {func.name} 包含多重条件分支 ({if_count} 个 if)",
            "line": func.lineno,
        })

    # 分治检测：递归 + 处理子问题（二分/切片操作）
    if is_recursive:
        for node in ast.walk(func):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                patterns.append({
                    "type": "分治 divide_and_conquer",
                    "description": f"函数 {func.name} 递归 + 切片操作，疑似分治策略",
                    "line": func.lineno,
                })
                break

    # 动态规划检测：缓存（字典存储）+ 递归
    has_cache = False
    for node in ast.walk(func):
        # 检测 memo/dict 赋值模式
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                if node.value.func.id in ("dict", "defaultdict"):
                    has_cache = True
                    break
        if isinstance(node, ast.Subscript):
            # 检测 dict[...] = ... 模式
            has_cache = True
            break
    if is_recursive and has_cache:
        patterns.append({
            "type": "动态规划 dynamic_programming",
            "description": f"函数 {func.name} 递归 + 缓存，疑似动态规划",
            "line": func.lineno,
        })

    return patterns


# ---------------------------------------------------------------------------
# 伪代码生成
# ---------------------------------------------------------------------------

def _generate_pseudo_code(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    patterns: list[dict[str, Any]],
) -> str:
    """从 AST 生成伪代码摘要。"""
    args = [a.arg for a in func.args.args]
    pattern_types = [p["type"].split()[0] for p in patterns]

    lines = [f"function {func.name}({', '.join(args)}):"]

    if "递归" in " ".join(pattern_types):
        lines.append("  if base_case:")
        lines.append("    return base_result")
        lines.append("  return f({func_name}(subproblem))".format(func_name=func.name))
    elif "迭代" in " ".join(pattern_types):
        lines.append("  result = initial_value")
        lines.append("  for each item in input:")
        lines.append("    update result")
        lines.append("  return result")
    else:
        # 通用伪代码
        for node in ast.walk(func):
            if isinstance(node, ast.Return):
                lines.append("  return <value>")
                break

    if not any("return" in l for l in lines[1:]):
        lines.append("  return <implicit None>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evidence 构建
# ---------------------------------------------------------------------------

def _build_evidence(
    n_funcs: int,
    patterns: list[dict[str, Any]],
    target: str,
) -> list[Evidence]:
    evidence: list[Evidence] = []

    evidence.append(Evidence(
        result=f"检测到 {n_funcs} 个函数, {len(patterns)} 种算法模式",
        provenance={"file": target, "analysis": "algorithm_reduction"},
        confidence=0.9,
        known_gaps=[
            "AST 模式匹配无法识别非标准实现（如函数指针/lambda 递归）",
            "伪代码为模板生成，不反映具体业务逻辑",
            "动态特性（eval/exec/反射）无法静态分析",
        ],
        level="derivation",
    ))

    for p in patterns:
        evidence.append(Evidence(
            result=f"模式: {p['type']} — {p['description']}",
            provenance={"file": target, "line": p["line"], "analysis": "pattern_match"},
            confidence=0.8,
            known_gaps=["模式匹配基于结构特征，可能误报"],
            level="inference",
        ))

    return evidence


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
