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
from core.investigation_workflow import investigate
from core.cognitive_integration import (
    prepare_audit_record_params,
    prepare_decision_record_params,
    prepare_record_params,
)
from core.ai_audit import audit_ai_output
from core.design_decision_recovery import recover_decisions
from core.evolution_narrative import generate_narrative


__all__ = [
    "S33_rea_analyze",
    "S33_rea_trace",
    "S33_rea_compare",
    "S33_rea_investigate",
    "S33_rea_recover_decisions",
    "S33_rea_narrative",
    "S33_rea_audit",
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
# S33_rea_investigate - 逆向调查工作流
# ---------------------------------------------------------------------------

def S33_rea_investigate(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_investigate 节点：四阶段逆向调查工作流。

    定位(Locate)→追踪(Trace)→还原(Reduce)→标注(Annotate)

    Params:
        target: 本地路径（目录或文件）（必填）
        feature: 要调查的功能描述（可选）
        entry: 入口函数名（可选）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {summary, phases, evidence, known_gaps, cognitive_record}
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_investigate",
            str(params.get("trace_id") or _gen_trace_id("s33inv")),
            ok=False, result={}, error="missing_target",
        )

    feature = params.get("feature")
    entry = params.get("entry")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33inv"))

    try:
        investigation = investigate(target, feature=feature, entry=entry)

        # 准备认知记忆参数
        cognitive_record = prepare_record_params(investigation)

        # 序列化 Evidence
        evidence_dicts = [
            e.to_dict() if hasattr(e, "to_dict") else e
            for e in investigation.get("evidence", [])
        ]

        return _make_output("S33_rea_investigate", trace_id, ok=True, result={
            "summary": investigation.get("summary", ""),
            "feature": investigation.get("feature"),
            "phases": investigation.get("phases", {}),
            "evidence": evidence_dicts,
            "known_gaps": investigation.get("known_gaps", []),
            "cognitive_record": cognitive_record,
            "trace_id": trace_id,
        })
    except Exception as e:
        return _make_output(
            "S33_rea_investigate", trace_id,
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_recover_decisions - 设计决策还原（PoE Task 2）
# ---------------------------------------------------------------------------

def S33_rea_recover_decisions(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_recover_decisions 节点：设计决策还原（ADR 风格）。

    Params:
        target: 本地路径（目录或文件）（必填）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {target, decisions, evidence, known_gaps, cognitive_record}
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_recover_decisions",
            str(params.get("trace_id") or _gen_trace_id("s33dec")),
            ok=False, result={}, error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33dec"))

    try:
        decision_result = recover_decisions(target)

        # 准备认知记忆参数
        cognitive_record = prepare_decision_record_params(decision_result)

        # 序列化 Evidence
        evidence_list = []
        known_gaps: list[str] = []
        for e in decision_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            # 提取 known_gaps
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        return _make_output("S33_rea_recover_decisions", trace_id, ok=True, result={
            "target": target,
            "decisions": decision_result.get("decisions", []),
            "evidence": evidence_list,
            "known_gaps": known_gaps,
            "cognitive_record": cognitive_record,
            "trace_id": trace_id,
        })
    except Exception as e:
        # FAIL-OPEN（TR-7.3）：返回含 unknown Evidence 的部分结果，不中断
        from core.evidence import Evidence, EvidenceLevel
        ev = Evidence(
            result=f"设计决策还原失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "recover_decisions"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output("S33_rea_recover_decisions", trace_id, ok=True, result={
            "target": target,
            "decisions": [],
            "evidence": [ev.to_dict()],
            "known_gaps": [f"节点异常: {e}"],
            "trace_id": trace_id,
        })


# ---------------------------------------------------------------------------
# S33_rea_narrative - 演化叙事生成（PoE Task 3）
# ---------------------------------------------------------------------------

def S33_rea_narrative(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_narrative 节点：演化叙事生成。

    Params:
        target: git 仓库根路径（必填）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {target, turning_points, tech_debt_timeline, evidence, known_gaps}
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_narrative",
            str(params.get("trace_id") or _gen_trace_id("s33nar")),
            ok=False, result={}, error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33nar"))

    try:
        narrative_result = generate_narrative(target)

        # 序列化 Evidence + 提取 known_gaps
        evidence_list = []
        known_gaps: list[str] = []
        for e in narrative_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        return _make_output("S33_rea_narrative", trace_id, ok=True, result={
            "target": target,
            "turning_points": narrative_result.get("turning_points", []),
            "tech_debt_timeline": narrative_result.get("tech_debt_timeline", []),
            "evidence": evidence_list,
            "known_gaps": known_gaps,
            "trace_id": trace_id,
        })
    except Exception as e:
        from core.evidence import Evidence, EvidenceLevel
        ev = Evidence(
            result=f"演化叙事生成失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "generate_narrative"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output("S33_rea_narrative", trace_id, ok=True, result={
            "target": target,
            "turning_points": [],
            "tech_debt_timeline": [],
            "evidence": [ev.to_dict()],
            "known_gaps": [f"节点异常: {e}"],
            "trace_id": trace_id,
        })


# ---------------------------------------------------------------------------
# S33_rea_audit - AI 产出审计（PoE Task 5 — 核心门禁）
# ---------------------------------------------------------------------------

def S33_rea_audit(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_audit 节点：AI 产出审计（PoE 核心门禁）。

    Params:
        target: AI 产出代码目录或文件路径（必填）
        ai_context: 可选 AI 上下文（agent_id/model/prompt_hash/timestamp）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {
                target, evidence_chain_score, poe_score, gate_decision,
                cognitive_debt, evidence, known_gaps, cognitive_record
            }
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_audit",
            str(params.get("trace_id") or _gen_trace_id("s33aud")),
            ok=False, result={}, error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33aud"))
    ai_context = params.get("ai_context")

    try:
        audit_result = audit_ai_output(target, ai_context=ai_context)

        # 准备认知记忆参数
        cognitive_record = prepare_audit_record_params(audit_result)

        # 序列化 Evidence + 提取 known_gaps
        evidence_list = []
        known_gaps: list[str] = []
        for e in audit_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        # FAIL-OPEN：审计失败时 audit_result 已含 unknown Evidence
        return _make_output("S33_rea_audit", trace_id, ok=True, result={
            "target": target,
            "evidence_chain_score": audit_result.get("evidence_chain_score", 0.0),
            "coverage_score": audit_result.get("coverage_score", 0.0),
            "complexity_penalty": audit_result.get("complexity_penalty", 0.0),
            "poe_score": audit_result.get("poe_score", 0.0),
            "gate_decision": audit_result.get("gate_decision", "review"),
            "cognitive_debt": audit_result.get("cognitive_debt", []),
            "audit_layer_status": audit_result.get("audit_layer_status", {}),
            "evidence": evidence_list,
            "known_gaps": known_gaps,
            "cognitive_record": cognitive_record,
            "trace_id": trace_id,
        })
    except Exception as e:
        # FAIL-OPEN（TR-7.3 + PoE §5.5）
        from core.evidence import Evidence, EvidenceLevel
        ev = Evidence(
            result=f"AI 审计失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "ai_audit"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output("S33_rea_audit", trace_id, ok=True, result={
            "target": target,
            "evidence_chain_score": 0.0,
            "poe_score": 0.0,
            "gate_decision": "review",
            "cognitive_debt": [],
            "evidence": [ev.to_dict()],
            "known_gaps": [f"节点异常: {e}"],
            "trace_id": trace_id,
        })


# ---------------------------------------------------------------------------
# DSH 节点注册表 - 供 DSH server.py 注册路由
# ---------------------------------------------------------------------------

def S33_rea_locate(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_locate 节点：文件定位（C3，41 SPEC §13.3/§7.11）。
    基于 41 code 类型索引按名称/模式定位源码文件，替代节点自建目录遍历。
    Params:
        name: 文件名或模式（必填，支持子串匹配）
        limit: 返回上限（默认 20）
        trace_id: 调用方传入的 trace_id（可选）
    """
    import json as _json
    import subprocess as _sp
    name = str(params.get("name") or "").strip()
    if not name:
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=False, result={}, error="missing_name",
        )
    limit = int(params.get("limit", 20))
    try:
        proc = _sp.run(
            ["/home/ubuntu/fis-p0/.venv/bin/python", "/home/ubuntu/fis-p0/scripts/search_cli.py"],
            input=_json.dumps({"query": name, "limit": limit, "filters": {"type": ["code"]}}),
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD", "xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE")},
        )
        res = _json.loads(proc.stdout or "{}")
        hits = res.get("hits", []) if res.get("success") else []
        matched = [
            h["source"]["path"]
            for h in hits
            if name.lower() in h["source"]["path"].lower()
        ][:limit]
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=True,
            result={"matched": matched, "count": len(matched), "source": "fis_code_index"},
        )
    except Exception as e:
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=False, result={}, error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# 反思层节点（SPEC-33-反思层 v0.3 §7.1）
# ---------------------------------------------------------------------------
def _reflection_pool(params: Dict[str, Any]):
    from core.reflection.replay_simulator import ReplayPool
    base = str(params.get("pool_dir") or "reflection_data/replay_pool")
    return ReplayPool(base)


def S33_rea_reflect(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_reflect 节点：对分析结果执行 R1-R3 反思。
    Params:
        report: 分析报告 dict（必填，字段见 ReflectionLayer.reflect）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.reflection_layer import ReflectionLayer
    report = params.get("report")
    if not isinstance(report, dict):
        return _make_output(
            "S33_rea_reflect",
            str(params.get("trace_id") or _gen_trace_id("s33rf")),
            ok=False, result={}, error="missing_report",
        )
    critique = ReflectionLayer().reflect(report)
    return _make_output(
        "S33_rea_reflect",
        str(params.get("trace_id") or _gen_trace_id("s33rf")),
        ok=True, result=critique,
    )


def S33_rea_dream(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_dream 节点：触发做梦评估循环。
    Params:
        pool_dir: 回放池目录（可选，默认 reflection_data/replay_pool）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.dreaming import DreamingLoop
    pool = _reflection_pool(params)
    if not pool.eval_ready():
        return _make_output(
            "S33_rea_dream",
            str(params.get("trace_id") or _gen_trace_id("s33dm")),
            ok=False, result={}, error="pool_not_eval_ready",
        )
    loop = DreamingLoop(pool)
    result = loop.dream()
    return _make_output(
        "S33_rea_dream",
        str(params.get("trace_id") or _gen_trace_id("s33dm")),
        ok=True, result=result,
    )


def S33_rea_replay(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_replay 节点：查询/重放历史分析轨迹。
    Params:
        tree_id: 指定发现树 ID（可选，缺省列出全部）
        provenance: internal / external 过滤（可选）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    pool = _reflection_pool(params)
    tree_id = str(params.get("tree_id") or "").strip()
    if tree_id:
        tree = pool.load(tree_id)
        if tree is None:
            return _make_output(
                "S33_rea_replay",
                str(params.get("trace_id") or _gen_trace_id("s33rp")),
                ok=False, result={}, error=f"tree_not_found: {tree_id}",
            )
        result = {"tree": tree.to_dict()}
    else:
        provenance = params.get("provenance")
        trees = pool.list_trees(provenance=str(provenance) if provenance else None)
        result = {
            "count": len(trees),
            "trees": [t.to_dict() for t in trees],
        }
    return _make_output(
        "S33_rea_replay",
        str(params.get("trace_id") or _gen_trace_id("s33rp")),
        ok=True, result=result,
    )


def S33_rea_harvest(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_harvest 节点：触发外部路径获取全链路（E1-E4）。
    Params:
        sources: [{source_type, location, label, patterns}]（必填）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.harvest import ExternalHarvester, HarvestSource
    raw_sources = params.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return _make_output(
            "S33_rea_harvest",
            str(params.get("trace_id") or _gen_trace_id("s33hv")),
            ok=False, result={}, error="missing_sources",
        )
    sources = []
    for s in raw_sources:
        if not isinstance(s, dict) or not s.get("location"):
            continue
        sources.append(HarvestSource(
            source_type=str(s.get("source_type") or "local_path"),
            location=str(s["location"]),
            label=str(s.get("label") or ""),
            patterns=list(s.get("patterns") or []),
        ))
    pool = _reflection_pool(params)
    harvester = ExternalHarvester(pool)
    outcome = harvester.harvest(sources)
    return _make_output(
        "S33_rea_harvest",
        str(params.get("trace_id") or _gen_trace_id("s33hv")),
        ok=True, result={
            "ok": outcome.ok,
            "injected_trees": outcome.injected_trees,
            "rejected": outcome.rejected,
            "errors": outcome.errors,
        },
    )


# ---------------------------------------------------------------------------
# 输出场景节点（SPEC-33-输出场景-意图系统.md §4/§5）
# ---------------------------------------------------------------------------
def S33_rea_spec_enhance(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_spec_enhance 节点：两段式 Spec 增强（Q1/Q2）。
    Params:
        spec_draft: Spec 草案文本（必填）
        pool_dir: 回放池目录（可选，默认 reflection_data/replay_pool）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.output_scenarios import SpecEnhancer
    spec_draft = str(params.get("spec_draft") or "").strip()
    if not spec_draft:
        return _make_output(
            "S33_rea_spec_enhance",
            str(params.get("trace_id") or _gen_trace_id("s33se")),
            ok=False, result={}, error="missing_spec_draft",
        )
    pool = _reflection_pool(params)
    enhancer = SpecEnhancer(pool)
    result = enhancer.enhance(spec_draft)
    return _make_output(
        "S33_rea_spec_enhance",
        str(params.get("trace_id") or _gen_trace_id("s33se")),
        ok=True, result=result,
    )


def S33_rea_optimal_path(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_optimal_path 节点：双层延迟策略评估（Q3/Q4）。
    Params:
        completed_node: 已完成节点 {analyzer, acceptance{passed, confidence}}（必填）
        force_heavy: 显式触发重量层（可选）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.output_scenarios import OptimalPathEvaluator
    completed_node = params.get("completed_node")
    if not isinstance(completed_node, dict) or not completed_node.get("analyzer"):
        return _make_output(
            "S33_rea_optimal_path",
            str(params.get("trace_id") or _gen_trace_id("s33op")),
            ok=False, result={}, error="missing_completed_node",
        )
    pool = _reflection_pool(params)
    evaluator = OptimalPathEvaluator(pool)
    result = evaluator.evaluate(
        completed_node,
        task_context=params.get("task_context"),
        force_heavy=bool(params.get("force_heavy")),
    )
    return _make_output(
        "S33_rea_optimal_path",
        str(params.get("trace_id") or _gen_trace_id("s33op")),
        ok=True, result=result,
    )


DSH_NODE_REGISTRY: Dict[str, Any] = {
    "s33_rea_analyze": S33_rea_analyze,
    "s33_rea_trace": S33_rea_trace,
    "s33_rea_compare": S33_rea_compare,
    "s33_rea_investigate": S33_rea_investigate,
    "s33_rea_recover_decisions": S33_rea_recover_decisions,
    "s33_rea_narrative": S33_rea_narrative,
    "s33_rea_audit": S33_rea_audit,
    "s33_rea_locate": S33_rea_locate,  # C3（41 SPEC §13.3）：41 code 索引文件定位供给
    "s33_rea_reflect": S33_rea_reflect,
    "s33_rea_dream": S33_rea_dream,
    "s33_rea_replay": S33_rea_replay,
    "s33_rea_harvest": S33_rea_harvest,
    "s33_rea_spec_enhance": S33_rea_spec_enhance,
    "s33_rea_optimal_path": S33_rea_optimal_path,
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
