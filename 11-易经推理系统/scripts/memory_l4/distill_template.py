"""蒸馏模板模块 — v0.2 兼容层。

保留原有 CLI 接口 (create_distill_template)，内部调用 distill_engine 的完整流程。
设计文档 7.3.3 要求。
"""

import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_distills_dir


def create_distill_template(
    distill_id: str,
    supporting_case_ids: List[str],
    kind: str = "risk_signal",
    review_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建蒸馏模板，兼容旧版 CLI + 内部调用 distill_engine。

    Args:
        distill_id: 蒸馏标识
        supporting_case_ids: 支持案例 ID 列表
        kind: 蒸馏类型
        review_record: 可选 ReviewRecord，提供后走 distill_engine 完整流程

    Returns:
        Distill 字典
    """
    if review_record is not None:
        # v0.2: 走 distill_engine 完整流程
        from scripts.memory_l4 import distill_engine

        review_record["review_id"] = review_record.get("review_id", f"REV_{distill_id}")
        review_record["case_id"] = review_record.get("case_id", supporting_case_ids[0] if supporting_case_ids else "")
        distill = distill_engine.init_distill(review_record, kind=kind, distill_id=distill_id)
        distill = distill_engine.run_full_distill_pipeline(review_record, kind=kind)
        distill["distill_id"] = distill_id
        distill["supporting_case_ids"] = supporting_case_ids
        return distill

    # v0.1 兼容: 返回骨架
    return {
        "distill_id": distill_id,
        "version": "v0.2",
        "kind": kind,
        "what_is_it": {
            "claim": "",
            "definition": None,
            "classification": [kind],
        },
        "why_it_works": {
            "causal_analysis": "",
            "theory_basis": [],
            "evidence_chain": [],
            "contradiction_resolved": None,
        },
        "how_to_apply": {
            "actionable_rules": [],
            "trigger_conditions": [],
            "step_by_step": [],
            "risk_warnings": [],
        },
        "claim": "",
        "supporting_case_ids": supporting_case_ids,
        "actionable_rules": [],
        "process_trace": {
            "intent": None, "investigation": None, "theory_refs": [],
            "hypothesis": None, "test_results": None, "conclusion": None,
            "implementation": None, "monitoring": None, "review_result": None,
            "reflection": None, "optimization": None,
        },
        "quadrant": {
            "x": 0.0,
            "y": 0.0,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": 0.0,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": ""
            }
        },
        "migration_history": []
    }


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args()

    case_ids = [s.strip() for s in args.cases.split(",") if s.strip()]
    data = create_distill_template(args.id, case_ids, kind=args.kind)
    out_path = memory_l4_distills_dir() / f"{args.id}.json"
    save_json(out_path, data)
    print(str(out_path))


if __name__ == "__main__":
    main()

