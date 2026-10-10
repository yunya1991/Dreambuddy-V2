"""
33-REA逆向解析工程 - DSH 节点封装

提供三个 DSH 节点函数，供 DreamOS C-Drive Agent 通过 IPC 调用：

- S33_rea_analyze:  整体架构分析（模块/依赖/调用图）
- S33_rea_trace:    功能追踪 — 某功能的调用链
- S33_rea_compare:  两工程对比

设计原则（Evidence-First）：
- 每条结论带 Evidence（provenance + confidence + known_gaps）
- 节点函数为纯计算 + 静态分析，不生成原始数据
- 输出是结构化 SubagentOutput 摘要（压缩格式）

调用契约（DSH stdin NDJSON）：
    {"method": "s33_rea_analyze", "params": {"target": "/path", "scope": "architecture"}}
    {"method": "s33_rea_trace", "params": {"target": "/path", "feature": "用户登录"}}
    {"method": "s33_rea_compare", "params": {"target_a": "/a", "target_b": "/b", "feature": "架构"}}
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# 确保模块可导入
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from core.dependency_graph import DependencyGraph
from core.call_chain_tracer import CallChainTracer
from core.python_analyzer import PythonAnalyzer


__all__ = [
    "S33_rea_analyze",
    "S33_rea_trace",
    "S33_rea_compare",
    "DSH_NODE_REGISTRY",
    "dispatch",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_output(
    node: str,
    trace_id: str,
    ok: bool,
    result: Dict[str, Any],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 DSH SubagentOutput 摘要（压缩格式）。"""
    return {
        "node": node,
        "trace_id": trace_id,
        "ok": ok,
        "result": result,
        "error": error,
        "ts": _now_ms(),
    }


def _gen_trace_id(prefix: str = "s33") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# S33_rea_analyze - 整体架构分析
# ---------------------------------------------------------------------------

