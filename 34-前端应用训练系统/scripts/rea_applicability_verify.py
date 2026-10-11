#!/usr/bin/env python3
"""33-REA 适用性验证脚本 — SPEC §3.3 P1 前置条件。

选取 5 个 34 目录实际开发的核心 Python 文件作为验证案例，
对每个案例跑 S33_rea_analyze + S33_rea_trace，评估指标：
  - algorithm_pattern 还原准确率（与实际设计意图对比）
  - call_chain 覆盖关键路径比例
  - evidence_level 分布（L1/L2/L3/L4 占比）
  - known_gaps 识别质量

通过标准（SPEC §3.3）：
  - algorithm_pattern 准确率 ≥ 70%
  - call_chain 覆盖关键路径 ≥ 80%
  - 不通过则降级：33-REA 仅作为辅助标注

用法:
  python scripts/rea_applicability_verify.py
  python scripts/rea_applicability_verify.py --json   # 机器可读输出
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# sys.path 注入：34 目录 + adapters + core + 33-REA 目录
_THIS_DIR = Path(__file__).resolve().parent
_34_DIR = _THIS_DIR.parent
_ADAPTERS_DIR = _34_DIR / "adapters"
_CORE_DIR = _34_DIR / "core"
_PROJECT_ROOT = _34_DIR.parent
_REA_DIR = _PROJECT_ROOT / "33-REA逆向解析工程"

for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR, _REA_DIR]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# 5 个验证案例（ground truth 来自实际设计意图）
# ---------------------------------------------------------------------------

_CASES: List[Dict[str, Any]] = [
    {
        "name": "rea_to_tdr_adapter",
        "file": "adapters/rea_to_tdr_adapter.py",
        "feature": "REA 结果转 TrainingCase 列表",
        "entry": "rea_to_training_cases",
        # ground truth 基于 AST: 函数内有 5+ 个 if (if rea_result is None / if rea_result.algorithm_patterns 等)
        "expected_patterns": {"conditional_branch"},
        "expected_chain_calls": [
            "rea_to_training_cases",
            "_make_text_case",
            "_quality_from_evidence_level",
        ],
        "design_intent": "遍历 REAParseResult 字段，累积生成 TrainingCase 列表（AST: 多重条件分支）",
    },
    {
        "name": "rea_native_parser",
        "file": "adapters/rea_native_parser.py",
        "feature": "33-REA 输出转 REAParseResult",
        "entry": "analyze",
        # analyze 方法主要是 try/except + 委托调用，无典型 for/while 循环或 if 链
        "expected_patterns": set(),
        "expected_chain_calls": ["analyze", "trace", "_convert_output", "_get_rea"],
        "design_intent": "延迟 import + 委托调用 + level 映射（AST: 无典型算法模式）",
    },
    {
        "name": "dual_mode_orchestrator",
        "file": "core/dual_mode_orchestrator.py",
        "feature": "触发被动训练",
        "entry": "trigger_passive_training",
        # trigger_passive_training 方法有 for executor 循环 + if layer_tags 判断
        "expected_patterns": {"iteration", "conditional_branch"},
        "expected_chain_calls": [
            "trigger_passive_training",
            "_build_coaching_context",
        ],
        "design_intent": "多 executor 循环 + 多 case 分发（AST: iteration + conditional_branch）",
    },
    {
        "name": "orchestrator_factory",
        "file": "core/orchestrator_factory.py",
        "feature": "创建双模式编排器",
        "entry": "create_orchestrator",
        "expected_patterns": set(),  # 简单工厂，无循环/分支
        "expected_chain_calls": ["create_orchestrator"],
        "design_intent": "简单工厂模式，组装 4 个适配器（AST: 无算法模式）",
    },
    {
        "name": "trigger_passive_training",
        "file": "trigger_passive_training.py",
        "feature": "执行被动训练触发",
        "entry": "run_trigger",
        # run_trigger 有 try/except + if status 判断，但无 for 循环
        "expected_patterns": set(),
        "expected_chain_calls": [
            "run_trigger",
            "_prepare_record_params",
        ],
        "design_intent": "步骤累积 + 参数准备 + 错误降级（AST: 无典型算法模式，跨模块调用无法静态追踪）",
    },
]


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _run_analyze(target_path: str) -> Dict[str, Any]:
    """跑 S33_rea_analyze。"""
    import dsh_nodes

    return dsh_nodes.S33_rea_analyze({"target": target_path, "scope": "architecture"})


def _run_trace(target_path: str, feature: str, entry: str) -> Dict[str, Any]:
    """跑 S33_rea_trace + 适配层补充 algorithm_reducer。

    直接复用 REANativeParser.trace()，因为它已集成 algorithm_reducer 增强。
    """
    from rea_native_parser import REANativeParser

    parser = REANativeParser()
    result = parser.trace(target_path=target_path, feature=feature, entry=entry)
    # 把 REAParseResult 包装回 dsh_nodes 输出结构（保持 _evaluate_case 的接口）
    return {
        "ok": not result.raw_evidence.get("error"),
        "result": {
            "feature": feature,
            "call_chain": {
                # 从 raw_evidence 提取（_convert_output 已填充）
                "all_functions": _extract_all_functions(result.raw_evidence),
                "entry_chain": result.call_chain,
            },
            "evidence": _collect_evidence(result),
            "known_gaps": result.known_gaps,
            # 适配层新增：algorithm_reducer 输出的 patterns
            "algorithm_patterns": result.algorithm_patterns,
        },
        "error": result.raw_evidence.get("error"),
    }


def _extract_all_functions(raw_evidence: Dict) -> List[str]:
    """从 raw_evidence 提取 all_functions 列表。"""
    result = raw_evidence.get("result", {}) or {}
    cc = result.get("call_chain", {}) or {}
    return cc.get("all_functions", []) or []


def _collect_evidence(result) -> List:
    """合并 REAParseResult 的 evidence（从 raw_evidence 提取）。"""
    raw = result.raw_evidence or {}
    out = raw.get("result", {}).get("evidence", []) or []
    # 加入 algorithm_reducer 输出的 evidence
    algo_ev = raw.get("algorithm_evidence", []) or []
    return out + algo_ev


def _evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """评估单个案例：跑 analyze+trace，计算指标。"""
    file_abs = str(_34_DIR / case["file"])
    result: Dict[str, Any] = {
        "name": case["name"],
        "file": case["file"],
        "design_intent": case["design_intent"],
        "analyze": None,
        "trace": None,
        "metrics": {},
    }

    # 1. analyze
    a_out = _run_analyze(file_abs)
    result["analyze"] = {
        "ok": a_out.get("ok", False),
        "summary": a_out.get("result", {}).get("summary", ""),
        "evidence_count": len(a_out.get("result", {}).get("evidence", [])),
        "error": a_out.get("error"),
    }

    # 2. trace
    t_out = _run_trace(file_abs, case["feature"], case["entry"])
    t_result = t_out.get("result", {}) if t_out.get("ok") else {}
    cc = t_result.get("call_chain", {}) or {}
    all_funcs = cc.get("all_functions", []) or []
    entry_chain = cc.get("entry_chain") or []
    known_gaps = t_result.get("known_gaps", []) or []
    evidence = t_result.get("evidence", []) or []

    result["trace"] = {
        "ok": t_out.get("ok", False),
        "feature": t_result.get("feature", ""),
        "all_functions_count": len(all_funcs),
        "entry_chain_len": len(entry_chain) if isinstance(entry_chain, list) else 0,
        "evidence_count": len(evidence),
        "known_gaps": known_gaps,
        "error": t_out.get("error"),
    }

    # 3. 指标计算
    # 3.1 algorithm_pattern 准确率
    # 适配层已通过 algorithm_reducer 增强识别，直接取 trace 输出的 patterns
    detected_patterns = set(t_result.get("algorithm_patterns", []) or [])
    # 兼容旧路径：若适配层未输出 patterns，从 evidence 字符串匹配关键词
    if not detected_patterns:
        pattern_keywords = [
            "recursion", "divide_conquer", "dynamic_programming",
            "iteration", "accumulator", "backtracking", "greedy",
        ]
        for e in evidence:
            res = str(e.get("result", "")).lower()
            for p in pattern_keywords:
                if p in res:
                    detected_patterns.add(p)

    expected = case["expected_patterns"]
    if expected:
        hits = expected & detected_patterns
        pattern_recall = _pct(len(hits), len(expected))
        false_pos = detected_patterns - expected
        pattern_precision = _pct(len(hits), len(hits) + len(false_pos)) if (hits or false_pos) else 100.0
    else:
        pattern_recall = 100.0 if not detected_patterns else 0.0
        pattern_precision = 100.0 if not detected_patterns else 0.0

    # 3.2 call_chain 覆盖关键路径
    # 33-REA 的函数名带前缀（如 "..rea_to_training_cases"），用 endswith 匹配
    expected_calls = case["expected_chain_calls"]
    all_funcs_list = all_funcs if isinstance(all_funcs, list) else []
    # 规范化：去除前缀，只保留函数名
    all_funcs_norm = set()
    for fn in all_funcs_list:
        fn_str = str(fn)
        # 去除 ".." 前缀和模块路径
        all_funcs_norm.add(fn_str.split(".")[-1] if "." in fn_str else fn_str)

    if expected_calls:
        covered = [c for c in expected_calls if c in all_funcs_norm]
        chain_coverage = _pct(len(covered), len(expected_calls))
    else:
        chain_coverage = 100.0

    # 3.3 evidence_level 分布
    level_dist = {"L1": 0, "L2": 0, "L3": 0, "L4": 0}
    level_map = {
        "observation": "L1", "derivation": "L2",
        "inference": "L3", "unknown": "L4",
    }
    for e in evidence:
        lv = level_map.get(e.get("level", ""), "L3")
        level_dist[lv] = level_dist.get(lv, 0) + 1

    # 4. 33-REA 识别出的 known_gaps 质量
    useful_gaps = [g for g in known_gaps if isinstance(g, str) and len(g) > 5]

    result["metrics"] = {
        "pattern_recall_pct": pattern_recall,
        "pattern_precision_pct": pattern_precision,
        "detected_patterns": sorted(detected_patterns),
        "expected_patterns": sorted(expected),
        "chain_coverage_pct": chain_coverage,
        "expected_chain_calls": expected_calls,
        "covered_calls": [c for c in expected_calls if c in all_funcs_norm] if expected_calls else [],
        "evidence_level_dist": level_dist,
        "useful_known_gaps": len(useful_gaps),
    }

    return result


def run_verification() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """跑全部 5 案例并汇总。"""
    case_results = []
    for case in _CASES:
        try:
            r = _evaluate_case(case)
        except Exception as e:
            r = {
                "name": case["name"],
                "file": case["file"],
                "error": f"{type(e).__name__}: {e}",
                "metrics": {},
            }
        case_results.append(r)

    # 汇总指标
    n = len(case_results)
    valid = [r for r in case_results if "metrics" in r and r.get("metrics")]
    valid_n = len(valid) or 1

    avg_recall = round(sum(r["metrics"].get("pattern_recall_pct", 0) for r in valid) / valid_n, 1)
    avg_precision = round(sum(r["metrics"].get("pattern_precision_pct", 0) for r in valid) / valid_n, 1)
    avg_coverage = round(sum(r["metrics"].get("chain_coverage_pct", 0) for r in valid) / valid_n, 1)

    total_levels = {"L1": 0, "L2": 0, "L3": 0, "L4": 0}
    for r in valid:
        for k, v in r["metrics"].get("evidence_level_dist", {}).items():
            total_levels[k] = total_levels.get(k, 0) + v
    total_evidence = sum(total_levels.values()) or 1
    level_dist_pct = {k: _pct(v, total_evidence) for k, v in total_levels.items()}

    passed = (
        avg_recall >= 70.0 and avg_coverage >= 80.0
    )
    # 降级建议：不通过则 33-REA 仅作辅助标注
    if not passed:
        recommendation = (
            "FAIL → 33-REA 仅作辅助标注，被动训练主要依赖 Trae 文本四元组（SPEC §3.3 降级路径）"
        )
    else:
        recommendation = "PASS → 33-REA 可作为被动训练主要教学材料来源"

    summary = {
        "total_cases": n,
        "valid_cases": len(valid),
        "avg_pattern_recall_pct": avg_recall,
        "avg_pattern_precision_pct": avg_precision,
        "avg_chain_coverage_pct": avg_coverage,
        "evidence_level_dist_pct": level_dist_pct,
        "threshold": {"pattern_recall_pct": 70.0, "chain_coverage_pct": 80.0},
        "passed": passed,
        "recommendation": recommendation,
    }
    return case_results, summary


def _format_report(case_results: List[Dict], summary: Dict) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("33-REA 适用性验证报告 (SPEC §3.3 P1 前置条件)")
    lines.append("=" * 70)
    lines.append("")

    for r in case_results:
        lines.append(f"[{r['name']}] {r.get('file', '')}")
        if "error" in r and "metrics" not in r:
            lines.append(f"  ERROR: {r['error']}")
            lines.append("")
            continue
        a = r.get("analyze", {}) or {}
        t = r.get("trace", {}) or {}
        m = r.get("metrics", {}) or {}
        lines.append(f"  设计意图: {r.get('design_intent', '')}")
        lines.append(f"  analyze: ok={a.get('ok')}, summary={a.get('summary', '')[:80]}")
        lines.append(
            f"  trace: ok={t.get('ok')}, "
            f"functions={t.get('all_functions_count', 0)}, "
            f"entry_chain_len={t.get('entry_chain_len', 0)}"
        )
        lines.append(f"  pattern_recall={m.get('pattern_recall_pct', 0)}% "
                     f"(detected={m.get('detected_patterns', [])}, expected={m.get('expected_patterns', [])})")
        lines.append(f"  chain_coverage={m.get('chain_coverage_pct', 0)}% "
                     f"(covered={m.get('covered_calls', [])})")
        lines.append(f"  evidence_levels={m.get('evidence_level_dist', {})}")
        gaps = t.get("known_gaps", [])
        lines.append(f"  known_gaps ({len(gaps)}): {gaps[:3]}")
        lines.append("")

    lines.append("-" * 70)
    lines.append("汇总")
    lines.append("-" * 70)
    lines.append(f"有效案例: {summary['valid_cases']}/{summary['total_cases']}")
    lines.append(f"平均 pattern_recall: {summary['avg_pattern_recall_pct']}% (阈值 ≥70%)")
    lines.append(f"平均 pattern_precision: {summary['avg_pattern_precision_pct']}%")
    lines.append(f"平均 chain_coverage: {summary['avg_chain_coverage_pct']}% (阈值 ≥80%)")
    lines.append(f"evidence_level 分布: {summary['evidence_level_dist_pct']}")
    verdict = "✅ PASS" if summary["passed"] else "🚩 FAIL"
    lines.append(f"结论: {verdict}")
    lines.append(f"建议: {summary['recommendation']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="33-REA 适用性验证")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    case_results, summary = run_verification()

    if args.json:
        print(json.dumps({"cases": case_results, "summary": summary},
                         ensure_ascii=False, indent=2))
    else:
        print(_format_report(case_results, summary))

    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
