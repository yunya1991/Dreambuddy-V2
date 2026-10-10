"""依赖图构建器 — 分析模块间 import 依赖关系。"""

from __future__ import annotations

import ast
import os
from collections import defaultdict
from typing import Any

from .evidence import Evidence


class DependencyGraph:
    """构建 Python 项目的模块依赖图。

    能力：
    - 扫描目录下所有 .py 文件
    - 解析 import / from-import
    - 构建邻接表：module → [依赖的模块]
    - 检测循环依赖
    - 返回带 Evidence 的图结构
    """

    def build(self, target: str) -> dict[str, Any]:
        """构建依赖图。

        Args:
            target: 目录路径或单个 .py 文件路径

        Returns:
            {
                "nodes": [模块名列表],
                "edges": [(from_module, to_module) 列表],
                "adjacency": {module: [依赖列表]},
                "cycles": [循环依赖列表],
                "evidence": [Evidence 列表],
            }
        """
        files = self._collect_files(target)
        if not files:
            return {"nodes": [], "edges": [], "adjacency": {}, "cycles": [], "evidence": [
                Evidence(result="未找到 Python 文件", provenance={"target": target},
                         confidence=1.0, known_gaps=["目标不是目录或不含 .py 文件"],
                         level="observation")
            ]}

        adjacency: dict[str, list[str]] = defaultdict(list)
        nodes: set[str] = set()

        for fpath in files:
            module_name = self._file_to_module(fpath, target)
            nodes.add(module_name)
            deps = self._extract_deps(fpath)
            for dep in deps:
                adjacency[module_name].append(dep)
                nodes.add(dep)

        edges = [(src, dst) for src, dsts in adjacency.items() for dst in dsts]
        cycles = self._detect_cycles(adjacency)

        evidence = self._build_evidence(len(nodes), len(edges), len(cycles), target)

        return {
            "nodes": sorted(nodes),
            "edges": edges,
            "adjacency": dict(adjacency),
            "cycles": cycles,
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

    def _extract_deps(self, fpath: str) -> list[str]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            return []

        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    deps.add(node.module.split(".")[0])
        return sorted(deps)

    def _detect_cycles(self, adjacency: dict[str, list[str]]) -> list[list[str]]:
        """检测循环依赖（DFS 三色标记）。"""
        cycles = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in adjacency}

        def dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            path.append(node)
            for nb in adjacency.get(node, []):
                if color.get(nb) == GRAY:
                    cycle_start = path.index(nb)
                    cycles.append(path[cycle_start:] + [nb])
                elif color.get(nb) == WHITE:
                    dfs(nb, path)
            path.pop()
            color[node] = BLACK

        for n in list(adjacency.keys()):
            if color.get(n) == WHITE:
                dfs(n, [])
        return cycles

    def _build_evidence(self, n_nodes: int, n_edges: int, n_cycles: int,
                        target: str) -> list[Evidence]:
        evidence = []
        evidence.append(Evidence(
            result=f"依赖图: {n_nodes} 节点, {n_edges} 边",
            provenance={"target": target, "analysis": "dependency_graph"},
            confidence=1.0,
            known_gaps=["第三方库依赖未解析（只记录顶层模块名）",
                        "动态 import / 条件 import 无法静态解析"],
            level="derivation",
        ))
        if n_cycles > 0:
            evidence.append(Evidence(
                result=f"检测到 {n_cycles} 个循环依赖",
                provenance={"target": target, "analysis": "cycle_detection"},
                confidence=0.9,
                known_gaps=["循环依赖可能由条件 import 导致，需人工确认"],
                level="inference",
            ))
        else:
            evidence.append(Evidence(
                result="未检测到循环依赖",
                provenance={"target": target, "analysis": "cycle_detection"},
                confidence=0.7,
                known_gaps=["静态分析可能漏检运行时循环依赖"],
                level="inference",
            ))
        return evidence
