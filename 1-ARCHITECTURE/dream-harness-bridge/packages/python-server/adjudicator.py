#!/usr/bin/env python3
"""adjudicator.py — 裁判评审层 (SPEC v1.2-rc1 §3 Layer 1)

6维评分体系 (InspireScore ACL 2025) + RFD 裁决理由 + AdjudicationResult。
在 Verdict 之后异步执行，面向训练层（不面向用户展示）。

6维评分:
  主观4维: 论证清晰度/论点编排/话题切题/情感诉求 (LLM Prompt 评分)
  客观2维: 事实真实性/逻辑有效性 (LLM + 知识库/谬误检测)

自评偏差校准 (M1):
  v1: "你是独立裁判不是辩手" Prompt 框架 + 透明声明偏差风险

FAIL-OPEN (HC1): 无 LLM 或异常时返回降级结果，不阻塞主流程。
延迟预算 (HC11): Layer 1-3 总延迟 < 10s。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.adjudicator")

# ── 6 维评分维度名称 ──────────────────────────────────────────

DIMENSIONS = [
    "clarity",             # 论证清晰度
    "arrangement",         # 论点编排
    "topic_relevance",     # 话题切题
    "emotional_appeal",    # 情感诉求
    "fact_authenticity",   # 事实真实性 (客观)
    "logical_validity",    # 逻辑有效性 (客观)
]

SUBJECTIVE_DIMS = ["clarity", "arrangement", "topic_relevance", "emotional_appeal"]
OBJECTIVE_DIMS = ["fact_authenticity", "logical_validity"]

# ── 评分 Prompt (M1: 自评偏差校准) ─────────────────────────────

ADJUDICATION_PROMPT = """你现在是独立裁判，不是辩手。你的任务是对以下辩论论点进行 6 维评分。

重要：你不是在评价自己的论点，而是在评价两个独立辩手的论点。
请保持中立，不偏向任何一方。

【正方论点】{bull_argument}
【反方论点】{bear_argument}

请对每一方分别评分（1-5 分）：
1. clarity: 论证清晰度 — 论点是否结构化（claim→warrant→impact）？
2. arrangement: 论点编排 — 论点排列是否有策略性？
3. topic_relevance: 话题切题 — 论点是否与辩题直接相关？
4. emotional_appeal: 情感诉求 — 金句是否有感染力？
5. fact_authenticity: 事实真实性 — 数据/引用是否真实准确？
6. logical_validity: 逻辑有效性 — 因果链是否成立？有无逻辑谬误？

输出 JSON: {{"bull": {{"clarity": N, "arrangement": N, "topic_relevance": N, "emotional_appeal": N, "fact_authenticity": N, "logical_validity": N}}, "bear": {{...同结构...}}, "rfd": "裁决理由", "key_clash_points": ["交锋点1", "交锋点2"]}}"""


# ── AdjudicationResult ─────────────────────────────────────────

@dataclass
class AdjudicationResult:
    """裁判评审结果 (SPEC §3.4)。

    Attributes:
        topic: 辩论话题
        bull_turn_scores: 正方逐轮评分 [{"turn": 1, "clarity": 4, ...}]
        bear_turn_scores: 反方逐轮评分
        bull_total: 正方总分 (6-30)
        bear_total: 反方总分 (6-30)
        dimension_comparison: 维度对比 {"clarity": {"bull": 4.0, "bear": 3.5}}
        winner: 胜方 "bull" | "bear" | "draw"
        rfd: Reason for Decision 裁决理由
        key_clash_points: 关键交锋点
        rebuttal_strength: 反驳力度 (附加指标)
        evidence_depth: 证据深度 (附加指标)
        timestamp: 时间戳
    """
    topic: str
    bull_turn_scores: list[dict]
    bear_turn_scores: list[dict]
    bull_total: float
    bear_total: float
    dimension_comparison: dict
    winner: str
    rfd: str
    key_clash_points: list[str]
    rebuttal_strength: dict
    evidence_depth: dict
    timestamp: str

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容的 dict。"""
        return {
            "topic": self.topic,
            "bull_turn_scores": self.bull_turn_scores,
            "bear_turn_scores": self.bear_turn_scores,
            "bull_total": self.bull_total,
            "bear_total": self.bear_total,
            "dimension_comparison": self.dimension_comparison,
            "winner": self.winner,
            "rfd": self.rfd,
            "key_clash_points": self.key_clash_points,
            "rebuttal_strength": self.rebuttal_strength,
            "evidence_depth": self.evidence_depth,
            "timestamp": self.timestamp,
        }


# ── JSON 解析 ─────────────────────────────────────────────────

