#!/usr/bin/env python3
"""debate_trainer.py — 算法训练层 (SPEC v1.2-rc1 §5 Layer 3)

三种训练方法 (Phase 1, 0-50场):
  1. 贝叶斯策略权重: P(S wins|T) ~ Beta(α,β), 每场更新 (§5.2)
  2. Persona Elo: 初始1200, 动态K=max(16,32-n/10), draw各得0.5 (§5.3+m2)
  3. CBR 案例检索: cosine similarity Top-K (§5.4+m3)

§5.6 参数消费闭环:
  - 贝叶斯 → build_system_prompt 策略推荐
  - Elo → match_personas ε-贪心选择
  - CBR → _inject_debate_memories 历史经验注入

§5.7 冷启动退化:
  0-5场: 纯Persona+SKILL无训练增强
  5-20场: 弱增强标注低置信度
  20-50场: 正常增强
  50+场: 成熟期

FAIL-OPEN (HC1): 无数据或异常时不崩溃
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.trainer")


# ── 默认编码器 (生产环境用 sentence-transformers, 测试用 hash) ──

def _default_encode(text: str, dim: int = 384) -> list[float]:
    """默认 hash 编码器 (生产环境替换为 all-MiniLM-L6-v2)。"""
    vec = [0.0] * dim
    for i, ch in enumerate(text):
        h = int(hashlib.md5(f"{ch}_{i}".encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的 cosine 相似度。"""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _classify_topic_type(topic: str) -> str:
    """§5.9 m4: 话题类型提取 (关键词匹配 + LLM 兜底)。"""
    topic_lower = topic.lower()
    if any(kw in topic_lower for kw in ["btc", "比特币", "crypto", "加密", "以太坊", "eth"]):
        return "crypto"
    if any(kw in topic_lower for kw in ["ai", "人工智能", "大模型", "llm", "agi"]):
        return "ai"
    if any(kw in topic_lower for kw in ["美股", "股票", "宏观", "利率", "通胀"]):
        return "macro"
    return "general"


# ── BayesianStrategyWeights (§5.2) ───────────────────────────

class BayesianStrategyWeights:
    """贝叶斯策略权重: P(S wins|T) ~ Beta(α,β)。

    每场辩论后更新:
      - 策略 S 被使用且获胜 → α += 1
      - 策略 S 被使用且失败 → β += 1
      - Posterior: P(S wins|T) = α / (α + β)

    冷启动 (§5.7): 0-5场 Beta(1,1) 均匀分布 → 策略随机
    """

    def __init__(self):
        # {topic_type: {strategy: [alpha, beta]}}
        self._weights: dict[str, dict[str, list[float]]] = {}

    def _get_entry(self, strategy: str, topic_type: str) -> list[float]:
        """获取或创建 Beta 分布参数 [α, β]。"""
        if topic_type not in self._weights:
            self._weights[topic_type] = {}
        if strategy not in self._weights[topic_type]:
            self._weights[topic_type][strategy] = [1.0, 1.0]  # Beta(1,1) 均匀先验
        return self._weights[topic_type][strategy]

    def update(self, strategy: str, topic_type: str, won: bool) -> None:
        """更新策略权重。"""
        alpha, beta = self._get_entry(strategy, topic_type)
        if won:
            alpha += 1
        else:
            beta += 1
        self._weights[topic_type][strategy] = [alpha, beta]

    def get_win_prob(self, strategy: str, topic_type: str) -> float:
        """获取策略胜率 P(S wins|T) = α / (α+β)。"""
        alpha, beta = self._get_entry(strategy, topic_type)
        return alpha / (alpha + beta)

    def get_top_strategies(
        self, topic_type: str, top_k: int = 3,
    ) -> list[tuple[str, float]]:
        """获取胜率最高的策略排序。"""
        strategies = self._weights.get(topic_type, {})
        if not strategies:
            return []
        ranked = sorted(
            strategies.items(),
            key=lambda x: x[1][0] / (x[1][0] + x[1][1]),
            reverse=True,
        )
        return [(s, a / (a + b)) for s, (a, b) in ranked[:top_k]]


# ── PersonaElo (§5.3 + m2) ────────────────────────────────────

