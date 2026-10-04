"""CLASSIC_PIPELINE 意图类型自动触发测试

测试 S 层 IntentEngine 能自动识别"经典流水线/C0-C8"等用户意图，
自动路由到 C_CLASSIC 链执行 C0-C8 九节点流水线。

TDD RED 阶段：全部断言应失败（CLASSIC_PIPELINE 尚未实现）
"""
import sys
import os

# 确保 dreamos 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_classic_pipeline_in_intent_types():
    """1. 枚举注册：CLASSIC_PIPELINE 在 all_types() 中"""
    from dreamos.core.sense import IntentType
    all_types = IntentType.all_types()
    assert "CLASSIC_PIPELINE" in all_types, f"CLASSIC_PIPELINE 不在 {all_types} 中"


def test_classic_pipeline_definition():
    """2. 意图定义：chain=C_CLASSIC, keywords 包含经典流水线"""
    from dreamos.core.sense import get_intent_definition
    defn = get_intent_definition("CLASSIC_PIPELINE")
    assert defn["chain"] == "C_CLASSIC", f"chain={defn.get('chain')}, 期望 C_CLASSIC"
    assert "经典流水线" in defn.get("keywords", []), f"keywords={defn.get('keywords')}"
    assert defn.get("priority", 99) <= 2, f"priority={defn.get('priority')}, 期望 <=2"


def test_classic_pipeline_in_intent_chain_map():
    """3. INTENT_CHAIN_MAP 映射：CLASSIC_PIPELINE → C_CLASSIC"""
    from dreamos.core.arrange.types import INTENT_CHAIN_MAP
    assert INTENT_CHAIN_MAP.get("CLASSIC_PIPELINE") == "C_CLASSIC", (
        f"INTENT_CHAIN_MAP={INTENT_CHAIN_MAP.get('CLASSIC_PIPELINE')}, 期望 C_CLASSIC"
    )


def test_rule_based_recognizer_classic_marker():
    """4. 规则识别器显式标记短路：零 Token 确定性路由"""
    from dreamos.core.sense import RuleBasedRecognizer, IntentInput
    rec = RuleBasedRecognizer()
    test_cases = [
        "跑一遍经典流水线",
        "classic pipeline",
        "C0-C8",
        "c0c8",
        "八阶段流水线",
        "经典交易",
    ]
    for msg in test_cases:
        result = rec.recognize(IntentInput(user_message=msg))
        assert result is not None, f"识别器返回 None: {msg}"
        assert result.intent_type == "CLASSIC_PIPELINE", (
            f"消息 '{msg}' 识别为 {result.intent_type}, 期望 CLASSIC_PIPELINE"
        )
        assert result.confidence >= 0.85, f"置信度 {result.confidence} < 0.85, 消息: {msg}"
        assert result.base_chain == ["C0","C1","C2","C3","C4","C5","C6","C7","C8"], (
            f"base_chain={result.base_chain}, 期望 9 节点"
        )
        assert result.tokens_used == 0, f"tokens_used={result.tokens_used}, 期望 0（零 Token）"


def test_classic_pipeline_no_false_positive():
    """5. 误伤防护：c0ffee / mac0 等不应触发 CLASSIC_PIPELINE"""
    from dreamos.core.sense import RuleBasedRecognizer, IntentInput
    rec = RuleBasedRecognizer()
    # 这些消息不应被识别为 CLASSIC_PIPELINE
    for msg in ["c0ffee is good", "mac0 disk", "a3 paper", "c3po robot"]:
        result = rec.recognize(IntentInput(user_message=msg))
        assert result.intent_type != "CLASSIC_PIPELINE", (
            f"误伤：'{msg}' 被识别为 CLASSIC_PIPELINE"
        )


def test_intent_engine_to_plan_classic_pipeline():
    """6. 端到端：IntentEngine → GraphPlanner → 选出 C0-C8"""
    from dreamos.core.sense import IntentEngine
    from dreamos.core.arrange import GraphPlanner
    from dreamos.capabilities.trading.nodes import register_all
    from dreamos.registry import get_default_registry
    from dreamos.shared.state import State

    # 注册节点
    reg = get_default_registry()
    register_all(reg)

    # 意图识别
    engine = IntentEngine(budget_mode="lean", use_llm_based=False)
    result = engine.recognize(user_message="跑经典流水线 C0-C8")
    assert result.intent_type == "CLASSIC_PIPELINE", (
        f"识别为 {result.intent_type}, 期望 CLASSIC_PIPELINE"
    )
    assert result.recommended_chain == "C_CLASSIC", (
        f"recommended_chain={result.recommended_chain}, 期望 C_CLASSIC"
    )

    # 图规划
    state = State()
    state.intent = result.to_dict() if hasattr(result, 'to_dict') else {
        "intent_type": result.intent_type,
        "recommended_chain": result.recommended_chain,
        "base_chain": result.base_chain,
        "confidence": result.confidence,
    }
    planner = GraphPlanner(registry=reg)
    plan = planner.plan(state)
    assert plan.planned_chain == "C_CLASSIC", (
        f"planned_chain={plan.planned_chain}, 期望 C_CLASSIC"
    )
    selected_ids = [m.node_id for m in plan.selected_nodes]
    for i in range(9):
        assert f"C{i}" in selected_ids, f"计划缺少 C{i}, selected={selected_ids}"


if __name__ == "__main__":
    """手动运行所有测试"""
    test_funcs = [
        test_classic_pipeline_in_intent_types,
        test_classic_pipeline_definition,
        test_classic_pipeline_in_intent_chain_map,
        test_rule_based_recognizer_classic_marker,
        test_classic_pipeline_no_false_positive,
        test_intent_engine_to_plan_classic_pipeline,
    ]
    passed = 0
    failed = 0
    for tf in test_funcs:
        try:
            tf()
            print(f"  PASS {tf.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {tf.__name__}: {e}")
            failed += 1
    print(f"\n结果: {passed} passed, {failed} failed (RED 阶段期望全 FAIL)")
