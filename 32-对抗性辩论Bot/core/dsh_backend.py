"""dsh_backend.py — P1: fast/deep 后端（DSH DebateEngine + Adjudicator）。

- fast：DSH `DebateEngine.run_fast`（1 轮并行，<10s，无 Judge）
- deep：DSH `DebateEngine.run_deep`（2 轮 + Judge + Persona）+ `Adjudicator` 6 维评分
- 输出统一为 DebateResult v1 dict，供 MCP 壳/其他 Agent 消费
- 不传 cognitive_adapter（避免 record/verify 写入），保持只读
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from core.llm_compat import LLMSettings, create_llm_client

REPO_ROOT = Path(__file__).resolve().parents[2]
DSH_ROOT = REPO_ROOT / "1-ARCHITECTURE" / "dream-harness-bridge" / "packages" / "python-server"


def _load_dsh():
    if str(DSH_ROOT) not in sys.path:
        sys.path.insert(0, str(DSH_ROOT))
    from adjudicator import Adjudicator
    from debate_engine import DebateEngine

    return DebateEngine, Adjudicator


def _sync_llm_fn(llm: Any):
    """把异步 LLMClient 适配为 DSH 需要的同步 (prompt, max_tokens)->str。"""
    def call(prompt: str, max_tokens: int = 600) -> str:
        return asyncio.run(
            llm.chat(
                "你是辩论助手，严格按要求输出 JSON。",
                prompt,
                max_tokens=max(1200, int(max_tokens or 600)),
            )
        )

    return call


def _fast_transcript(result: dict) -> list[dict]:
    return [
        {
            "speaker": "bull",
            "round": 1,
            "content": {
                "thesis": str(result.get("bull_thesis") or ""),
                "arguments": [],
                "quote": "",
                "confidence": float(result.get("bull_confidence") or 0.0),
            },
        },
        {
            "speaker": "bear",
            "round": 1,
            "content": {
                "thesis": str(result.get("bear_thesis") or ""),
                "arguments": [],
                "quote": "",
                "confidence": float(result.get("bear_confidence") or 0.0),
            },
        },
    ]


def _normalize_winner(value: Any) -> str | None:
    """DebateResult v1 只允许 bull/bear/null；其余一律视为平局。"""
    return value if value in ("bull", "bear") else None


def _fast_verdict(result: dict) -> dict:
    bull = float(result.get("bull_confidence") or 0.0)
    bear = float(result.get("bear_confidence") or 0.0)
    if abs(bull - bear) < 0.05:
        winner = None
    else:
        winner = "bull" if bull > bear else "bear"
    return {
        "summary": f"fast mode：bull={bull:.2f} bear={bear:.2f}",
        "winner": winner,
        "key_insights": [],
        "topic_angle": "",
    }


def run_dsh_debate_sync(
    mode: str,
    topic: str,
    background: str = "",
    *,
    settings: LLMSettings | None = None,
    research: bool = False,
    research_sources: list[str] | None = None,
    research_max_items: int = 8,
    research_timeout: float = 20.0,
    debate_id: str | None = None,
    engine: Any = None,
    adjudicator: Any = None,
    profile: str = "generic",
) -> dict:
    """执行 fast/deep 辩论，返回 DebateResult v1 dict。

    profile=signal 时走 32 Bot 的 signal profile（交易信号评审），
    其余值保持 DSH DebateEngine 的通用 fast/deep 行为。
    """
    mode = (mode or "").strip().lower()
    if mode not in ("fast", "deep"):
        raise ValueError(f"unsupported DSH mode: {mode!r}")

    if (profile or "").strip().lower() == "signal":
        from core.review_runner import run_review_sync

        review = run_review_sync(
            topic,
            background=background,
            rounds=1 if mode == "fast" else 2,
            judge=True,
            settings=settings,
            research=research,
            research_sources=research_sources,
            research_max_items=research_max_items,
            research_timeout=research_timeout,
            debate_id=debate_id,
            adjudication=False,
            profile="signal",
        )
        data = review.to_dict()
        data["mode"] = mode
        data["meta"]["backend"] = "32-signal"
        data["meta"]["profile"] = "signal"
        return data

    started = time.perf_counter()
    degraded = False
    research_meta: dict[str, Any] | None = None
    if research:
        from core.research import collect_research, merge_background

        brief = collect_research(
            topic, background,
            sources=research_sources,
            max_items=research_max_items,
            timeout=research_timeout,
        )
        background = merge_background(background, brief)
        research_meta = brief.to_dict()
        degraded = degraded or bool(research_meta.get("degraded"))

    llm = None
    llm_fn = None
    if engine is None or (mode == "deep" and adjudicator is None):
        llm = create_llm_client(settings)
        llm_fn = _sync_llm_fn(llm)

    DebateEngine, Adjudicator = _load_dsh()
    if engine is None:
        engine = DebateEngine(llm_fn=llm_fn, config={}, cognitive_adapter=None)

    if mode == "fast":
        topic_input = topic if not background else f"{topic}\n\n背景材料：{background}"
        raw = asyncio.run(engine.run_fast(topic_input))
        transcript = _fast_transcript(raw)
        verdict = _fast_verdict(raw)
        adjudication = None
        rounds = 1
    else:
        raw = asyncio.run(engine.run_deep(topic, background))
        transcript = list(raw.get("transcript") or [])
        verdict = dict(raw.get("verdict") or {
            "summary": "裁判未返回裁决", "winner": None,
            "key_insights": [], "topic_angle": "",
        })
        verdict["winner"] = _normalize_winner(verdict.get("winner"))
        adjudication = None
        try:
            adj = adjudicator or Adjudicator(llm_fn=llm_fn)
            adj_result = adj.adjudicate(topic, transcript, verdict)
            adjudication = adj_result.to_dict() if hasattr(adj_result, "to_dict") else adj_result
        except Exception as exc:  # noqa: BLE001 — adjudication FAIL-OPEN
            adjudication = None
            degraded = True
            verdict = dict(verdict)
            verdict.setdefault("summary", "")
            verdict["summary"] = (verdict.get("summary", "") + f" [adjudication_failed:{type(exc).__name__}]").strip()
        rounds = 2

    meta = {
        "provider": getattr(llm, "provider", "injected"),
        "model": getattr(llm, "model", None),
        "mode": mode,
        "profile": profile,
        "backend": "dsh",
        "adjudication": adjudication is not None,
        "degraded": degraded,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }
    return {
        "schema_version": "debate-result-v1",
        "debate_id": debate_id or uuid.uuid4().hex[:12],
        "status": "completed",
        "mode": mode,
        "topic": topic,
        "rounds": rounds,
        "transcript": transcript,
        "verdict": verdict,
        "adjudication": adjudication,
        "research": research_meta,
        "meta": meta,
        "error": "",
    }