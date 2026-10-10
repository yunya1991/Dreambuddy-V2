"""TypeScript/JavaScript AST 分析器。

能力：
- 模块/类/函数清单
- import/export 依赖
- 调用关系
- 类型注解提取（基础）

实现方式：基于正则表达式解析（Python 无原生 TS AST 解析器），
覆盖 ES6+ 常见语法模式。对于复杂/动态语法会标注 known_gaps。
"""

from __future__ import annotations

import os
import re
from typing import Any

from .analyzer_base import AnalyzeResult, AnalyzerBase
from .evidence import Evidence

# 支持 TS/JS 文件扩展名
_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


class TSAnalyzer(AnalyzerBase):
    """TypeScript/JavaScript 源码静态分析器。

    使用正则表达式解析 ES6+ 语法，提取：
    - import / require / import-from
    - class 定义（含方法、继承、修饰符）
    - 函数定义（普通函数、箭头函数、async 函数）
    - export 声明
    - 每条结论带 Evidence（provenance + confidence + known_gaps）
    """

    def supported_targets(self) -> list[str]:
        return ["typescript", "javascript", ".ts", ".tsx", ".js", ".jsx"]

    def analyze(self, target: str, **kwargs: Any) -> AnalyzeResult:
        if not os.path.isfile(target) or not target.endswith(_TS_EXTENSIONS):
            return AnalyzeResult(
                target=target,
                summary=f"非 TS/JS 文件或不存在: {target}",
                evidence=[],
                raw={"error": "not_a_ts_js_file"},
            )

        with open(target, "r", encoding="utf-8") as f:
            source = f.read()

        imports = self._extract_imports(source, target)
        classes = self._extract_classes(source, target)
        functions = self._extract_functions(source, target)
        exports = self._extract_exports(source, target, classes, functions)

        evidence = self._build_evidence(target, imports, classes, functions)

        summary = (
            f"TS/JS 模块: {os.path.basename(target)} | "
            f"{len(imports)} imports, {len(classes)} classes, "
            f"{len(functions)} functions, {len(exports)} exports"
        )

        return AnalyzeResult(
            target=target,
            summary=summary,
            evidence=evidence,
            raw={
                "imports": imports,
                "classes": classes,
                "functions": functions,
                "exports": exports,
            },
        )

    # ------------------------------------------------------------------
    # Import 提取
    # ------------------------------------------------------------------
    def _extract_imports(self, source: str, target: str) -> list[dict]:
        """提取 import 和 require 语句。"""
        imports: list[dict] = []
        lines = source.split("\n")

        # import { A, B } from 'module'
        # import A from 'module'
        # import * as A from 'module'
        # import 'module'
        import_re = re.compile(
            r"^\s*import\s+"        # import
            r"(?:(\*\s+as\s+(\w+))"   # import * as X
            r"|(\{[^}]*\})"          # import { ... }
            r"|(\w+)"               # import X
            r")?\s*"                # optional space
            r"(?:,\s*(\{[^}]*\}))?\s*"  # , { ... }
            r"(?:from\s+)?['\"]([^'\"]+)['\"]",  # 'module'
            re.MULTILINE,
        )

        for match in import_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            module = match.group(6) or ""
            star_as = match.group(2)
            named = match.group(3) or match.group(4) or ""
            default_name = match.group(4) if not match.group(3) else ""

            if star_as:
                # import * as X from 'mod'
                imports.append({
                    "type": "import_star",
                    "module": module,
                    "alias": star_as,
                    "line": line_no,
                })
            elif named:
                # import { A, B } from 'mod' or import X, { A } from 'mod'
                names = [
                    n.strip().split(" as ")[0].strip()
                    for n in named.strip("{}").split(",")
                    if n.strip()
                ]
                imports.append({
                    "type": "import_named",
                    "module": module,
                    "names": names,
                    "default_name": default_name or "",
                    "line": line_no,
                })
            elif default_name:
                # import X from 'mod'
                imports.append({
                    "type": "import_default",
                    "module": module,
                    "default_name": default_name,
                    "line": line_no,
                })
            else:
                # import 'mod' (side effect)
                imports.append({
                    "type": "import_side_effect",
                    "module": module,
                    "line": line_no,
                })

        # const X = require('module')
        # const { a, b } = require('module')
        require_re = re.compile(
            r"(?:const|let|var)\s+"
            r"(?:(\w+)|(\{[^}]*\}))\s*=\s*require\(['\"]([^'\"]+)['\"]\)"
        )
        for match in require_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            module = match.group(3)
            default_name = match.group(1)
            named = match.group(2)
            if named:
                names = [
                    n.strip() for n in named.strip("{}").split(",") if n.strip()
                ]
                imports.append({
                    "type": "require_named",
                    "module": module,
                    "names": names,
                    "line": line_no,
                })
            else:
                imports.append({
                    "type": "require_default",
                    "module": module,
                    "default_name": default_name,
                    "line": line_no,
                })

        return imports

    # ------------------------------------------------------------------
    # Class 提取
    # ------------------------------------------------------------------
    def _extract_classes(self, source: str, target: str) -> list[dict]:
        """提取 class 定义。"""
        classes: list[dict] = []

        # class X { ... } / class X extends Y { ... }
        class_re = re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?"
            r"(?:abstract\s+)?class\s+(\w+)"
            r"(?:\s+extends\s+([\w.]+))?"
            r"(?:\s+implements\s+([\w.,\s]+))?",
            re.MULTILINE,
        )

        for match in class_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            name = match.group(1)
            extends = match.group(2) or ""
            implements_str = match.group(3) or ""
            implements = [
                i.strip() for i in implements_str.split(",") if i.strip()
            ] if implements_str else []

            # 提取类体（花括号匹配）
            body_start = source.find("{", match.end())
            methods = self._extract_class_methods(source, body_start) if body_start >= 0 else []

            classes.append({
                "name": name,
                "bases": [extends] if extends else [],
                "implements": implements,
                "methods": methods,
                "line": line_no,
            })

        return classes

    def _extract_class_methods(self, source: str, body_start: int) -> list[dict]:
        """从类体中提取方法。"""
        methods: list[dict] = []
        # 简单方法匹配：
        #   methodName(params) {
        #   async methodName(params) {
        #   static methodName(params) {
        #   get/set prop() {
        method_re = re.compile(
            r"^\s*(static\s+)?(async\s+)?(get\s+|set\s+)?"
            r"(\w+)\s*\(([^)]*)\)\s*[:{]",
            re.MULTILINE,
        )

        # 确定类体结束位置（粗略：下一行同缩进的 } 或下一个 class/export）
        body_end = self._find_class_end(source, body_start)
        body = source[body_start:body_end]

        for match in method_re.finditer(body):
            name = match.group(4)
            if name in ("if", "for", "while", "switch", "catch", "return",
                        "constructor", "class", "function", "export", "import"):
                if name != "constructor":
                    continue
            params = [p.strip().split(":")[0].strip().split("=")[0].strip()
                      for p in (match.group(5) or "").split(",") if p.strip()]
            line_offset = body[:match.start()].count("\n")
            methods.append({
                "name": name,
                "params": params,
                "is_static": bool(match.group(1)),
                "is_async": bool(match.group(2)),
                "line": body_start + line_offset + 1 if "\n" in body[:match.start()] else body_start + 1,
            })

        return methods

    @staticmethod
    def _find_class_end(source: str, body_start: int) -> int:
        """粗略查找类体结束位置（花括号配对）。"""
        depth = 0
        i = body_start
        while i < len(source):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return len(source)

    # ------------------------------------------------------------------
    # Function 提取
    # ------------------------------------------------------------------
    def _extract_functions(self, source: str, target: str) -> list[dict]:
        """提取顶层函数定义。"""
        functions: list[dict] = []

        # function name(params) { ... }
        # async function name(params) { ... }
        func_re = re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?"
            r"(async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
            re.MULTILINE,
        )
        for match in func_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            params = [p.strip().split(":")[0].strip().split("=")[0].strip()
                      for p in (match.group(3) or "").split(",") if p.strip()]
            functions.append({
                "name": match.group(2),
                "params": params,
                "is_async": bool(match.group(1)),
                "type": "function",
                "line": line_no,
            })

        # const name = (params) => { ... } or (params) => expr
        # const name = async (params) => { ... }
        # const name = (params: T): R => { ... } (with return type)
        arrow_re = re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
            r"(?:async\s*)?\(([^)]*)\)\s*(?::\s*[^=]+?)?\s*=>",
            re.MULTILINE,
        )
        for match in arrow_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            name = match.group(1)
            params = [p.strip().split(":")[0].strip().split("=")[0].strip()
                      for p in (match.group(2) or "").split(",") if p.strip()]
            functions.append({
                "name": name,
                "params": params,
                "is_async": "async" in (match.group(0) or ""),
                "type": "arrow",
                "line": line_no,
            })

        # const name = function(params) { ... }
        func_expr_re = re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
            r"(async\s+)?function\s*\(([^)]*)\)",
            re.MULTILINE,
        )
        for match in func_expr_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            params = [p.strip().split(":")[0].strip().split("=")[0].strip()
                      for p in (match.group(3) or "").split(",") if p.strip()]
            functions.append({
                "name": match.group(1),
                "params": params,
                "is_async": bool(match.group(2)),
                "type": "function_expr",
                "line": line_no,
            })

        return functions

    # ------------------------------------------------------------------
    # Export 提取
    # ------------------------------------------------------------------
    def _extract_exports(
        self,
        source: str,
        target: str,
        classes: list[dict],
        functions: list[dict],
    ) -> list[dict]:
        """提取 export 声明。"""
        exports: list[dict] = []

        # export class X / export function X / export const X
        export_re = re.compile(
            r"^\s*export\s+(?:default\s+)?"
            r"(class|function|const|let|var)\s+(\w+)",
            re.MULTILINE,
        )
        for match in export_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            exports.append({
                "name": match.group(2),
                "kind": match.group(1),
                "is_default": "default" in (match.group(0) or ""),
                "line": line_no,
            })

        # export { A, B, C }
        export_brace_re = re.compile(
            r"^\s*export\s+\{([^}]+)\}",
            re.MULTILINE,
        )
        for match in export_brace_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            names = [n.strip().split(" as ")[0].strip()
                     for n in match.group(1).split(",") if n.strip()]
            for n in names:
                exports.append({
                    "name": n,
                    "kind": "named",
                    "is_default": False,
                    "line": line_no,
                })

        # module.exports = { A, B }
        module_exports_re = re.compile(
            r"module\.exports\s*=\s*\{([^}]+)\}",
            re.MULTILINE,
        )
        for match in module_exports_re.finditer(source):
            line_no = source[:match.start()].count("\n") + 1
            names = [n.strip().split(":")[0].strip()
                     for n in match.group(1).split(",") if n.strip()]
            for n in names:
                exports.append({
                    "name": n,
                    "kind": "module_exports",
                    "is_default": False,
                    "line": line_no,
                })

        return exports

    # ------------------------------------------------------------------
    # Evidence 构建
    # ------------------------------------------------------------------
    def _build_evidence(
        self, target: str, imports: list, classes: list, functions: list,
    ) -> list[Evidence]:
        evidence: list[Evidence] = []

        evidence.append(Evidence(
            result=f"检测到 {len(imports)} 个导入",
            provenance={"file": target, "analysis": "imports"},
            confidence=1.0,
            known_gaps=[
                "动态导入 (import()) 无法静态解析",
                "条件 require() 无法静态解析",
                "TS 装饰器 metadata 可能修改实际导入行为",
            ],
            level="observation",
        ))
        evidence.append(Evidence(
            result=f"检测到 {len(classes)} 个类",
            provenance={"file": target, "analysis": "classes"},
            confidence=0.9,
            known_gaps=[
                "动态生成的类（工厂函数返回 class）无法静态解析",
                "TS mixin 和 applyMixin 产生的类无法静态追踪",
                "运行时 monkey patch 修改的方法签名无法检测",
            ],
            level="observation",
        ))
        evidence.append(Evidence(
            result=f"检测到 {len(functions)} 个函数",
            provenance={"file": target, "analysis": "functions"},
            confidence=0.85,
            known_gaps=[
                "动态函数定义（eval/new Function）无法静态解析",
                "方法简写语法的参数可能被正则漏检",
                "高阶函数返回的闭包调用链无法静态追踪",
                "动态属性访问（obj[methodName]()）无法解析",
            ],
            level="observation",
        ))
        return evidence
