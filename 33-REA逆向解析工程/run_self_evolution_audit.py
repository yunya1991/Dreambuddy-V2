"""用 REA 逆向解析工程对自进化系统做逆向解析。

聚焦目标：
1. 主入口 evolution_pipeline.py（单文件完整四阶段 investigate）
2. engines/ 目录依赖图（模块耦合证据）
3. 关键引擎算法还原（reflection_engine / primary_contradiction_detector）

输出 Evidence-based 报告到 reports/。
"""
from __future__ import annotations

import json
import os
import sys

# 确保能 import core
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core.investigation_workflow import investigate
from core.dependency_graph import DependencyGraph
from core.algorithm_reducer import reduce_algorithm
from core.git_history import trace_git_history

TARGET_BASE = os.path.join(
    HERE, "..", "23-四层闭环自进化交易架构", "dreambuddy_evolution",
)
TARGET_BASE = os.path.abspath(TARGET_BASE)
REPORT_DIR = os.path.join(HERE, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def ev_to_dict(ev):
    """Evidence 对象转 dict（兼容 dataclass / dict）。"""
    if hasattr(ev, "to_dict"):
        return ev.to_dict()
    if isinstance(ev, dict):
        return ev
    return {"result": str(ev)}


def phase_evidence_to_dict(phase: dict) -> dict:
    """phase 里的 evidence 列表转 dict。"""
    out = dict(phase)
    out["evidence"] = [ev_to_dict(e) for e in phase.get("evidence", [])]
    return out


def run_pipeline_investigate() -> dict:
    """对主入口 evolution_pipeline.py 做完整四阶段逆向调查。"""
    target = os.path.join(TARGET_BASE, "evolution_pipeline.py")
    print(f"[1/3] investigate target={target}")
    result = investigate(target, feature="四层闭环主编排")
    # 序列化 evidence
    result["evidence"] = [ev_to_dict(e) for e in result.get("evidence", [])]
    result["phases"] = {
        k: phase_evidence_to_dict(v) for k, v in result.get("phases", {}).items()
    }
    return result


def run_engines_dependency_graph() -> dict:
    """对 engines/ 目录做依赖图分析（模块耦合证据）。"""
    target = os.path.join(TARGET_BASE, "engines")
    print(f"[2/3] dependency_graph target={target}")
    dg = DependencyGraph()
    result = dg.build(target)
    result["evidence"] = [ev_to_dict(e) for e in result.get("evidence", [])]
    return result


def run_key_engine_algorithm_reduce() -> dict:
    """对关键引擎做算法还原。"""
    targets = [
        "reflection_engine.py",
        "primary_contradiction_detector.py",
        "auto_weight_adjuster.py",
    ]
    out = {"engines": []}
    for name in targets:
        path = os.path.join(TARGET_BASE, "engines", name)
        if not os.path.isfile(path):
            out["engines"].append({"file": name, "error": "not found"})
            continue
        print(f"[3/3] reduce_algorithm target={name}")
        r = reduce_algorithm(path)
        r["evidence"] = [ev_to_dict(e) for e in r.get("evidence", [])]
        r["file"] = name
        out["engines"].append(r)
    return out


def run_git_history() -> dict:
    """对自进化系统做 git 历史溯源。"""
    target = os.path.join(HERE, "..", "23-四层闭环自进化交易架构")
    target = os.path.abspath(target)
    print(f"[git] git_history target={target}")
    repo_root = os.path.abspath(os.path.join(HERE, ".."))
    # 关键文件溯源
    files = [
        "23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py",
        "23-四层闭环自进化交易架构/dreambuddy_evolution/engines/reflection_engine.py",
        "23-四层闭环自进化交易架构/dreambuddy_evolution/engines/primary_contradiction_detector.py",
    ]
    out = {"files": []}
    for rel in files:
        try:
            res = trace_git_history(repo_root, rel)
            res["evidence"] = [ev_to_dict(e) for e in res.get("evidence", [])]
            res["file"] = rel
            out["files"].append(res)
        except Exception as exc:
            out["files"].append({"file": rel, "error": str(exc)})
    return out


def main() -> None:
    report = {}
    try:
        report["pipeline_investigate"] = run_pipeline_investigate()
    except Exception as exc:
        report["pipeline_investigate"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        report["engines_dependency"] = run_engines_dependency_graph()
    except Exception as exc:
        report["engines_dependency"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        report["key_engine_algorithms"] = run_key_engine_algorithm_reduce()
    except Exception as exc:
        report["key_engine_algorithms"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        report["git_history"] = run_git_history()
    except Exception as exc:
        report["git_history"] = {"error": f"{type(exc).__name__}: {exc}"}

    out_path = os.path.join(REPORT_DIR, "self_evolution_rea_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已输出: {out_path}")

    # 控制台打印摘要
    pi = report.get("pipeline_investigate", {})
    print("\n=== 摘要 ===")
    print(f"pipeline investigate summary: {pi.get('summary', pi.get('error', '?'))}")
    ed = report.get("engines_dependency", {})
    print(f"engines nodes: {len(ed.get('nodes', []))} edges: {len(ed.get('edges', []))}")
    ke = report.get("key_engine_algorithms", {})
    for e in ke.get("engines", []):
        print(f"  {e.get('file')}: {len(e.get('functions', []))} funcs, {len(e.get('patterns', []))} patterns")
    gh = report.get("git_history", {})
    for gf in gh.get("files", []):
        print(f"  git {gf.get('file')}: {gf.get('summary', gf.get('error', '?'))}")


if __name__ == "__main__":
    main()
