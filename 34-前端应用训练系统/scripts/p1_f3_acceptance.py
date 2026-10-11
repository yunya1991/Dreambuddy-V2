#!/usr/bin/env python3
"""P1.3 验收脚本 — SPEC F3: TDR案例包含algorithm_pattern和dependency_graph字段。

端到端调用 orchestrator.trigger_passive_training()，然后检查
rea_to_training_cases() 生成的 TrainingCase 列表中是否包含：
  - algorithm_pattern 字段（DSH层，source=rea_algorithm）
  - dependency_graph 字段（G层，source=rea_dependency_graph）

用法:
  python scripts/p1_f3_acceptance.py
"""
import json
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_34_DIR = _THIS_DIR.parent
_ADAPTERS_DIR = _34_DIR / "adapters"
_CORE_DIR = _34_DIR / "core"
_REA_DIR = _34_DIR.parent / "33-REA逆向解析工程"
for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR, _REA_DIR]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def run_f3_acceptance() -> dict:
    """端到端验收 F3。"""
    from orchestrator_factory import create_orchestrator
    from rea_to_tdr_adapter import rea_to_training_cases

    # 1. 准备收尾案例（含 code_path，触发 REA 解析）
    wrapup_case = {
        "intent": "P1.3 F3验收: TDR案例字段完整性",
        "actions": ["analyze", "trace", "rea_to_training_cases"],
        "outcome_text": "F3验收通过",
        "outcome": "success",
        "learned": ["dependency_graph从imports构造", "algorithm_reducer增强pattern"],
        "code_path": str(_34_DIR / "adapters" / "rea_to_tdr_adapter.py"),
        "feature": "REA转TrainingCase",
        "entry": "rea_to_training_cases",
        "acceptance_level": "PASS",
        "domain_tag": "前端训练",
        "novelty": 0.7,
        "significance": 0.8,
        "anomaly": 0.0,
        "reproducibility": 0.9,
    }

    # 2. 创建编排器（REA 默认启用）
    orchestrator = create_orchestrator(enable_rea=True)

    # 3. 触发被动训练（内部会调 analyze+trace+rea_to_training_cases）
    result = orchestrator.trigger_passive_training(wrapup_case)

    if result.get("status") != "coaching_started":
        return {
            "passed": False,
            "reason": f"trigger failed: {result.get('status')}",
        }

    coaching_ctx = result.get("coaching_context", {})

    # 4. 重新跑 rea_to_training_cases 检查 TrainingCase 字段
    #    （orchestrator 内部已调用，这里重新调用以检查字段）
    rea_result_dict = result.get("rea_result")
    # 从 rea_result 重建 REAParseResult（因为 orchestrator 返回的是 __dict__）
    if rea_result_dict:
        from interfaces.rea_parser import REAParseResult
        rea_result = REAParseResult(
            algorithm_patterns=rea_result_dict.get("algorithm_patterns", []),
            call_chain=rea_result_dict.get("call_chain", []),
            dependency_graph=rea_result_dict.get("dependency_graph", {}),
            known_gaps=rea_result_dict.get("known_gaps", []),
            observations=rea_result_dict.get("observations", []),
            evidence_level=rea_result_dict.get("evidence_level", "L3"),
            confidence=rea_result_dict.get("confidence", 0.5),
            raw_evidence=rea_result_dict.get("raw_evidence", {}),
        )
    else:
        rea_result = None

    training_cases = rea_to_training_cases(wrapup_case, rea_result)

    # 5. 检查 F3 验收标准
    algo_case = None
    dep_case = None
    for c in training_cases:
        meta_str = str(c.metadata) if c.metadata else ""
        if "algorithm_patterns" in meta_str or "patterns" in meta_str:
            if "rea_algorithm" in (c.source or ""):
                algo_case = c
        if "dependency_graph" in meta_str or "node_count" in meta_str:
            if "rea_dependency_graph" in (c.source or ""):
                dep_case = c

    # 6. 输出验收结果
    report = {
        "passed": algo_case is not None and dep_case is not None,
        "total_cases": len(training_cases),
        "coaching_context": {
            "algorithm_patterns": coaching_ctx.get("algorithm_patterns", []),
            "dependency_graph": coaching_ctx.get("dependency_graph", {}),
            "call_chain": coaching_ctx.get("call_chain", []),
            "known_gaps_count": len(coaching_ctx.get("known_gaps", [])),
        },
        "f3_checks": {
            "algorithm_pattern_field": {
                "passed": algo_case is not None,
                "layer_tags": algo_case.layer_tags if algo_case else [],
                "source": algo_case.source if algo_case else None,
                "learned": algo_case.learned[:3] if algo_case else [],
            },
            "dependency_graph_field": {
                "passed": dep_case is not None,
                "layer_tags": dep_case.layer_tags if dep_case else [],
                "source": dep_case.source if dep_case else None,
                "metadata": dep_case.metadata if dep_case else {},
            },
        },
    }
    return report


def main():
    report = run_f3_acceptance()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report.get("passed") else 1)


if __name__ == "__main__":
    main()