def S33_rea_analyze(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_analyze 节点：整体架构分析。

    Params:
        target: 本地路径（目录或文件）（必填）
        scope:  architecture / modules / dependencies / full（可选，默认 architecture）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {summary, evidence, raw{modules, dependencies, call_graph}}
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_analyze",
            str(params.get("trace_id") or _gen_trace_id("s33an")),
            ok=False, result={}, error="missing_target",
        )

    scope = str(params.get("scope") or "architecture")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33an"))

    try:
        # 根据目标类型选择分析器
        if os.path.isfile(target) and target.endswith(".py"):
            # 单文件分析
            analyzer = PythonAnalyzer()
            result = analyzer.analyze(target)
            return _make_output("S33_rea_analyze", trace_id, ok=True, result={
                "summary": result.summary,
                "evidence": [e.to_dict() for e in result.evidence],
                "raw": result.raw,
                "trace_id": trace_id,
            })
        elif os.path.isdir(target):
            # 目录级分析：依赖图 + 调用链
            all_evidence = []

            # 依赖图
            dep_graph = DependencyGraph()
            dep_result = dep_graph.build(target)
            all_evidence.extend(
                e.to_dict() for e in dep_result.get("evidence", [])
            )

            # 调用链
            tracer = CallChainTracer()
            chain_result = tracer.trace(target)
            all_evidence.extend(
                e.to_dict() for e in chain_result.get("evidence", [])
            )

            # 模块清单（从依赖图 nodes 提取）
            modules = dep_result.get("nodes", [])
            n_edges = len(dep_result.get("edges", []))
            n_cycles = len(dep_result.get("cycles", []))
            n_funcs = len(chain_result.get("all_functions", []))

            summary = (
                f"架构分析: {len(modules)} 模块, {n_edges} 依赖, "
                f"{n_cycles} 循环依赖, {n_funcs} 函数"
            )

            return _make_output("S33_rea_analyze", trace_id, ok=True, result={
                "summary": summary,
                "evidence": all_evidence,
                "raw": {
                    "modules": modules,
                    "dependencies": dep_result.get("adjacency", {}),
                    "cycles": dep_result.get("cycles", []),
                    "call_graph": {
                        "callers": chain_result.get("callers", {}),
                        "callees": chain_result.get("callees", {}),
                    },
                },
                "trace_id": trace_id,
            })
        else:
            return _make_output(
                "S33_rea_analyze", trace_id,
                ok=False, result={}, error="invalid_target_type",
            )
    except Exception as e:
        return _make_output(
            "S33_rea_analyze", trace_id,
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_trace - 功能追踪
# ---------------------------------------------------------------------------

def S33_rea_trace(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_trace 节点：功能追踪 — 某功能是怎么实现的。

    Params:
        target:  本地路径（目录或文件）（必填）
        feature: 要追踪的功能描述（必填）
        entry:   可选入口函数/类名
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {feature, call_chain, evidence, known_gaps}
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_trace",
            str(params.get("trace_id") or _gen_trace_id("s33tr")),
            ok=False, result={}, error="missing_target",
        )

    feature = str(params.get("feature") or "").strip()
    if not feature:
        return _make_output(
            "S33_rea_trace",
            str(params.get("trace_id") or _gen_trace_id("s33tr")),
            ok=False, result={}, error="missing_feature",
        )

    entry = params.get("entry")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33tr"))

    try:
        tracer = CallChainTracer()
        chain_result = tracer.trace(target, entry=entry)

        evidence_list = [
            e.to_dict() for e in chain_result.get("evidence", [])
        ]

        entry_chain = chain_result.get("entry_chain")

        known_gaps = []
        if not entry_chain:
            known_gaps.append("未指定入口或入口函数不在分析范围内")
        if not chain_result.get("callees"):
            known_gaps.append("未检测到函数调用关系（可能全是外部库调用）")

        call_chain = {
            "callers": chain_result.get("callers", {}),
            "callees": chain_result.get("callees", {}),
            "all_functions": chain_result.get("all_functions", []),
            "entry_chain": entry_chain,
        }

        return _make_output("S33_rea_trace", trace_id, ok=True, result={
            "feature": feature,
            "call_chain": call_chain,
            "evidence": evidence_list,
            "known_gaps": known_gaps,
            "trace_id": trace_id,
        })
    except Exception as e:
        return _make_output(
            "S33_rea_trace", trace_id,
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_compare - 两工程对比
# ---------------------------------------------------------------------------

def S33_rea_compare(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_compare 节点：两工程对比。

    Params:
        target_a: 工程A路径（必填）
        target_b: 工程B路径（必填）
        feature:  对比的功能描述
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {common, differences, evidence_a, evidence_b}
        ok=False:
            error: 错误描述
    """
    target_a = str(params.get("target_a") or "").strip()
    target_b = str(params.get("target_b") or "").strip()

    if not target_a or not target_b:
        return _make_output(
            "S33_rea_compare",
            str(params.get("trace_id") or _gen_trace_id("s33cmp")),
            ok=False, result={}, error="missing_targets",
        )

    feature = str(params.get("feature") or "整体架构")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33cmp"))

    try:
        # 分析工程A
        result_a = _analyze_project(target_a)
        # 分析工程B
        result_b = _analyze_project(target_b)

        # 对比
        modules_a = set(result_a.get("modules", []))
        modules_b = set(result_b.get("modules", []))
        common_modules = sorted(modules_a & modules_b)
        only_a = sorted(modules_a - modules_b)
        only_b = sorted(modules_b - modules_a)

        funcs_a = set(result_a.get("functions", []))
        funcs_b = set(result_b.get("functions", []))
        common_funcs = sorted(funcs_a & funcs_b)
        only_a_funcs = sorted(funcs_a - funcs_b)
        only_b_funcs = sorted(funcs_b - funcs_a)

        return _make_output("S33_rea_compare", trace_id, ok=True, result={
            "common": {
                "modules": common_modules,
                "functions": common_funcs,
            },
            "differences": {
                "only_in_a": {"modules": only_a, "functions": only_a_funcs},
                "only_in_b": {"modules": only_b, "functions": only_b_funcs},
            },
            "evidence_a": result_a.get("evidence", []),
            "evidence_b": result_b.get("evidence", []),
            "summary_a": result_a.get("summary", ""),
            "summary_b": result_b.get("summary", ""),
            "trace_id": trace_id,
        })
    except Exception as e:
        return _make_output(
            "S33_rea_compare", trace_id,
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


def _analyze_project(target: str) -> Dict[str, Any]:
    """辅助：分析单个工程，返回模块/函数/evidence。"""
    result: Dict[str, Any] = {
        "modules": [],
        "functions": [],
        "evidence": [],
        "summary": "",
    }

    if os.path.isfile(target) and target.endswith(".py"):
        analyzer = PythonAnalyzer()
        res = analyzer.analyze(target)
        result["modules"] = [os.path.basename(target)]
        result["evidence"] = [e.to_dict() for e in res.evidence]
        result["summary"] = res.summary
    elif os.path.isdir(target):
        dep_graph = DependencyGraph()
        dep_res = dep_graph.build(target)
        tracer = CallChainTracer()
        chain_res = tracer.trace(target)

        result["modules"] = dep_res.get("nodes", [])
        result["functions"] = chain_res.get("all_functions", [])
        result["evidence"] = (
            [e.to_dict() for e in dep_res.get("evidence", [])] +
            [e.to_dict() for e in chain_res.get("evidence", [])]
        )
        result["summary"] = (
            f"{len(result['modules'])} 模块, "
            f"{len(result['functions'])} 函数"
        )

    return result


# ---------------------------------------------------------------------------
# DSH 节点注册表 - 供 DSH server.py 注册路由
# ---------------------------------------------------------------------------

DSH_NODE_REGISTRY: Dict[str, Any] = {
    "s33_rea_analyze": S33_rea_analyze,
    "s33_rea_trace": S33_rea_trace,
    "s33_rea_compare": S33_rea_compare,
}


def dispatch(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """DSH 调度入口：根据 method 路由到对应节点。

    用法（在 DSH server.py 主循环中）：
        if method.startswith("s33_"):
            result = dispatch(method, params)
    """
    fn = DSH_NODE_REGISTRY.get(method)
    if fn is None:
        return _make_output(
            "S33_unknown",
            str(params.get("trace_id") or _gen_trace_id()),
            ok=False, result={}, error=f"unknown_method: {method}",
        )
    try:
        return fn(params)
    except Exception as e:
        return _make_output(
            "S33_error",
            str(params.get("trace_id") or _gen_trace_id()),
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# 命令行自检（可选）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=== S33_rea_analyze self-test ===")
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "test.py")).write_text(
            "import os\n\ndef main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n"
        )
        r1 = S33_rea_analyze({"target": d, "scope": "architecture"})
        print(f"  ok={r1['ok']}, summary={r1['result'].get('summary', '')}")

    print("=== S33_rea_trace self-test ===")
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "test.py")).write_text(
            "def func_a():\n    return 1\n\ndef func_b():\n    return func_a()\n"
        )
        r2 = S33_rea_trace({"target": d, "feature": "测试功能", "entry": "func_b"})
        print(f"  ok={r2['ok']}, feature={r2['result'].get('feature', '')}")

    print("=== S33_rea_compare self-test ===")
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        Path(os.path.join(d1, "app.py")).write_text("import os\nprint('a')\n")
        Path(os.path.join(d2, "app.py")).write_text("import sys\nprint('b')\n")
        r3 = S33_rea_compare({"target_a": d1, "target_b": d2, "feature": "架构"})
        print(f"  ok={r3['ok']}")
