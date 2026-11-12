"""逆向调查工作流编排 — 四阶段结构化逆向分析。

工作流四阶段（借鉴 REA 调查方法论）：
1. 定位 (Locate)  — 检测目标类型，识别模块/入口点
2. 追踪 (Trace)   — 构建调用图，追踪关键调用链
3. 还原 (Reduce)  — 识别算法模式，生成伪代码
4. 标注 (Annotate)— 聚合 Evidence，生成调查报告 + known_gaps

每阶段输出独立 Evidence，标注阶段汇总后形成最终调查报告。
"""

from __future__ import annotations  # noqa: I001

import os
from typing import Any

from .analyzer_base import AnalyzeResult
from .call_chain_tracer import CallChainTracer
from .dependency_graph import DependencyGraph
from .evidence import Evidence, reverse_evidence
from .python_analyzer import PythonAnalyzer
from .algorithm_reducer import reduce_algorithm

# TS 分析器（可选导入，TS 扩展时加载）
try:
    from .ts_analyzer import TSAnalyzer
    from .ts_project_analyzer import TSProjectAnalyzer
except ImportError:
    TSAnalyzer = None  # type: ignore
    TSProjectAnalyzer = None  # type: ignore


# 常见入口函数名（按优先级排序）
_ENTRY_CANDIDATES = [
    "main",
    "__main__",
    "run",
    "start",
    "execute",
    "handle",
    "app",
    "create_app",
    "cli",
    "entry_point",
]

# Python 文件扩展名
_PY_EXTS = (".py",)
_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


