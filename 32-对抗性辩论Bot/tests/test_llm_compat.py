"""llm_compat 单元测试：provider 自动探测、客户端构造、健康检查。"""
import asyncio

import pytest

from core import llm_compat
from core.llm_compat import LLMUnavailable, LLMSettings, create_llm_client, health_check


def _clear_llm_env(monkeypatch):
    for key in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_auto_anthropic(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    client = create_llm_client(LLMSettings(provider="auto"))
    assert client.provider == "anthropic"


def test_auto_openai_compat(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-token")
    client = create_llm_client(LLMSettings(provider="auto"))
    assert client.provider == "openai_compat"


def test_missing_config_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    with pytest.raises(LLMUnavailable):
        create_llm_client(LLMSettings(provider="anthropic"))


def test_health_check_ok(monkeypatch):
    class FakeLLM:
        provider = "fake"
        model = "fake-model"

        async def chat(self, system_prompt, user_prompt, max_tokens=None):
            return "OK"

    monkeypatch.setattr(llm_compat, "create_llm_client", lambda settings: FakeLLM())
    result = asyncio.run(health_check())
    assert result["ok"] is True
    assert result["provider"] == "fake"
    assert result["reply"] == "OK"


def test_health_check_failure(monkeypatch):
    def _boom(settings):
        raise LLMUnavailable("no key")

    monkeypatch.setattr(llm_compat, "create_llm_client", _boom)
    result = asyncio.run(health_check())
    assert result["ok"] is False
    assert "no key" in result["error"]