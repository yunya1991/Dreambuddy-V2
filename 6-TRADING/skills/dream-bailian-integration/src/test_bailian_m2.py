#!/usr/bin/env python3
"""M2: 百炼集成 KB+RAG+Function Calling 测试

覆盖 BailianClient 新增 3 个方法:
- chat_with_tools: OpenAI 兼容 Function Calling 调用
- kb_query: 百炼 RAG 应用查询 (无 APP_ID 时 informative error)
- rag_retrieve: 向量库召回 (无 collection 时 informative error)

测试策略: mock _call_api 避免实际网络调用.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 让 src/ 可导入
SRC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_DIR))

from bailian_client import BailianClient, BailianAPIError  # type: ignore


class _MockResponse:
    """模拟 urlopen 响应"""
    def __init__(self, payload: Dict[str, Any], status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _make_client_with_mock(mock_payload: Dict[str, Any],
                            captured: Optional[List[Dict[str, Any]]] = None) -> BailianClient:
    """构造 BailianClient, _call_api 全部走 mock"""
    client = BailianClient(api_key="sk-test-mock-key")
    if captured is None:
        captured = []

    def _mock_call(endpoint: str, data: Dict[str, Any],
                    method: str = "POST", trace_id: Optional[str] = None) -> Dict[str, Any]:
        captured.append({"endpoint": endpoint, "data": data, "method": method})
        return mock_payload

    client._call_api = _mock_call  # type: ignore[assignment]
    return client


# ── chat_with_tools 测试 ─────────────────────────

def test_chat_with_tools_sends_tools_and_tool_choice():
    """chat_with_tools 正确构造 tools/tool_choice/temperature"""
    captured: List[Dict[str, Any]] = []
    mock_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_price", "arguments": '{"symbol":"BTC"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }
    client = _make_client_with_mock(mock_resp, captured)

    tools = [{
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "获取最新价格",
            "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}},
        },
    }]
    result = client.chat_with_tools(
        messages=[{"role": "user", "content": "BTC 价格?"}],
        tools=tools,
        tool_choice="auto",
    )

    assert result == mock_resp
    assert len(captured) == 1
    call = captured[0]
    assert call["endpoint"] == "/chat/completions"
    assert call["data"]["tools"] == tools
    assert call["data"]["tool_choice"] == "auto"
    # 默认低温度 0.2 保证 Function Calling 确定性
    assert call["data"]["temperature"] == 0.2


def test_chat_with_tools_custom_temperature_overrides_default():
    """显式 temperature 覆盖默认 0.2"""
    captured: List[Dict[str, Any]] = []
    client = _make_client_with_mock({"choices": [{"message": {"content": "ok"}}]}, captured)

    client.chat_with_tools(
        messages=[{"role": "user", "content": "x"}],
        tools=[],
        temperature=0.8,
    )
    assert captured[0]["data"]["temperature"] == 0.8


def test_chat_with_tools_max_tokens_passed_when_set():
    """max_tokens 设置时透传"""
    captured: List[Dict[str, Any]] = []
    client = _make_client_with_mock({"choices": [{"message": {"content": "ok"}}]}, captured)

    client.chat_with_tools(
        messages=[{"role": "user", "content": "x"}],
        tools=[],
        max_tokens=512,
    )
    assert captured[0]["data"]["max_tokens"] == 512


def test_chat_with_tools_extracts_tool_calls():
    """Function Calling 模型响应含 tool_calls"""
    mock_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_price", "arguments": '{"symbol":"ETH"}'},
                }],
            },
        }],
    }
    client = _make_client_with_mock(mock_resp)
    result = client.chat_with_tools(
        messages=[{"role": "user", "content": "ETH?"}],
        tools=[{"type": "function", "function": {"name": "get_price", "parameters": {}}}],
    )
    tool_calls = result["choices"][0]["message"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "get_price"
    args = json.loads(tool_calls[0]["function"]["arguments"])
    assert args["symbol"] == "ETH"


# ── kb_query 测试 ────────────────────────────────

def test_kb_query_without_app_id_returns_informative_error(monkeypatch):
    """无 BAILIAN_APP_ID 时返回 informative error, 不抛异常"""
    monkeypatch.delenv("BAILIAN_APP_ID", raising=False)
    client = BailianClient(api_key="sk-test")

    result = client.kb_query("BTC 趋势?")

    assert result["success"] is False
    assert "BAILIAN_APP_ID" in result["error"]
    assert "hint" in result


def test_kb_query_with_app_id_calls_apps_endpoint(monkeypatch):
    """有 BAILIAN_APP_ID 时调用 apps/{app_id}/completion 端点"""
    monkeypatch.setenv("BAILIAN_APP_ID", "app_abc123")
    captured: List[Dict[str, Any]] = []
    client = _make_client_with_mock(
        {"output": {"text": "BTC 看涨"}, "references": [{"doc": "ref1"}]},
        captured,
    )

    result = client.kb_query("BTC 趋势?", top_k=3)

    assert "output" in result
    assert captured[0]["endpoint"] == "apps/app_abc123/completion"
    assert captured[0]["data"]["input"]["prompt"] == "BTC 趋势?"
    assert captured[0]["data"]["parameters"]["top_k"] == 3


def test_kb_query_explicit_app_id_overrides_env(monkeypatch):
    """显式 application_id 参数覆盖环境变量"""
    monkeypatch.setenv("BAILIAN_APP_ID", "env_app")
    captured: List[Dict[str, Any]] = []
    client = _make_client_with_mock({"output": {"text": "ok"}}, captured)

    client.kb_query("test", application_id="explicit_app")

    assert captured[0]["endpoint"] == "apps/explicit_app/completion"


# ── rag_retrieve 测试 ───────────────────────────

def test_rag_retrieve_without_collection_returns_informative_error(monkeypatch):
    """无 BAILIAN_COLLECTION 时返回 informative error"""
    monkeypatch.delenv("BAILIAN_COLLECTION", raising=False)
    client = BailianClient(api_key="sk-test")

    result = client.rag_retrieve("BTC")

    assert result["success"] is False
    assert "BAILIAN_COLLECTION" in result["error"]
    assert "hint" in result


def test_rag_retrieve_with_collection_calls_embed_then_search(monkeypatch):
    """有 collection 时先 embed 再向量检索"""
    monkeypatch.setenv("BAILIAN_COLLECTION", "test_collection")
    captured: List[Dict[str, Any]] = []
    # 第一次 embed, 第二次 search
    responses = [
        {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        {"matches": [{"id": "doc1", "score": 0.95}]},
    ]
    resp_idx = [0]
    client = BailianClient(api_key="sk-test")

    def _mock_call(endpoint: str, data: Dict[str, Any],
                    method: str = "POST", trace_id=None) -> Dict[str, Any]:
        captured.append({"endpoint": endpoint, "data": data})
        r = responses[resp_idx[0]]
        resp_idx[0] += 1
        return r

    client._call_api = _mock_call  # type: ignore

    result = client.rag_retrieve("BTC 上涨原因", top_k=5)

    assert "matches" in result
    assert len(captured) == 2
    # 第一次 embed
    assert captured[0]["endpoint"] == "/embeddings"
    assert captured[0]["data"]["input"] == ["BTC 上涨原因"]
    # 第二次向量检索
    assert captured[1]["endpoint"] == "vector-service/search"
    assert captured[1]["data"]["collection"] == "test_collection"
    assert captured[1]["data"]["query_vector"] == [0.1, 0.2, 0.3]
    assert captured[1]["data"]["top_k"] == 5


def test_rag_retrieve_embed_failure_returns_error(monkeypatch):
    """embed 失败时返回 informative error, 不抛异常"""
    monkeypatch.setenv("BAILIAN_COLLECTION", "test_collection")
    client = BailianClient(api_key="sk-test")

    def _bad_call(endpoint: str, data: Dict[str, Any],
                    method: str = "POST", trace_id=None) -> Dict[str, Any]:
        if "embeddings" in endpoint:
            raise BailianAPIError(code=401, message="bad api key", trace_id="t1")
        return {}

    client._call_api = _bad_call  # type: ignore

    result = client.rag_retrieve("test")
    assert result["success"] is False
    assert "embed" in result["error"]


# ── HC-1 FAIL-OPEN 集成测试 ──────────────────────

def test_bailian_client_no_api_key_raises_value_error():
    """无 API key 时 BailianClient 构造失败 (显式 raise, 由调用方 try/except 兜底)"""
    # BailianClient 强制要求 API key — 这是 M2 客户端层的行为契约
    # 真正的 FAIL-OPEN 在 subagent_registry.make_bailian_llm_fn() (M3 已实现)
    import os as _os
    saved = _os.environ.pop("BAILIAN_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="API Key"):
            BailianClient()
    finally:
        if saved is not None:
            _os.environ["BAILIAN_API_KEY"] = saved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
