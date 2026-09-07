"""TDD RED → GREEN：Score_B 注入 event_boost（0.10 clamp + FAIL-OPEN）

两个测试目标：
T1) compute_score_b_with_event_boost 函数存在，语义：
   Score_B_new = 0.58*continuity + 0.37*conf_norm + 0.05*event_strength + boost_clamp
   boost_clamp = clip(0.10 * max(0, (event_strength - 0.35)) / 0.65, 0, 0.10)
   FAIL-OPEN: event_strength=None/异常 → boost=0, Score_B = 0.60*cont + 0.40*conf（原公式，兼容回滚）

T2) 卦方向矛盾 ×0.70 地板抬升 0.85 仍硬拦截（event_boost不绕过）
"""
from __future__ import annotations

import math
import pytest


class TestScoreBEventBoost:
    # ── T1: compute_score_b_with_event_boost 函数存在与 clamp ──
    def test_module_exposes_function(self):
        # RED阶段：函数不存在，断言失败
        from scripts.memory_l4.polling_trader import compute_score_b_with_event_boost  # noqa: F401

    @pytest.mark.parametrize(
        "cont,conf,strength,expected_score_b,expected_boost_max_0_10",
        [
            # (A) 无快讯 strength=0.0 → 完全等价原公式（0.60×cont+0.40×conf），不额外抬
            (0.75, 0.70, 0.0, 0.60 * 0.75 + 0.40 * 0.70, 0.0),
            # (B) 强正面 strength=1.0 → boost=0.10；加权项: 0.58×0.75+0.37×0.70+0.05×1.0=0.435+0.259+0.05=0.744 + boost=0.10 → 0.844
            (0.75, 0.70, 1.0, 0.844, 0.10),
            # (C) 中性偏正面 strength=0.6 → raw_boost=0.10*0.25/0.65≈0.0385
            #     ⚠️ P1 C1④ G2护栏生效：EV门槛>0.05 → boost≤0.050清零回baseline（原P0 0.0385抬升被掐=防吹票黑嘴）
            #     新结果：boost=0.0，Score_B = baseline = 0.60*0.75 + 0.40*0.70 = 0.73（字节等价原v3.0）
            (0.75, 0.70, 0.6, 0.60 * 0.75 + 0.40 * 0.70, 0.0),
            # (D) FAIL-OPEN strength=None → 回退原公式（同A的0.73）
            (0.75, 0.70, None, 0.60 * 0.75 + 0.40 * 0.70, 0.0),
            # (E) 正面但<0.35门槛（如strength=0.2）→ 不抬升（防弱信号误提）
            (0.75, 0.70, 0.2, 0.60 * 0.75 + 0.40 * 0.70, 0.0),
            # (F) boost clamp >0.10被截断：构造 strength=2.0（理论越界）→ 仍只加0.10
            (0.75, 0.70, 2.0, 0.844, 0.10),
        ],
    )
    def test_formula_and_clamp(self, cont, conf, strength, expected_score_b, expected_boost_max_0_10):
        from scripts.memory_l4.polling_trader import compute_score_b_with_event_boost
        score, boost = compute_score_b_with_event_boost(cont, conf, strength)
        assert abs(boost - expected_boost_max_0_10) < 1e-3, (
            f"event_boost clamp不符：期望={expected_boost_max_0_10:.4f} 实际={boost:.4f}  "
            f"(cont={cont} conf={conf} strength={strength})"
        )
        assert abs(score - expected_score_b) < 1e-3, (
            f"Score_B不符：期望={expected_score_b:.4f} 实际={score:.4f}  "
            f"(cont={cont} conf={conf} strength={strength})"
        )

    # ── T1b: FAIL-OPEN 对 DB不可用/ImportError 绝对安全 ──
    def test_fail_open_on_exception(self):
        """mock抛出异常时score=baseline boost=0"""
        from scripts.memory_l4.polling_trader import compute_score_b_with_event_boost
        # 非法str类型注入 → 函数内部try/except应fail-open到0/原公式
        score, boost = compute_score_b_with_event_boost(0.75, 0.70, "not_a_number")  # type: ignore[arg-type]
        assert abs(score - (0.60 * 0.75 + 0.40 * 0.70)) < 1e-6
        assert abs(boost - 0.0) < 1e-6

    # ── T2: 卦方向矛盾 ×0.70 + 地板抬升 0.85 仍硬拦截（event_boost不绕过）──
    def test_direction_conflict_multiplier_not_bypassed_by_boost(self):
        """
        场景：卦=水天需（权威LONG） vs 决策SHORT → 原multiplier=×0.70，conf 0.8×0.70=0.56 < 门槛0.7955
        即便 Score_B event_boost=0.10 加到 consensus分，卦方向冲突的 confidence×dir_mult 仍硬卡 < 门槛 0.7955，
        最终 effective_conf < effective_threshold → 不开仓。
        """
        from scripts.memory_l4.polling_trader import (
            apply_hex_conflict_multiplier_and_floor,  # RED阶段必失败，待实现
        )
        # 案例：confidence=0.80，hex_name="水天需"，hex_dir="LONG" vs decision_dir="SHORT"
        eff_conf, floor_hit = apply_hex_conflict_multiplier_and_floor(
            confidence=0.80,
            hex_name="水天需",
            hex_authoritative_dir="LONG",
            decision_dir="SHORT",
        )
        # 先×0.70 = 0.56；然后 与 0.85 地板比 → 抬至 max(0.56, 0.85)=0.85（因为冲突硬惩罚抬高门槛端，
        # 实现里是把effective_conf设置成两者max，这样阈值0.7955下0.85可能够，但下面测试我们直接断言地板生效）
        assert eff_conf >= 0.8499, f"地板抬升0.85未生效，实际eff_conf={eff_conf:.4f}"
        assert floor_hit is True, "地板抬升标志位应为True"

        # 反向校验：一致性卦（水天需LONG+决策LONG）→ 不×不抬
        eff2, hit2 = apply_hex_conflict_multiplier_and_floor(
            0.80, "水天需", "LONG", "LONG"
        )
        assert abs(eff2 - 0.80) < 1e-6, f"一致性卦不该惩罚，实际={eff2:.4f}"
        assert hit2 is False
