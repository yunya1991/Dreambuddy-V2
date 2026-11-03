"""TB5 PolicySelectLoop（GRPO 借喻）— SPEC-L0-AGENT-TRAIN-BASE v0.1 §5

冻结 LLM 权重，只调策略输出格式（【H2 硬约束】：无 .train()/.backward()/.backprop，
仅对候选配置做 argmax 选择）。
依赖 TB1 classify_drift + TB2 BetaState + TB3 AlphaPareto + TB4 regime gate。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from cognitive_interfaces import BetaState
from drift_detector import classify_drift
from regime_gate import ThompsonSamplingRegimeGate
from training_reward import compute_reward, pareto_score


@dataclass
class StrategyConfig:
    """Agent 策略配置（冻结权重，只调格式）。

    注意：这不是神经网络权重，是 JSON 格式的输出偏好配置（H2）。
    """

    field_order: List[str] = field(default_factory=list)  # JSON 字段输出顺序
    known_gaps_threshold: int = 5  # known_gaps ≤ 此值才算合格
    evidence_min_confidence: float = 0.5  # PoE 证据链最低置信度
    max_cross_domain_refs: int = 10  # 跨域引用上限（防膨胀）
    process_weight: float = 0.3  # 维度 5 process_reward 权重（B2）
    transition_weight: float = 0.2  # 维度 6 transition_smoothness 权重（B2）
    oracle_weight: float = 0.2  # Oracle oracle_confidence 吸收权重（B5）
    version: str = "v0.1"


class GRPOEvolutionLoop:
    """轻量策略进化 loop（冻结权重，只调策略格式）。

    依赖：TB1 + TB2 + TB3 + TB4；零 GPU。
    """

    def __init__(
        self,
        candidate_configs: List[StrategyConfig],
        regime_gate: ThompsonSamplingRegimeGate,
    ):
        self.candidates = candidate_configs
        self.regime_gate = regime_gate
        self.current_config = candidate_configs[0]  # 初始选第一个
        self.history: List[dict] = []

    def evaluate_config(
        self,
        config: StrategyConfig,
        beta_state: BetaState,
        psi_value: float,
        recall_hits: int,
        recall_total: int,
        known_gaps_count: int,
        cross_domain_refs: int,
    ) -> float:
        """评估某个策略配置的 Reward。

        1. 用配置过滤 known_gaps / cross_domain_refs
        2. 用 TB3 AlphaPareto 算六维奖励
        3. 用 pareto_score 加权综合
        """
        filtered_gaps = min(known_gaps_count, config.known_gaps_threshold)
        filtered_refs = min(cross_domain_refs, config.max_cross_domain_refs)

        reward = compute_reward(
            beta_state=beta_state,
            psi_value=psi_value,
            recall_hits=recall_hits,
            recall_total=recall_total,
            known_gaps_count=filtered_gaps,
            cross_domain_refs=filtered_refs,
        )
        return pareto_score(reward)

    def evolve_step(
        self,
        beta_state: BetaState,
        psi_value: float,
        recall_hits: int,
        recall_total: int,
        known_gaps_count: int,
        cross_domain_refs: int,
    ) -> Optional[StrategyConfig]:
        """执行一轮策略进化。

        Returns:
            改进后的策略配置；当前已最优则返回 None（不劣化保证）。

        【H4 硬约束】：FAIL-OPEN，单轮失败不阻塞主流程，自动保留上一稳定配置。
        """
        try:
            # 1. TB1 漂移检测
            drift_level = classify_drift(psi_value)

            # 2. TB4 regime gate 选最优 regime（漂移时 Bayesian reset）
            regime = self.regime_gate.select_regime()
            self.regime_gate.update(
                arm=regime,
                success_rate=beta_state.mean,
                drift_detected=(drift_level != "stable"),
            )

            # 3. 候选策略评估（含当前策略，Dream-RSI 不劣化保证）
            current_score = self.evaluate_config(
                self.current_config,
                beta_state,
                psi_value,
                recall_hits,
                recall_total,
                known_gaps_count,
                cross_domain_refs,
            )
            scores = [
                (
                    config,
                    self.evaluate_config(
                        config,
                        beta_state,
                        psi_value,
                        recall_hits,
                        recall_total,
                        known_gaps_count,
                        cross_domain_refs,
                    ),
                )
                for config in self.candidates
            ]

            # 4. argmax 选最优（Dream-RSI argmax V 选择机制，H2 无梯度）
            best_config, best_score = max(scores, key=lambda x: x[1])

            # 5. 不劣化保证：仅在严格改进时切换
            if best_score > current_score:
                self.current_config = best_config
                self.history.append(
                    {
                        "action": "switch",
                        "from_version": "previous",
                        "to_version": best_config.version,
                        "score": best_score,
                    }
                )
                return best_config
            return None

        except Exception as e:
            # 【H4 硬约束】：FAIL-OPEN，保留上一稳定版本
            self.history.append({"error": str(e), "fallback": True})
            return None
