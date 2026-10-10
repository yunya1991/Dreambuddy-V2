#!/usr/bin/env python3
"""debate_dpo.py — T-DPO 偏好学习层 (SPEC v1.2-rc1 §9.2.2 + §9.3 Phase 3)

T-DPO (Tree-structured DPO, D&R arXiv 2506.03541, BIT 2025):
  辩论日志 → 构建偏好树 → 层次化训练
  - 每轮辩论的 (response, feedback) 对组成树节点
  - 胜出的分支作为正样本，失败的分支作为负样本

Self-Play DPO (arXiv 2409.16636): 概率奖励而非离散 win/loss
  reward = log(P_win / P_lose)

Trae 驱动适配 (§9.3 Phase 3 备选路径):
  用偏好数据微调 Persona 的 strategy 权重（非 LLM 微调）。
  因 Trae 驱动的 LLM 不可微，DPO 的梯度更新以"margin 加权的贝叶斯更新"近似实现。

触发条件 (§5.5): 累积 100+ 场辩论后触发。
FAIL-OPEN (HC1): 无数据/异常时不崩溃，返回 trained=False。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("debate.dpo")

# 有意义的 margin 下限（避免噪声偏好对）
_MIN_MARGIN = 1e-6


# ── 概率奖励 (§9.2.1 Self-Play DPO) ───────────────────────────

def compute_reward_margin(
    chosen_score: float, rejected_score: float,
) -> float:
    """计算概率奖励 margin = log(chosen / rejected)。

    Self-Play DPO 用 judge 的概率奖励而非离散 win/loss。
    数值稳定性：分数加 1e-6 避免除零/取零对数。
    """
    c = max(float(chosen_score), 0.0) + _MIN_MARGIN
    r = max(float(rejected_score), 0.0) + _MIN_MARGIN
    return math.log(c / r)


# ── 偏好树节点 (§9.2.2) ───────────────────────────────────────

@dataclass
class PreferenceNode:
    """偏好树节点 = 一轮辩论的 (response, feedback) 对。

    Attributes:
        turn: 轮次
        side: 该轮节点所属方 'bull' | 'bear'
        strategies: 该轮使用的策略标签 (Layer A 生成时标签)
        score: 该轮综合评分
        chosen: 是否属于胜出分支
        feedback: 反馈 (RFD/评分摘要)
    """
    turn: int
    side: str
    strategies: list[str]
    score: float
    chosen: bool
    feedback: str = ""


@dataclass
class PreferencePair:
    """偏好对 (chosen, rejected, margin)。

    Attributes:
        prompt: 上下文 (话题)
        chosen: 胜出策略集
        rejected: 失败策略集
        margin: 概率奖励差 log(chosen/rejected)
        chosen_score: 胜出方评分
        rejected_score: 失败方评分
    """
    prompt: str
    chosen: list[str]
    rejected: list[str]
    margin: float
    chosen_score: float
    rejected_score: float


# ── 偏好树构建 (§9.2.2) ───────────────────────────────────────

class PreferenceTreeBuilder:
    """辩论日志 → 偏好树 → 偏好对。"""

    # 逐轮评分使用的维度
    _SCORE_DIMS = ["clarity", "fact_authenticity", "logical_validity"]

    def build_preference_tree(
        self,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> list[PreferenceNode]:
        """从辩论日志 + 评审结果构建偏好树。

        每轮生成两个节点 (bull + bear)，按该轮评分标记 chosen。
        胜出方节点 chosen=True，失败方 chosen=False。
        """
        if not transcript or adjudication_result is None:
            return []

        bull_by_turn = self._index_turn_scores(
            getattr(adjudication_result, "bull_turn_scores", []))
        bear_by_turn = self._index_turn_scores(
            getattr(adjudication_result, "bear_turn_scores", []))

        nodes: list[PreferenceNode] = []
        for t in transcript:
            side = t.get("speaker")
            if side not in ("bull", "bear"):
                continue
            turn_no = t.get("round", 0)
            content = t.get("content", {}) or {}
            strategies = self._extract_turn_strategies(content)

            # 该轮评分
            if side == "bull":
                score = bull_by_turn.get(turn_no, 0.0)
                opp_score = bear_by_turn.get(turn_no, 0.0)
            else:
                score = bear_by_turn.get(turn_no, 0.0)
                opp_score = bull_by_turn.get(turn_no, 0.0)

            nodes.append(PreferenceNode(
                turn=turn_no,
                side=side,
                strategies=strategies,
                score=score,
                chosen=score >= opp_score,
                feedback="",
            ))
        return nodes

    def extract_preference_pairs(
        self,
        tree: list[PreferenceNode],
    ) -> list[PreferencePair]:
        """从偏好树提取逐轮偏好对。

        同一轮内：chosen 节点的策略 → chosen，另一方策略 → rejected。
        """
        # 按轮分组
        by_turn: dict[int, list[PreferenceNode]] = {}
        for node in tree:
            by_turn.setdefault(node.turn, []).append(node)

        pairs: list[PreferencePair] = []
        for turn, nodes in sorted(by_turn.items()):
            if len(nodes) < 2:
                continue
            chosen_nodes = [n for n in nodes if n.chosen]
            rejected_nodes = [n for n in nodes if not n.chosen]
            if not chosen_nodes or not rejected_nodes:
                # 同轮并列 → 跳过（无偏好信号）
                continue

            c = chosen_nodes[0]
            r = rejected_nodes[0]
            # 仅当双方都有策略标签时才构成有效偏好对
            if not c.strategies or not r.strategies:
                continue

            margin = compute_reward_margin(c.score, r.score)
            if abs(margin) < _MIN_MARGIN:
                continue

            pairs.append(PreferencePair(
                prompt="",
                chosen=list(c.strategies),
                rejected=list(r.strategies),
                margin=margin,
                chosen_score=c.score,
                rejected_score=r.score,
            ))
        return pairs

    # ── 内部工具 ──────────────────────────────────────────────

    @classmethod
    def _index_turn_scores(cls, turn_scores: list[dict]) -> dict[int, float]:
        """将逐轮评分索引为 {turn: 综合分}。"""
        out: dict[int, float] = {}
        for item in turn_scores or []:
            turn = item.get("turn", 0)
            vals = [float(item[d]) for d in cls._SCORE_DIMS if d in item]
            if vals:
                out[turn] = sum(vals) / len(vals)
        return out

    @staticmethod
    def _extract_turn_strategies(content: dict) -> list[str]:
        """从 Turn.content 提取策略标签 (Layer A 生成时标签)。"""
        strat = content.get("strategy") if isinstance(content, dict) else None
        if isinstance(strat, str) and strat:
            return [strat]
        if isinstance(strat, list):
            return [s for s in strat if isinstance(s, str)]
        return []


# ── DPO 训练器 (§9.3 Phase 3) ─────────────────────────────────

class DebateDPOTrainer:
    """T-DPO 偏好学习器。

    因 Trae 驱动的 LLM 不可微，DPO 的梯度更新以
    "margin 加权的贝叶斯更新"近似实现：
      - chosen 策略: α += margin_weight
      - rejected 策略: β += margin_weight
    其中 margin_weight ∝ 概率奖励差 (Self-Play DPO 的概率奖励)。
    """

    MIN_DEBATES = 100  # §5.5: 累积 100+ 场后触发

    def __init__(self):
        self._last_pairs = 0

    def should_trigger(self, debate_count: int) -> bool:
        """是否满足 DPO 触发条件 (累积 100+ 场)。"""
        return debate_count >= self.MIN_DEBATES

    def train(
        self,
        adjudication_result: Any,
        transcript: list[dict],
        bayesian: Any,
        topic_type: str,
        debate_count: int,
    ) -> dict:
        """执行 DPO 偏好微调。

        Args:
            adjudication_result: AdjudicationResult (Layer 1)
            transcript: 辩论记录 (含逐轮 strategy 标签)
            bayesian: BayesianStrategyWeights (被微调对象)
            topic_type: 话题类型
            debate_count: 累计辩论场次

        Returns:
            {"trained": bool, "pairs": int, "updates": int}

        FAIL-OPEN: 参数缺失/未达阈值/异常 → trained=False。
        """
        result = {"trained": False, "pairs": 0, "updates": 0}

        if adjudication_result is None or not transcript or bayesian is None:
            return result
        if not self.should_trigger(debate_count):
            return result

        try:
            builder = PreferenceTreeBuilder()
            tree = builder.build_preference_tree(transcript, adjudication_result)
            pairs = builder.extract_preference_pairs(tree)

            for pair in pairs:
                # margin 加权：概率奖励越大，更新越强 (带上下限防爆炸)
                weight = min(abs(pair.margin), 2.0)
                if weight < _MIN_MARGIN:
                    continue
                for strat in pair.chosen:
                    bayesian.update(strat, topic_type, won=True)
                    self._soft_update(bayesian, strat, topic_type,
                                      delta_alpha=weight)
                for strat in pair.rejected:
                    self._soft_update(bayesian, strat, topic_type,
                                      delta_beta=weight)
                result["updates"] += 1

            result["pairs"] = len(pairs)
            result["trained"] = len(pairs) > 0
            self._last_pairs = len(pairs)

        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning("DPO 偏好训练异常(FAIL-OPEN): %s", e)

        return result

    @staticmethod
    def _soft_update(
        bayesian: Any,
        strategy: str,
        topic_type: str,
        delta_alpha: float = 0.0,
        delta_beta: float = 0.0,
    ) -> None:
        """margin 加权的软更新：直接调整 Beta 参数。"""
        entry = bayesian._get_entry(strategy, topic_type)  # noqa: SLF001
        entry[0] += delta_alpha
        entry[1] += delta_beta