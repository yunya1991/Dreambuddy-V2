"""调用链追踪器 — 分析函数/方法间的调用关系。"""

from __future__ import annotations

import ast
import os
from typing import Any

from .evidence import Evidence


class CallChainTracer:
    """追踪 Python 源码中的函数调用关系。

    能力：
    - 扫描目录下所有 .py 文件
    - 构建函数定义表（module.class.func / module.func）
    - 构建调用图：caller → [callees]
    - 追踪指定函数的调用链（向上：谁调用了它；向下：它调用了谁）
    - 返回带 Evidence 的调用图
    """

    def trace(self, target: str, entry: str | None = None) -> dict[str, Any]:
        """追踪调用链。

        Args:
            target: 目录路径或单个 .py 文件
            entry: 入口函数名（可选），指定后返回该函数的完整调用链

        Returns:
            {
                "callers": {func: [调用者列表]},
                "callees": {func: [被调用者列表]},
                "all_functions": [所有函数定义],
                "entry_chain": {callers_up, callees_down} (仅当 entry 指定时),
                "evidence": [Evidence],
            }
        """
        files = self._collect_files(target)
        if not files:
            return {"callers": {}, "callees": {}, "all_functions": [],
                    "entry_chain": None, "evidence": [
                Evidence(result="未找到 Python 文件", provenance={"target": target},
                         confidence=1.0, known_gaps=["目标不是目录或不含 .py 文件"],
                         level="observation")
            ]}

        callers: dict[str, list[str]] = {}
        callees: dict[str, list[str]] = {}
        all_funcs: set[str] = set()

        for fpath in files:
            module = self._file_to_module(fpath, target)
            self._analyze_file(fpath, module, callers, callees, all_funcs)

        entry_chain = None
        if entry:
            entry_chain = self._trace_entry(entry, callers, callees)

        evidence = self._build_evidence(len(all_funcs), len(callees), entry, target)

        return {
            "callers": callers,
            "callees": callees,
            "all_functions": sorted(all_funcs),
            "entry_chain": entry_chain,
            "evidence": evidence,
        }

    # ------------------------------------------------------------------
    def _collect_files(self, target: str) -> list[str]:
        files = []
        if os.path.isfile(target) and target.endswith(".py"):
            files.append(target)
        elif os.path.isdir(target):
            for root, _, names in os.walk(target):
                for n in names:
                    if n.endswith(".py") and not n.startswith("__"):
                        files.append(os.path.join(root, n))
        return files

    @staticmethod
    def _file_to_module(fpath: str, root: str) -> str:
        rel = os.path.relpath(fpath, root)
        return rel.replace(os.sep, ".").removesuffix(".py")

    def _analyze_file(self, fpath: str, module: str,
                      callers: dict, callees: dict, all_funcs: set) -> None:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            return

        # 第一遍：收集函数定义
        func_defs: dict[str, str] = {}  # func_name -> full_name
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 找父类
                parent_class = None
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef) and node in parent.body:
                        parent_class = parent.name
                        break
                if parent_class:
                    full = f"{module}.{parent_class}.{node.name}"
                else:
                    full = f"{module}.{node.name}"
                func_defs[node.name] = full
                all_funcs.add(full)

        # 第二遍：收集调用
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                caller_full = func_defs.get(node.name, f"{module}.{node.name}")
                calls = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        callee = self._call_name(sub.func)
                        if callee and callee in func_defs:
                            calls.add(func_defs[callee])
                if calls:
                    callees[caller_full] = sorted(calls)
                    for c in calls:
                        callers.setdefault(c, []).append(caller_full)

    @staticmethod
    def _call_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _trace_entry(self, entry: str, callers: dict, callees: dict) -> dict:
        return {
            "callers_up": callers.get(entry, []),
            "callees_down": callees.get(entry, []),
        }

    def _build_evidence(self, n_funcs: int, n_callers: int, entry: str | None,
                        target: str) -> list[Evidence]:
        evidence = []
        evidence.append(Evidence(
            result=f"调用图: {n_funcs} 函数, {n_callers} 调用关系",
            provenance={"target": target, "analysis": "call_chain"},
            confidence=0.9,
            known_gaps=["动态调用 (getattr/反射) 无法静态追踪",
                        "装饰器修改的函数名可能不匹配",
                        "跨模块调用需完整解析 import 链"],
            level="derivation",
        ))
        if entry:
            evidence.append(Evidence(
                result=f"入口函数 {entry} 的调用链已追踪",
                provenance={"target": target, "entry": entry},
                confidence=0.8,
                known_gaps=["入口函数若不在分析范围内，结果为空"],
                level="inference",
            ))
        return evidence
