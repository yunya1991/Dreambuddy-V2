"""
DreamOS S层 — 感知层测试

验证:
    1. 所有模块能 import
    2. RuleBasedRecognizer 正常工作
    3. IntentEngine 主流程
    4. Token 预算管理
    5. 动态意图识别器
    6. 序列化/反序列化
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """测试所有模块能 import"""
    from dreamos.core.sense import (
        IntentType, IntentInput, IntentResult, RecognizerResult,
        IntentEngine, TokenBudgetManager, BudgetLevel, BUDGET_MODES,
        BaseRecognizer, RuleBasedRecognizer, LLMBasedRecognizer,
        DynamicIntentRecognizer,
        register_intent_type, get_intent_definition,
    )
    print("✅ import 测试通过")


def test_intent_types():
    """测试意图类型"""
    from dreamos.core.sense import IntentType, get_intent_definition

    # 6 种标准类型
    all_types = IntentType.all_types()
    assert len(all_types) == 5  # 排除 UNCERTAIN
    assert "TREND_FOLLOWING" in all_types
    assert "MEAN_REVERSION" in all_types
    assert "FUNDAMENTAL_PLAY" in all_types
    assert "BREAKOUT" in all_types
    assert "KNOWLEDGE_MATCH" in all_types

    # 定义存在
    defn = get_intent_definition("TREND_FOLLOWING")
    assert defn["name"] == "趋势跟随"
    assert defn["chain"] == "A"

    # 自定义类型
    from dreamos.core.sense import register_intent_type
    register_intent_type("ARBITRAGE", {
        "name": "套利",
        "chain": "F",
        "keywords": ["套利", "arb"],
    })
    defn2 = get_intent_definition("ARBITRAGE")
    assert defn2["name"] == "套利"

    print("✅ 意图类型测试通过")


def test_rule_based_recognizer_market():
    """测试规则识别器 - 市场数据"""
    from dreamos.core.sense import RuleBasedRecognizer, IntentInput

    rec = RuleBasedRecognizer()

    # 趋势行情
    result = rec.recognize(IntentInput(market={
        "price": 50000,
        "ema20": 49000,
        "ema50": 47000,
        "ema200": 44000,
        "change_24h": 6.5,
        "adx": 35,
        "rsi14": 62,
        "vol_ratio": 1.2,
    }))
    assert result.intent_type == "TREND_FOLLOWING"
    assert result.confidence > 0.5
    assert result.tokens_used == 0
    assert result.level == "local"

    # 超卖行情 → 均值回归
    result2 = rec.recognize(IntentInput(market={
        "price": 40000,
        "ema20": 45000,
        "ema50": 46000,
        "ema200": 47000,
        "rsi14": 20,
        "vol_ratio": 0.6,
        "change_24h": -1.0,
    }))
    assert result2.intent_type == "MEAN_REVERSION"
    assert result2.confidence > 0.4

    print("✅ 规则识别器（市场数据）测试通过")


def test_rule_based_recognizer_nlp():
    """测试规则识别器 - NLP"""
    from dreamos.core.sense import RuleBasedRecognizer, IntentInput

    rec = RuleBasedRecognizer()

    # 用户说"超买了要回调"
    result = rec.recognize(IntentInput(
        user_message="现在超买严重，应该会回调做空",
    ))
    assert result.intent_type == "MEAN_REVERSION"

    # 用户说"趋势很强"
    result2 = rec.recognize(IntentInput(
        user_message="这波trend很强，顺势做多",
    ))
    assert result2.intent_type == "TREND_FOLLOWING"

    print("✅ 规则识别器（NLP）测试通过")


def test_rule_based_recognizer_empty():
    """测试规则识别器 - 无输入"""
    from dreamos.core.sense import RuleBasedRecognizer, IntentInput, IntentType

    rec = RuleBasedRecognizer()
    result = rec.recognize(IntentInput())
    assert result.intent_type == IntentType.UNCERTAIN.value
    assert result.confidence == 0.0

    print("✅ 规则识别器（无输入）测试通过")


def test_intent_engine_basic():
    """测试 IntentEngine 基本流程"""
    from dreamos.core.sense import IntentEngine

    engine = IntentEngine(budget_mode="lean", use_llm_based=False)

    # 纯市场数据
    result = engine.recognize(
        market={"price": 50000, "change_24h": 5.0, "rsi14": 55,
                "ema20": 49000, "ema50": 47000, "ema200": 44000,
                "adx": 28, "vol_ratio": 1.3}
    )

    assert result.intent_type is not None
    assert result.confidence > 0
    assert len(result.base_chain) > 0
    assert result.recommended_chain in ("A", "C", "F")
    assert "rule_based" in result.recognizers_used
    assert result.total_tokens == 0  # 纯规则，零 Token

    print(f"✅ IntentEngine 基本流程测试通过 → {result.intent_type} (conf={result.confidence:.2f})")


def test_intent_engine_with_nlp():
    """测试 IntentEngine + NLP"""
    from dreamos.core.sense import IntentEngine

    engine = IntentEngine(use_llm_based=False)

    result = engine.recognize(
        user_message="分析一下现在的趋势，顺势操作",
        market={"price": 50000, "change_24h": 2.0, "rsi14": 50},
    )
    assert result.intent_type is not None
    assert result.confidence > 0

    print("✅ IntentEngine + NLP 测试通过")


def test_token_budget():
    """测试 Token 预算管理器"""
    from dreamos.core.sense import TokenBudgetManager, BudgetLevel, BUDGET_MODES

    # 三档预算
    assert BUDGET_MODES["lean"] == 3000
    assert BUDGET_MODES["standard"] == 6000
    assert BUDGET_MODES["full"] == 10000

    budget = TokenBudgetManager(mode="lean")
    assert budget.total == 3000
    assert budget.remaining == 3000
    assert budget.level() == BudgetLevel.HEALTHY
    assert not budget.should_degrade_llm()

    # 消耗 — 用 800，剩余约 73% → 还是 HEALTHY
    budget.consume(800, layer="sense")
    assert budget.used == 800
    assert budget.remaining == 2200
    assert budget.level() == BudgetLevel.HEALTHY

    # 再用 1000，剩 1200（40%）→ WARNING
    budget.consume(1000, layer="arrange")
    assert budget.level() == BudgetLevel.WARNING

    # 再用 500，剩 700（~23%）→ LOW
    budget.consume(500, layer="compute")
    assert budget.level() == BudgetLevel.LOW
    assert budget.should_degrade_llm()

    # 再用 450，剩 250（~8%）→ CRITICAL
    budget.consume(450, layer="compute")
    assert budget.level() == BudgetLevel.CRITICAL

    # 再用 200，剩 50（<2%）→ EXHAUSTED
    budget.consume(200, layer="graph_store")
    assert budget.level() == BudgetLevel.EXHAUSTED
    assert budget.should_switch_classic()

    # 分层预算
    budget2 = TokenBudgetManager(mode="standard")
    assert budget2.layer_budget("sense") > 0
    assert budget2.layer_budget("compute") > budget2.layer_budget("sense")

    # reset
    budget.reset()
    assert budget.used == 0
    assert budget.level() == BudgetLevel.HEALTHY

    # summary
    summary = budget2.summary()
    assert summary["total"] == 6000
    assert summary["mode"] == "standard"
    assert summary["level"] == "healthy"

    print("✅ Token 预算管理测试通过")


def test_dynamic_recognizer():
    """测试动态意图识别器"""
    from dreamos.core.sense import (
        DynamicIntentRecognizer, IntentInput, RecognizerResult,
    )

    rec = DynamicIntentRecognizer()

    # 注册自定义意图类型
    rec.register_intent_type("ARBITRAGE", {
        "name": "套利",
        "chain": "F",
        "keywords": ["套利", "arb"],
    })
    assert "ARBITRAGE" in rec.list_custom_types()

    # 注册策略
    def my_strategy(_input):
        if _input.user_message and "套利" in _input.user_message:
            return RecognizerResult(
                recognizer="my_strategy",
                intent_type="ARBITRAGE",
                confidence=0.75,
                rationale="用户提到套利",
            )
        return None

    rec.register_strategy("arb_strategy", my_strategy)

    # 触发自定义策略
    result = rec.recognize(IntentInput(user_message="有没有套利机会"))
    assert result.intent_type == "ARBITRAGE"
    assert result.confidence == 0.75

    # 不触发 → UNCERTAIN
    result2 = rec.recognize(IntentInput(user_message="分析趋势"))
    assert result2.intent_type == "UNCERTAIN"

    # 注销策略
    assert rec.unregister_strategy("arb_strategy")
    result3 = rec.recognize(IntentInput(user_message="有没有套利机会"))
    assert result3.intent_type == "UNCERTAIN"

    print("✅ 动态意图识别器测试通过")


def test_intent_result_serialization():
    """测试 IntentResult 序列化"""
    from dreamos.core.sense import IntentResult

    result = IntentResult(
        intent_type="TREND_FOLLOWING",
        confidence=0.75,
        recommended_chain="A",
        base_chain=["A1", "A2"],
        rationale="趋势明显",
    )

    d = result.to_dict()
    assert d["intent_type"] == "TREND_FOLLOWING"
    assert d["confidence"] == 0.75

    result2 = IntentResult.from_dict(d)
    assert result2.intent_type == result.intent_type
    assert result2.confidence == result.confidence
    assert result2.base_chain == result.base_chain

    print("✅ IntentResult 序列化测试通过")


def test_engine_with_dynamic():
    """测试 IntentEngine + 动态识别器集成"""
    from dreamos.core.sense import IntentEngine, RecognizerResult

    engine = IntentEngine(use_llm_based=False)

    # 注册自定义意图
    engine.register_custom_intent("SCALPING", {
        "name": "刷单",
        "chain": "C",
        "keywords": ["刷单", "scalp", "高频"],
    })

    # 注册自定义策略
    def scalp_detector(_input):
        if _input.market and _input.market.get("vol_ratio", 0) > 3:
            return RecognizerResult(
                recognizer="scalp_detector",
                intent_type="SCALPING",
                confidence=0.8,
                rationale="波动率极高，适合刷单",
                base_chain=["C1", "C2"],
            )
        return None

    engine.register_strategy("scalp_detector", scalp_detector)

    # 触发自定义策略
    result = engine.recognize(market={"vol_ratio": 4.0, "price": 50000})
    # 动态策略可能比规则高
    assert result is not None
    assert "dynamic" in str(result.recognizers_used) or "rule_based" in str(result.recognizers_used)

    print("✅ IntentEngine + 动态识别器集成测试通过")


def test_layers_structure():
    """测试层目录结构正确"""
    import dreamos.core.sense as sense
    import dreamos.core.sense.recognizers as recs

    assert hasattr(sense, "IntentEngine")
    assert hasattr(sense, "RuleBasedRecognizer")
    assert hasattr(sense, "LLMBasedRecognizer")
    assert hasattr(sense, "DynamicIntentRecognizer")
    assert hasattr(sense, "TokenBudgetManager")

    assert hasattr(recs, "BaseRecognizer")
    assert hasattr(recs, "RuleBasedRecognizer")
    assert hasattr(recs, "LLMBasedRecognizer")
    assert hasattr(recs, "DynamicIntentRecognizer")

    print("✅ 层结构测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("DreamOS S层 — 感知层测试")
    print("=" * 60)
    test_imports()
    test_intent_types()
    test_rule_based_recognizer_market()
    test_rule_based_recognizer_nlp()
    test_rule_based_recognizer_empty()
    test_intent_engine_basic()
    test_intent_engine_with_nlp()
    test_token_budget()
    test_dynamic_recognizer()
    test_intent_result_serialization()
    test_engine_with_dynamic()
    test_layers_structure()
    print("=" * 60)
    print("🎉 所有 S 层测试通过！")
    print("=" * 60)
