"""Python AST 分析器 — 提取模块导入、类、函数结构。"""

from __future__ import annotations

import ast
import os
from typing import Any

from .analyzer_base import AnalyzerBase, AnalyzeResult
from .evidence import Evidence


class PythonAnalyzer(AnalyzerBase):
    """Python 源码 AST 分析器。

    能力：
    - 提取 import / from-import
    - 提取类（名称、方法、装饰器、基类）
    - 提取函数（名称、参数、装饰器、返回标注）
    - 每条结论带 Evidence（provenance=文件:行号, confidence, known_gaps）
    """

    def supported_targets(self) -> list[str]:
        return ["python", ".py"]

    def analyze(self, target: str, **kwargs: Any) -> AnalyzeResult:
        if not os.path.isfile(target) or not target.endswith(".py"):
            return AnalyzeResult(
                target=target,
                summary=f"非 Python 文件或不存在: {target}",
                evidence=[],
                raw={"error": "not_a_python_file"},
            )

        with open(target, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=target)
        except SyntaxError as e:
            return AnalyzeResult(
                target=target,
                summary=f"语法错误: {e}",
                evidence=[Evidence(
                    result=f"语法错误: {e}",
                    provenance={"file": target, "line": e.lineno},
                    confidence=1.0,
                    known_gaps=["无法分析语法错误的文件"],
                    level="observation",
                )],
                raw={"error": "syntax_error", "detail": str(e)},
            )

        imports = self._extract_imports(tree, target)
        classes = self._extract_classes(tree, target)
        functions = self._extract_functions(tree, target)

        evidence = self._build_evidence(target, imports, classes, functions)

        summary = (
            f"Python 模块: {os.path.basename(target)} | "
            f"{len(imports)} imports, {len(classes)} classes, {len(functions)} functions"
        )

        return AnalyzeResult(
            target=target,
            summary=summary,
            evidence=evidence,
            raw={
                "imports": imports,
                "classes": classes,
                "functions": functions,
            },
        )

    # ------------------------------------------------------------------
    # 提取逻辑
    # ------------------------------------------------------------------
    def _extract_imports(self, tree: ast.Module, target: str) -> list[dict]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "type": "import",
                        "module": alias.name,
                        "asname": alias.asname,
                        "line": node.lineno,
                    })
            elif isinstance(node, ast.ImportFrom):
                imports.append({
                    "type": "from",
                    "module": node.module or "",
                    "names": [a.name for a in node.names],
                    "level": node.level,
                    "line": node.lineno,
                })
        return imports

    def _extract_classes(self, tree: ast.Module, target: str) -> list[dict]:
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": item.name,
                            "args": [a.arg for a in item.args.args],
                            "decorators": [self._decorator_name(d) for d in item.decorator_list],
                            "line": item.lineno,
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                        })
                classes.append({
                    "name": node.name,
                    "bases": [self._expr_name(b) for b in node.bases],
                    "decorators": [self._decorator_name(d) for d in node.decorator_list],
                    "methods": methods,
                    "line": node.lineno,
                    "docstring": ast.get_docstring(node),
                })
        return classes

    def _extract_functions(self, tree: ast.Module, target: str) -> list[dict]:
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 跳过类的方法（已在 classes 中提取）
                # 注意: ast.walk 遍历所有节点，部分节点(IfExp/Lambda)的 body
                # 是单个表达式而非列表，需先检查 isinstance(body, list)
                is_method = False
                for parent in ast.walk(tree):
                    parent_body = getattr(parent, "body", None)
                    if isinstance(parent_body, list) and node in parent_body:
                        if isinstance(parent, ast.ClassDef):
                            is_method = True
                            break
                if is_method:
                    continue
                functions.append({
                    "name": node.name,
                    "args": [a.arg for a in node.args.args],
                    "defaults": len(node.args.defaults),
                    "decorators": [self._decorator_name(d) for d in node.decorator_list],
                    "line": node.lineno,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": ast.get_docstring(node),
                })
        return functions

    # ------------------------------------------------------------------
    # Evidence 构建
    # ------------------------------------------------------------------
    def _build_evidence(self, target: str, imports: list, classes: list,
                        functions: list) -> list[Evidence]:
        evidence = []
        evidence.append(Evidence(
            result=f"检测到 {len(imports)} 个导入",
            provenance={"file": target, "analysis": "imports"},
            confidence=1.0,
            known_gaps=["动态导入 (importlib/__import__) 无法静态解析"],
            level="observation",
        ))
        evidence.append(Evidence(
            result=f"检测到 {len(classes)} 个类",
            provenance={"file": target, "analysis": "classes"},
            confidence=1.0,
            known_gaps=["元类动态生成的类无法静态解析"],
            level="observation",
        ))
        evidence.append(Evidence(
            result=f"检测到 {len(functions)} 个顶层函数",
            provenance={"file": target, "analysis": "functions"},
            confidence=1.0,
            known_gaps=["动态函数定义/装饰器修改的函数签名可能不准确",
                        "运行时动态调用无法静态追踪"],
            level="observation",
        ))
        return evidence

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _decorator_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{PythonAnalyzer._expr_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return PythonAnalyzer._decorator_name(node.func)
        return "<unknown>"

    @staticmethod
    def _expr_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{PythonAnalyzer._expr_name(node.value)}.{node.attr}"
        return "<unknown>"
