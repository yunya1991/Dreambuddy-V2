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
import os
import time
import logging

logger = logging.getLogger(__name__)


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
# DeepSeek LLM (OpenAI 兼容接口, V4-Pro)
# ============================================================

class DeepSeekLLMClient(LLMClient):
    """DeepSeek LLM 客户端 — OpenAI 兼容接口

    通过 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL 环境变量配置。
    失败时降级返回 NoOp 响应,确保节点不会因 LLM 异常而中断。
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
        self._session = None
        self._max_retries = 2
        self._timeout = 60
        # 延迟导入 requests,避免无网络环境加载失败
        try:
            import requests
            self._requests = requests
        except ImportError:
            self._requests = None
            logger.warning("requests 未安装,DeepSeekLLMClient 将降级为 NoOp")

    def _get_session(self):
        if self._session is None and self._requests is not None:
            self._session = self._requests.Session()
            self._session.trust_env = False
        return self._session

    def chat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        # 无 api_key 或无 requests 时降级
        if not self.api_key or self._requests is None:
            return NoOpLLMClient().chat(messages, model, temperature, max_tokens, tools)

        used_model = model or self.model
        # 转换 LLMMessage → OpenAI 格式
        oai_messages = []
        for m in messages:
            oai_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": used_model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        s = self._get_session()
        last_err = None
        for attempt in range(self._max_retries + 1):
            try:
                t0 = time.time()
                r = s.post(url, json=payload, headers=headers, timeout=self._timeout)
                latency_ms = (time.time() - t0) * 1000
                if r.status_code == 429:
                    # 限流,等待后重试
                    time.sleep(1.5 * (attempt + 1))
                    last_err = f"rate_limited:{r.status_code}"
                    continue
                if r.status_code != 200:
                    last_err = f"http_{r.status_code}:{r.text[:200]}"
                    logger.warning(f"DeepSeek 调用失败 (attempt {attempt+1}): {last_err}")
                    time.sleep(0.5 * (attempt + 1))
                    continue
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return LLMResponse(
                    content=content,
                    model=data.get("model", used_model),
                    tokens_input=usage.get("prompt_tokens", 0),
                    tokens_output=usage.get("completion_tokens", 0),
                    latency_ms=latency_ms,
                    finish_reason=data.get("choices", [{}])[0].get("finish_reason", "stop"),
                    raw=data,
                )
            except Exception as e:
                last_err = str(e)
                logger.warning(f"DeepSeek 调用异常 (attempt {attempt+1}): {e}")
                time.sleep(0.5 * (attempt + 1))

        # 全部重试失败,降级返回
        logger.error(f"DeepSeek 全部重试失败,降级 NoOp: {last_err}")
        return NoOpLLMClient().chat(messages, model, temperature, max_tokens, tools)

    async def achat(self, messages, model=None, temperature=0.7, max_tokens=None, tools=None):
        # 简化异步实现:委托给同步 chat
        return self.chat(messages, model, temperature, max_tokens, tools)

    def count_tokens(self, messages):
        # 粗略估算:4 字符 ≈ 1 token
        return sum(len(m.content) // 4 for m in messages)


# ============================================================
# 工厂
# ============================================================

_default_client: Optional[LLMClient] = None


def get_default_client() -> LLMClient:
    """获取默认 LLM 客户端（单例）

    优先级:
        1. 已通过 set_default_client 显式设置的
        2. DEEPSEEK_API_KEY 环境变量存在 → DeepSeekLLMClient
        3. 兜底 → NoOpLLMClient
    """
    global _default_client
    if _default_client is None:
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if deepseek_key:
            _default_client = DeepSeekLLMClient()
            logger.info(f"LLM 默认客户端: DeepSeek (model={_default_client.model})")
        else:
            _default_client = NoOpLLMClient()
            logger.info("LLM 默认客户端: NoOp (未配置 DEEPSEEK_API_KEY)")
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