class InvestigationWorkflow:
    """逆向调查工作流编排器。

    四阶段：
        Locate → Trace → Reduce → Annotate

    用法：
        wf = InvestigationWorkflow()
        result = wf.run("/path/to/project", feature="用户登录", entry="main")
    """

    def __init__(self) -> None:
        # 同一次调查内复用 TS 项目级解析结果（避免 locate/trace 重复全量扫描）
        self._ts_cache: dict[str, AnalyzeResult] = {}

    def _analyze_ts_project(self, target: str) -> AnalyzeResult | None:
        """TS 项目级分析（带缓存）。"""
        if TSProjectAnalyzer is None:
            return None
        key = os.path.abspath(target)
        if key not in self._ts_cache:
            self._ts_cache[key] = TSProjectAnalyzer(key).analyze()
        return self._ts_cache[key]

    def run(
        self,
        target: str,
        feature: str | None = None,
        entry: str | None = None,
    ) -> dict[str, Any]:
        """执行完整四阶段逆向调查。

        Args:
            target: 目标路径（目录或文件）
            feature: 要调查的功能描述（可选）
            entry: 指定入口函数名（可选）

        Returns:
            {
                "target": str,
                "feature": str | None,
                "summary": str,
                "phases": {locate, trace, reduce, annotate},
                "evidence": [Evidence],
                "known_gaps": [str],
            }
        """
        result: dict[str, Any] = {
            "target": target,
            "feature": feature,
            "summary": "",
            "phases": {},
            "evidence": [],
            "known_gaps": [],
        }

        # Phase 1: 定位
        locate = self._phase_locate(target, entry)
        result["phases"]["locate"] = locate

        # 如果目标无效，提前返回
        if not locate.get("valid", True):
            result["evidence"] = locate.get("evidence", [])
            result["summary"] = locate.get("summary", "定位失败")
            result["known_gaps"] = ["目标无效，调查中止"]
            return result

        # Phase 2: 追踪
        trace = self._phase_trace(target, entry, locate)
        result["phases"]["trace"] = trace

        # Phase 3: 还原
        reduce = self._phase_reduce(target, locate, trace)
        result["phases"]["reduce"] = reduce

        # Phase 4: 标注
        annotate = self._phase_annotate(result["phases"], target, feature)
        result["phases"]["annotate"] = annotate

        # 聚合顶层（按 evidence_id 去重，标注阶段已含前序阶段证据）
        all_evidence: list[Evidence] = []
        all_gaps: list[str] = []
        for phase_data in result["phases"].values():
            all_evidence.extend(phase_data.get("evidence", []))
            for ev in phase_data.get("evidence", []):
                all_gaps.extend(ev.known_gaps)

        result["evidence"] = _dedupe_evidence(all_evidence)
        result["known_gaps"] = list(set(all_gaps))  # 去重
        result["summary"] = annotate.get("summary", "")

        return result

    # ------------------------------------------------------------------
    # Phase 1: 定位 (Locate)
    # ------------------------------------------------------------------
    def _phase_locate(
        self,
        target: str,
        entry: str | None,
    ) -> dict[str, Any]:
        """定位阶段：检测目标类型、识别模块和入口点。"""
        phase: dict[str, Any] = {
            "valid": True,
            "target_type": "unknown",
            "language": "unknown",
            "entry_points": [],
            "modules": [],
            "evidence": [],
            "summary": "",
        }

        if not os.path.exists(target):
            phase["valid"] = False
            phase["evidence"].append(
                Evidence(
                    result=f"目标不存在: {target}",
                    provenance={"target": target, "phase": "locate"},
                    confidence=1.0,
                    known_gaps=["无法定位不存在的目标"],
                    level="unknown",
                )
            )
            phase["summary"] = f"目标不存在: {target}"
            return phase

        # 检测目标类型
        if os.path.isfile(target):
            phase["target_type"] = "file"
            ext = os.path.splitext(target)[1]
            if ext in _PY_EXTS:
                phase["language"] = "python"
            elif ext in _TS_EXTS:
                phase["language"] = "typescript"
            else:
                phase["language"] = "unknown"

            # 单文件分析
            analyzer = self._get_analyzer(phase["language"])
            if analyzer:
                analyze_result = analyzer.analyze(target)
                phase["modules"] = [os.path.basename(target)]
                phase["evidence"].extend(analyze_result.evidence)
                phase["entry_points"] = self._detect_entry_points_single(
                    analyze_result,
                    entry,
                )
            else:
                phase["evidence"].append(
                    Evidence(
                        result=f"不支持的语言: {ext}",
                        provenance={"target": target, "phase": "locate"},
                        confidence=1.0,
                        known_gaps=["该语言类型暂不支持分析"],
                        level="unknown",
                    )
                )
        elif os.path.isdir(target):
            phase["target_type"] = "directory"
            # 检测目录主要语言
            phase["language"] = self._detect_directory_language(target)

            if phase["language"] == "typescript":
                # TS/React 项目级分析：路由 / 依赖图 / 组件 / store / 架构模式
                ts_result = self._analyze_ts_project(target)
                if ts_result is not None:
                    raw = ts_result.raw
                    graph = raw.get("graph", {})
                    phase["modules"] = list(graph.get("nodes", []))
                    phase["evidence"].extend(ts_result.evidence)
                    phase["entry_points"] = self._detect_ts_entry_points(raw, entry)
                else:
                    phase["evidence"].append(
                        Evidence(
                            result="TS 项目级分析器不可用",
                            provenance={"target": target, "phase": "locate"},
                            confidence=0.5,
                            known_gaps=["TSProjectAnalyzer 导入失败，仅能降级"],
                            level="unknown",
                        )
                    )
            else:
                # 依赖图
                dep_graph = DependencyGraph()
                dep_result = dep_graph.build(target)
                phase["modules"] = dep_result.get("nodes", [])
                phase["evidence"].extend(dep_result.get("evidence", []))

                # 分析入口文件
                phase["entry_points"] = self._detect_entry_points_dir(
                    target,
                    phase["language"],
                    entry,
                )
        else:
            phase["valid"] = False
            phase["evidence"].append(
                Evidence(
                    result=f"目标类型无法识别: {target}",
                    provenance={"target": target, "phase": "locate"},
                    confidence=1.0,
                    known_gaps=["目标既不是文件也不是目录"],
                    level="unknown",
                )
            )

        phase["summary"] = (
            f"定位: {phase['language']} {phase['target_type']} | "
            f"{len(phase['modules'])} 模块 | "
            f"{len(phase['entry_points'])} 入口点"
        )

        if not phase["evidence"]:
            phase["evidence"].append(
                Evidence(
                    result="定位阶段完成",
                    provenance={"target": target, "phase": "locate"},
                    confidence=0.9,
                    known_gaps=["入口点可能需要人工确认"],
                    level="observation",
                )
            )

        return phase

    # ------------------------------------------------------------------
    # Phase 2: 追踪 (Trace)
    # ------------------------------------------------------------------
    def _phase_trace(
        self,
        target: str,
        entry: str | None,
        locate: dict[str, Any],
    ) -> dict[str, Any]:
        """追踪阶段：构建调用图，追踪关键调用链。"""
        phase: dict[str, Any] = {
            "callers": {},
            "callees": {},
            "all_functions": [],
            "entry_chain": None,
            "evidence": [],
            "summary": "",
        }

        # TS/JS：基于项目级 import 图追踪模块依赖（不做函数级调用链）
        if locate.get("language") == "typescript":
            ts_result = self._analyze_ts_project(target) if os.path.isdir(target) else None
            if ts_result is None:
                phase["evidence"].append(
                    Evidence(
                        result="TS/JS 单文件调用链追踪暂不支持",
                        provenance={"target": target, "phase": "trace"},
                        confidence=1.0,
                        known_gaps=["单文件 TS 追踪需项目上下文（import 图），请传目录目标"],
                        level="unknown",
                    )
                )
                phase["summary"] = "追踪: TS 单文件，跳过"
                return phase

            raw = ts_result.raw
            graph = raw.get("graph", {})
            adjacency = graph.get("adjacency", {})
            callers: dict[str, list[str]] = {}
            for src, dsts in adjacency.items():
                for dst in dsts:
                    callers.setdefault(dst, []).append(src)
            phase["callers"] = {k: sorted(set(v)) for k, v in callers.items()}
            phase["callees"] = {k: sorted(set(v)) for k, v in adjacency.items()}
            phase["all_functions"] = [
                {"name": c["name"], "file": c.get("file", ""), "kind": "component"}
                for c in raw.get("components", [])
            ] + [{"name": h, "file": "", "kind": "hook"} for h in raw.get("hooks", [])]
            phase["entry_chain"] = self._ts_entry_chain(raw)
            phase["evidence"].extend(
                e
                for e in ts_result.evidence
                if e.provenance.get("analysis")
                in {"dependency_graph", "cycle_detection", "orphan_scan"}
            )
            phase["summary"] = (
                f"追踪: TS/React {len(graph.get('nodes', []))} 模块, "
                f"{len(graph.get('edges', []))} 依赖边, "
                f"{len(graph.get('cycles', []))} 循环"
            )
            return phase

        tracer = CallChainTracer()
        # 确定追踪目标
        trace_target = target
        if os.path.isfile(target) and not target.endswith(".py"):
            phase["evidence"].append(
                Evidence(
                    result="非 Python 文件，调用链追踪跳过",
                    provenance={"target": target, "phase": "trace"},
                    confidence=1.0,
                    known_gaps=["CallChainTracer 仅支持 Python AST"],
                    level="observation",
                )
            )
            phase["summary"] = "追踪: 非 Python 目标，跳过"
            return phase

        # 如果是单文件，追踪所在目录
        if os.path.isfile(target):
            trace_target = os.path.dirname(target)

        trace_result = tracer.trace(trace_target, entry=entry)

        phase["callers"] = trace_result.get("callers", {})
        phase["callees"] = trace_result.get("callees", {})
        phase["all_functions"] = trace_result.get("all_functions", [])
        phase["entry_chain"] = trace_result.get("entry_chain")
        phase["evidence"].extend(trace_result.get("evidence", []))

        n_funcs = len(phase["all_functions"])
        n_calls = sum(len(v) for v in phase["callers"].values())

        phase["summary"] = f"追踪: {n_funcs} 函数, {n_calls} 调用关系" + (
            f", 入口链={entry}" if entry else ""
        )

        return phase

    # ------------------------------------------------------------------
    # Phase 3: 还原 (Reduce)
    # ------------------------------------------------------------------
    def _phase_reduce(
        self,
        target: str,
        locate: dict[str, Any],
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        """还原阶段：识别算法模式，生成伪代码。"""
        phase: dict[str, Any] = {
            "functions": [],
            "patterns": [],
            "pseudo_code": [],
            "evidence": [],
            "summary": "",
        }

        # 仅支持 Python 文件的算法伪代码还原
        if locate.get("language") != "python":
            ts_evidence: list[Evidence] = []
            if locate.get("language") == "typescript":
                ts_evidence.append(
                    Evidence(
                        result="TS/React 目标：算法伪代码还原跳过，已由项目级结构还原替代",
                        provenance={"target": target, "phase": "reduce"},
                        confidence=0.9,
                        known_gaps=[
                            "AlgorithmReducer 仅支持 Python AST",
                            "TS 组件/状态流已通过 import 图与组件图还原，函数级伪代码未生成",
                        ],
                        level="observation",
                    )
                )
            else:
                ts_evidence.append(
                    Evidence(
                        result="非 Python 目标，算法还原跳过",
                        provenance={"target": target, "phase": "reduce"},
                        confidence=1.0,
                        known_gaps=["AlgorithmReducer 仅支持 Python AST"],
                        level="observation",
                    )
                )
            phase["evidence"].extend(ts_evidence)
            phase["summary"] = "还原: 非 Python 目标，跳过"
            return phase

        # 对目标中的每个 Python 文件执行算法还原
        py_files: list[str] = []
        if os.path.isfile(target) and target.endswith(".py"):
            py_files = [target]
        elif os.path.isdir(target):
            for root, _, files in os.walk(target):
                for f in files:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(root, f))

        all_functions: list[dict] = []
        all_patterns: list[dict] = []
        all_pseudo: list[str] = []

        for py_file in py_files:
            reduce_result = reduce_algorithm(py_file)
            all_functions.extend(reduce_result.get("functions", []))
            all_patterns.extend(reduce_result.get("patterns", []))
            all_pseudo.extend(reduce_result.get("pseudo_code", []))
            phase["evidence"].extend(reduce_result.get("evidence", []))

        phase["functions"] = all_functions
        phase["patterns"] = all_patterns
        phase["pseudo_code"] = all_pseudo

        phase["summary"] = f"还原: {len(all_functions)} 函数分析, " f"{len(all_patterns)} 模式识别"

        if not all_functions:
            phase["evidence"].append(
                Evidence(
                    result="未识别到算法模式",
                    provenance={"target": target, "phase": "reduce"},
                    confidence=0.8,
                    known_gaps=["可能全是简单函数调用，无复杂算法"],
                    level="observation",
                )
            )

        return phase

    # ------------------------------------------------------------------
    # Phase 4: 标注 (Annotate)
    # ------------------------------------------------------------------
    def _phase_annotate(
        self,
        phases: dict[str, Any],
        target: str,
        feature: str | None,
    ) -> dict[str, Any]:
        """标注阶段：聚合所有 Evidence，生成调查报告。"""
        # 聚合 Evidence（按 evidence_id 去重，保持首次出现顺序）
        all_evidence: list[Evidence] = []
        all_gaps: list[str] = []
        for phase_data in phases.values():
            all_evidence.extend(phase_data.get("evidence", []))
            for ev in phase_data.get("evidence", []):
                all_gaps.extend(ev.known_gaps)
        unique_evidence = _dedupe_evidence(all_evidence)

        # 去重 known_gaps
        unique_gaps = sorted(set(all_gaps))

        # 统计 Evidence 层级分布
        level_counts: dict[str, int] = {}
        for e in unique_evidence:
            level = e.level.value if hasattr(e.level, "value") else str(e.level)
            level_counts[level] = level_counts.get(level, 0) + 1

        # P3-2: 补充架构债务维度 Evidence（供 ArchitectureReverseDeriver 消费）
        arch_evidence = self._collect_architecture_debt_evidence(target, phases, unique_gaps)
        unique_evidence = _dedupe_evidence(unique_evidence + arch_evidence)
        for ev in arch_evidence:
            unique_gaps.extend(ev.known_gaps)
        unique_gaps = sorted(set(unique_gaps))

        locate = phases.get("locate", {})
        trace = phases.get("trace", {})
        reduce = phases.get("reduce", {})

        summary_parts = [
            f"逆向调查: {locate.get('language', '?')} 项目",
        ]
        if feature:
            summary_parts.append(f"功能={feature}")
        summary_parts.append(
            f"定位({len(locate.get('modules', []))}模块/"
            f"{len(locate.get('entry_points', []))}入口)"
        )
        summary_parts.append(f"追踪({len(trace.get('all_functions', []))}函数)")
        summary_parts.append(
            f"还原({len(reduce.get('functions', []))}函数/"
            f"{len(reduce.get('patterns', []))}模式)"
        )
        summary_parts.append(f"证据({len(unique_evidence)}条/{len(unique_gaps)}局限)")

        summary = " | ".join(summary_parts)

        return {
            "evidence": unique_evidence,
            "known_gaps": unique_gaps,
            "level_distribution": level_counts,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _collect_architecture_debt_evidence(
        self, target: str, phases: dict[str, Any], known_gaps: list[str]
    ) -> list[Evidence]:
        """P3-2: 采集架构债务四维度 Evidence（供 ArchitectureReverseDeriver 消费）。

        维度：file_size / out_degree / known_gaps / git_evolution
        与 engines/reverse_deriver.py _DIMENSION_RULES 的 analysis 关键词对齐。
        """
        evidence: list[Evidence] = []

        # 1. 文件行数（按目标语言扫描源码，报告行数最高的文件）
        language = phases.get("locate", {}).get("language", "python")
        scan_exts = _TS_EXTS if language == "typescript" else _PY_EXTS
        try:
            if os.path.isdir(target):
                max_file, max_lines = "", 0
                for root, _, files in os.walk(target):
                    if "__pycache__" in root or "node_modules" in root:
                        continue
                    for f in files:
                        if not f.endswith(scan_exts) or f == "__init__.py":
                            continue
                        fp = os.path.join(root, f)
                        try:
                            with open(fp, encoding="utf-8", errors="replace") as fh:
                                lines = sum(1 for _ in fh)
                        except OSError:
                            continue
                        if lines > max_lines:
                            max_lines = lines
                            max_file = os.path.relpath(fp, target)
                if max_file:
                    evidence.append(
                        reverse_evidence(
                            result=f"文件 {max_file}: {max_lines} 行",
                            provenance={"target": target, "analysis": "line_count"},
                            confidence=1.0,
                        )
                    )
        except Exception as e:
            evidence.append(
                reverse_evidence(
                    result="文件行数统计失败",
                    provenance={"target": target, "analysis": "line_count"},
                    confidence=0.0,
                    known_gaps=[f"line_count fail: {e}"],
                )
            )

        # 2. 出度（从 dependency_graph evidence 估算：边数/节点数 = 平均出度）
        try:
            dep_ev = None
            for ev in phases.get("trace", {}).get("evidence", []):
                prov = getattr(ev, "provenance", {}) or {}
                if prov.get("analysis") == "dependency_graph":
                    dep_ev = ev
                    break
            if dep_ev is not None:
                res = str(getattr(dep_ev, "result", ""))
                import re as _re

                m = _re.search(r"(\d+)\s*节点.*?(\d+)\s*边", res)
                if m:
                    nodes, edges = int(m.group(1)), int(m.group(2))
                    avg_out = edges / nodes if nodes > 0 else 0
                    evidence.append(
                        reverse_evidence(
                            result=f"出度: {avg_out:.1f}",
                            provenance={"target": target, "analysis": "out_degree"},
                            confidence=0.8,
                        )
                    )
        except Exception:
            pass

        # 3. 豁口数（known_gaps 数量）
        gap_count = len(known_gaps)
        evidence.append(
            reverse_evidence(
                result=f"豁口: {gap_count} 项",
                provenance={"target": target, "analysis": "known_gap_audit"},
                confidence=1.0,
            )
        )

        # 4. git 演化（feat/refactor 提交计数）
        try:
            import subprocess

            git_dir = target if os.path.isdir(target) else os.path.dirname(target)
            log = subprocess.run(
                ["git", "log", "--oneline", "-n", "200", "--", target],
                capture_output=True,
                text=True,
                cwd=git_dir,
                timeout=10,
            )
            if log.returncode == 0:
                feat = sum(1 for l in log.stdout.splitlines() if "feat" in l.lower())  # noqa: E741
                ref = sum(
                    1 for l in log.stdout.splitlines() if "refactor" in l.lower()  # noqa: E741
                )  # noqa: E741
                evidence.append(
                    reverse_evidence(
                        result=f"演化: {feat} feat / {ref} refactor",
                        provenance={"target": target, "analysis": "git_history"},
                        confidence=0.9,
                    )
                )
        except Exception:
            pass

        return evidence

    @staticmethod
    def _get_analyzer(language: str):
        """根据语言获取分析器实例。"""
        if language == "python":
            return PythonAnalyzer()
        if language == "typescript" and TSAnalyzer is not None:
            return TSAnalyzer()
        return None

    @staticmethod
    def _detect_directory_language(target: str) -> str:
        """检测目录的主要编程语言。"""
        py_count = 0
        ts_count = 0
        for root, _, files in os.walk(target):  # noqa: B007
            for f in files:
                if f.endswith(".py"):
                    py_count += 1
                elif f.endswith((".ts", ".tsx", ".js", ".jsx")):
                    ts_count += 1
        if py_count > 0 and py_count >= ts_count:
            return "python"
        if ts_count > 0:
            return "typescript"
        return "unknown"

    @staticmethod
    def _detect_ts_entry_points(raw: dict[str, Any], entry: str | None) -> list[str]:
        """TS 项目入口 = API route + 顶层页面 + (可选)指定入口。"""
        if entry:
            return [entry]
        api = [f"{r['path']} [{','.join(r.get('methods', []))}]" for r in raw.get("api_routes", [])]
        pages = [r["path"] for r in raw.get("routes", [])]
        points = api[:20] + pages[:20]
        return points or ["(未自动检测到入口)"]

    @staticmethod
    def _ts_entry_chain(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
        """从首个 API route 出发，沿 import 图向下展开 3 层，作为模块级调用链。"""
        graph = raw.get("graph", {})
        adjacency = graph.get("adjacency", {})
        api_routes = raw.get("api_routes", [])
        if not api_routes:
            return None
        start = api_routes[0]["file"]
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()

        def walk(node: str, depth: int) -> None:
            if depth > 3 or node in seen:
                return
            seen.add(node)
            right = adjacency.get(node, [])
            chain.append({"module": node, "depth": depth, "imports": right})
            for nb in right:
                walk(nb, depth + 1)

        walk(start, 0)
        return chain

    @staticmethod
    def _detect_entry_points_single(
        analyze_result: AnalyzeResult,
        entry: str | None,
    ) -> list[str]:
        """从单文件分析结果检测入口点。"""
        if entry:
            return [entry]

        functions = analyze_result.raw.get("functions", [])
        func_names = [f["name"] for f in functions]
        entry_points = [name for name in _ENTRY_CANDIDATES if name in func_names]
        return entry_points if entry_points else func_names[:3]

    @staticmethod
    def _detect_entry_points_dir(
        target: str,
        language: str,
        entry: str | None,
    ) -> list[str]:
        """从目录结构检测入口点。"""
        if entry:
            return [entry]

        entry_points: list[str] = []

        # 查找常见入口文件
        for name in ("main.py", "app.py", "run.py", "cli.py", "index.ts", "index.js"):
            path = os.path.join(target, name)
            if os.path.isfile(path):
                entry_points.append(name)

        # 查找 __main__.py
        for root, _, files in os.walk(target):
            if "__main__.py" in files:
                rel = os.path.relpath(
                    os.path.join(root, "__main__.py"),
                    target,
                )
                entry_points.append(rel)

        return entry_points if entry_points else ["(未自动检测到入口)"]


def _dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """按 evidence_id 去重，保持首次出现顺序。"""
    seen_ids: set[str] = set()
    unique: list[Evidence] = []
    for ev in evidence:
        if ev.evidence_id not in seen_ids:
            seen_ids.add(ev.evidence_id)
            unique.append(ev)
    return unique


# 模块级便捷函数
def investigate(
    target: str,
    feature: str | None = None,
    entry: str | None = None,
) -> dict[str, Any]:
    """执行逆向调查工作流（便捷函数）。

    Args:
        target: 目标路径（目录或文件）
        feature: 要调查的功能描述（可选）
        entry: 指定入口函数名（可选）

    Returns:
        完整调查报告（含四阶段结果 + Evidence + known_gaps）
    """
    wf = InvestigationWorkflow()
    return wf.run(target, feature=feature, entry=entry)
