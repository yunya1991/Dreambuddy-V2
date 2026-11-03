"""TB3 AlphaPareto 七维奖励 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §3

为 TB5 PolicySelectLoop 提供多目标奖励定义（维度定义唯一事实源）。
维度 7 `pnl_delta_score`（2026-11-03 三问评估补充）：跨域组合相对单域 baseline
的回测 Alpha 提升，消费 DOMAIN-DISCOVERY P4 沙箱回执；无回执时 FAIL-OPEN 中性 0.5。
依赖 TB2 `BetaState`（绝对 import；本目录非包）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from cognitive_interfaces import BetaState

# 初版权重（七维，和=1.0）；影子期按 SPEC §6.5 校准协议回测后改常量，
# 禁止运行期动态调整（与 TB1 H8 同类硬约束）。
# 维度 7 pnl_delta_score 初始权重偏低（0.10），等沙箱稳定后可校准上调。
REWARD_WEIGHTS: Tuple[float, ...] = (0.23, 0.18, 0.18, 0.14, 0.12, 0.05, 0.10)

# 极端值上限：PSI > 1.0 按 1.0 算；known_gaps > 10 按下限 0 算
PSI_MAX_CAP: float = 1.0
KNOWN_GAPS_CAP: int = 10
CROSS_DOMAIN_BONUS: float = 0.1

# 维度 7 归一化参数（SPEC §3.3）：clip((treatment - control + 0.05) / 0.25, 0, 1)
PNL_ALPHA_MARGIN: float = 0.05
PNL_ALPHA_RANGE: float = 0.25
PNL_NEUTRAL: float = 0.5  # FAIL-OPEN：无回执或缺字段时中性


@dataclass
class RewardComponents:
    """AlphaPareto 七维奖励分量（六维 + pnl_delta_score）。"""

    p_verify_success: float  # 维度 1：TB2 Beta verify mean
    p_recall_hit: float  # 维度 2：同类事件 recall 命中率
    psi_stability: float  # 维度 3：1 - PSI → 漂移越小越稳定
    citation_diversity: float  # 维度 4：known_gaps 越少越高 + 跨域引用加权 + Oracle 置信度吸收
    process_reward: float  # 维度 5：中间 step 可验证子目标奖励
    transition_smoothness: float  # 维度 6：相邻 step 状态转移平滑度
    pnl_delta_score: float  # 维度 7：跨域组合 vs 单域 baseline 的 Alpha 提升（无回执 → 0.5）


def _compute_pnl_delta_score(counterfactual_result: Optional[dict]) -> float:
    """维度 7：P4 沙箱回执 → pnl_delta_score ∈ [0, 1]。

    FAIL-OPEN：回执缺失、非 dict、字段缺失、类型不可转 float → 中性 0.5。
    """
    if not isinstance(counterfactual_result, dict):
        return PNL_NEUTRAL
    try:
        treatment = float(counterfactual_result["treatment_alpha"])
        control = float(counterfactual_result["control_alpha_mean"])
    except (KeyError, TypeError, ValueError):
        return PNL_NEUTRAL
    raw = (treatment - control + PNL_ALPHA_MARGIN) / PNL_ALPHA_RANGE
    return min(max(raw, 0.0), 1.0)


def compute_reward(
    beta_state: BetaState,
    psi_value: float,
    recall_hits: int,
    recall_total: int,
    known_gaps_count: int,
    cross_domain_refs: int,
    process_reward: float = 0.0,
    transition_smoothness: float = 1.0,
    counterfactual_result: Optional[dict] = None,
) -> RewardComponents:
    """AlphaPareto 七维奖励定义。

    P_verify_success = TB2 Beta mean
    P_recall_hit = recall_hits / recall_total（total=0 时 0.0）
    psi_stability = max(0, 1 - min(PSI, 1.0))
    citation_diversity = max(0, 1 - min(gaps, 10)/10) * (1 + 0.1 * refs)
    pnl_delta_score = clip((treatment - control + 0.05) / 0.25, 0, 1)；无回执 → 0.5
    """
    p_verify = beta_state.mean
    p_recall = recall_hits / max(recall_total, 1)
    psi_stab = max(0.0, 1.0 - min(psi_value, PSI_MAX_CAP))
    citation = max(0.0, 1.0 - min(known_gaps_count, KNOWN_GAPS_CAP) / KNOWN_GAPS_CAP) * (
        1.0 + CROSS_DOMAIN_BONUS * cross_domain_refs
    )

    return RewardComponents(
        p_verify_success=p_verify,
        p_recall_hit=p_recall,
        psi_stability=psi_stab,
        citation_diversity=citation,
        process_reward=process_reward,
        transition_smoothness=transition_smoothness,
        pnl_delta_score=_compute_pnl_delta_score(counterfactual_result),
    )


def pareto_score(reward: RewardComponents, weights: Tuple[float, ...] = REWARD_WEIGHTS) -> float:
    """Pareto 前沿综合评分（初版七维加权和，后续升级为 MAP 流形感知）。"""
    components = (
        reward.p_verify_success,
        reward.p_recall_hit,
        reward.psi_stability,
        reward.citation_diversity,
        reward.process_reward,
        reward.transition_smoothness,
        reward.pnl_delta_score,
    )
    return sum(w * c for w, c in zip(weights, components, strict=True))
