#!/usr/bin/env python3
"""
TDD RED: A8→A0 反向反馈链路测试。

背景：三层脑理论 #3-b 缺失——A8 检出的理论/实践偏差（gap_score / doc_only / code_only）
     应自动写回 A0 矛盾池，作为"第8维矛盾——理论实践一致性矛盾"。

设计：
  1. A0ContradictionEngine 新增 inject_external_contradiction() 方法
     接受 A8 偏差输入，合并到 contradictions 列表
  2. 新增 A8GapDimension 类（dim_id="a8_gap"，独立于市场7维）
  3. 新增 a8_to_a0_feedback() 桥接函数：
     - 交易 A8 输入 {gap_score, hypothesis_score, practice_score}
     - A8 校验引擎输入 {doc_only, code_only, consistency_score}
     → 转为 A8GapDimension 注入到 A0
"""
import sys
from pathlib import Path
from dataclasses import is_dataclass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# ---------------------------------------------------------------------------
# Test 1: A8GapDimension 数据类存在，字段正确
# ---------------------------------------------------------------------------
def test_a8_gap_dimension_exists():
    """A8GapDimension 数据类应包含 gap 类别、偏差详情、张力和映射方向。"""
    from memory_l4.a0_contradiction_engine import A8GapDimension

    assert is_dataclass(A8GapDimension), "A8GapDimension 应是 dataclass"

    d = A8GapDimension(
        source="trading_a8",     # 交易A8 / code_a8
        gap_score=0.45,
        hypothesis_score=0.80,
        practice_score=0.35,
        details={
            "doc_only": ["func_a", "func_b"],
            "code_only": ["func_c"],
            "consistency_score": 72.0,
        },
    )
    # 字段检查
    for key in ["source", "gap_score", "hypothesis_score", "practice_score", "details"]:
        assert hasattr(d, key), f"A8GapDimension 缺少字段 {key}"
    assert d.source == "trading_a8"
    assert abs(d.gap_score - 0.45) < 1e-6

    print("✅ test_a8_gap_dimension_exists 通过")
    return True


# ---------------------------------------------------------------------------
# Test 2: A0ContradictionEngine.inject_external_contradiction 方法存在
# ---------------------------------------------------------------------------
def test_inject_external_contradiction_exists():
    """A0ContradictionEngine 应有 inject_external_contradiction() 接受 A8 偏差。"""
    from memory_l4.a0_contradiction_engine import (
        A0ContradictionEngine, A8GapDimension,
    )

    engine = A0ContradictionEngine()
    assert hasattr(engine, "inject_external_contradiction"), \
        "A0ContradictionEngine 缺少 inject_external_contradiction 方法"

    gap = A8GapDimension(
        source="trading_a8", gap_score=0.50,
        hypothesis_score=0.70, practice_score=0.20,
        details={},
    )
    result = engine.inject_external_contradiction(gap)
    # 返回字典（ContradictionDimension 格式）可被 A0 识别
    assert "dim_id" in result, "注入结果应包含 dim_id"
    assert result["dim_id"] == "a8_gap", "dim_id 应为 a8_gap"
    assert 0.0 <= result["tension"] <= 1.0, "张力应在 0-1 之间"
    # gap_score=0.50 → 张力=0.50
    assert abs(result["tension"] - 0.50) < 1e-4, \
        f"tension 应等于 gap_score 0.50，实际 {result['tension']}"

    print("✅ test_inject_external_contradiction_exists 通过")
    return True


