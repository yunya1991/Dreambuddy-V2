# -*- coding: utf-8 -*-
"""S1 契约门控 + 复合问法闸（E2-D5）测试。

锁三条：
  1. 默认 S0 行为零变化（复合问法仍走原链路，不出现 compound_query）；
  2. S1 下复合问法交 L2、且不调用认知召回；
  3. S1 下有能力契约的意图直答（route_confidence=1.0）。
"""

import os
import sys

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "3.1-FRONTEND", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402


class _ExplodingL0:
    """任何召回调用都失败 → 证明 S1 不依赖认知记忆。"""

    def fetch_context(self, scope, params=None):
        raise AssertionError(f"S1 不应调用认知召回: {scope}")

    def settle(self, result, ctx):
        pass


def _mem(score):
    return {"id": f"VM-{score}", "content": "c", "score": score}


class _FakeL0:
    def __init__(self, memories):
        self._memories = memories

    def fetch_context(self, scope, params=None):
        return {"ok": True, "data": self._memories, "degraded": False, "meta": {}}

    def settle(self, result, ctx):
        pass


@pytest.fixture(autouse=True)
def _patch_executors(monkeypatch):
    for intent in list(lrs.EXECUTORS):
        monkeypatch.setitem(
            lrs.EXECUTORS, intent, lambda m: {"success": True, "answer": "ok", "data": {}}
        )
    monkeypatch.setattr(lrs, "settle_to_cognitive", lambda *a, **k: None)


class TestCompoundDetector:
    @pytest.mark.parametrize(
        "message",
        [
            "BTC价格和CPI数据",
            "黄金阻力位和BTC支撑位",
            "BTC现价、SOL现价、黄金现价",
            "非农数据和失业率数据",
            "以太坊新闻和BTC现价",
            "恐慌指数多少，多空比多少",
        ],
    )
    def test_positive(self, message):
        assert lrs.is_compound_query(message) is True

    def test_known_miss(self):
        """D5 已知漏网（E2 recall 78.8% 的余量）：同意图双时点问法，留待 P3a 能力目录。"""
        assert lrs.is_compound_query("下次CPI时间和下次议息时间") is False

    @pytest.mark.parametrize(
        "message",
        [
            "BTC和ETH涨跌幅对比",
            "SOL和ETH最近涨幅对比",
            "以太坊 最近新闻",
            "BTC现在什么价格",
            "现在能不能上车",
            "你好",
            "",
        ],
    )
    def test_negative(self, message):
        assert lrs.is_compound_query(message) is False


class TestS1Routing:
    def test_compound_handoff_without_recall(self, monkeypatch):
        monkeypatch.setenv("L1_ROUTING_STRATEGY", "S1")
        monkeypatch.setattr(lrs, "get_l0", lambda: _ExplodingL0())
        out = lrs.route_query("BTC价格和CPI数据")
        assert out["handled"] is False
        assert out["route_signal"]["decision"] == "L2_HANDOFF"
        assert "compound_query" in out["route_signal"]["reasons"]

    def test_contract_direct_without_recall(self, monkeypatch):
        monkeypatch.setenv("L1_ROUTING_STRATEGY", "S1")
        monkeypatch.setattr(lrs, "get_l0", lambda: _ExplodingL0())
        out = lrs.route_query("BTC现在什么价格")
        assert out["handled"] is True
        assert out["route_signal"]["decision"] == "L1_DIRECT"
        assert out["route_signal"]["route_confidence"] == 1.0
        assert "executor_contract_ok" in out["route_signal"]["reasons"]

    def test_no_executor_still_handoff(self, monkeypatch):
        monkeypatch.setenv("L1_ROUTING_STRATEGY", "S1")
        monkeypatch.setattr(lrs, "get_l0", lambda: _ExplodingL0())
        out = lrs.route_query("帮我查文档里怎么写的风控")
        assert out["handled"] is False
        assert "l1_no_executor" in out["route_signal"]["reasons"]

    def test_default_s0_unchanged(self, monkeypatch):
        """默认策略下，复合问法仍走原链路（不触发 compound_query）。"""
        monkeypatch.delenv("L1_ROUTING_STRATEGY", raising=False)
        monkeypatch.setattr(lrs, "get_l0", lambda: _FakeL0([_mem(0.9)] * 3))
        out = lrs.route_query("BTC现价、SOL现价、黄金现价", intent="price_query")
        assert out["handled"] is True
        assert "compound_query" not in out["route_signal"]["reasons"]
