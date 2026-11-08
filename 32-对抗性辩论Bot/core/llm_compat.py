"""llm_compat.py — 无 LangChain 依赖的 LLM 适配层。

支持：
- anthropic：Anthropic Messages API（含 Claude Code 代理，读取
  ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL）
- openai_compat：OpenAI 兼容接口（DashScope / OpenAI / 自建网关）
- langchain：兼容旧的 core.llm_adapter（可选，未安装时明确报错）

设计目标：
- 任何 agent 只需 `await llm.chat(system, user, max_tokens)`；
- `health_check()` 可在 CLI/MCP 中做连通性自检；
- 失败重试 + 超时，不让一次网络抖动毁掉整场辩论。
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any


class LLMUnavailable(RuntimeError):
    """没有可用的 LLM 配置/依赖。"""


@dataclass
class LLMSettings:
    provider: str = "auto"          # auto | anthropic | openai_compat | langchain
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_sec: float = 90.0
    max_retries: int = 2
    max_tokens: int = 2000
    extra: dict = field(default_factory=dict)


class BaseLLM:
    provider = "base"

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.model = settings.model

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int | None = None) -> str:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.settings.base_url,
            "timeout_sec": self.settings.timeout_sec,
        }


def _text_from_blocks(blocks: Any) -> str:
    parts: list[str] = []
    for block in blocks or []:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


class AnthropicLLM(BaseLLM):
    provider = "anthropic"

    def __init__(self, settings: LLMSettings):
        super().__init__(settings)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise LLMUnavailable("anthropic 未安装：pip install anthropic") from exc

        self.api_key = settings.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        self.settings.base_url = settings.base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self.model = settings.model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-latest[1M]"
        if not self.api_key or not self.settings.base_url:
            raise LLMUnavailable(
                "Anthropic 配置缺失：需要 ANTHROPIC_AUTH_TOKEN 与 ANTHROPIC_BASE_URL"
            )
        self.client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.settings.base_url,
            timeout=settings.timeout_sec,
            max_retries=0,
            default_headers={"Authorization": f"Bearer {self.api_key}"},
        )

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                resp = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.settings.max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return _text_from_blocks(resp.content)
            except Exception as exc:  # noqa: BLE001 - 重试后抛出
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                await asyncio.sleep(min(2 ** attempt, 4))
        raise LLMUnavailable(f"Anthropic 调用失败: {last_error}") from last_error


class OpenAICompatLLM(BaseLLM):
    provider = "openai_compat"

    def __init__(self, settings: LLMSettings):
        super().__init__(settings)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise LLMUnavailable("openai 未安装：pip install openai") from exc

        dashscope_key = os.environ.get("DASHSCOPE_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        self.api_key = settings.api_key or dashscope_key or openai_key
        base_url = settings.base_url
        if not base_url and dashscope_key:
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.settings.base_url = base_url
        self.model = settings.model or ("qwen-plus" if dashscope_key else "gpt-4o-mini")
        if not self.api_key:
            raise LLMUnavailable(
                "OpenAI 兼容接口缺少 key：DASHSCOPE_API_KEY / OPENAI_API_KEY / llm.api_key"
            )
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=settings.timeout_sec,
            max_retries=0,
        )

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens or self.settings.max_tokens,
                    temperature=0.7,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001 - 重试后抛出
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                await asyncio.sleep(min(2 ** attempt, 4))
        raise LLMUnavailable(f"OpenAI 兼容调用失败: {last_error}") from last_error


class LangChainLLM(BaseLLM):
    provider = "langchain"

    def __init__(self, settings: LLMSettings):
        super().__init__(settings)
        try:
            from core.llm_adapter import create_llm_adapter
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(
                "LangChain 适配不可用（缺 langchain 依赖或 llm_factory 导入失败）；"
                "请改用 provider=anthropic 或 openai_compat"
            ) from exc
        self._inner = create_llm_adapter(model_name=settings.model or "qwen-plus")

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int | None = None) -> str:
        return await self._inner.chat(
            system_prompt, user_prompt,
            max_tokens or self.settings.max_tokens,
        )


def _resolve_auto_provider() -> str:
    if os.environ.get("ANTHROPIC_AUTH_TOKEN") and os.environ.get("ANTHROPIC_BASE_URL"):
        return "anthropic"
    if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "openai_compat"
    return "anthropic"


def create_llm_client(settings: LLMSettings | None = None) -> BaseLLM:
    settings = settings or LLMSettings()
    provider = (settings.provider or "auto").strip().lower()
    if provider == "auto":
        provider = _resolve_auto_provider()
    if provider == "anthropic":
        return AnthropicLLM(settings)
    if provider in ("openai_compat", "openai", "qwen_compat"):
        return OpenAICompatLLM(settings)
    if provider in ("langchain", "qwen"):
        return LangChainLLM(settings)
    raise LLMUnavailable(f"未知 provider: {settings.provider!r}")


async def health_check(settings: LLMSettings | None = None) -> dict[str, Any]:
    """轻量连通性自检：返回结构化结果，不抛异常。"""
    started = time.perf_counter()
    try:
        client = create_llm_client(settings)
        text = await client.chat(
            "你是健康检查助手。只回复 OK，不要解释。",
            "ping",
            max_tokens=8,
        )
        return {
            "ok": True,
            "provider": client.provider,
            "model": client.model,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "reply": text.strip()[:40],
        }
    except Exception as exc:  # noqa: BLE001 - 健康检查本身不抛
        return {
            "ok": False,
            "provider": (settings.provider if settings else "auto"),
            "model": (settings.model if settings else None),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }