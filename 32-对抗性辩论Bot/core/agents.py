"""agents.py — BullAgent / BearAgent 辩手

核心设计（借鉴 TradingAgents）：
- Prompt 锁立场：Bull 只支持 / Bear 只反对
- LLM 调用 → JSON 解析 → 失败重试 1 次 → FAIL-OPEN 兜底
- 上下文注入：transcript 对方上轮 + background + injected_views
"""

from __future__ import annotations

import logging
from typing import Protocol

from core.models import Argument, Turn, Verdict
from core.profiles import DebateProfile, get_profile
from core.prompts import (
    build_cross_exam_answer_prompt,
    build_cross_exam_question_prompt,
    build_user_prompt,
)
from core.robust_json import extract_json_object

logger = logging.getLogger("debate.agents")


class LLMClient(Protocol):
    """LLM 客户端接口（duck-typed）。"""

    async def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
        """调用 LLM，返回文本响应。"""
        ...


def _extract_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象（委托 robust_json）。

    支持代码围栏、前后散文、嵌套对象/数组；旧实现的
    `\\{[^{}]*\\}` 在嵌套 JSON 上会截断，已由单元测试覆盖。
    """
    return extract_json_object(raw)


def _parse_argument(raw: str) -> Argument | None:
    """解析 LLM 输出为 Argument，失败返回 None。"""
    data = _extract_json(raw)
    if data is None:
        return None

    try:
        return Argument(
            thesis=str(data["thesis"]),
            arguments=list(data.get("arguments", [])),
            quote=str(data.get("quote", "")),
            confidence=float(data.get("confidence", 0.0)),
            raw=raw,
            evidence=list(data.get("evidence", [])),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Argument 解析失败: %s", e)
        return None


def _get_opponent_thesis(transcript: list[Turn], my_side: str) -> str | None:
    """从 transcript 中提取对方最后一轮的 thesis。

    Args:
        transcript: 辩论历史
        my_side: 'bull' 或 'bear'
    """
    opponent = "bear" if my_side == "bull" else "bull"
    for turn in reversed(transcript):
        if turn.speaker == opponent and isinstance(turn.content, Argument):
            return turn.content.thesis
    return None


def _string_list(value: object, limit: int) -> list[str]:
    """把 LLM 返回的 list 归一化为非空字符串列表。"""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


class BaseAgent:
    """辩手基类：立场 prompt + LLM 调用 + JSON 解析 + 重试 + FAIL-OPEN。"""

    def __init__(
        self,
        llm_client: LLMClient,
        system_prompt: str,
        side: str,
        max_tokens: int = 2000,
        profile: DebateProfile | str | None = None,
    ):
        self.llm = llm_client
        self.system_prompt = system_prompt
        self.side = side  # 'bull' or 'bear'
        self.side_name = "正方" if side == "bull" else "反方"
        self.stance = "支持" if side == "bull" else "反对"
        self.max_tokens = max_tokens
        self.profile = get_profile(profile)

    async def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict | None:
        """调用 LLM 并解析 JSON；失败重试 1 次，仍失败返回 None。"""
        try:
            raw = await self.llm.chat(
                system_prompt,
                user_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 交叉质询 LLM 调用异常: %s", self.side, e)
            return None

        data = extract_json_object(raw)
        if data is not None:
            return data

        retry_prompt = user_prompt + (
            "\n\n请严格只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字。"
        )
        try:
            raw2 = await self.llm.chat(
                system_prompt,
                retry_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 交叉质询重试异常: %s", self.side, e)
            return None
        return extract_json_object(raw2)

    async def cross_examine(
        self,
        topic: str,
        transcript: list[Turn],
        background: str = "",
        injected_views: list[str] | None = None,
    ) -> list[str]:
        """作为质询方，针对对方上一轮论点生成 2-3 个问题。"""
        opponent_last = _get_opponent_thesis(transcript, self.side)
        opponent_label = "反方" if self.side == "bull" else "正方"
        user_prompt = build_cross_exam_question_prompt(
            topic,
            opponent_last,
            background,
            injected_views,
            opponent_label=opponent_label,
        )
        system_prompt = self.profile.question_system.format(
            side_name=self.side_name,
            stance=self.stance,
        )
        data = await self._chat_json(system_prompt, user_prompt)
        if data is None:
            logger.warning("%s 质询生成失败，跳过该方向", self.side)
            return []
        return _string_list(data.get("questions"), limit=3)

    async def answer_cross(
        self,
        topic: str,
        questions: list[str],
        transcript: list[Turn],
        background: str = "",
        injected_views: list[str] | None = None,
    ) -> list[str]:
        """作为回答方，逐条回答对方质询。"""
        if not questions:
            return []
        user_prompt = build_cross_exam_answer_prompt(
            topic,
            questions,
            background,
            injected_views,
        )
        system_prompt = self.profile.answer_system.format(
            side_name=self.side_name,
            stance=self.stance,
        )
        data = await self._chat_json(system_prompt, user_prompt)
        answers = (
            _string_list(data.get("answers"), limit=len(questions)) if data is not None else []
        )
        # 解析失败/数量不足时补齐，保证 answers 与 questions 一一对应
        if len(answers) < len(questions):
            answers += ["（本方未能回答）"] * (len(questions) - len(answers))
        return answers[: len(questions)]

    async def _speak(
        self,
        topic: str,
        transcript: list[Turn],
        background: str = "",
        injected_views: list[str] | None = None,
    ) -> Argument:
        """核心逻辑：构建 prompt → LLM 调用 → JSON 解析 → 重试 → 兜底。"""
        opponent_last = _get_opponent_thesis(transcript, self.side)
        opponent_label = "反方" if self.side == "bull" else "正方"
        user_prompt = build_user_prompt(
            topic,
            opponent_last,
            background,
            injected_views,
            opponent_label=opponent_label,
        )

        # 第一次调用
        try:
            raw = await self.llm.chat(
                self.system_prompt,
                user_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 第一次 LLM 调用异常: %s", self.side, e)
            return Argument.fallback()

        arg = _parse_argument(raw)
        if arg is not None:
            return arg

        # 重试 1 次（追加严格 JSON 提示；保留原始输出便于排查）
        logger.info("%s JSON 解析失败，重试 1 次（raw=%r）", self.side, raw[:300])
        retry_prompt = user_prompt + (
            "\n\n请严格只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字。"
        )
        try:
            raw2 = await self.llm.chat(
                self.system_prompt,
                retry_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("%s 重试 LLM 调用异常: %s", self.side, e)
            return Argument.fallback()

        arg2 = _parse_argument(raw2)
        if arg2 is not None:
            return arg2

        # 两次都失败 → FAIL-OPEN 兜底
        logger.warning(
            "%s 两次 JSON 解析均失败，返回兜底 Argument（raw=%r）", self.side, raw2[:300]
        )
        return Argument.fallback()


class BullAgent(BaseAgent):
    """正方辩手：立场锁定为支持话题；profile 决定角色设定。"""

    def __init__(
        self,
        llm_client: LLMClient,
        max_tokens: int = 600,
        profile: DebateProfile | str | None = None,
    ):
        p = get_profile(profile)
        super().__init__(llm_client, p.bull_system_prompt, "bull", max_tokens, profile=p)

    async def argue(
        self,
        topic: str,
        transcript: list[Turn],
        background: str = "",
        injected_views: list[str] | None = None,
    ) -> Argument:
        """正方发言。"""
        return await self._speak(topic, transcript, background, injected_views)


class BearAgent(BaseAgent):
    """反方辩手：立场锁定为反对话题；profile 决定角色设定。"""

    def __init__(
        self,
        llm_client: LLMClient,
        max_tokens: int = 600,
        profile: DebateProfile | str | None = None,
    ):
        p = get_profile(profile)
        super().__init__(llm_client, p.bear_system_prompt, "bear", max_tokens, profile=p)

    async def rebut(
        self,
        topic: str,
        transcript: list[Turn],
        background: str = "",
        injected_views: list[str] | None = None,
    ) -> Argument:
        """反方反驳。"""
        return await self._speak(topic, transcript, background, injected_views)


# ─── JudgeAgent ───────────────────────────────────────────────────


def _parse_verdict(raw: str) -> Verdict | None:
    """解析 LLM 输出为 Verdict，失败返回 None。"""
    data = _extract_json(raw)
    if data is None:
        return None

    try:
        winner = data.get("winner")
        # winner 只允许 'bull', 'bear' 或 None
        if winner not in ("bull", "bear", None):
            winner = None
        feasibility_raw = data.get("feasibility")
        try:
            feasibility = float(feasibility_raw) if feasibility_raw is not None else None
        except (TypeError, ValueError):
            feasibility = None
        signal = data.get("signal")
        if not isinstance(signal, dict):
            signal = None
        return Verdict(
            summary=str(data.get("summary", "")),
            winner=winner,
            key_insights=list(data.get("key_insights", [])),
            topic_angle=str(data.get("topic_angle", "")),
            feasibility=feasibility,
            risks=list(data.get("risks", [])),
            evidence_gaps=list(data.get("evidence_gaps", [])),
            recommendation=str(data.get("recommendation", "")),
            signal=signal,
        )
    except (TypeError, ValueError) as e:
        logger.warning("Verdict 解析失败: %s", e)
        return None


def _build_judge_user_prompt(
    topic: str,
    transcript: list[Turn],
    max_chars: int = 6000,
    output_hint: str = "",
) -> str:
    """构建紧凑裁判 prompt：只取双方最后一轮 + 前 2 条论据。

    旧实现把全部 transcript 塞进 prompt，长上下文会被部分网关截断
    （表现：模型只返回 `{"`）。这里压缩到可预测的长度，并显式要求
    纯 JSON。
    """
    last_by_side: dict[str, Turn] = {}
    for turn in transcript:
        if isinstance(turn.content, Argument):
            last_by_side[turn.speaker] = turn

    parts = [f"辩论话题：{topic}\n"]
    for speaker in ("bull", "bear"):
        turn = last_by_side.get(speaker)
        if turn is None:
            continue
        side_name = "正方" if speaker == "bull" else "反方"
        args = "；".join(turn.content.arguments[:2])
        parts.append(
            f"【{side_name}·第{turn.round}轮】\n" f"论点：{turn.content.thesis}\n" f"论据：{args}\n"
        )

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(已截断)"
    hint = output_hint or (
        '{"summary":"...","winner":"bull|bear|null",' '"key_insights":["..."],"topic_angle":"..."}'
    )
    text += f"\n请只输出一个严格 JSON 对象：{hint}。" "不要 markdown/代码围栏/解释文字。"
    return text


def _fallback_verdict(transcript: list[Turn]) -> Verdict:
    """裁判 LLM/JSON 失败时的规则降级裁决（FAIL-OPEN，不抛异常）。"""
    bull_conf: list[float] = []
    bear_conf: list[float] = []
    insights: list[str] = []
    for turn in transcript:
        if not isinstance(turn.content, Argument):
            continue
        if turn.speaker == "bull":
            bull_conf.append(float(turn.content.confidence or 0.0))
        elif turn.speaker == "bear":
            bear_conf.append(float(turn.content.confidence or 0.0))
        if turn.content.thesis:
            insights.append(f"{turn.speaker}: {turn.content.thesis[:80]}")
    bull = sum(bull_conf) / len(bull_conf) if bull_conf else 0.0
    bear = sum(bear_conf) / len(bear_conf) if bear_conf else 0.0
    if abs(bull - bear) < 0.05:
        winner = None
    else:
        winner = "bull" if bull > bear else "bear"
    return Verdict(
        summary=(
            "裁判 JSON 解析失败，已用规则降级裁决（基于双方平均置信度）。"
            f" bull={bull:.2f} bear={bear:.2f}"
        ),
        winner=winner,
        key_insights=insights[:3],
        topic_angle="",
    )


class JudgeAgent:
    """综合裁判：综合双方论点 → Verdict。

    profile 决定角色设定与输出字段（technical / signal 有额外字段）。
    """

    _OUTPUT_HINTS = {
        "technical": (
            '{"summary":"...","winner":"bull|bear|null","key_insights":["..."],'
            '"topic_angle":"","feasibility":0.0,"risks":["..."],'
            '"evidence_gaps":["..."],"recommendation":"..."}'
        ),
        "signal": (
            '{"summary":"...","winner":"bull|bear|null","key_insights":["..."],'
            '"topic_angle":"","signal":{"direction":"long|short|neutral",'
            '"confidence":0.0,"risk_flags":["..."],"evidence":["..."],'
            '"counter_evidence":["..."]}}'
        ),
    }

    def __init__(
        self,
        llm_client: LLMClient,
        max_tokens: int = 1600,
        profile: DebateProfile | str | None = None,
    ):
        self.llm = llm_client
        self.max_tokens = max_tokens
        self.profile = get_profile(profile)

    async def synthesize(self, topic: str, transcript: list[Turn]) -> Verdict:
        """综合双方论点，输出裁决。"""
        user_prompt = _build_judge_user_prompt(
            topic,
            transcript,
            output_hint=self._OUTPUT_HINTS.get(self.profile.name, ""),
        )

        # 第一次调用
        try:
            raw = await self.llm.chat(
                self.profile.judge_system_prompt,
                user_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("Judge 第一次 LLM 调用异常: %s", e)
            return _fallback_verdict(transcript)

        verdict = _parse_verdict(raw)
        if verdict is not None:
            return verdict

        # 重试 1 次
        logger.info("Judge JSON 解析失败，重试 1 次（raw=%r）", raw[:300])
        retry_prompt = user_prompt + (
            "\n\n请严格只输出一个 JSON 对象，不要 markdown/代码围栏/解释文字。"
        )
        try:
            raw2 = await self.llm.chat(
                self.profile.judge_system_prompt,
                retry_prompt,
                self.max_tokens,
            )
        except Exception as e:
            logger.warning("Judge 重试 LLM 调用异常: %s", e)
            return _fallback_verdict(transcript)

        verdict2 = _parse_verdict(raw2)
        if verdict2 is not None:
            return verdict2

        # FAIL-OPEN 兜底
        logger.warning("Judge 两次 JSON 解析均失败，使用规则降级裁决（raw=%r）", raw2[:300])
        return _fallback_verdict(transcript)
