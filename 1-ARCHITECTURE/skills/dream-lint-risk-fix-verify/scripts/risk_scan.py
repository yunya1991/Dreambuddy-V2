#!/usr/bin/env python3
"""Lint 修复风险扫描器：对 ruff 命中项做静态副作用分级，不修改任何文件。

用法：
    python3 risk_scan.py --root . --output /tmp/lint-risk.json --summary
    python3 risk_scan.py --root . --rules F841,F401 --only-risky --summary
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HIGH, MEDIUM, LOW = "high", "medium", "low"
RISK_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}

DEFAULT_RULES = [
    "F401",
    "F841",
    "I001",
    "E402",
    "E712",
    "B905",
    "B023",
    "E722",
    "F601",
    "F821",
    "F811",
    "F403",
    "E721",
    "E731",
    "E741",
]

SAFE_RULES = {
    "W291",
    "W292",
    "W293",
    "F541",
    "E401",
    "C401",
    "C403",
    "C408",
    "C414",
    "C416",
    "C420",
    "B009",
    "B010",
    "B033",
    "E701",
    "E702",
    "E713",
    "B904",
}

ARRAY_LIB_PATTERN = re.compile(r"^\s*(?:import|from)\s+(?:numpy|pandas|torch|jax|cupy)\b", re.M)
NAME_PATTERN = re.compile(r"`([^`]+)`")


def run_ruff(root: Path, rules: list[str]) -> list[dict]:
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        ",".join(rules),
        "--output-format",
        "json",
        str(root),
    ]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"ruff 执行失败，exit={proc.returncode}")
    return json.loads(proc.stdout) if proc.stdout.strip() else []


def parse_tree(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None


def collect_all_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            names.add(elt.value)
    return names


def has_side_effect_call(node: ast.AST) -> bool:
    side_types = (ast.Call, ast.Await, ast.Yield, ast.YieldFrom)
    return any(isinstance(child, side_types) for child in ast.walk(node))


def detect_f841(tree: ast.AST, row: int) -> tuple[str, str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.lineno == row:
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.lineno == row and node.value is not None:
            value = node.value
        else:
            continue
        if has_side_effect_call(value):
            return HIGH, "赋值右侧含调用/await/yield，删除会丢失副作用"
        return LOW, "右侧为纯表达式"
    return MEDIUM, "未定位到赋值节点（可能为 with/except 变量），需人工确认"


def detect_f401(path: Path, all_names: set[str], line: str, message: str) -> tuple[str, str]:
    if path.name == "__init__.py":
        return HIGH, "包 __init__ 再导出，外部 import 可能依赖"
    match = NAME_PATTERN.search(message)
    name = match.group(1) if match else ""
    if name and name in all_names:
        return HIGH, "该名字在 __all__ 中声明，删除会改变公共 API"
    if line.lstrip().startswith("import "):
        return MEDIUM, "模块级 import 可能用于副作用注册"
    return LOW, "from-import 的未使用名字"


def detect_i001(tree: ast.AST) -> tuple[str, str]:
    definitions = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in tree.body:
        if isinstance(node, definitions):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            kind = type(node).__name__
            return HIGH, f"模块级 {kind} 语句，导入位置/顺序敏感"
        if isinstance(node, ast.Expr):
            return HIGH, "模块级表达式语句（可能为注册/初始化调用）"
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = getattr(node, "value", None)
            if value is not None and has_side_effect_call(value):
                return MEDIUM, "模块级赋值右侧含调用"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {"append", "insert", "extend", "update"}:
                continue
            target = ast.unparse(node.func.value)
            if "sys.path" in target or "environ" in target:
                return HIGH, f"运行时修改 {target}，导入顺序敏感"
    return LOW, "模块级仅有定义与常量"


def detect_e712(source: str) -> tuple[str, str]:
    if ARRAY_LIB_PATTERN.search(source):
        return MEDIUM, "数组库文件中的 True/False 比较，可能触发真值歧义"
    return LOW, "未使用数组库"


def detect_b905(path: Path) -> tuple[str, str]:
    if "experiments/ab-trading" in path.as_posix():
        return HIGH, "ab-trading workflow 使用 Python 3.9，strict= 参数会 TypeError"
    return LOW, "项目 target-version 为 py310，strict= 兼容"


def detect_f601(tree: ast.AST, row: int) -> tuple[str, str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: dict[str, str] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or value.lineno != row:
                continue
            literal = repr(key.value)
            if literal in seen:
                return HIGH, f"重复键 {literal}: 前值={seen[literal]} 后值={ast.unparse(value)}"
            seen[literal] = ast.unparse(value)
    return MEDIUM, "未定位到字典重复键，需人工确认"


def detect_f821(line: str) -> tuple[str, str]:
    text = line.strip()
    if text.startswith(("def ", "class ", "@")) or "->" in text or text.startswith("#"):
        return MEDIUM, "可能为类型注解或条件导入上下文"
    return HIGH, "未定义名，执行到即 NameError"


def classify(finding: dict, path: Path, tree: ast.AST | None, source: str) -> tuple[str, str]:
    code = finding.get("code") or "invalid-syntax"
    row = finding["location"]["row"]
    line = source.splitlines()[row - 1] if row <= len(source.splitlines()) else ""

    if code in SAFE_RULES:
        return LOW, "语义等价改写"
    if code in {"W291", "W293", "W292"}:
        return LOW, "仅空白变化"
    if code == "invalid-syntax":
        return HIGH, "文件无法编译，必须优先人工修复"
    if tree is None:
        return HIGH, "AST 解析失败，无法自动判定"
    if code == "F841":
        return detect_f841(tree, row)
    if code == "F401":
        return detect_f401(path, collect_all_names(tree), line, finding.get("message", ""))
    if code == "I001":
        return detect_i001(tree)
    if code == "E712":
        return detect_e712(source)
    if code == "B905":
        return detect_b905(path)
    if code == "F601":
        return detect_f601(tree, row)
    if code == "F821":
        return detect_f821(line)
    if code == "F811":
        return MEDIUM, "重复定义，前者可能已被后者覆盖"
    if code == "E722":
        return MEDIUM, "bare except 收窄会改变中断/退出行为"
    if code == "E402":
        return HIGH, "导入不在顶部，多为 sys.path hack 之后，不可移动"
    if code == "B023":
        return HIGH, "闭包捕获循环变量，修复会改变运行时取值"
    if code in {"E721", "E731", "F403", "E741"}:
        return MEDIUM, "手动规则，需逐文件判断"
    return MEDIUM, "未分类规则，默认人工复核"


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint 修复风险扫描（只读）")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--rules", default="", help="逗号分隔的 ruff 规则，默认风险规则集")
    parser.add_argument("--output", default="", help="JSON 报告路径")
    parser.add_argument("--summary", action="store_true", help="打印汇总")
    parser.add_argument("--only-risky", action="store_true", help="仅输出 medium/high")
    parser.add_argument("--fail-on-high", action="store_true", help="存在 high 时 exit 1")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rules = [item.strip() for item in args.rules.split(",") if item.strip()] or DEFAULT_RULES
    findings = run_ruff(root, rules)

    tree_cache: dict[Path, ast.AST | None] = {}
    source_cache: dict[Path, str] = {}
    results = []
    for finding in findings:
        path = Path(finding["filename"]).resolve()
        if path not in tree_cache:
            tree_cache[path] = parse_tree(path)
            try:
                source_cache[path] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                source_cache[path] = ""
        risk, reason = classify(finding, path, tree_cache[path], source_cache[path])
        if args.only_risky and risk == LOW:
            continue
        results.append(
            {
                "file": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "line": finding["location"]["row"],
                "rule": finding.get("code") or "invalid-syntax",
                "risk": risk,
                "reason": reason,
            }
        )

    results.sort(key=lambda item: (-RISK_ORDER[item["risk"]], item["rule"], item["file"]))
    summary = {
        "root": str(root),
        "rules": rules,
        "total": len(results),
        "by_risk": dict(Counter(item["risk"] for item in results)),
        "by_rule": dict(Counter(item["rule"] for item in results)),
        "high_files": sorted({item["file"] for item in results if item["risk"] == HIGH}),
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps({"summary": summary, "findings": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.fail_on_high and summary["high_files"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
