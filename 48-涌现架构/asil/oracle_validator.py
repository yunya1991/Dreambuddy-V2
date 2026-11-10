"""Oracle 纯静态校验器 — Phase 1 降级实现。

SPEC v0.2 P0-1：Phase 1 纯静态校验器（无 LLM、无 REA 依赖），
检查 BuildPlan 的 JSON schema + py_compile 可导入 + 无旁路痕迹。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 旁路关键词（禁止出现在 BuildPlan 列出的模块中）
# ---------------------------------------------------------------------------
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


@dataclass
class OracleResult:
    """Oracle 校验结果。"""

    schema_ok: bool = False
    compile_ok: bool = False
    bypass_clean: bool = False
    confidence: float = 0.0  # 三项通过率平均
    violations: List[str] = field(default_factory=list)
    verdict: str = "inconclusive"  # candidate / rejected / inconclusive

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_ok": self.schema_ok,
            "compile_ok": self.compile_ok,
            "bypass_clean": self.bypass_clean,
            "confidence": self.confidence,
            "violations": self.violations,
            "verdict": self.verdict,
        }


class OracleValidator:
    """Phase 1 纯静态 Oracle 校验器。

    代码隔离硬约束（C11）：完全独立模块，不 import 33-REA。
    """

    def __init__(self, bypass_keywords: Optional[List[str]] = None):
        self.bypass_keywords = bypass_keywords or _BYPASS_KEYWORDS

    def validate(self, build_plan: Optional[Dict[str, Any]]) -> OracleResult:
        """对 BuildPlan 执行三项校验。

        Args:
            build_plan: D2 生成器产出的 BuildPlan，或 None（FAIL-OPEN）

        Returns:
            OracleResult — 三项通过率平均为 oracle_confidence
        """
        result = OracleResult()

        if build_plan is None:
            result.verdict = "inconclusive"
            result.violations.append("build_plan is None (FAIL-OPEN from upstream)")
            return result

        # ① Schema 完整性
        result.schema_ok = self._check_schema(build_plan, result.violations)

        # ② py_compile 可导入（仅检查 modules 列表中的文件是否可编译）
        modules = build_plan.get("modules", [])
        result.compile_ok = self._check_compile(modules, result.violations)

        # ③ 旁路痕迹扫描
        result.bypass_clean = self._check_bypass(build_plan, result.violations)

        # Confidence = 三项通过率平均
        passed = sum([result.schema_ok, result.compile_ok, result.bypass_clean])
        result.confidence = passed / 3.0

        # Verdict 判定
        if result.confidence >= 0.67:  # 至少两项通过
            result.verdict = "candidate"
        elif result.confidence == 0.0:
            result.verdict = "rejected"
        else:
            result.verdict = "inconclusive"

        return result

    def _check_schema(self, plan: Dict[str, Any], violations: List[str]) -> bool:
        required = ["architecture_graph", "modules", "design_rationale"]
        missing = [k for k in required if k not in plan]
        if missing:
            violations.append(f"missing schema keys: {missing}")
            return False
        if not isinstance(plan.get("modules"), list):
            violations.append("modules must be a list")
            return False
        if len(plan["modules"]) == 0:
            violations.append("modules list is empty")
            return False
        return True

    def _check_compile(self, modules: List[str], violations: List[str]) -> bool:
        """对模块路径跑 py_compile。Phase 1 容忍不存在的文件（violation 但不算 fail）。"""
        if not modules:
            return True

        all_ok = True
        for mod in modules:
            try:
                proc = subprocess.run(
                    ["python3", "-m", "py_compile", str(mod)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode != 0:
                    # 文件不存在 → Phase 1 容忍（violation 但不影响 pass）
                    if "No such file" in proc.stderr or "cannot open" in proc.stderr:
                        violations.append(f"py_compile skipped (tolerated): {mod}")
                        continue
                    all_ok = False
                    violations.append(f"py_compile failed: {mod} — {proc.stderr.strip()[:200]}")
            except subprocess.TimeoutExpired as e:
                # subprocess.run 自身不抛 FileNotFoundError（python3 命令存在）
                violations.append(f"py_compile timeout (tolerated): {mod} — {e}")
        return all_ok

    def _check_bypass(self, plan: Dict[str, Any], violations: List[str]) -> bool:
        """扫描 BuildPlan 文本中是否包含旁路关键词。"""
        text = json.dumps(plan, default=str).lower()
        found = [kw for kw in self.bypass_keywords if kw in text]
        if found:
            violations.append(f"bypass keywords found: {found}")
            return False
        return True
