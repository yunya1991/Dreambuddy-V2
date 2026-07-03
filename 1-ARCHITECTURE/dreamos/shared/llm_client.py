"""
Dreambuddy OS — LLM 客户端抽象

统一的 LLM 调用接口，支持:
    - 多 provider 切换 (OpenAI / Anthropic / 本地)
    - Token 计数和预算控制
    - 失败重试
    - 调用日志

P0 阶段提供接口和基础实现，具体 provider 适配在 P1+ 补充。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: str                              # system / user / assistant / tool
    content: str
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    role: str = "assistant"
    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    raw: Optional[Dict[str, Any]] = None

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output


class LLMClient(ABC):
    """LLM 客户端接口

    所有 provider 实现 this interface。
    通过 LLMClientFactory 创建具体实例。
    """

    @abstractmethod
    def chat(self, messages: List[LLMMessage],
             model: Optional[str] = None,
             temperature: float = 0.7,
             max_tokens: Optional[int] = None,
             tools: Optional[List[Dict]] = None) -> LLMResponse:
        """同步对话"""
        ...

    @abstractmethod
    async def achat(self, messages: List[LLMMessage],
                    model: Optional[str] = None,
                    temperature: float = 0.7,
                    max_tokens: Optional[int] = None,
                    tools: Optional[List[Dict]] = None) -> LLMResponse:
        """异步对话"""
        ...

    @abstractmethod
    def count_tokens(self, messages: List[LLMMessage]) -> int:
        """估算 token 数"""
        ...


# ============================================================
# 基础实现：NoOp LLM（开发/测试用）
# ============================================================

class NoOpLLMClient(LLMClient):
    """空操作 LLM 客户端 — 用于测试和开发阶段"""

    def chat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        return LLMResponse(
            content="[NoOp LLM] 模拟响应",
            tokens_input=sum(len(m.content) // 4 for m in messages),
            tokens_output=10,
            latency_ms=0.1,
        )

    async def achat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        return self.chat(messages, model, temperature, max_tokens, tools)

    def count_tokens(self, messages):
        return sum(len(m.content) // 4 for m in messages)


# ============================================================
# 工厂
# ============================================================

_default_client: Optional[LLMClient] = None


def get_default_client() -> LLMClient:
    """获取默认 LLM 客户端（单例）"""
    global _default_client
    if _default_client is None:
        _default_client = NoOpLLMClient()
    return _default_client


def set_default_client(client: LLMClient) -> None:
    """设置默认 LLM 客户端"""
    global _default_client
    _default_client = client


def make_messages(system: str = "", user: str = "",
                 history: Optional[List[LLMMessage]] = None) -> List[LLMMessage]:
    """便捷构造消息列表"""
    msgs: List[LLMMessage] = []
    if system:
        msgs.append(LLMMessage(role="system", content=system))
    if history:
        msgs.extend(history)
    if user:
        msgs.append(LLMMessage(role="user", content=user))
    return msgs
