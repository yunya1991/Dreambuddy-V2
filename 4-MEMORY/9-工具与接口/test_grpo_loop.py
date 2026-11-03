"""TB5 PolicySelectLoop（GRPO 借喻）TDD 用例 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §5

RED 1-5 对应 SPEC §5.4。
"""

import pytest
from cognitive_interfaces import BetaState
from grpo_evolution import GRPOEvolutionLoop, StrategyConfig
from regime_gate import REGIME_ARMS, ThompsonSamplingRegimeGate


def _beta_with_mean(mean: float) -> BetaState:
    return BetaState(alpha=mean, beta=1.0 - mean)


def _score(loop: GRPOEvolutionLoop, config: StrategyConfig, **kwargs) -> float:
    return loop.evaluate_config(config, **kwargs)


# RED 1: 理想数据 → 选出 pareto_score 最高的 config（不劣化）
def test_red1_selects_best_config():
    gate = ThompsonSamplingRegimeGate()
    current = StrategyConfig(known_gaps_threshold=5)
    better = StrategyConfig(known_gaps_threshold=0)
    loop = GRPOEvolutionLoop([current, better], gate)

    result = loop.evolve_step(
        beta_state=_beta_with_mean(0.9),
        psi_value=0.05,
        recall_hits=10,
        recall_total=10,
        known_gaps_count=5,
        cross_domain_refs=0,
    )

    assert result is not None
    assert loop.current_config is better
    assert _score(
        loop,
        loop.current_config,
        beta_state=_beta_with_mean(0.9),
        psi_value=0.05,
        recall_hits=10,
        recall_total=10,
        known_gaps_count=5,
        cross_domain_refs=0,
    ) >= _score(
        loop,
        current,
        beta_state=_beta_with_mean(0.9),
        psi_value=0.05,
        recall_hits=10,
        recall_total=10,
        known_gaps_count=5,
        cross_domain_refs=0,
    )


# RED 2: 次优 config 得分更高 → evolve_step 切换，方向正确
def test_red2_evolution_direction():
    gate = ThompsonSamplingRegimeGate()
    strict = StrategyConfig(known_gaps_threshold=10)  # citation 低
    lenient = StrategyConfig(known_gaps_threshold=0)  # citation 高
    loop = GRPOEvolutionLoop([strict, lenient], gate)

    kwargs = {
        "beta_state": _beta_with_mean(0.6),
        "psi_value": 0.1,
        "recall_hits": 5,
        "recall_total": 10,
        "known_gaps_count": 5,
        "cross_domain_refs": 2,
    }
    before = _score(loop, loop.current_config, **kwargs)
    result = loop.evolve_step(**kwargs)
    after = _score(loop, loop.current_config, **kwargs)

    assert result is lenient
    assert after > before


# RED 3: PSI > 0.25 → severe_drift → regime gate 全 arm 重置
def test_red3_psi_drift_resets_regime_gate():
    gate = ThompsonSamplingRegimeGate()
    gate.update("risk", 1.0)
    gate.update("bond", 1.0)
    assert gate.alpha["risk"] == pytest.approx(2.0)

    loop = GRPOEvolutionLoop([StrategyConfig()], gate)
    loop.evolve_step(
        beta_state=_beta_with_mean(0.7),
        psi_value=0.3,
        recall_hits=5,
        recall_total=10,
        known_gaps_count=2,
        cross_domain_refs=1,
    )

    for arm in REGIME_ARMS:
        assert gate.alpha[arm] == pytest.approx(1.0)
        assert gate.beta[arm] == pytest.approx(1.0)


# RED 4: 内部异常（beta_state=None）→ 返回 None + history 记录 fallback（H4 FAIL-OPEN）
def test_red4_fail_open_on_exception():
    gate = ThompsonSamplingRegimeGate()
    loop = GRPOEvolutionLoop([StrategyConfig()], gate)

    result = loop.evolve_step(
        beta_state=None,  # type: ignore[arg-type]
        psi_value=0.05,
        recall_hits=5,
        recall_total=10,
        known_gaps_count=2,
        cross_domain_refs=1,
    )

    assert result is None
    assert loop.history[-1]["fallback"] is True
    assert "error" in loop.history[-1]


# RED 5: 所有候选均劣于当前 → 返回 None，当前配置不变（不劣化）
def test_red5_no_degradation():
    gate = ThompsonSamplingRegimeGate()
    current = StrategyConfig(known_gaps_threshold=0)
    worse = StrategyConfig(known_gaps_threshold=10)
    loop = GRPOEvolutionLoop([current, worse], gate)

    result = loop.evolve_step(
        beta_state=_beta_with_mean(0.5),
        psi_value=0.05,
        recall_hits=5,
        recall_total=10,
        known_gaps_count=5,
        cross_domain_refs=0,
    )

    assert result is None
    assert loop.current_config is current