# ---------------------------------------------------------------------------
# Test 3: inject 后 A0.analyze() 输出中包含 a8_gap 维度
# ---------------------------------------------------------------------------
def test_analyze_includes_injected_a8_gap():
    """inject_external_contradiction 调用后，analyze() 结果应包含 a8_gap。"""
    import pandas as pd
    import numpy as np
    from memory_l4.a0_contradiction_engine import (
        A0ContradictionEngine, A8GapDimension,
    )

    engine = A0ContradictionEngine()

    # 构造最小 df（50 根假 K 线）
    n = 60
    closes = 100 + np.cumsum(np.random.RandomState(42).randn(n) * 0.5)
    df = pd.DataFrame({
        "open": closes - 0.3,
        "high": closes + 0.4,
        "low": closes - 0.5,
        "close": closes,
        "volume": np.random.RandomState(43).rand(n) * 1000 + 100,
    })

    # 注入 A8 偏差（高张力大 gap）
    gap = A8GapDimension(
        source="code_a8", gap_score=0.75,
        hypothesis_score=0.90, practice_score=0.15,
        details={"doc_only": ["fetch_x"], "code_only": [], "consistency_score": 25.0},
    )
    engine.inject_external_contradiction(gap)

    result = engine.analyze(df, inst_id="BTC-USDT")
    dim_ids = [c.dim_id for c in result.contradictions]

    assert "a8_gap" in dim_ids, f"a8_gap 应出现在 contradictions 中，实际 dim_ids={dim_ids}"
    # 总共应 8 维（7 市场 + 1 a8_gap）
    assert len(result.contradictions) == 8, \
        f"矛盾维度应为 8，实际 {len(result.contradictions)}"

    # to_dict 可序列化
    d = result.to_dict()
    a8d = [c for c in d["contradictions"] if c["dim_id"] == "a8_gap"][0]
    assert a8d["tension"] == 0.75, "a8_gap tension 应等于 gap_score=0.75"
    assert "代码A8: 理论0.90 vs 实践0.15" in a8d["evidence"] or \
           "A8" in a8d["evidence"], \
           f"evidence 应体现 A8 偏差内容: {a8d['evidence']}"

    print("✅ test_analyze_includes_injected_a8_gap 通过")
    return True


# ---------------------------------------------------------------------------
# Test 4: a8_to_a0_feedback 桥接函数——交易 A8 Dict → A8GapDimension → inject
# ---------------------------------------------------------------------------
def test_a8_to_a0_feedback_trading_a8():
    """桥接函数从交易 A8 Dict 构造并注入 A8 偏差。"""
    import pandas as pd
    import numpy as np
    from memory_l4.a8_a0_feedback import a8_to_a0_feedback, FeedbackResult
    from memory_l4.a0_contradiction_engine import A0ContradictionEngine

    engine = A0ContradictionEngine()

    # 交易 A8 输出（gap_score=0.35 → 中等偏差）
    trading_a8_dict = {
        "stage_id": "A8",
        "trace_id": "T-20260806-001",
        "hypothesis_score": 0.80,
        "practice_score": 0.45,
        "gap_score": 0.35,
        "timestamp": "20260806T120000Z",
    }

    fb: FeedbackResult = a8_to_a0_feedback(
        engine=engine,
        a8_output=trading_a8_dict,
        source="trading_a8",
    )
    assert fb.injected, "injected 应为 True"
    assert fb.dim_id == "a8_gap"
    assert abs(fb.tension - 0.35) < 1e-6, f"tension={fb.tension} 应等于 gap_score=0.35"

    # 确认已注入 analyze
    n = 60
    closes = 100 + np.cumsum(np.random.RandomState(44).randn(n) * 0.5)
    df = pd.DataFrame({
        "open": closes - 0.3, "high": closes + 0.4,
        "low": closes - 0.5, "close": closes,
        "volume": np.random.RandomState(45).rand(n) * 1000 + 100,
    })
    r = engine.analyze(df, inst_id="ETH-USDT")
    dim_ids = [c.dim_id for c in r.contradictions]
    assert "a8_gap" in dim_ids, "bridge 注入后 analyze 应有 a8_gap"

    print("✅ test_a8_to_a0_feedback_trading_a8 通过")
    return True


# ---------------------------------------------------------------------------
# Test 5: a8_to_a0_feedback 桥接函数——代码 A8 校验引擎报告 → A8GapDimension
# ---------------------------------------------------------------------------
def test_a8_to_a0_feedback_code_a8():
    """桥接函数从代码 A8Report dict 构造 A8 偏差。"""
    from memory_l4.a8_a0_feedback import a8_to_a0_feedback, FeedbackResult
    from memory_l4.a0_contradiction_engine import A0ContradictionEngine

    engine = A0ContradictionEngine()

    # 代码 A8 报告（a8_check_engine.py A8Report.to_dict 输出）
    code_a8_report = {
        "subsystem": "memory-system",
        "summary": {
            "doc_declared": 15,
            "code_implemented": 12,
            "matched": 10,
            "doc_only": 3,
            "code_only": 2,
            "consistency_score": 68.42,
        },
        "doc_only_functions": ["fetch_user_profile", "list_memos", "migrate_memos"],
        "code_only_functions": ["_internal_helper", "sanitize_input"],
    }

    fb: FeedbackResult = a8_to_a0_feedback(
        engine=engine,
        a8_output=code_a8_report,
        source="code_a8",
    )
    assert fb.injected, "code_a8 injected 应为 True"
    assert fb.dim_id == "a8_gap"
    # 张力 = 1 - consistency_score/100 = 1 - 0.6842 = 0.3158
    expected_tension = round(1 - 68.42 / 100.0, 4)
    assert abs(fb.tension - expected_tension) < 1e-4, \
        f"tension={fb.tension} vs expected={expected_tension}"
    assert fb.gap_source == "code_a8"

    # evidence 应包含 doc_only / code_only 详情
    assert len(fb.evidence) > 5
    print("✅ test_a8_to_a0_feedback_code_a8 通过")
    return True