class PersonaElo:
    """Persona Elo 评分系统。

    初始 Elo = 1200
    动态 K = max(16, 32 - debates_count / 10)
    Draw: 双方各得 0.5 分
    """

    INITIAL_ELO = 1200.0

    def __init__(self):
        # {persona_name: {"elo": float, "debates": int}}
        self._registry: dict[str, dict] = {}

    def _get_entry(self, persona: str) -> dict:
        """获取或创建 Persona 条目。"""
        if persona not in self._registry:
            self._registry[persona] = {"elo": self.INITIAL_ELO, "debates": 0}
        return self._registry[persona]

    def get_elo(self, persona: str) -> float:
        """获取 Persona Elo。"""
        return self._get_entry(persona)["elo"]

    def get_k_factor(self, persona: str) -> int:
        """动态 K = max(16, 32 - n/10)。"""
        n = self._get_entry(persona)["debates"]
        return max(16, int(32 - n / 10))

    def update(
        self,
        bull_persona: str,
        bear_persona: str,
        winner: str,
    ) -> None:
        """更新双方 Elo。

        Args:
            winner: "bull" | "bear" | "draw"
        """
        bull = self._get_entry(bull_persona)
        bear = self._get_entry(bear_persona)
        bull_elo = bull["elo"]
        bear_elo = bear["elo"]

        # 期望胜率
        expected_bull = 1 / (1 + 10 ** ((bear_elo - bull_elo) / 400))

        # 实际得分 (m2: draw 各得 0.5)
        if winner == "bull":
            bull_score, bear_score = 1.0, 0.0
        elif winner == "bear":
            bull_score, bear_score = 0.0, 1.0
        else:  # draw
            bull_score, bear_score = 0.5, 0.5

        # K 因子取双方中较小的 (更保守)
        k = min(self.get_k_factor(bull_persona),
                self.get_k_factor(bear_persona))

        # 更新 Elo
        bull["elo"] = bull_elo + k * (bull_score - expected_bull)
        bear["elo"] = bear_elo + k * (bear_score - (1 - expected_bull))
        bull["debates"] += 1
        bear["debates"] += 1


# ── CBRCaseLibrary (§5.4 + m3) ────────────────────────────────

@dataclass
class CBRCse:
    """CBR 案例结构。"""
    case_id: str
    topic: str
    topic_type: str
    topic_embedding: list[float]
    strategies_used: list[str]
    winner: str
    bull_score: float
    bear_score: float
    effective_dimensions: list[str]
    effective_strategies: list[str]
    adaptation_hints: list[str]
    created_at: float = 0.0


class CBRCaseLibrary:
    """CBR 案例检索库。

    使用 cosine similarity 检索 Top-K 相似案例。
    冷启动 (§5.7): <5 案例时跳过检索。
    Embedding (m3): all-MiniLM-L6-v2 384维 (生产环境)，
                    hash编码 (测试环境)。
    """

    COLD_START_THRESHOLD = 5  # <5 案例时跳过检索

    def __init__(self, encode_fn: Callable[[str], list[float]] = None):
        """
        Args:
            encode_fn: 话题编码函数 topic -> list[float]。
                None 时用默认 hash 编码器。
        """
        self._encode_fn = encode_fn or _default_encode
        self._cases: list[CBRCse] = []

    def add_case(
        self,
        topic: str,
        topic_type: str,
        strategies_used: list[str],
        winner: str,
        bull_score: float,
        bear_score: float,
        effective_dimensions: list[str],
        effective_strategies: list[str],
        adaptation_hints: list[str],
    ) -> str | None:
        """案例入库。"""
        case_id = f"CBR-{int(time.time() * 1000)}-{hash(topic) % 10000}"
        embedding = self._encode_fn(topic)
        case = CBRCse(
            case_id=case_id,
            topic=topic,
            topic_type=topic_type,
            topic_embedding=embedding,
            strategies_used=strategies_used,
            winner=winner,
            bull_score=bull_score,
            bear_score=bear_score,
            effective_dimensions=effective_dimensions,
            effective_strategies=effective_strategies,
            adaptation_hints=adaptation_hints,
            created_at=time.time(),
        )
        self._cases.append(case)
        return case_id

    def retrieve(
        self, topic: str, top_k: int = 5,
    ) -> list[dict]:
        """检索相似案例 (cosine similarity Top-K)。

        冷启动 (§5.7): <5 案例时返回空列表。
        """
        if len(self._cases) < self.COLD_START_THRESHOLD:
            return []

        query_embedding = self._encode_fn(topic)

        # 计算相似度
        scored = []
        for case in self._cases:
            sim = _cosine_similarity(query_embedding, case.topic_embedding)
            scored.append((sim, case))

        # 按相似度降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 取 Top-K
        results = []
        for sim, case in scored[:top_k]:
            results.append({
                "case_id": case.case_id,
                "topic": case.topic,
                "topic_type": case.topic_type,
                "strategies_used": case.strategies_used,
                "winner": case.winner,
                "bull_score": case.bull_score,
                "bear_score": case.bear_score,
                "effective_dimensions": case.effective_dimensions,
                "effective_strategies": case.effective_strategies,
                "adaptation_hints": case.adaptation_hints,
                "similarity": sim,
            })
        return results

    def case_count(self) -> int:
        """案例总数。"""
        return len(self._cases)