def _extract_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。"""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 尝试提取第一个 JSON 对象
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _extract_argument_text(turn: dict) -> str:
    """从 Turn 提取论点文本用于评分。"""
    content = turn.get("content", {})
    if isinstance(content, dict):
        parts = []
        if content.get("thesis"):
            parts.append(f"核心论点: {content['thesis']}")
        if content.get("arguments"):
            parts.append(f"论据: {', '.join(content['arguments'])}")
        if content.get("quote"):
            parts.append(f"金句: {content['quote']}")
        return "\n".join(parts) if parts else str(content)
    return str(content)


def _determine_winner(bull_total: float, bear_total: float) -> str:
    """根据总分判定胜方。"""
    if bull_total > bear_total:
        return "bull"
    elif bear_total > bull_total:
        return "bear"
    else:
        return "draw"


# ── Adjudicator ───────────────────────────────────────────────

class Adjudicator:
    """裁判评审器 (SPEC §3 Layer 1)。

    在 Verdict 之后异步执行，生成 AdjudicationResult 供训练层使用。
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[..., str]] = None,
    ):
        """
        Args:
            llm_fn: LLM 调用函数 (prompt, max_tokens) -> str。
                None 时降级为 Verdict 兜底 (FAIL-OPEN)。
        """
        self._llm_fn = llm_fn

    def adjudicate(
        self,
        topic: str,
        transcript: list[dict],
        verdict: dict,
    ) -> AdjudicationResult:
        """执行 6 维评分 + RFD 生成。

        Args:
            topic: 辩论话题
            transcript: 辩论记录 [{speaker, round, content, persona}]
            verdict: 裁判裁决 {summary, winner, key_insights, topic_angle}

        Returns:
            AdjudicationResult

        FAIL-OPEN: 无 LLM 或异常时返回降级结果 (用 Verdict winner)。
        """
        ts = datetime.now().isoformat()

        # 分离正反方 Turn
        bull_turns = [t for t in transcript if t.get("speaker") == "bull"]
        bear_turns = [t for t in transcript if t.get("speaker") == "bear"]

        # 无 LLM → 降级
        if self._llm_fn is None:
            return self._degraded_result(topic, verdict, ts)

        try:
            # 构建评分 Prompt
            bull_text = "\n".join(
                _extract_argument_text(t) for t in bull_turns)
            bear_text = "\n".join(
                _extract_argument_text(t) for t in bear_turns)

            prompt = ADJUDICATION_PROMPT.format(
                bull_argument=bull_text,
                bear_argument=bear_text,
            )

            raw = self._call_llm(prompt)
            data = _extract_json(raw)

            if data is None:
                logger.warning("裁判评分 JSON 解析失败，降级")
                return self._degraded_result(topic, verdict, ts)

            # 提取 6 维评分
            bull_scores = data.get("bull", {})
            bear_scores = data.get("bear", {})

            # 构建 dimension_comparison
            dim_comp = {}
            for dim in DIMENSIONS:
                b_val = bull_scores.get(dim, 3)
                r_val = bear_scores.get(dim, 3)
                try:
                    b_val = int(b_val)
                    r_val = int(r_val)
                except (ValueError, TypeError):
                    b_val = 3
                    r_val = 3
                # 钳制 1-5
                b_val = max(1, min(5, b_val))
                r_val = max(1, min(5, r_val))
                dim_comp[dim] = {"bull": float(b_val), "bear": float(r_val)}

            # 计算总分
            bull_total = sum(dim_comp[d]["bull"] for d in DIMENSIONS)
            bear_total = sum(dim_comp[d]["bear"] for d in DIMENSIONS)

            # 逐轮评分（简化版：将总分分配到每轮）
            bull_turn_scores = [
                {"turn": t.get("round", i + 1), **{
                    d: int(dim_comp[d]["bull"]) for d in DIMENSIONS
                }}
                for i, t in enumerate(bull_turns)
            ]
            bear_turn_scores = [
                {"turn": t.get("round", i + 1), **{
                    d: int(dim_comp[d]["bear"]) for d in DIMENSIONS
                }}
                for i, t in enumerate(bear_turns)
            ]

            # 胜方判定
            winner = _determine_winner(bull_total, bear_total)

            # RFD
            rfd = str(data.get("rfd", ""))
            if not rfd:
                rfd = f"{'正方' if winner == 'bull' else '反方'}总分 {max(bull_total, bear_total):.0f} 领先"

            # 关键交锋点
            clash_points = data.get("key_clash_points", [])
            if not isinstance(clash_points, list):
                clash_points = []

            # 附加指标（简化版：从维度分数推导）
            rebuttal_strength = {
                "bull": int(dim_comp["logical_validity"]["bull"]),
                "bear": int(dim_comp["logical_validity"]["bear"]),
            }
            evidence_depth = {
                "bull": int(dim_comp["fact_authenticity"]["bull"]),
                "bear": int(dim_comp["fact_authenticity"]["bear"]),
            }

            return AdjudicationResult(
                topic=topic,
                bull_turn_scores=bull_turn_scores,
                bear_turn_scores=bear_turn_scores,
                bull_total=bull_total,
                bear_total=bear_total,
                dimension_comparison=dim_comp,
                winner=winner,
                rfd=rfd,
                key_clash_points=clash_points,
                rebuttal_strength=rebuttal_strength,
                evidence_depth=evidence_depth,
                timestamp=ts,
            )

        except Exception as e:
            logger.warning("裁判评审异常(FAIL-OPEN): %s", e)
            return self._degraded_result(topic, verdict, ts)

    def _degraded_result(
        self, topic: str, verdict: dict, ts: str,
    ) -> AdjudicationResult:
        """降级结果：无 LLM 或异常时使用 Verdict 兜底。"""
        verdict_winner = verdict.get("winner") or "draw"
        # 统一 winner 格式
        if verdict_winner == "bull":
            winner = "bull"
        elif verdict_winner == "bear":
            winner = "bear"
        else:
            winner = "draw"

        # 降级评分：各维 3 分 (中性)
        dim_comp = {d: {"bull": 3.0, "bear": 3.0} for d in DIMENSIONS}
        total = sum(3.0 for _ in DIMENSIONS)  # 18.0

        return AdjudicationResult(
            topic=topic,
            bull_turn_scores=[],
            bear_turn_scores=[],
            bull_total=total,
            bear_total=total,
            dimension_comparison=dim_comp,
            winner=winner,
            rfd=f"[降级] 使用 Verdict 结果: {verdict.get('summary', '')}",
            key_clash_points=verdict.get("key_insights", []),
            rebuttal_strength={"bull": 3, "bear": 3},
            evidence_depth={"bull": 3, "bear": 3},
            timestamp=ts,
        )

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM（同步），处理两种签名兼容。"""
        try:
            return self._llm_fn(prompt, 600)
        except TypeError:
            return self._llm_fn(prompt)
