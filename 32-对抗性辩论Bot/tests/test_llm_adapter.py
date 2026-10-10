"""test_llm_adapter.py — LLMAdapter 单元测试（TDD RED phase）

测试 P0-1：将 llm_factory 返回的 LangChain ChatModel 包装为 LLMClient Protocol。

LLMClient 接口（来自 core.agents）：
    async def chat(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str

LangChain ChatModel 接口：
    async def ainvoke(messages: list[BaseMessage]) -> AIMessage
        messages 支持 SystemMessage / HumanMessage
"""
from __future__ import annotations

from typing import Sequence

import pytest

from core.llm_adapter import LLMAdapter


# ─── Mock LangChain ChatModel ───────────────────────────────────

class MockChatModel:
    """模拟 LangChain ChatModel 的 ainvoke 接口。"""

    def __init__(self, responses: Sequence[str] | str = "mock response"):
        self._responses = list(responses) if isinstance(responses, (list, tuple)) else [responses]
        self._idx = 0
        self.calls: list[list] = []  # 记录每次 ainvoke 的 messages

    async def ainvoke(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": kwargs})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return _FakeAIMessage(resp)
        raise RuntimeError("MockChatModel: no more responses")


class _FakeAIMessage:
    """模拟 LangChain AIMessage（有 content 属性）。"""

    def __init__(self, content: str):
        self.content = content


# ─── 基本接口测试 ────────────────────────────────────────────────

class TestLLMAdapterBasic:
    """测试 LLMAdapter 基本接口。"""

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() 返回 str（LLM 输出文本）。"""
        model = MockChatModel("hello world")
        adapter = LLMAdapter(model)
        result = await adapter.chat("sys", "user")
        assert isinstance(result, str)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_chat_passes_system_and_user_messages(self):
        """chat(system_prompt, user_prompt) 构造 SystemMessage + HumanMessage。"""
        model = MockChatModel("resp")
        adapter = LLMAdapter(model)
        await adapter.chat("你是助手", "你好")
        messages = model.calls[0]["messages"]
        # 第一条是 system 消息
        assert messages[0].type == "system"
        assert messages[0].content == "你是助手"
        # 第二条是 human 消息
        assert messages[1].type == "human"
        assert messages[1].content == "你好"

    @pytest.mark.asyncio
    async def test_chat_uses_max_tokens(self):
        """max_tokens 参数被传递到 ainvoke 调用。"""
        model = MockChatModel("resp")
        adapter = LLMAdapter(model)
        await adapter.chat("sys", "user", max_tokens=123)
        assert model.calls[0]["kwargs"].get("max_tokens") == 123


# ─── max_tokens 传递测试 ────────────────────────────────────────

class TestMaxTokensPassing:
    """测试 max_tokens 参数传递。"""

    @pytest.mark.asyncio
    async def test_max_tokens_default_600(self):
        """默认 max_tokens=600。"""
        calls = []

        class CaptureModel:
            async def ainvoke(self, messages, **kwargs):
                calls.append(kwargs)
                return _FakeAIMessage("ok")

        adapter = LLMAdapter(CaptureModel())
        await adapter.chat("sys", "user")
        assert calls[0].get("max_tokens") == 600

    @pytest.mark.asyncio
    async def test_max_tokens_custom(self):
        """自定义 max_tokens 被传递。"""
        calls = []

        class CaptureModel:
            async def ainvoke(self, messages, **kwargs):
                calls.append(kwargs)
                return _FakeAIMessage("ok")

        adapter = LLMAdapter(CaptureModel())
        await adapter.chat("sys", "user", max_tokens=800)
        assert calls[0].get("max_tokens") == 800


# ─── 异常处理测试 ────────────────────────────────────────────────

class TestErrorHandling:
    """测试 LLM 调用异常处理。"""

    @pytest.mark.asyncio
    async def test_ainvoke_error_propagates(self):
        """ainvoke 抛出异常时，chat() 向上传播。"""

        class ErrorModel:
            async def ainvoke(self, messages, **kwargs):
                raise RuntimeError("API rate limit")

        adapter = LLMAdapter(ErrorModel())
        with pytest.raises(RuntimeError, match="rate limit"):
            await adapter.chat("sys", "user")


# ─── create_llm_adapter 工厂测试 ─────────────────────────────────

class TestCreateLLMAdapter:
    """测试 create_llm_adapter 工厂函数（基于 config 创建）。"""

    def test_create_with_dict_config(self, monkeypatch):
        """传入 dict config（符合 llm_factory 格式）创建 adapter。"""
        import core.llm_adapter as mod

        def fake_create_llm(config):
            return MockChatModel("ok")

        monkeypatch.setattr(mod, "create_llm", fake_create_llm)

        cfg = {"llm": {"provider": "qwen", "model": "qwen-turbo"}}
        adapter = mod.create_llm_adapter(cfg)
        assert isinstance(adapter, LLMAdapter)

    def test_create_with_model_name_only(self, monkeypatch):
        """仅传 model_name 快捷创建（默认 qwen provider）。"""
        import core.llm_adapter as mod

        def fake_create_llm(config):
            return MockChatModel("ok")

        monkeypatch.setattr(mod, "create_llm", fake_create_llm)

        adapter = mod.create_llm_adapter(model_name="qwen-turbo")
        assert isinstance(adapter, LLMAdapter)

    def test_create_missing_config_raises(self):
        """无 config 且无 model_name → 抛 ValueError。"""
        from core.llm_adapter import create_llm_adapter

        with pytest.raises(ValueError):
            create_llm_adapter()
