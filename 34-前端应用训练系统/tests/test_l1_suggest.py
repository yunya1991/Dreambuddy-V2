# -*- coding: utf-8 -*-
"""建议器实盘测试：只挂 L2、query 可命中 S1、超时/关闭降级。"""

import os
import sys
import time

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "3.1-FRONTEND", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402
import l1_suggest as sug  # noqa: E402


@pytest.fixture
def examples(monkeypatch):
    monkeypatch.setattr(sug, "_embed_server_ready", lambda: True)
    monkeypatch.setattr(sug, "_load_examples", lambda intent: ["BTC现在什么价格", "ETH最新价"])
    monkeypatch.setattr(
        lrs, "semantic_candidates", lambda m, k=3: [("price_query", 0.82), ("data_query", 0.71)]
    )


def test_disabled_returns_empty(monkeypatch, examples):
    monkeypatch.setenv("L1_SUGGEST_ENABLED", "0")
    assert sug.build_suggestions("随便问问") == []


def test_build_returns_canonical_queries(examples):
    out = sug.build_suggestions("这东西怎么样")
    assert out
    assert out[0]["intent"] == "price_query"
    assert lrs.detect_intent_regex(out[0]["query"]) == "price_query"
    assert out[0]["query"] != "这东西怎么样"


def test_excludes_current_message(monkeypatch, examples):
    monkeypatch.setattr(sug, "_load_examples", lambda intent: ["这东西怎么样"])
    assert sug.build_suggestions("这东西怎么样") == []


def test_timeout_degrades_to_empty(monkeypatch, examples):
    monkeypatch.setenv("L1_SUGGEST_BUDGET_MS", "5")

    def _slow(m, k=3):
        time.sleep(0.2)
        return [("price_query", 0.9)]

    monkeypatch.setattr(lrs, "semantic_candidates", _slow)
    assert sug.build_suggestions("慢查询") == []
    time.sleep(0.25)  # 等后台任务结束，避免污染后续用例的单线程池


def test_route_query_l2_has_suggestions(monkeypatch, examples):
    monkeypatch.setenv("L1_SUGGEST_ENABLED", "1")
    out = lrs.route_query("你好")
    assert out["handled"] is False
    assert isinstance(out.get("suggestions"), list)
    assert out["suggestions"]


def test_route_query_l1_has_no_suggestions(monkeypatch, examples):
    monkeypatch.setenv("L1_ROUTING_STRATEGY", "S1")
    monkeypatch.setitem(
        lrs.EXECUTORS, "price_query", lambda m: {"success": True, "answer": "ok", "data": {}}
    )
    monkeypatch.setattr(lrs, "settle_to_cognitive", lambda *a, **k: None)
    out = lrs.route_query("BTC现在什么价格")
    assert out["handled"] is True
    assert "suggestions" not in out
