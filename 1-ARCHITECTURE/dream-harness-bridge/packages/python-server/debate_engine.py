#!/usr/bin/env python3
"""debate_engine.py — C-Drive 内部辩论引擎 (SPEC v2.0-rc3 第六节)

C-Drive 自身和外部调用方（Trae/32-bot）共用此引擎。
C-Drive 自驱动时用 self._llm_fn；外部驱动时由调用方提供内容。

两种模式：
  - run_fast: 1轮并行 Bull/Bear，无 Persona，无 Judge，<10s
  - run_deep: 2轮+Judge+Persona+认知闭环，20-40s

认知闭环：
  - _recall_debate_memories: 辩论前检索历史记忆
  - _record_debate: 辩论后存储经验
  - _inject_debate_memories: B+级过滤 + prompt 注入

位置：dream-harness-bridge/packages/python-server/debate_engine.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from persona import (
    Persona, DEFAULT_BULL, DEFAULT_BEAR, DEFAULT_JUDGE, match_personas,
)

logger = logging.getLogger("cdrive.debate_engine")

# ── v1 平面 prompt（run_fast 用） ──────────────────────────────

_BULL_FAST_PROMPT = """你是正方辩手。你的立场是：必须支持话题。
规则：
1. 只输出支持的论点和论据
2. 提供 2-3 个论点
3. 输出 JSON: {"thesis": "核心论点", "arguments": ["论据1", "论据2"], "quote": "金句", "confidence": 0.0-1.0}
4. 只输出 JSON"""

_BEAR_FAST_PROMPT = """你是反方辩手。你的立场是：必须反对话题。
规则：
1. 只输出反对的论点和论据
2. 提供 2-3 个论点
3. 输出 JSON: {"thesis": "核心论点", "arguments": ["论据1", "论据2"], "quote": "金句", "confidence": 0.0-1.0}
4. 只输出 JSON"""

_JUDGE_PROMPT = """你是一位中立裁判。请综合双方辩手的论点，给出客观裁决。
规则：
1. 总结辩论核心分歧
2. 判定哪方论据更充分（或平局）
3. 提炼 2-3 条核心洞察
4. 给出话题升华角度
5. 输出 JSON: {"summary": "辩论总结", "winner": "bull|bear|null", "key_insights": ["洞察1", "洞察2"], "topic_angle": "话题升华角度"}
6. 只输出 JSON"""


# ── JSON 解析（C-Drive 内部，不依赖 32-bot） ───────────────────

def _extract_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象。"""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


@dataclass
class _Argument:
    """辩手结构化输出（C-Drive 内部最小实现）。"""
    thesis: str = ""
    arguments: list[str] = field(default_factory=list)
    quote: str = ""
    confidence: float = 0.0
    raw: str = ""

    @classmethod
    def fallback(cls) -> "_Argument":
        return cls(thesis="（技术原因无法输出完整论点）")

    @classmethod
    def parse(cls, raw: str) -> "_Argument":
        """从 LLM 输出解析 Argument，失败返回 fallback。"""
        data = _extract_json(raw)
        if data is None:
            return cls.fallback()
        try:
            return cls(
                thesis=str(data.get("thesis", "")),
                arguments=list(data.get("arguments", [])),
                quote=str(data.get("quote", "")),
                confidence=float(data.get("confidence", 0.0)),
                raw=raw,
            )
        except (TypeError, ValueError):
            return cls.fallback()


def _get_opponent_thesis(transcript: list[dict], my_side: str) -> str | None:
    """从 transcript 中提取对方最后一轮的 thesis。"""
    opponent_side = "bear" if my_side == "bull" else "bull"
    for turn in reversed(transcript):
        if turn["speaker"] == opponent_side:
            return turn["content"].get("thesis") if isinstance(turn["content"], dict) else None
    return None


# ── DebateEngine ──────────────────────────────────────────────