# ── DebateTrainer ─────────────────────────────────────────────

class DebateTrainer:
    """算法训练器 (SPEC §5 Layer 3)。

    协调三种训练方法的更新:
      1. 贝叶斯策略权重更新
      2. Persona Elo 更新
      3. CBR 案例入库
    """

    def __init__(
        self,
        encode_fn: Callable[[str], list[float]] = None,
        cognitive_adapter: Any = None,
    ):
        """
        Args:
            encode_fn: 话题编码函数 (CBR 用)。
            cognitive_adapter: 认知适配器 (可选, verify 用)。
        """
        self.bayesian = BayesianStrategyWeights()
        self.elo = PersonaElo()
        self.cbr = CBRCaseLibrary(encode_fn=encode_fn)
        self._cognitive = cognitive_adapter
        self._debate_count = 0

    def train(
        self,
        adjudication_result: Any,
        reflection_report: Any,
        bull_persona: str,
        bear_persona: str,
    ) -> dict:
        """执行训练更新。

        Args:
            adjudication_result: AdjudicationResult (Layer 1)
            reflection_report: ReflectionReport (Layer 2)
            bull_persona: 正方 Persona 名称
            bear_persona: 反方 Persona 名称

        Returns:
            {"bayesian_updated": bool, "elo_updated": bool, "cbr_ingested": bool}

        FAIL-OPEN: 参数为 None 或异常时返回 updated=False。
        """
        result = {
            "bayesian_updated": False,
            "elo_updated": False,
            "cbr_ingested": False,
        }

        if adjudication_result is None or reflection_report is None:
            return result

        try:
            # 提取数据
            topic = getattr(adjudication_result, "topic", "")
            winner = getattr(adjudication_result, "winner", "draw")
            bull_total = getattr(adjudication_result, "bull_total", 18.0)
            bear_total = getattr(adjudication_result, "bear_total", 18.0)
            strategy_tags = getattr(reflection_report, "strategy_tags", [])
            effective_dims = []
            dim_comp = getattr(adjudication_result, "dimension_comparison", {})
            for dim, scores in dim_comp.items():
                if isinstance(scores, dict):
                    bull_score = scores.get("bull", 0)
                    if bull_score >= 4.0:
                        effective_dims.append(dim)

            topic_type = _classify_topic_type(topic)
            bull_won = winner == "bull"
            bear_won = winner == "bear"

            # 1. 贝叶斯策略权重更新
            for tag in strategy_tags:
                # 策略被使用 → 根据该方是否获胜更新
                # 简化: 所有策略按胜方更新
                won = bull_won  # 正方策略按正方结果, 反方策略按反方结果
                self.bayesian.update(tag, topic_type, won=won)
            result["bayesian_updated"] = True

            # 2. Persona Elo 更新
            self.elo.update(bull_persona, bear_persona, winner)
            result["elo_updated"] = True

            # 3. CBR 案例入库
            effective_strategies = []
            strat_analysis = getattr(reflection_report, "strategy_analysis", {})
            for strat, analysis in strat_analysis.items():
                if isinstance(analysis, dict) and analysis.get("effect", 0) >= 4:
                    effective_strategies.append(strat)

            adaptation_hints = []
            gaps = getattr(reflection_report, "gaps", {})
            if isinstance(gaps, dict):
                adaptation_hints = gaps.get("evidence_gaps", [])

            self.cbr.add_case(
                topic=topic,
                topic_type=topic_type,
                strategies_used=strategy_tags,
                winner=winner,
                bull_score=bull_total,
                bear_score=bear_total,
                effective_dimensions=effective_dims,
                effective_strategies=effective_strategies,
                adaptation_hints=adaptation_hints,
            )
            result["cbr_ingested"] = True

            self._debate_count += 1

            # 4. 认知系统 verify (可选)
            memory_id = getattr(reflection_report, "memory_id", None)
            if self._cognitive is not None and memory_id:
                try:
                    # verify 策略预测是否正确
                    self._cognitive.verify(
                        memory_id=memory_id,
                        success=bull_won or winner == "draw",
                    )
                except Exception as e:
                    logger.warning("trainer verify 失败(FAIL-OPEN): %s", e)

        except Exception as e:
            logger.warning("训练更新异常(FAIL-OPEN): %s", e)

        return result

    def get_cold_start_phase(self) -> str:
        """§5.7 冷启动阶段判定。

        Returns:
            "cold_start" (0-5场)
            "weak_enhancement" (5-20场)
            "normal" (20-50场)
            "mature" (50+场)
        """
        n = self._debate_count
        if n < 5:
            return "cold_start"
        elif n < 20:
            return "weak_enhancement"
        elif n < 50:
            return "normal"
        else:
            return "mature"
