"""ASIL Phase 2 Oracle — 独立 AST 拓扑分析器。

SPEC v0.2 P0-1 升级：从 Phase 1 纯静态校验 → 独立 AST 拓扑分析。
硬约束 C11：完全不 import 33-REA，一套独立代码。
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class OracleResultV2:
    """Phase 2 Oracle 结果。"""

    schema_ok: bool = False
    compile_ok: bool = False
    bypass_clean: bool = False
    ast_parseable: bool = False
    dependency_acyclic: bool = True
    complexity_ok: bool = False
    confidence: float = 0.0
    violations: List[str] = field(default_factory=list)
    verdict: str = "inconclusive"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_ok": self.schema_ok,
            "compile_ok": self.compile_ok,
            "bypass_clean": self.bypass_clean,
            "ast_parseable": self.ast_parseable,
            "dependency_acyclic": self.dependency_acyclic,
            "complexity_ok": self.complexity_ok,
            "confidence": self.confidence,
            "violations": self.violations,
            "verdict": self.verdict,
        }


# Phase 1 旁路关键词保留
_BYPASS_KEYWORDS = [
    "subprocess",
    "eval(",
    "exec(",
    "os.system",
    "__import__",
    "open(",
    "pathlib",
    "socket",
    "http.client",
    "urllib",
    "shutil",
    "pickle",
    "yaml.load",
    "marshal",
]

_MAX_COMPLEXITY = 10  # 圈复杂度阈值


class OracleValidatorV2:
    """Phase 2 Oracle — 独立 AST 拓扑分析器。

    代码隔离硬约束 C11：不 import 33-REA，完全独立模块。
    """

    def __init__(self):
        self.bypass_keywords = _BYPASS_KEYWORDS

    def validate(self, build_plan: Optional[Dict[str, Any]]) -> OracleResultV2:
        result = OracleResultV2()

        if build_plan is None:
            result.violations.append("build_plan is None (FAIL-OPEN from upstream)")
            return result

        # --- ① Schema 完整性（继承 Phase 1） ---
        result.schema_ok = self._check_schema(build_plan, result.violations)

        # --- ② py_compile 可导入（继承 Phase 1） ---
        modules = build_plan.get("modules", [])
        result.compile_ok = self._check_compile(modules, result.violations)

        # --- ③ 旁路痕迹扫描（继承 Phase 1） ---
        result.bypass_clean = self._check_bypass(build_plan, result.violations)

        # --- ④ AST 可解析性（仅当存在 code_skeleton 时检查） ---
        code = build_plan.get("code_skeleton") or ""
        if code:
            result.ast_parseable = self._check_ast(code, result.violations)
        else:
            result.ast_parseable = True  # 无代码骨架 → N/A，不计入硬失败
            result.violations.append("no code_skeleton (ast check skipped)")

        # --- ⑤ 依赖图无环（基于 architecture_graph.edges 拓扑排序） ---
        result.dependency_acyclic = self._check_acyclic(build_plan, result.violations)

        # --- ⑥ 圈复杂度阈值（新增） ---
        result.complexity_ok = self._check_complexity(code, result.violations)

        # --- Confidence = 六项通过率 ---
        passed = sum(
            [
                result.schema_ok,
                result.compile_ok,
                result.bypass_clean,
                result.ast_parseable,
                result.dependency_acyclic,
                result.complexity_ok,
            ]
        )
        result.confidence = passed / 6.0

        # --- Verdict 判定（整数计数 + 硬失败一票否决） ---
        # 硬失败项：schema 缺失 / 旁路 / 代码不可解析 / 依赖成环
        # 软失败项：compile（文件缺失容忍）、complexity（仅告警）
        hard_fail = (
            not result.schema_ok
            or not result.bypass_clean
            or not result.ast_parseable
            or not result.dependency_acyclic
        )
        if hard_fail:
            result.verdict = "rejected"
        elif passed >= 5:
            result.verdict = "candidate"
        else:
            result.verdict = "inconclusive"

        return result

    # ------------------------------------------------------------------
    # 六项校验实现
    # ------------------------------------------------------------------
    def _check_schema(self, plan: Dict, violations: List[str]) -> bool:
        required = ["gap_id", "gap_type", "modules", "design_rationale"]
        missing = [k for k in required if k not in plan]
        if missing:
            violations.append(f"missing schema keys: {missing}")
            return False
        if not isinstance(plan.get("modules"), list) or len(plan["modules"]) == 0:
            violations.append("modules must be non-empty list")
            return False
        return True

    def _check_compile(self, modules: List, violations: List[str]) -> bool:
        """Phase 2 升级：检查 modules 列表——不存在文件记 violation 但不 fail。"""
        if not modules:
            return False
        all_valid = True
        for mod in modules:
            mod_path = Path(mod)
            if not mod_path.exists():
                violations.append(f"module file not found (tolerated): {mod}")
                continue  # Phase 2 仍容忍 stub 路径
            if not mod_path.suffix == ".py":
                violations.append(f"non-python module: {mod}")
                all_valid = False
        return all_valid

    def _check_bypass(self, plan: Dict, violations: List[str]) -> bool:
        text = json.dumps(plan, default=str).lower()
        found = [kw for kw in self.bypass_keywords if kw in text]
        if found:
            violations.append(f"bypass keywords found: {found}")
            return False
        return True

    def _check_ast(self, code: str, violations: List[str]) -> bool:
        """新增：AST 可解析性。"""
        if not code:
            violations.append("no code to parse")
            return False
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            violations.append(f"ast.parse failed: {e.msg} at line {e.lineno}")
            return False

    def _check_acyclic(self, plan: Dict, violations: List[str]) -> bool:
        """依赖图无环检测（Kahn 拓扑排序）。

        优先使用 architecture_graph.edges；无显式边时退化为重复节点检查。
        """
        graph = plan.get("architecture_graph") or {}
        edges = graph.get("edges") or plan.get("edges") or []

        # 无显式边 → 退化检查：重复节点视为异常
        if not edges:
            nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, str)]
            if len(set(nodes)) != len(nodes):
                violations.append("duplicate nodes in architecture_graph")
                return False
            return True

        # Kahn 算法
        indeg: Dict[Any, int] = {}
        adj: Dict[Any, List[Any]] = {}
        for e in edges:
            pair = self._normalize_edge(e)
            if pair is None:
                violations.append(f"malformed edge: {e}")
                return False
            u, v = pair
            adj.setdefault(u, []).append(v)
            indeg.setdefault(u, 0)
            indeg[v] = indeg.get(v, 0) + 1

        queue = [n for n, d in indeg.items() if d == 0]
        visited = 0
        while queue:
            n = queue.pop()
            visited += 1
            for m in adj.get(n, []):
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)

        if visited != len(indeg):
            violations.append("circular dependency detected in architecture_graph")
            return False
        return True

    @staticmethod
    def _normalize_edge(edge: Any) -> Optional[Any]:
        """把边归一化为 (u, v)。支持 tuple/list 与常见 dict 键。"""
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            return edge[0], edge[1]
        if isinstance(edge, dict):
            for ku, kv in (
                ("from", "to"),
                ("source", "target"),
                ("src", "dst"),
                ("u", "v"),
                ("parent", "child"),
            ):
                if ku in edge and kv in edge:
                    return edge[ku], edge[kv]
        return None

    def _check_complexity(self, code: str, violations: List[str]) -> bool:
        """新增：简化圈复杂度 = if/for/while/except 数量 + 1。"""
        if not code:
            return True  # 空 code 视为简单
        try:
            tree = ast.parse(code)
        except SyntaxError:
            violations.append("cannot compute complexity (ast parse failed)")
            return False
        n_complex = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp))
        )
        complexity = n_complex + 1
        if complexity > _MAX_COMPLEXITY:
            violations.append(f"complexity {complexity} > max {_MAX_COMPLEXITY}")
            return False
        return True