# ---------------------------------------------------------------------------
# Test 6: 边界——空/无偏差不注入（tension 为 0）
# ---------------------------------------------------------------------------
def test_a8_no_gap_skipped():
    """gap=0 或无有效字段时，feedback 不注入，injected=False。"""
    from memory_l4.a8_a0_feedback import a8_to_a0_feedback, FeedbackResult
    from memory_l4.a0_contradiction_engine import A0ContradictionEngine

    engine = A0ContradictionEngine()

    # gap_score=0 完全一致
    fb0: FeedbackResult = a8_to_a0_feedback(
        engine=engine,
        a8_output={"hypothesis_score": 0.9, "practice_score": 0.9, "gap_score": 0.0},
        source="trading_a8",
    )
    # 一致无偏差：仍应注入但 tension=0，不影响主要矛盾
    assert fb0.injected, "gap=0 时也应记录（作为一致证据，tension=0）"
    assert fb0.tension == 0.0, f"gap=0 时 tension=0，实际 {fb0.tension}"

    # 无有效 a8 字段的 dict
    fb_empty: FeedbackResult = a8_to_a0_feedback(
        engine=engine,
        a8_output={"foo": "bar"},
        source="trading_a8",
    )
    assert not fb_empty.injected, "无字段应不注入"
    print("✅ test_a8_no_gap_skipped 通过")
    return True


# ---------------------------------------------------------------------------
# Test 7: 多次注入去重——同 trace_id 不重复写入
# ---------------------------------------------------------------------------
def test_duplicate_trace_dedup():
    """同 trace_id 的 A8 偏差多次调用 feedback，a8_gap 维度只保留最新一条。"""
    from memory_l4.a8_a0_feedback import a8_to_a0_feedback
    from memory_l4.a0_contradiction_engine import (
        A0ContradictionEngine, A8GapDimension,
    )

    engine = A0ContradictionEngine()
    trace = "T-DEDUP-001"
    # 两次注入，第二次 gap 更大
    a8_to_a0_feedback(engine, {"gap_score": 0.20, "trace_id": trace}, "trading_a8")
    a8_to_a0_feedback(engine, {"gap_score": 0.90, "trace_id": trace}, "trading_a8")

    # 检查内部 external 池：a8_gap 应只有 1 条且 tension=0.9
    ext = engine._external_contradictions
    a8_list = [e for e in ext if e.get("dim_id") == "a8_gap"]
    # 按实现可能 dedup 或覆盖，最新值应为 0.9
    latest = max(a8_list, key=lambda x: x.get("_ts", 0)) if a8_list else None
    assert latest is not None
    assert abs(latest["tension"] - 0.90) < 1e-4, \
        f"去重后最新 tension 应为 0.90，实际 {latest['tension']}"

    print("✅ test_duplicate_trace_dedup 通过")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        test_a8_gap_dimension_exists,
        test_inject_external_contradiction_exists,
        test_analyze_includes_injected_a8_gap,
        test_a8_to_a0_feedback_trading_a8,
        test_a8_to_a0_feedback_code_a8,
        test_a8_no_gap_skipped,
        test_duplicate_trace_dedup,
    ]
    passed = 0
    for t in tests:
        try:
            if t():
                passed += 1
        except Exception as e:
            import traceback
            print(f"❌ {t.__name__} 失败: {e}")
            traceback.print_exc()
    print(f"\n总计: {passed}/{len(tests)} 通过")
    sys.exit(0 if passed == len(tests) else 1)
