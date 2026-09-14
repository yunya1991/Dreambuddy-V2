"""
复杂度分级验证脚本 (PROP-20260829D)

两个功能:
    1. golden  — 黄金集验证（AC2: 一致率 >= 90%）
    2. baseline — 基线快照（记录正典问题当前编排行为，供 AC3 回归比对）

用法:
    python3 test_complexity_grading.py golden
    python3 test_complexity_grading.py baseline
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH_DIR = os.path.dirname(HERE)          # 1-ARCHITECTURE
GOLDEN_PATH = os.path.join(HERE, "golden_set_complexity.json")
BASELINE_PATH = os.path.join(HERE, "baseline_complexity_snapshot.json")

sys.path.insert(0, ARCH_DIR)

from dreamos.core.sense.complexity_classifier import classify_complexity  # noqa: E402


def run_golden() -> int:
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data["cases"]

    hits, misses = 0, []
    for c in cases:
        decision = classify_complexity(c["q"], intent_type="")
        ok = decision.tier == c["expected"]
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] #{c['id']:02d} {c['expected']}→{decision.tier} "
              f"({decision.rule_hit}) {c['q']}")
        if ok:
            hits += 1
        else:
            misses.append({
                "id": c["id"], "q": c["q"], "expected": c["expected"],
                "got": decision.tier, "rule_hit": decision.rule_hit,
                "rationale": decision.rationale,
            })

    rate = hits / len(cases) if cases else 0.0
    print(f"\n一致率: {hits}/{len(cases)} = {rate:.1%} (AC2 要求 >= 90%)")
    if misses:
        print("不一致项:")
        for m in misses:
            print(f"  #{m['id']} 期望{m['expected']} 实际{m['got']} "
                  f"[{m['rule_hit']}] {m['q']}")
    return 0 if rate >= 0.9 else 1


def run_baseline() -> int:
    """记录正典问题的当前编排行为（改造前/回归比对用）"""
    from dreamos.core.sense.intent_engine import IntentEngine
    from dreamos.core.arrange.graph_planner import GraphPlanner
    from dreamos.registry.node_registry import get_default_registry
    from dreamos.capabilities.trading import TradingCapability

    registry = get_default_registry()
    if len(registry) == 0:
        TradingCapability().register(registry)  # 注册 22 个交易节点
    canonical_q = "BTC 现在能做多吗"
    market = {"price": 108400, "symbol": "BTC", "coin": "BTC"}

    engine = IntentEngine(use_llm_based=False)     # 纯本地，零 Token
    intent = engine.recognize(user_message=canonical_q, market=market,
                              symbol="BTC")

    planner = GraphPlanner(registry=registry)
    plan = planner.plan_from_intent(
        intent_type=intent.intent_type,
        recommended_chain=intent.recommended_chain,
        base_chain=intent.base_chain,
        extend_nodes=intent.extend_nodes,
        confidence=intent.confidence,
    )

    tier_decision = classify_complexity(canonical_q,
                                        intent_type=intent.intent_type)

    snapshot = {
        "created_at": datetime.utcnow().isoformat(),
        "canonical_question": canonical_q,
        "registered_node_count": len(registry),
        "intent": {
            "type": intent.intent_type,
            "confidence": intent.confidence,
            "chain": intent.recommended_chain,
            "base_chain": intent.base_chain,
            "extend_nodes": intent.extend_nodes,
        },
        "complexity_tier": tier_decision.to_dict(),
        "plan": {
            "node_ids": plan.node_ids,
            "node_count": len(plan.node_ids),
            "required": [m.node_id for m in plan.required_nodes],
            "optional": [m.node_id for m in plan.optional_nodes],
            "est_tokens": plan.estimated_total_tokens,
            "est_latency_ms": plan.estimated_total_latency_ms,
        },
    }
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"\n基线快照已写入: {BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "golden"
    sys.exit(run_golden() if mode == "golden" else run_baseline())
