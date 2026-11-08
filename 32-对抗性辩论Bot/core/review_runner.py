"""review_runner.py — 供 Agent/CLI/MCP 复用的对抗评审入口。

与营销辩论路径不同：不生成营销素材/质量评分，只返回结构化
transcript + verdict + 元数据，便于其他系统直接消费。

用法（Python）：
    from core.review_runner import run_review_sync
    result = run_review_sync("命题", background="背景", rounds=2)
    print(result["verdict"])
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.agents import BullAgent, BearAgent, JudgeAgent
from core.cross_exam import run_cross_examination
from core.llm_compat import LLMSettings, create_llm_client
from core.models import Turn
from core.profiles import get_profile


def _turn_dict(turn: Turn) -> dict:
    content = turn.content
    if isinstance(content, str):
        serialized: Any = content
    elif hasattr(content, "__dict__"):
        serialized = dict(content.__dict__)
    else:
        serialized = str(content)
    return {
        "speaker": turn.speaker,
        "round": turn.round,
        "content": serialized,
        "timestamp": turn.timestamp.isoformat(),
    }


@dataclass
class ReviewResult:
    topic: str
    background: str
    rounds: int
    transcript: list[Turn]
    verdict: Any | None
    meta: dict = field(default_factory=dict)
    status: str = "completed"
    debate_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: str = "review"
    adjudication: Any | None = None

    def to_dict(self) -> dict:
        return {
            "schema_version": "debate-result-v1",
            "debate_id": self.debate_id,
            "status": self.status,
            "mode": self.mode,
            "topic": self.topic,
            "rounds": self.rounds,
            "transcript": [_turn_dict(t) for t in self.transcript],
            "verdict": self.verdict.__dict__ if self.verdict is not None else None,
            "adjudication": self.adjudication,
            "research": self.meta.get("research"),
            "meta": self.meta,
        }


def _adjudicate_sync(
    judge_llm: Any, topic: str, transcript: list[dict], verdict: dict,
) -> dict:
    """同步调用 DSH Adjudicator（在线程中执行）。"""
    from core.dsh_backend import _load_dsh

    Adjudicator = _load_dsh()[1]

    def llm_fn(prompt: str, max_tokens: int = 600) -> str:
        return asyncio.run(
            judge_llm.chat(
                "你是辩论评审助手，严格按要求输出 JSON。",
                prompt,
                max_tokens=max(1200, int(max_tokens or 600)),
            )
        )

    result = Adjudicator(llm_fn=llm_fn).adjudicate(topic, transcript, verdict)
    return result.to_dict() if hasattr(result, "to_dict") else result


async def _run_adjudication(
    judge_llm: Any, topic: str, transcript: list[dict], verdict: dict,
    adjudicator: Any = None,
) -> Any:
    """执行 6 维 adjudication；注入 adjudicator 便于测试/复用。"""
    if adjudicator is not None:
        result = await asyncio.to_thread(
            adjudicator.adjudicate, topic, transcript, verdict,
        )
    else:
        result = await asyncio.to_thread(
            _adjudicate_sync, judge_llm, topic, transcript, verdict,
        )
    return result.to_dict() if hasattr(result, "to_dict") else result


async def run_review(
    topic: str,
    background: str = "",
    rounds: int = 2,
    judge: bool = True,
    *,
    settings: LLMSettings | None = None,
    debater_llm: Any = None,
    judge_llm: Any = None,
    research: bool = False,
    research_sources: list[str] | None = None,
    research_max_items: int = 8,
    research_timeout: float = 20.0,
    debate_id: str | None = None,
    cross_examination: bool = False,
    adjudication: bool = True,
    adjudicator: Any = None,
    profile: str = "technical",
) -> ReviewResult:
    """执行一场结构化对抗评审（无营销/质量步骤）。

    debater_llm / judge_llm 可注入（测试或其他 Agent 复用）；
    未注入时按 settings/环境自动创建。
    research=True 时先执行 Research Prepass（只读 L0 MCP + 本地代码检索）。
    """
    rounds = max(1, min(int(rounds), 5))
    profile_obj = get_profile(profile)

    research_meta: dict[str, Any] | None = None
    if research:
        try:
            from core.research import collect_research, merge_background

            brief = await asyncio.to_thread(
                collect_research,
                topic,
                background,
                sources=research_sources,
                max_items=research_max_items,
                timeout=research_timeout,
                profile=profile_obj.name,
            )
            background = merge_background(background, brief)
            research_meta = brief.to_dict()
        except Exception as exc:  # noqa: BLE001 — 调研失败不阻塞辩论
            research_meta = {
                "brief": "",
                "citations": [],
                "source_stats": [],
                "degraded": True,
                "errors": [f"research_failed:{type(exc).__name__}:{exc}"],
            }

    debater_llm = debater_llm or create_llm_client(settings)
    judge_llm = judge_llm or create_llm_client(settings)

    bull = BullAgent(debater_llm, max_tokens=2000, profile=profile_obj)
    bear = BearAgent(debater_llm, max_tokens=2000, profile=profile_obj)
    judge_agent = (
        JudgeAgent(judge_llm, max_tokens=1600, profile=profile_obj)
        if judge else None
    )

    transcript: list[Turn] = []
    degraded_turns: list[dict] = []
    for round_index in range(1, rounds + 1):
        bull_arg = await bull.argue(topic, transcript, background)
        transcript.append(Turn(speaker="bull", round=round_index, content=bull_arg))
        if not bull_arg.arguments:
            degraded_turns.append({"speaker": "bull", "round": round_index})

        bear_arg = await bear.rebut(topic, transcript, background)
        transcript.append(Turn(speaker="bear", round=round_index, content=bear_arg))
        if not bear_arg.arguments:
            degraded_turns.append({"speaker": "bear", "round": round_index})

        if cross_examination and round_index == 1:
            await run_cross_examination(
                bull, bear, topic, transcript, background=background,
                round_num=round_index,
            )

    verdict = None
    if judge_agent is not None:
        verdict = await judge_agent.synthesize(topic, transcript)
        if not verdict.key_insights and verdict.winner is None:
            degraded_turns.append({"speaker": "judge", "round": 0})

    adjudication_result: Any | None = None
    adjudication_error = ""
    if adjudication:
        try:
            adjudication_result = await _run_adjudication(
                judge_llm, topic, [_turn_dict(t) for t in transcript],
                verdict.__dict__ if verdict is not None else {},
                adjudicator=adjudicator,
            )
        except Exception as exc:  # noqa: BLE001 — adjudication FAIL-OPEN
            adjudication_error = f"{type(exc).__name__}: {exc}"
            degraded_turns.append({"speaker": "adjudicator", "round": 0})

    meta = {
        "generated_at": datetime.now().isoformat(),
        "provider": getattr(debater_llm, "provider", "injected"),
        "model": getattr(debater_llm, "model", None),
        "judge_provider": getattr(judge_llm, "provider", "injected"),
        "judge_model": getattr(judge_llm, "model", None),
        "degraded_turns": degraded_turns,
        "degraded": bool(degraded_turns),
        "judge_enabled": judge,
        "profile": profile_obj.name,
        "cross_examination": cross_examination,
        "adjudication": adjudication_result is not None,
        "adjudication_error": adjudication_error,
        "research": research_meta,
    }
    return ReviewResult(
        topic=topic,
        background=background,
        rounds=rounds,
        transcript=transcript,
        verdict=verdict,
        meta=meta,
        status="completed",
        debate_id=debate_id or uuid.uuid4().hex[:12],
        adjudication=adjudication_result,
    )


def run_review_sync(
    topic: str,
    *,
    timeout: float | None = None,
    **kwargs: Any,
) -> ReviewResult:
    """同步入口；timeout 为整场评审（含 research）的总超时秒数。"""
    async def _runner() -> ReviewResult:
        coro = run_review(topic, **kwargs)
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    return asyncio.run(_runner())