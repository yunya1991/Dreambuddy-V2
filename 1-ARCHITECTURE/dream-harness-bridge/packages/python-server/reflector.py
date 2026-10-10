#!/usr/bin/env python3
"""reflector.py — 赛后反思层 (SPEC v1.2-rc1 §4 Layer 2)

5步反思循环 (SuperDebate Guide Practice Loop):
  Step 1: 复盘 (Review) — 逐轮回放 + 关键转折 + RFD
  Step 2: 分析 (Analyze) — 策略效果 + Persona 表现 + 证据分析
  Step 3: 缺口识别 (Gap) — 证据缺口 + 论点遗漏 + 策略空白
  Step 4: 改进建议 (Refinement) — 推荐策略 + Persona 建议
  Step 5: 存储 (Store) — 认知系统 record + 策略标签

§4.0 策略提取 (前置):
  Layer A: 生成时标签 (Persona 生成论点时声明策略)
  Layer B: 回溯标签 (LLM 从论点文本识别策略) — 本实现用 Layer B

HC7: 策略标签前置 — 无策略标签时跳过策略分析
HC1: FAIL-OPEN — 无 LLM 或异常时返回降级结果
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.reflector")

# ── 策略标签清单 (§4.0) ───────────────────────────────────────

ALL_STRATEGY_TAGS = [
    "definition-lock",          # 定义锁定
    "preemptive-refutation",     # 预防性反驳
    "evidence-heavy",            # 证据密集
    "counterplan",               # 替代方案
    "disadvantage",              # 劣势论证
    "value-flip",                # 价值翻转
    "burden-delay",              # 拖延举证
    "kritik",                     # 批判论证
    # 正方专属
    "stop-counterplan",          # 反方案应对
    "burden-of-proof",           # 举证责任
    # 反方专属
    "definition-attack",        # 定义攻击
    "counter-example",          # 反例构造
]

# ── 策略提取 Prompt (§4.0 Layer B) ─────────────────────────────

STRATEGY_EXTRACT_PROMPT = """分析以下辩论论点，识别使用了哪些辩论策略（可多选）：

策略清单：
- definition-lock: 定义锁定（选择对己方有利的定义）
- preemptive-refutation: 预防性反驳（预判对方攻击并提前回应）
- evidence-heavy: 证据密集（多层证据支撑）
- counterplan: 替代方案（提出反方案的替代方案）
- disadvantage: 劣势论证（证明对方方案带来负面后果）
- value-flip: 价值翻转（将对方价值翻转为支持己方）
- burden-delay: 拖延举证（质疑对方证据充分性）
- kritik: 批判论证（攻击对方底层假设）

【正方论点】{bull_thesis}
【正方论据】{bull_arguments}

【反方论点】{bear_thesis}
【反方论据】{bear_arguments}

输出 JSON: {{"bull_strategies": ["evidence-heavy", ...], "bear_strategies": ["counter-example", ...], "confidence": 0.85}}"""

# ── 反思 Prompt ───────────────────────────────────────────────

REFLECTION_PROMPT = """你是赛后反思助手。请对以下辩论进行5步反思分析。

【辩题】{topic}
【裁判评分】正方总分 {bull_total}, 反方总分 {bear_total}, 胜方 {winner}
【RFD】{rfd}
【策略标签】正方: {bull_strategies}, 反方: {bear_strategies}
【关键交锋点】{clash_points}

