"""端到端测试：开仓 → 结算 → 逆向推导 → 精准奖惩 全链路。

模拟真实交易结算流程，验证方向3 逆向推导子系统的完整闭环。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))

from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
from reverse_deriver import ReverseDeriver


@pytest.fixture
def engine():
    return ReflectionEngine()


@pytest.fixture
def deriver():
    return ReverseDeriver()


def test_e2e_true_failure_full_chain(engine, deriver):
    """E2E: 真失败场景 — 开仓long但行情short，C1资金流错判。

    链路：create_snapshot → calculate_cs → ReverseDeriver.derive → apply_reward_with_derive
    预期：C1资金流入因子降权，ESS扣减，gmax×0.5。
    """
    # Step 1: 开仓快照（含维度预测 + 因子权重）
    snapshot = engine.create_snapshot(
        symbol="BTC-USDT-SWAP",
        u_open=50000.0,
        action="long",
        level0_dstar="long",
        ess_id="ess_btc_001",
        ess_dir="long",
        cbr_sim=0.6,
        cbr_top1_outcome="SL",
        cluster_id="C_BTC_MOM",
        dimension_predictions={"C1": "long", "C2": "short", "C3": "long"},
        dimension_factors={
            "C1": {"资金流入": 0.5, "主力净买": 0.3},
            "C2": {"多空比": 0.4},
            "C3": {"MACD金叉": 0.6},
        },
    )
    assert "dimension_predictions" in snapshot
    assert "dimension_factors" in snapshot

    # Step 2: 结算结果
    outcome = {"real_direction": "short", "real_outcome": "SL"}

    # Step 3: 计算 CS 一致性得分
    cs = engine.calculate_cs(snapshot, outcome)
    assert cs <= -0.2  # d*=long vs real=short → cos=-1, ESS同 → -1, CBR SL=SL → +1
    # CS = 0.4*(-1) + 0.3*(-1) + 0.3*(+1) = -0.4 -0.3 +0.3 = -0.4

    # Step 4: 逆向推导
    derive_result = deriver.derive(snapshot, outcome)
    # dimension_factors存在但factor_values缺失 → evidence_trace判定data_error
    assert derive_result.root_cause_type in ("factor_error", "weight_error", "data_error")
    assert "C1" in derive_result.wrong_dimensions  # C1预测long实际short → 错
    assert derive_result.per_dimension_correctness["C2"] is True  # C2 short对

    # Step 5: 精准奖惩
    reward = engine.apply_reward_with_derive(
        cs=cs, outcome="SL", cluster_id="C_BTC_MOM", ess_id="ess_btc_001",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # base_reward：CS≤-0.2 & SL → ess_delta=-0.05, gmax_mult=0.5
    assert reward["ess_delta"] == pytest.approx(-0.05)
    assert reward["gmax_mult"] == pytest.approx(0.5)

    # factor_adjustments：C1错→资金流入/主力净买×0.9，C2对→多空比×1.05，C3错→MACD×0.9
    fa = reward["factor_adjustments"]
    assert fa["资金流入"] == pytest.approx(0.5 * 0.9)
    assert fa["主力净买"] == pytest.approx(0.3 * 0.9)
    assert fa["多空比"] == pytest.approx(0.4 * 1.05)
    assert fa["MACD金叉"] == pytest.approx(0.6 * 0.9)


def test_e2e_false_failure_full_chain(engine, deriver):
    """E2E: 假失败场景 — 方向对但被扫损，不应扣ESS，因子全升权。"""
    snapshot = engine.create_snapshot(
        symbol="ETH-USDT-SWAP",
        u_open=3000.0,
        action="long",
        level0_dstar="long",
        ess_id="ess_eth_001",
        ess_dir="long",
        cbr_sim=0.85,
        cbr_top1_outcome="TP",
        cluster_id="C_ETH_TREND",
        dimension_predictions={"C1": "long", "C3": "long"},
        dimension_factors={
            "C1": {"资金流入": 0.5},
            "C3": {"MACD金叉": 0.6},
        },
    )
    outcome = {"real_direction": "long", "real_outcome": "SL"}  # 方向对但被扫损

    cs = engine.calculate_cs(snapshot, outcome)
    # d*=long=real→+1, ESS=long=real→+1, CBR=TP vs SL→-1
    # CS = 0.4*1 + 0.3*1 + 0.3*(-1) = 0.4+0.3-0.3 = 0.4
    assert -0.2 <= cs < 0.7

    derive_result = deriver.derive(snapshot, outcome)
    assert derive_result.wrong_dimensions == []  # 维度全对
    assert derive_result.root_cause_type == "unknown"

    reward = engine.apply_reward_with_derive(
        cs=cs, outcome="SL", cluster_id="C_ETH_TREND", ess_id="ess_eth_001",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # 假失败：CS≥0.7&SL才触发gmax×1.2；此处CS=0.4走中性
    assert reward["ess_delta"] == pytest.approx(0.0)
    # 维度全对 → 全部升权 ×1.05
    assert reward["factor_adjustments"]["资金流入"] == pytest.approx(0.5 * 1.05)
    assert reward["factor_adjustments"]["MACD金叉"] == pytest.approx(0.6 * 1.05)


def test_e2e_true_success_full_chain(engine, deriver):
    """E2E: 真成功场景 — 全对且TP，ESS大步长+0.05，因子全升权。"""
    snapshot = engine.create_snapshot(
        symbol="SOL-USDT-SWAP",
        u_open=150.0,
        action="short",
        level0_dstar="short",
        ess_id="ess_sol_001",
        ess_dir="short",
        cbr_sim=0.9,
        cbr_top1_outcome="TP",
        cluster_id="C_SOL_BREAK",
        dimension_predictions={"C1": "short", "C2": "short", "C3": "short"},
        dimension_factors={
            "C1": {"资金流出": 0.5},
            "C2": {"多空比": 0.4},
            "C3": {"MACD死叉": 0.6},
        },
    )
    outcome = {"real_direction": "short", "real_outcome": "TP"}

    cs = engine.calculate_cs(snapshot, outcome)
    assert cs >= 0.9  # 全对 → 0.4+0.3+0.3 = 1.0

    derive_result = deriver.derive(snapshot, outcome)
    assert derive_result.wrong_dimensions == []

    reward = engine.apply_reward_with_derive(
        cs=cs, outcome="TP", cluster_id="C_SOL_BREAK", ess_id="ess_sol_001",
        gmax=0.3, snapshot=snapshot, derive_result=derive_result,
    )

    # CS≥0.9 & TP → ess_delta=+0.05
    assert reward["ess_delta"] == pytest.approx(0.05)
    # 全对 → 全升权
    assert reward["factor_adjustments"]["资金流出"] == pytest.approx(0.5 * 1.05)
    assert reward["factor_adjustments"]["多空比"] == pytest.approx(0.4 * 1.05)
    assert reward["factor_adjustments"]["MACD死叉"] == pytest.approx(0.6 * 1.05)
