# -*- coding: utf-8 -*-
"""P2: L1 路由置信度门控信号测试（C3 匹配度 + C4 预测误差 → route_confidence）。

依据: PLAN-L0L1L2-implementation.md P2 + SSoT v4.0 §16.5 / CDrive SPEC §7.7。
阈值跨系统唯一，禁止第二套：
  THRESHOLD_HIGH=0.7 / CASE_DENSITY_MIN=3 / PREDICTION_ERROR_MAX=0.3
  FAST_PATH: match≥0.8 & density≥5
公式:
  route_confidence = match_score − 0.3(若 prediction_error>0.3) − 0.2(若 case_density<3)
路由:
  route_confidence >= 0.7 → L1 直答（零 token）；< 0.7 → 转 L2（透传 l1_intent_hint）
FAIL-OPEN:
  recall 空/超时 → route_confidence=0 → L2；C4 不可用 → 退化为纯 C3；
  认知整体不可用 → 退回注册表静态置信度。

复用（不重写）: core.cognitive_router.evaluate_match + core.jev_gate 常量。
RED 阶段：core/route_confidence.py 不存在 → ModuleNotFoundError。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mems(scores):
    """构造对象型 memories（evaluate_match 同时兼容 dict 型）。"""
    return [SimpleNamespace(score=s, content=f"m{i}") for i, s in enumerate(scores)]


# ============================================================
# 1. 模块导入 + 阈值单一事实源
# ============================================================

class TestModuleImport:
    def test_import_api(self):
        from core.route_confidence import (
            evaluate_route, compute_route_confidence, compute_prediction_error,
            should_handle_l1, RouteConfidenceResult,
        )
        assert callable(evaluate_route)
        assert callable(compute_route_confidence)
        assert callable(compute_prediction_error)
        assert callable(should_handle_l1)

    def test_thresholds_are_cross_system_unique(self):
        from core import route_confidence as rc
        from core import cognitive_router as c3
        from core import jev_gate as c4
        assert rc.THRESHOLD_HIGH == 0.7
        assert rc.CASE_DENSITY_MIN == 3 == c3.TIER1_DENSITY_THRESHOLD
        assert rc.PREDICTION_ERROR_MAX == 0.3 == c4.PREDICTION_ERROR_THRESHOLD
        assert rc.FAST_PATH_MATCH == 0.8 == c4.FAST_PATH_MATCH
        assert rc.FAST_PATH_DENSITY == 5 == c4.FAST_PATH_DENSITY
        assert rc.L1_DIRECT == "L1_DIRECT"
        assert rc.L2_HANDOFF == "L2_HANDOFF"


# ============================================================
# 2. C4 预测误差（actual 取值顺序：rea_confidence → debate.bull_confidence → 不可用）
# ============================================================

class TestPredictionError:
    def test_rea_confidence_takes_priority(self):
        from core.route_confidence import compute_prediction_error
        err = compute_prediction_error(0.9, rea_confidence=0.4,
                                       debate_result={"bull_confidence": 0.1})
        assert err == pytest.approx(0.5)

    def test_debate_bull_confidence_fallback(self):
        from core.route_confidence import compute_prediction_error
        err = compute_prediction_error(0.9, debate_result={"bull_confidence": 0.35})
        assert err == pytest.approx(0.55)

    def test_no_c4_signal_means_unavailable(self):
        from core.route_confidence import compute_prediction_error
        assert compute_prediction_error(0.9) is None
        assert compute_prediction_error(0.9, debate_result=None) is None

    def test_boundary_error_equal_threshold_not_penalized(self):
        from core.route_confidence import compute_prediction_error
        # |0.9 - 0.6| = 0.3，规则为 >0.3 才扣分
        assert compute_prediction_error(0.9, rea_confidence=0.6) == pytest.approx(0.3)


# ============================================================
# 3. route_confidence 公式
# ============================================================

class TestRouteConfidenceFormula:
    def test_high_match_pure_c3_goes_l1(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9, 0.9, 0.9]))
        assert r.match_score == pytest.approx(0.9)
        assert r.case_density == 3
        assert r.prediction_error is None          # 无 C4 实际值 → C4 不可用，纯 C3
        assert r.route_confidence == pytest.approx(0.9)
        assert r.decision == "L1_DIRECT"
        assert r.degraded is False
        assert r.fast_path is False

    def test_prediction_error_penalty_03(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9, 0.9, 0.9]), rea_confidence=0.4)
        assert r.prediction_error == pytest.approx(0.5)
        assert r.route_confidence == pytest.approx(0.6)
        assert r.decision == "L2_HANDOFF"
        assert "prediction_error_penalty" in r.reasons

    def test_low_density_penalty_02(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.8]))           # density=1
        assert r.route_confidence == pytest.approx(0.6)
        assert r.decision == "L2_HANDOFF"
        assert "low_density_penalty" in r.reasons

    def test_both_penalties_stack(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9]), rea_confidence=0.4)
        assert r.route_confidence == pytest.approx(0.4)
        assert r.decision == "L2_HANDOFF"

    def test_threshold_boundary_07_goes_l1(self):
        from core.route_confidence import evaluate_route
        # match=0.9（单条记忆 max=avg=0.9），density<3 扣 0.2 → 恰好 0.7
        r = evaluate_route(_mems([0.9]))
        assert r.route_confidence == pytest.approx(0.7)
        assert r.decision == "L1_DIRECT"

    def test_error_equal_threshold_not_penalized(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9, 0.9, 0.9]), rea_confidence=0.6)  # err=0.3
        assert r.route_confidence == pytest.approx(0.9)
        assert r.decision == "L1_DIRECT"

    def test_fast_path_flag_but_formula_still_authoritative(self):
        # fast-path 标记仅为透传信号；门控决策严格按 route_confidence 公式
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9] * 5), rea_confidence=0.2)
        assert r.fast_path is True
        assert r.route_confidence == pytest.approx(0.6)
        assert r.decision == "L2_HANDOFF"

    def test_dict_style_memories_supported(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route([{"score": 0.9}, {"score": 0.9}, {"score": 0.9}])
        assert r.route_confidence == pytest.approx(0.9)
        assert r.decision == "L1_DIRECT"

    def test_to_dict_json_serializable(self):
        import json
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9, 0.9, 0.9]))
        d = r.to_dict()
        json.dumps(d, ensure_ascii=False)
        assert d["decision"] == "L1_DIRECT"
        assert {"route_confidence", "decision", "match_score", "case_density",
                "prediction_error", "fast_path", "degraded", "reasons"} <= set(d.keys())


# ============================================================
# 4. FAIL-OPEN 降级矩阵
# ============================================================

class TestFailOpen:
    def test_empty_memories_route_confidence_zero_to_l2(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route([])
        assert r.route_confidence == 0.0
        assert r.match_score == 0.0
        assert r.case_density == 0
        assert r.decision == "L2_HANDOFF"
        assert r.degraded is True
        assert "recall_empty" in r.reasons

    def test_none_memories_route_confidence_zero_to_l2(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(None)
        assert r.route_confidence == 0.0
        assert r.decision == "L2_HANDOFF"
        assert r.degraded is True

    def test_c4_unavailable_degrades_to_pure_c3(self):
        from core.route_confidence import evaluate_route
        # 即使传入 rea_confidence，c4_available=False 时必须忽略 C4、不扣分
        r = evaluate_route(_mems([0.9, 0.9, 0.9]),
                           rea_confidence=0.1, c4_available=False)
        assert r.prediction_error is None
        assert r.route_confidence == pytest.approx(0.9)
        assert r.decision == "L1_DIRECT"
        assert "c4_unavailable" in r.reasons

    def test_c4_exception_degrades_to_pure_c3(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(_mems([0.9, 0.9, 0.9]),
                           debate_result="not-a-dict", c4_available=True)
        # 异常被吞掉 → 纯 C3，绝不抛错
        assert r.prediction_error is None
        assert r.route_confidence == pytest.approx(0.9)
        assert r.decision == "L1_DIRECT"

    def test_cognitive_down_falls_back_to_static_high(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(None, cognitive_available=False, static_confidence=0.8)
        assert r.degraded is True
        assert r.route_confidence == 0.8
        assert r.decision == "L1_DIRECT"
        assert "cognitive_unavailable_static_fallback" in r.reasons

    def test_cognitive_down_static_low_goes_l2(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(None, cognitive_available=False, static_confidence=0.5)
        assert r.decision == "L2_HANDOFF"

    def test_cognitive_down_no_static_defaults_zero(self):
        from core.route_confidence import evaluate_route
        r = evaluate_route(None, cognitive_available=False)
        assert r.route_confidence == 0.0
        assert r.decision == "L2_HANDOFF"


# ============================================================
# 5. should_handle_l1 布尔便捷入口（供 L1 路由器/TS 信号对齐）
# ============================================================

class TestShouldHandleL1:
    def test_true_for_high_confidence(self):
        from core.route_confidence import should_handle_l1
        assert should_handle_l1(_mems([0.9, 0.9, 0.9])) is True

    def test_false_for_empty_and_low(self):
        from core.route_confidence import should_handle_l1
        assert should_handle_l1([]) is False
        assert should_handle_l1(_mems([0.5])) is False  # 0.5-0.2=0.3