请输出 JSON:
{{
  "review": {{"turn_points": [{{"turn": N, "bull_score": X, "bear_score": X}}], "key_pivot": "转折点", "rfd_summary": "RFD摘要"}},
  "strategy_analysis": {{"策略名": {{"used_by": "bull/bear", "effect": 1-5}}, ...}},
  "gaps": {{"evidence_gaps": [...], "dropped_args": [...], "unused_tactics": [...]}},
  "recommendations": ["改进建议1", ...],
  "persona_suggestions": {{"bull": "...", "bear": "..."}}
}}"""


# ── ReflectionReport ──────────────────────────────────────────

@dataclass
class ReflectionReport:
    """赛后反思报告 (SPEC §4.2)。

    Attributes:
        topic: 辩论话题
        review: Step 1 复盘 {turn_points, key_pivot, rfd_summary}
        strategy_analysis: Step 2 策略效果分析
        persona_analysis: Step 2 Persona 表现
        evidence_analysis: Step 2 证据分析
        gaps: Step 3 缺口 {evidence_gaps, dropped_args, unused_tactics}
        recommendations: Step 4 改进建议
        strategy_tags: 策略标签列表
        persona_suggestions: Step 4 Persona 建议
        memory_id: Step 5 认知系统 memory_id
        timestamp: 时间戳
    """
    topic: str
    review: dict
    strategy_analysis: dict
    persona_analysis: dict
    evidence_analysis: dict
    gaps: dict
    recommendations: list[str]
    strategy_tags: list[str]
    persona_suggestions: dict
    memory_id: str | None
    timestamp: str

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容的 dict。"""
        return {
            "topic": self.topic,
            "review": self.review,
            "strategy_analysis": self.strategy_analysis,
            "persona_analysis": self.persona_analysis,
            "evidence_analysis": self.evidence_analysis,
            "gaps": self.gaps,
            "recommendations": self.recommendations,
            "strategy_tags": self.strategy_tags,
            "persona_suggestions": self.persona_suggestions,
            "memory_id": self.memory_id,
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
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _extract_argument_text(turn: dict) -> str:
    """从 Turn 提取论点文本。"""
    content = turn.get("content", {})
    if isinstance(content, dict):
        return str(content.get("thesis", "")) + " " + str(content.get("arguments", []))
    return str(content)


# ── Reflector ─────────────────────────────────────────────────

class Reflector:
    """赛后反思器 (SPEC §4 Layer 2)。

    在 Adjudication 之后执行，生成 ReflectionReport 供训练层使用。
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[..., str]] = None,
        cognitive_adapter: Optional[Any] = None,
    ):
        """
        Args:
            llm_fn: LLM 调用函数 (prompt, max_tokens) -> str。
                None 时降级 (FAIL-OPEN)。
            cognitive_adapter: 认知适配器 (recall/record/verify)。
                None 时跳过 record (FAIL-OPEN)。
        """
        self._llm_fn = llm_fn
        self._cognitive = cognitive_adapter

    def extract_strategies(self, transcript: list[dict]) -> dict:
        """§4.0 策略提取 (Layer B 回溯标签)。

        从 transcript 论点文本中识别使用的辩论策略。

        Returns:
            {"bull_strategies": [...], "bear_strategies": [...], "confidence": float}
            无 LLM 时返回空策略 (HC7: 策略标签前置)。
        """
        if self._llm_fn is None:
            return {"bull_strategies": [], "bear_strategies": [], "confidence": 0.0}

        try:
            bull_turns = [t for t in transcript if t.get("speaker") == "bull"]
            bear_turns = [t for t in transcript if t.get("speaker") == "bear"]

            bull_text = _extract_argument_text(bull_turns[0]) if bull_turns else ""
            bear_text = _extract_argument_text(bear_turns[0]) if bear_turns else ""

            # 拆分 thesis 和 arguments
            bull_thesis = bull_text.split()[0] if bull_text else ""
            bull_args = bull_text
            bear_thesis = bear_text.split()[0] if bear_text else ""
            bear_args = bear_text

            prompt = STRATEGY_EXTRACT_PROMPT.format(
                bull_thesis=bull_thesis,
                bull_arguments=bull_args,
                bear_thesis=bear_thesis,
                bear_arguments=bear_args,
            )

            raw = self._call_llm(prompt)
            data = _extract_json(raw)

            if data is None:
                return {"bull_strategies": [], "bear_strategies": [], "confidence": 0.0}

            bull_strats = data.get("bull_strategies", [])
            bear_strats = data.get("bear_strategies", [])
            conf = float(data.get("confidence", 0.5))

            return {
                "bull_strategies": bull_strats if isinstance(bull_strats, list) else [],
                "bear_strategies": bear_strats if isinstance(bear_strats, list) else [],
                "confidence": conf,
            }

        except Exception as e:
            logger.warning("策略提取异常(FAIL-OPEN): %s", e)
            return {"bull_strategies": [], "bear_strategies": [], "confidence": 0.0}

    def reflect(
        self,
        topic: str,
        transcript: list[dict],
        adjudication_result: Any,
    ) -> ReflectionReport:
        """执行 5 步反思循环。

        Args:
            topic: 辩论话题
            transcript: 辩论记录
            adjudication_result: AdjudicationResult (Layer 1 产出)

        Returns:
            ReflectionReport

        FAIL-OPEN: 无 LLM 或异常时返回降级结果。
        """
        ts = datetime.now().isoformat()

        # HC7: 策略标签前置 — 先提取策略
        strategies = self.extract_strategies(transcript)
        strategy_tags = list(set(
            strategies.get("bull_strategies", []) +
            strategies.get("bear_strategies", [])
        ))

        # 无 LLM → 降级
        if self._llm_fn is None:
            return self._degraded_report(topic, adjudication_result, ts, strategy_tags)

        try:
            # 构建反思 Prompt
            bull_total = getattr(adjudication_result, "bull_total", 18.0)
            bear_total = getattr(adjudication_result, "bear_total", 18.0)
            winner = getattr(adjudication_result, "winner", "draw")
            rfd = getattr(adjudication_result, "rfd", "")
            clash = getattr(adjudication_result, "key_clash_points", [])

            prompt = REFLECTION_PROMPT.format(
                topic=topic,
                bull_total=bull_total,
                bear_total=bear_total,
                winner=winner,
                rfd=rfd,
                bull_strategies=strategies.get("bull_strategies", []),
                bear_strategies=strategies.get("bear_strategies", []),
                clash_points=clash,
            )

            raw = self._call_llm(prompt)
            data = _extract_json(raw)

            if data is None:
                logger.warning("反思 JSON 解析失败，降级")
                return self._degraded_report(topic, adjudication_result, ts, strategy_tags)

            # Step 1: 复盘
            review = data.get("review", {})
            if not isinstance(review, dict):
                review = {}

            # Step 2: 分析
            strategy_analysis = data.get("strategy_analysis", {})
            if not isinstance(strategy_analysis, dict):
                strategy_analysis = {}

            # HC7: 无策略标签时跳过策略分析
            if not strategy_tags:
                strategy_analysis = {}

            # 从 transcript 提取 Persona 信息
            bull_persona = ""
            bear_persona = ""
            for t in transcript:
                if t.get("speaker") == "bull" and not bull_persona:
                    bull_persona = t.get("persona", "")
                elif t.get("speaker") == "bear" and not bear_persona:
                    bear_persona = t.get("persona", "")

            persona_analysis = {
                "bull_persona": bull_persona,
                "bear_persona": bear_persona,
            }

            # 从 AdjudicationResult 推导证据分析
            evidence_depth = getattr(adjudication_result, "evidence_depth", {})
            fact_auth = getattr(adjudication_result, "dimension_comparison", {}).get(
                "fact_authenticity", {})
            evidence_analysis = {
                "bull_fact_score": fact_auth.get("bull", 3.0) if isinstance(fact_auth, dict) else 3.0,
                "bear_fact_score": fact_auth.get("bear", 3.0) if isinstance(fact_auth, dict) else 3.0,
                "bull_evidence_depth": evidence_depth.get("bull", 3) if isinstance(evidence_depth, dict) else 3,
                "bear_evidence_depth": evidence_depth.get("bear", 3) if isinstance(evidence_depth, dict) else 3,
            }

            # Step 3: 缺口
            gaps = data.get("gaps", {})
            if not isinstance(gaps, dict):
                gaps = {}
            # 确保缺口字段完整
            if "evidence_gaps" not in gaps:
                gaps["evidence_gaps"] = []
            if "dropped_args" not in gaps:
                gaps["dropped_args"] = []
            if "unused_tactics" not in gaps:
                gaps["unused_tactics"] = []

            # Step 4: 改进建议
            recommendations = data.get("recommendations", [])
            if not isinstance(recommendations, list):
                recommendations = []

            persona_suggestions = data.get("persona_suggestions", {})
            if not isinstance(persona_suggestions, dict):
                persona_suggestions = {}

            # Step 5: 存储 (认知系统 record)
            memory_id = None
            if self._cognitive is not None:
                try:
                    record_content = json.dumps({
                        "type": "reflection",
                        "topic": topic,
                        "winner": winner,
                        "strategy_tags": strategy_tags,
                        "gaps": gaps,
                        "recommendations": recommendations,
                    }, ensure_ascii=False)
                    tags = f"debate,reflection,{topic[:20]}"
                    result = self._cognitive.record(
                        content=record_content,
                        quality_level="B",
                        tags=tags,
                    )
                    if isinstance(result, dict):
                        memory_id = result.get("memory_id")
                    elif isinstance(result, str):
                        memory_id = result
                except Exception as e:
                    logger.warning("反思 record 失败(FAIL-OPEN): %s", e)

            return ReflectionReport(
                topic=topic,
                review=review,
                strategy_analysis=strategy_analysis,
                persona_analysis=persona_analysis,
                evidence_analysis=evidence_analysis,
                gaps=gaps,
                recommendations=recommendations,
                strategy_tags=strategy_tags,
                persona_suggestions=persona_suggestions,
                memory_id=memory_id,
                timestamp=ts,
            )

        except Exception as e:
            logger.warning("反思异常(FAIL-OPEN): %s", e)
            return self._degraded_report(topic, adjudication_result, ts, strategy_tags)

    def _degraded_report(
        self,
        topic: str,
        adjudication_result: Any,
        ts: str,
        strategy_tags: list[str],
    ) -> ReflectionReport:
        """降级报告：无 LLM 或异常时使用 AdjudicationResult 兜底。"""
        winner = getattr(adjudication_result, "winner", "draw")
        rfd = getattr(adjudication_result, "rfd", "")
        clash = getattr(adjudication_result, "key_clash_points", [])

        return ReflectionReport(
            topic=topic,
            review={
                "turn_points": [],
                "key_pivot": "",
                "rfd_summary": f"[降级] {rfd}",
            },
            strategy_analysis={},  # HC7: 无策略标签时跳过
            persona_analysis={},
            evidence_analysis={},
            gaps={
                "evidence_gaps": [],
                "dropped_args": [],
                "unused_tactics": [],
            },
            recommendations=[],
            strategy_tags=strategy_tags if strategy_tags else [],
            persona_suggestions={},
            memory_id=None,
            timestamp=ts,
        )

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM（同步），处理两种签名兼容。"""
        try:
            return self._llm_fn(prompt, 600)
        except TypeError:
            return self._llm_fn(prompt)