class DebateEngine:
    """C-Drive 内部辩论引擎。

    C-Drive 自身和外部调用方（Trae/32-bot）共用此引擎。
    C-Drive 自驱动时用 self._llm_fn；外部驱动时由调用方提供内容。
    """

    def __init__(
        self,
        llm_fn: Callable[..., str],
        config: dict,
        cognitive_adapter: Optional[Any] = None,
    ):
        """
        Args:
            llm_fn: LLM 调用函数 (prompt, max_tokens) -> str
            config: 辩论配置
            cognitive_adapter: 认知适配器（需有 recall/record/verify），
                None 时跳过认知闭环（FAIL-OPEN）
        """
        self._llm_fn = llm_fn
        self._config = config
        self._cognitive = cognitive_adapter

    # ── 快速模式 ────────────────────────────────────────────

    async def run_fast(self, topic: str, background: str = "") -> dict:
        """快速模式：1轮 Bull/Bear 并行，无 Persona，无 Judge。

        延迟：~10s（2 次 LLM 调用，并行）
        用途：C-Drive 低价值交易决策

        Returns: {bull_thesis, bull_confidence, bear_thesis, bear_confidence}
        """
        bull_prompt = f"{_BULL_FAST_PROMPT}\n话题:{topic}"
        bear_prompt = f"{_BEAR_FAST_PROMPT}\n话题:{topic}"

        bull_raw, bear_raw = await asyncio.gather(
            asyncio.to_thread(self._call_llm, bull_prompt),
            asyncio.to_thread(self._call_llm, bear_prompt),
        )
        bull_arg = _Argument.parse(bull_raw)
        bear_arg = _Argument.parse(bear_raw)

        return {
            "bull_thesis": bull_arg.thesis,
            "bull_confidence": bull_arg.confidence,
            "bear_thesis": bear_arg.thesis,
            "bear_confidence": bear_arg.confidence,
        }

    # ── 深度模式 ────────────────────────────────────────────

    async def run_deep(
        self,
        topic: str,
        background: str = "",
        bull_persona: Persona | None = None,
        bear_persona: Persona | None = None,
    ) -> dict:
        """深度模式：2轮 Bull/Bear + Judge + Persona + 认知闭环。

        延迟：~20-40s（5 次 LLM 调用）
        用途：C-Drive 高价值交易决策 / 外部高质量辩论

        Returns: {topic, transcript, verdict}
        """
        # 1. recall 历史记忆
        memories = self._recall_debate_memories(topic)
        memory_strs = self._format_memories_for_prompt(memories)

        # 2. 构建 Persona
        if bull_persona is None or bear_persona is None:
            auto_bull, auto_bear = match_personas(topic)
            bull_persona = bull_persona or auto_bull
            bear_persona = bear_persona or auto_bear

        # 3. 2轮辩论
        transcript: list[dict] = []
        for round_num in range(2):
            # Bull
            opponent = _get_opponent_thesis(transcript, "bull")
            bull_sys = bull_persona.build_system_prompt(
                topic, opponent_thesis=opponent,
                background=background, memories=memory_strs or None,
            )
            bull_raw = await asyncio.to_thread(
                self._call_llm, f"{bull_sys}\n话题:{topic}")
            bull_arg = _Argument.parse(bull_raw)
            transcript.append({
                "speaker": "bull", "round": round_num + 1,
                "content": {
                    "thesis": bull_arg.thesis,
                    "arguments": bull_arg.arguments,
                    "quote": bull_arg.quote,
                    "confidence": bull_arg.confidence,
                },
                "persona": bull_persona.name,
                "timestamp": datetime.now().isoformat(),
            })

            # Bear
            opponent = _get_opponent_thesis(transcript, "bear")
            bear_sys = bear_persona.build_system_prompt(
                topic, opponent_thesis=opponent,
                background=background, memories=memory_strs or None,
            )
            bear_raw = await asyncio.to_thread(
                self._call_llm, f"{bear_sys}\n话题:{topic}")
            bear_arg = _Argument.parse(bear_raw)
            transcript.append({
                "speaker": "bear", "round": round_num + 1,
                "content": {
                    "thesis": bear_arg.thesis,
                    "arguments": bear_arg.arguments,
                    "quote": bear_arg.quote,
                    "confidence": bear_arg.confidence,
                },
                "persona": bear_persona.name,
                "timestamp": datetime.now().isoformat(),
            })

        # 4. Judge
        verdict = await self._run_judge(topic, transcript)

        # 5. record 辩论经验
        self._record_debate(topic, transcript, verdict)

        return {
            "topic": topic,
            "transcript": transcript,
            "verdict": verdict,
        }

    # ── Judge ───────────────────────────────────────────────

    async def _run_judge(self, topic: str, transcript: list[dict]) -> dict:
        """裁判裁决。"""
        debate_summary = "\n".join(
            f"{'正方' if t['speaker'] == 'bull' else '反方'}(第{t['round']}轮): "
            f"{t['content'].get('thesis', '')}"
            for t in transcript
        )
        prompt = f"{_JUDGE_PROMPT}\n\n辩论话题:{topic}\n辩论记录:\n{debate_summary}"
        raw = await asyncio.to_thread(self._call_llm, prompt)
        data = _extract_json(raw)
        if data is None:
            return {"summary": "裁判裁决生成失败", "winner": None,
                    "key_insights": [], "topic_angle": ""}
        return {
            "summary": str(data.get("summary", "")),
            "winner": data.get("winner"),
            "key_insights": list(data.get("key_insights", [])),
            "topic_angle": str(data.get("topic_angle", "")),
        }

    # ── 认知闭环 ───────────────────────────────────────────

    def _recall_debate_memories(self, topic: str) -> list[dict]:
        """从 4-MEMORY 检索历史辩论记忆。

        FAIL-OPEN: 无 cognitive_adapter 时返回空列表。
        """
        if self._cognitive is None:
            return []
        try:
            result = self._cognitive.recall(
                context=f"{topic} 辩论论据",
                top_k=5,
                min_quality="C",
            )
            if isinstance(result, list):
                return result
            # MCP recall 返回 {"memories": [...]} 格式
            if isinstance(result, dict) and "memories" in result:
                return result["memories"]
            return []
        except Exception as e:
            logger.warning("recall 辩论记忆失败(FAIL-OPEN): %s", e)
            return []

    def _record_debate(
        self, topic: str, transcript: list[dict], verdict: dict,
    ):
        """将辩论经验写入 4-MEMORY。

        FAIL-OPEN: 无 cognitive_adapter 时跳过。
        """
        if self._cognitive is None:
            return
        try:
            for turn in transcript:
                content = turn["content"]
                side = turn["speaker"]
                record_content = json.dumps({
                    "type": "argument",
                    "subtype": "argument-pattern",
                    "topic": topic,
                    "side": side,
                    "thesis": content.get("thesis", ""),
                    "arguments": content.get("arguments", []),
                    "quote": content.get("quote", ""),
                    "confidence": content.get("confidence", 0.0),
                    "persona": turn.get("persona", ""),
                    "round": turn.get("round", 0),
                }, ensure_ascii=False)
                # 双维度 tags: 辩论维度 + 交易维度
                tags = f"debate,argument-pattern,{topic[:20]}"
                self._cognitive.record(
                    content=record_content,
                    quality_level="B",
                    tags=tags,
                )
            # 记录裁判裁决
            if verdict:
                verdict_content = json.dumps({
                    "type": "verdict",
                    "topic": topic,
                    "winner": verdict.get("winner"),
                    "summary": verdict.get("summary", ""),
                    "key_insights": verdict.get("key_insights", []),
                    "topic_angle": verdict.get("topic_angle", ""),
                }, ensure_ascii=False)
                self._cognitive.record(
                    content=verdict_content,
                    quality_level="B",
                    tags=f"debate,verdict,{topic[:20]}",
                )
        except Exception as e:
            logger.warning("record 辩论经验失败(FAIL-OPEN): %s", e)

    def _inject_debate_memories(self, topic: str, memories: list[dict]) -> str:
        """将辩论记忆注入 C-Drive 推理 prompt。

        过滤规则：仅 B 级以上（quality_score ≥ 0.40）注入。
        """
        if not memories:
            return ""

        qualified = [
            m for m in memories
            if m.get("quality_score", 0) >= 0.40
        ]
        if not qualified:
            return ""

        lines = ["[历史辩论经验]"]
        for m in qualified[:5]:  # 最多注入 5 条
            quality_label = m.get("quality", "C")
            verified = "已验证" if m.get("verified") else "未验证"
            content = m.get("content", "")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    content = {}
            if not isinstance(content, dict):
                content = {}

            side_label = "正方" if content.get("side") == "bull" else "反方"
            lines.append(
                f"- [{quality_label}级·{verified}] {side_label}论点: "
                f"\"{content.get('thesis', '')}\" "
                f"(置信度{content.get('confidence', 0)})"
            )
        lines.append("[以上为历史辩论中产出的论据，可参考但需独立判断]")
        return "\n".join(lines)

    # ── 内部工具 ───────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM（同步），处理两种签名兼容。"""
        try:
            return self._llm_fn(prompt, 600)
        except TypeError:
            # 单参数签名 (prompt) -> str
            return self._llm_fn(prompt)

    @staticmethod
    def _format_memories_for_prompt(memories: list[dict]) -> list[str]:
        """将记忆列表格式化为 prompt 可用的字符串列表。"""
        result = []
        for m in memories[:5]:
            content = m.get("content", "")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    continue
            if isinstance(content, dict) and content.get("thesis"):
                result.append(content["thesis"])
        return result
