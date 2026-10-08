"""P1 T7 红测：StatAggregator BMA + KL散度加权聚合

测试用例：
  T7.1 test_aggregate_weights_sum_to_one              — 权重和=1
  T7.2 test_aggregate_satisfies_hard_constraints       — SL≥4%, TP≥12%, RR≥2
  T7.3 test_aggregate_kl_divergence_weighting          — 与 prior 差异大的算法权重高
  T7.4 test_aggregate_with_empty_observations          — 空输入回退默认值
  T7.5 test_aggregate_single_observation               — 单算法时权重=1
  T7.6 test_aggregate_confidence_propagation           — 置信度按权重传播

运行：
  python -m pytest 16-调控系统/scripts/param_center/tests/test_aggregator.py -v
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

# 路径设置
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent
_SCRIPTS_16 = _PARAM_CENTER.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# 导入被测对象（实现尚未编写 → RED）
from param_center.aggregator import (  # noqa: E402
    StatAggregator,
    AlgoObservation,
    ParamProposal,
)


def _make_obs(name: str, sl: float, tp: float, atr: float, conf: float = 0.8) -> AlgoObservation:
    """构造测试用 observation"""
    return AlgoObservation(
        algo_name=name,
        params={"sl_floor": sl, "tp_floor": tp, "atr_mult": atr},
        confidence=conf,
        timestamp=datetime.utcnow(),
    )


# ============================================================================
# T7.1 权重和 = 1
# ============================================================================
def test_aggregate_weights_sum_to_one():
    obs_list = [
        _make_obs("hmm", 0.05, 0.15, 4.5),
        _make_obs("bagua", 0.06, 0.18, 5.0),
        _make_obs("hurst", 0.04, 0.12, 4.0),
    ]
    agg = StatAggregator()
    proposal = agg.aggregate(obs_list)

    assert isinstance(proposal, ParamProposal)
    weight_sum = sum(proposal.weights.values())
    assert abs(weight_sum - 1.0) < 1e-6, f"权重和应为 1.0，实际 {weight_sum}"


# ============================================================================
# T7.2 硬约束兜底
# ============================================================================
def test_aggregate_satisfies_hard_constraints():
    # 故意构造低于硬约束的输入
    obs_list = [
        _make_obs("weak_algo", 0.01, 0.05, 2.0, conf=0.9),  # SL=1%, TP=5% 违规
        _make_obs("normal_algo", 0.05, 0.15, 4.5, conf=0.5),
    ]
    agg = StatAggregator()
    proposal = agg.aggregate(obs_list)

    params = proposal.params
    assert params["sl_floor"] >= 0.03, f"SL 下限违规: {params['sl_floor']}"
    assert params["tp_floor"] >= 0.12, f"TP 下限违规: {params['tp_floor']}"
    assert params["tp_floor"] / params["sl_floor"] >= 2.0, "RR 比违规"


# ============================================================================
# T7.3 KL散度加权：与 prior 差异大的算法权重高
# ============================================================================
def test_aggregate_kl_divergence_weighting():
    """与 prior 差异越大的算法，权重应越高（纠正群体保守偏差）"""
    prior = ParamProposal(
        params={"sl_floor": 0.04, "tp_floor": 0.12, "atr_mult": 4.0},
        confidence=0.5,
        weights={},
    )
    # algo_close 与 prior 接近，algo_far 与 prior 差异大
    obs_list = [
        _make_obs("algo_close", 0.045, 0.13, 4.2, conf=0.8),  # 接近 prior
        _make_obs("algo_far", 0.08, 0.24, 5.5, conf=0.8),     # 远离 prior
    ]
    agg = StatAggregator()
    proposal = agg.aggregate(obs_list, prior=prior)

    w_close = proposal.weights["algo_close"]
    w_far = proposal.weights["algo_far"]
    assert w_far > w_close, (
        f"KL散度大的算法权重应更高: far={w_far}, close={w_close}"
    )


# ============================================================================
# T7.4 空输入回退默认值
# ============================================================================
def test_aggregate_with_empty_observations():
    agg = StatAggregator()
    proposal = agg.aggregate([])

    # 应回退到默认参数 SL=3%, TP=12%
    assert proposal.params["sl_floor"] == 0.03, (
        f"空输入应回退默认 SL=3%, 实际 {proposal.params['sl_floor']}"
    )
    assert proposal.params["tp_floor"] == 0.12, (
        f"空输入应回退默认 TP=12%, 实际 {proposal.params['tp_floor']}"
    )
    assert proposal.confidence == 0.0, "空输入置信度应为 0"


# ============================================================================
# T7.5 单算法时权重=1
# ============================================================================
def test_aggregate_single_observation():
    obs_list = [_make_obs("solo", 0.05, 0.15, 4.5, conf=0.9)]
    agg = StatAggregator()
    proposal = agg.aggregate(obs_list)

    assert abs(proposal.weights["solo"] - 1.0) < 1e-6, (
        f"单算法权重应为 1.0，实际 {proposal.weights['solo']}"
    )
    assert proposal.confidence == pytest.approx(0.9, abs=1e-6)


# ============================================================================
# T7.6 置信度按权重传播
# ============================================================================
def test_aggregate_confidence_propagation():
    obs_list = [
        _make_obs("a", 0.05, 0.15, 4.5, conf=0.6),
        _make_obs("b", 0.06, 0.18, 5.0, conf=0.9),
    ]
    agg = StatAggregator()
    proposal = agg.aggregate(obs_list)

    # 置信度应为加权平均
    w_a = proposal.weights["a"]
    w_b = proposal.weights["b"]
    expected_conf = w_a * 0.6 + w_b * 0.9
    assert abs(proposal.confidence - expected_conf) < 1e-6, (
        f"置信度应={expected_conf}, 实际={proposal.confidence}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
