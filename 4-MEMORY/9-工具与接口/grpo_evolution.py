"""TB5 PolicySelectLoop（GRPO 借喻）— SPEC-L0-AGENT-TRAIN-BASE v0.1 §5

冻结 LLM 权重，只调策略输出格式（【H2 硬约束】：无 .train()/.backward()/.backprop，
仅对候选配置做 argmax 选择）。
依赖 TB1 classify_drift + TB2 BetaState + TB3 AlphaPareto + TB4 regime gate。
P4 回执消费（DOMAIN-DISCOVERY §4.5.4）：`p4_receipts` → v_adjusted（alpha 加权）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from cognitive_interfaces import BetaState
from drift_detector import classify_drift
from regime_gate import ThompsonSamplingRegimeGate
from training_reward import (
    PNL_NEUTRAL,
    V_ALPHA,
    compute_reward,
    pareto_score,
    pnl_delta_score_from_receipt,
)

# P4 回执 alpha 加权系数 / pnl_delta_score 中性值收敛至 training_reward.py，
# 本文件不再重复定义（避免同源常量漂移，锚点③收敛动作）。


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
        2. 用 TB3 AlphaPareto 算七维奖励
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

    @staticmethod
    def _validated_pnl_mean(p4_receipts: Optional[List[dict]]) -> Tuple[int, float]:
        """P4 回执筛选 + 归一化 pnl 均值（DOMAIN-DISCOVERY §4.5.4）。

        仅接受含非空 `trace_id` 且 `counterfactual_result` 可解析的回执；
        其余（非 dict / 缺 trace_id / 字段坏 / 非 list 容器）一律丢弃（FAIL-OPEN）。
        无有效回执 → (0, 0.5) 中性，v_adjusted 不偏移。
        """
        if not isinstance(p4_receipts, list):
            return 0, PNL_NEUTRAL

        scores: List[float] = []
        for receipt in p4_receipts:
            if not isinstance(receipt, dict):
                continue
            trace_id = receipt.get("trace_id")
            if not isinstance(trace_id, str) or not trace_id.strip():
                continue
            cf = receipt.get("counterfactual_result")
            if not isinstance(cf, dict):
                continue
            scores.append(pnl_delta_score_from_receipt(cf))

        if not scores:
            return 0, PNL_NEUTRAL
        return len(scores), sum(scores) / len(scores)

    def evolve_step(
        self,
        beta_state: BetaState,
        psi_value: float,
        recall_hits: int,
        recall_total: int,
        known_gaps_count: int,
        cross_domain_refs: int,
        p4_receipts: Optional[List[dict]] = None,
        _principal: Optional[dict] = None,  # D2：Mandate 感知，port 层硬门禁消费
    ) -> Optional[StrategyConfig]:
        """执行一轮策略进化。

        Args:
            p4_receipts: P4 沙箱验证回执列表；有效回执按 alpha 加权修正 V，
                无回执时 v_adjusted == pareto_score（零行为变化）。

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

            # 3. P4 回执 alpha 加权（全局偏移量，不影响候选间相对排序）
            p4_validated, p4_pnl_mean = self._validated_pnl_mean(p4_receipts)
            v_offset = V_ALPHA * (p4_pnl_mean - PNL_NEUTRAL)

            # 4. 候选策略评估（含当前策略，Dream-RSI 不劣化保证）
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

            # 5. argmax 选最优（Dream-RSI argmax V 选择机制，H2 无梯度）
            best_config, best_score = max(scores, key=lambda x: x[1])
            v_adjusted = best_score + v_offset

            # 6. 不劣化保证：仅在严格改进时切换（v_offset 为全局常量，不改变相对排序）
            if best_score > current_score:
                self.current_config = best_config
                self.history.append(
                    {
                        "action": "switch",
                        "from_version": "previous",
                        "to_version": best_config.version,
                        "score": best_score,
                        "v_adjusted": v_adjusted,
                        "p4_validated": p4_validated,
                        "p4_pnl_mean": p4_pnl_mean,
                    }
                )
                return best_config
            return None

        except Exception as e:
            # 【H4 硬约束】：FAIL-OPEN，保留上一稳定版本
            self.history.append({"error": str(e), "fallback": True})
            return None
