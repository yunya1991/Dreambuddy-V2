"""l1.intent.mcp 三工具契约测试（零 token / 纯确定性 / 无外部依赖）。

覆盖：
  C1 tools/list 精确 = [list_intents, classify_intent, execute_intent]
  C2 initialize / ping / serverInfo.name 正确
  C3 list_intents 返回 12 个意图 + 描述
  C4 classify_intent 空/非空/未命中/边界（置信度 0.8 fallback, 1.0 required）
  C5 execute_intent 命中/未命中 + l1_hit + zero_token meta
  C6 与 TS 侧 l1-intent-registry.test.ts 对齐（交叉验证，漂移门禁）
  C7 所有工具 annotations.readOnlyHint=true，无 write
  C8 壳零业务逻辑（_INTENT_REGISTRY 与 TS 正则镜像）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_shells.l1_intent import server  # noqa: E402

# ── TS 对齐测试用例（与 3.1-FRONTEND/src/lib/l1-intent-registry.test.ts 同源） ──
TS_ALIGN_CASES = [
    # (query, expected_intent_or_None)
    ("查一下 CPI 最新数据", "data_query"),
    ("帮我写首诗", None),
    ("当前持仓风控状态", "risk_control"),
    ("BTC 现在什么价", "price_query"),
    ("今天天气咋样", None),
    ("最小阻力路径该多还是空", "path_insight"),
    ("FOMC 会议结果超预期", "event_analysis"),
    ("估值百分位高不高", "fundamental_valuation"),
    ("技术面置信度多少", "technical_analysis"),
    ("美股和加密现在趋势如何", "asset_class_trend"),
    ("最近有什么金融新闻", "event_listing"),
    ("帮我检索一下交易 SPEC", "doc_search"),
    ("资金面和技术面出现矛盾吗", "contradiction_insight"),
]


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    """构造 MCP JSON-RPC 2.0 请求并直接调用壳 handler。"""
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return server._handle_request(req)


def _content_text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


# ════════════════════════════════════════════════════════════════════════════
# C1 tools/list
# ════════════════════════════════════════════════════════════════════════════


def test_tools_list_exact_three_tools():
    resp = _rpc("tools/list")
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"list_intents", "classify_intent", "execute_intent"}


def test_tools_list_all_readonly_hint():
    """硬约束 H1 继承：L1 intent 壳全只读，无 write 能力。"""
    resp = _rpc("tools/list")
    for tool in resp["result"]["tools"]:
        ann = tool.get("annotations", {})
        assert ann.get("readOnlyHint") is True, f"{tool['name']} readOnlyHint must be true"
    assert all(t["name"] != "forward_signal" for t in resp["result"]["tools"])


# ════════════════════════════════════════════════════════════════════════════
# C2 initialize / ping
# ════════════════════════════════════════════════════════════════════════════


def test_initialize():
    init = _rpc("initialize")
    assert init["result"]["serverInfo"]["name"] == "l1.intent.mcp"
    assert init["result"]["serverInfo"]["version"] == "0.1"


def test_ping():
    ping = _rpc("ping")
    assert ping["result"] == {}


# ════════════════════════════════════════════════════════════════════════════
# C3 list_intents
# ════════════════════════════════════════════════════════════════════════════


def test_list_intents_returns_twelve_intents():
    resp = _rpc("tools/call", {"name": "list_intents", "arguments": {}})
    payload = json.loads(_content_text(resp))
    assert payload["total"] == 12
    intents = {i["intent"] for i in payload["intents"]}
    expected = {
        "data_query",
        "data_insight",
        "contradiction_insight",
        "path_insight",
        "technical_analysis",
        "fundamental_valuation",
        "asset_class_trend",
        "event_analysis",
        "risk_control",
        "price_query",
        "event_listing",
        "doc_search",
    }
    assert intents == expected


def test_list_intents_each_has_description():
    resp = _rpc("tools/call", {"name": "list_intents", "arguments": {}})
    payload = json.loads(_content_text(resp))
    for i in payload["intents"]:
        assert isinstance(i["description"], str) and len(i["description"]) > 0
    assert payload["source"] == "l1-intent-registry.ts"


# ════════════════════════════════════════════════════════════════════════════
# C4 classify_intent（Pass 1 fallback 优先 + Pass 2 required 兜底）
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("query,expected", TS_ALIGN_CASES)
def test_classify_intent_aligns_with_ts(query: str, expected: str | None):
    """与 TS l1-intent-registry.test.ts 对齐（漂移门禁 C6）。"""
    resp = _rpc("tools/call", {"name": "classify_intent", "arguments": {"query": query}})
    payload = json.loads(_content_text(resp))
    if expected is None:
        assert payload["matched"] is False
        assert payload["intent"] is None
    else:
        assert payload["matched"] is True
        assert payload["intent"] == expected
        assert payload["confidence"] in (0.8, 1.0)
        assert payload["pattern_type"] in ("fallback", "required")


def test_classify_intent_fallback_confidence():
    resp = _rpc("tools/call", {"name": "classify_intent", "arguments": {"query": "BTC 现在什么价"}})
    payload = json.loads(_content_text(resp))
    assert payload["matched"] is True
    assert payload["intent"] == "price_query"
    assert payload["confidence"] == 0.8
    assert payload["pattern_type"] == "fallback"


def test_classify_intent_required_confidence():
    resp = _rpc(
        "tools/call", {"name": "classify_intent", "arguments": {"query": "查一下 CPI 最新数据"}}
    )
    payload = json.loads(_content_text(resp))
    assert payload["matched"] is True
    assert payload["intent"] == "data_query"
    assert payload["confidence"] == 1.0
    assert payload["pattern_type"] == "required"


def test_classify_intent_empty_query_rejected():
    """空/非字符串 query → ok=false（工具级输入校验）。"""
    resp = _rpc("tools/call", {"name": "classify_intent", "arguments": {"query": ""}})
    payload = json.loads(_content_text(resp))
    assert payload.get("ok") is False
    assert payload.get("error_code") == "invalid"

    resp2 = _rpc("tools/call", {"name": "classify_intent", "arguments": {"query": 42}})
    payload2 = json.loads(_content_text(resp2))
    assert payload2.get("ok") is False


def test_classify_intent_no_match_fails_open():
    """未命中 → matched=False，但 ok=true（工具正常返回，FAIL-OPEN 语义）。"""
    resp = _rpc("tools/call", {"name": "classify_intent", "arguments": {"query": "今天天气咋样"}})
    payload = json.loads(_content_text(resp))
    assert payload.get("ok", True) is True  # 壳正常
    assert payload["matched"] is False


def test_classify_intent_fallback_takes_precedence_over_required():
    """关键行为：同 query 同时命中 data_query.requiredPattern（含"当前"）和 risk_control.fallbackPattern
    时，fallback 意图优先命中（与 TS 侧 canHandleL1 行为一致）。"""
    resp = _rpc(
        "tools/call", {"name": "classify_intent", "arguments": {"query": "当前持仓风控状态"}}
    )
    payload = json.loads(_content_text(resp))
    assert payload["matched"] is True
    assert payload["intent"] == "risk_control"  # 不是 data_query
    assert payload["pattern_type"] == "fallback"


# ════════════════════════════════════════════════════════════════════════════
# C5 execute_intent
# ════════════════════════════════════════════════════════════════════════════


def test_execute_intent_hit_returns_context():
    resp = _rpc(
        "tools/call", {"name": "execute_intent", "arguments": {"query": "查一下 CPI 最新数据"}}
    )
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["executed"] is True
    assert payload["l1_hit"] is True
    assert payload["intent_name"] == "data_query"
    assert payload["classification"]["intent"] == "data_query"
    assert payload["classification"]["confidence"] == 1.0
    assert payload["classification"]["pattern_type"] == "required"
    assert payload["context"]["query"] == "查一下 CPI 最新数据"
    assert payload["meta"]["zero_token"] is True
    assert payload["meta"]["source"] == "l1.intent.mcp"


def test_execute_intent_miss_returns_l1_hit_false():
    resp = _rpc("tools/call", {"name": "execute_intent", "arguments": {"query": "帮我写首诗"}})
    payload = json.loads(_content_text(resp))
    assert payload["ok"] is True
    assert payload["executed"] is False
    assert payload["l1_hit"] is False
    assert "走 L2" in payload["reason"]


def test_execute_intent_contract_says_zero_token_always():
    """硬约束：l1.intent 壳所有执行路径零 token（不调任何 LLM）。"""
    cases = ["查一下 CPI 最新数据", "当前持仓风控状态", "帮我写首诗", "技术面置信度多少"]
    for q in cases:
        resp = _rpc("tools/call", {"name": "execute_intent", "arguments": {"query": q}})
        payload = json.loads(_content_text(resp))
        if "meta" in payload:
            assert payload["meta"]["zero_token"] is True, f"query={q!r} violated zero_token"


def test_execute_intent_empty_rejected():
    resp = _rpc("tools/call", {"name": "execute_intent", "arguments": {"query": ""}})
    payload = json.loads(_content_text(resp))
    assert payload.get("ok") is False
    assert payload.get("error_code") == "invalid"


# ════════════════════════════════════════════════════════════════════════════
# C8 壳零业务逻辑（_INTENT_REGISTRY 与 TS 数量对齐）
# ════════════════════════════════════════════════════════════════════════════


def test_intent_registry_size_matches_ts():
    """漂移门禁：Python _INTENT_REGISTRY 数量必须 == TS 侧 12 意图。"""
    assert len(server._INTENT_REGISTRY) == 12


def test_intent_registry_has_no_llm_dependency():
    """硬约束 H1：l1.intent 是纯确定性壳，不含任何 LLM 调用。"""
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    forbidden = [
        "openai",
        "chat.completion",
        "anthropic",
        "model_response",
        "llm",
        "langchain",
        "transformers",
    ]
    for kw in forbidden:
        assert kw.lower() not in source.lower(), f"禁止词 {kw!r} 出现在 l1.intent 源码"
