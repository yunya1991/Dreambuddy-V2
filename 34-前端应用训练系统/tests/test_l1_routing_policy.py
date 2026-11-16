# -*- coding: utf-8 -*-
"""E1（SPEC-v1.4 §7.1）纯决策模块测试。

两个目标：
  1. **S0 等价锁**：decide("S0", ...) 与线上 route_query 的 decision/intent 完全一致，
     保证抽纯函数没有改变生产行为（route_query 本身零改动）。
  2. S1–S5 判定规则单测：语义阈值、margin、认知裁决、纯语义通道。

语义通道在测试中打桩（不加载 bge 模型），避免测试依赖本机模型缓存。
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
import l1_routing_policy as pol  # noqa: E402


def _mem(score):
    return {"id": f"VM-{score}", "content": "c", "score": score}


class FakeL0:
    def __init__(self, memories=None, *, degraded=False):
        self._memories = memories or []
        self._degraded = degraded

    def fetch_context(self, scope, params=None):
        if self._degraded:
            return {"ok": False, "data": [], "degraded": True, "meta": {"reason": "x"}}
        return {"ok": True, "data": self._memories, "degraded": False, "meta": {}}

    def settle(self, result, ctx):
        pass


@pytest.fixture(autouse=True)
def _no_semantic(monkeypatch):
    """默认关闭真实语义通道；需要语义的用例自行注入特征。"""
    monkeypatch.setattr(lrs, "_semantic_matcher", None)


def _patch_executors(monkeypatch):
    for intent in list(lrs.EXECUTORS):
        monkeypatch.setitem(
            lrs.EXECUTORS, intent, lambda m: {"success": True, "answer": "ok", "data": {}}
        )


class TestS0ParityWithRouteQuery:
    """S0 必须与线上 route_query 判决一致（防抽函数引入行为漂移）。"""

    @pytest.mark.parametrize(
        "message,intent,memories",
        [
            ("BTC什么价", "price_query", []),
            ("BTC什么价", "price_query", [_mem(0.9)] * 3),
            ("查一下最新CPI", "", []),
            ("查询巨鲸动向", "", []),
            ("以太坊 最近新闻", "", []),
            ("RWA 规模多少", "", []),
            ("你好", "", [_mem(0.99)] * 5),
            ("帮我看看这个冷门指标现在多少", "", []),
        ],
    )
    def test_s0_matches_route_query(self, monkeypatch, message, intent, memories):
        _patch_executors(monkeypatch)
        monkeypatch.setattr(lrs, "get_l0", lambda: FakeL0(memories))

        live = lrs.route_query(message, intent=intent)
        feats = pol.build_features(message, recall_memories=memories)
        if intent:
            # 前端透传 intent 时，特征侧等价于正则命中该意图
            feats = pol.Features(
                message=feats.message,
                regex_intent=intent,
                semantic_top=feats.semantic_top,
                series_ok=feats.series_ok,
                recall_memories=feats.recall_memories,
            )
        got = pol.decide("S0", feats)

        assert got.decision == live["route_signal"]["decision"]
        assert got.intent == live["intent"]
        assert got.route_confidence == live["route_signal"]["route_confidence"]

    def test_s0_empty_recall_reason_preserved(self, monkeypatch):
        _patch_executors(monkeypatch)
        monkeypatch.setattr(lrs, "get_l0", lambda: FakeL0([]))
        live = lrs.route_query("BTC什么价", intent="price_query")
        got = pol.decide(
            "S0",
            pol.Features(message="BTC什么价", regex_intent="price_query", recall_memories=()),
        )
        assert "recall_empty" in live["route_signal"]["reasons"]
        assert "recall_empty" in got.reasons


class TestSemanticGate:
    SEM = ("price_query", 0.80)
    SEM2 = ("fundamental_valuation", 0.74)

    def _f(self, **kw):
        base = {"message": "这个标的现在报多少", "regex_intent": "", "series_ok": False}
        base.update(kw)
        return pol.Features(**base)

    def test_s1_ignores_semantic_channel(self):
        got = pol.decide("S1", self._f(semantic_top=(self.SEM, self.SEM2)))
        assert got.decision == "L2_HANDOFF"
        assert got.reasons == ("intent_unknown",)

    def test_s2_accepts_high_confidence_semantic(self):
        got = pol.decide("S2", self._f(semantic_top=(self.SEM, self.SEM2)))
        assert got.decision == "L1_DIRECT"
        assert got.intent == "price_query"
        assert got.channel == "semantic"
        assert got.route_confidence == 1.0

    def test_s2_rejects_low_confidence(self):
        got = pol.decide("S2", self._f(semantic_top=(("price_query", 0.60),)))
        assert got.decision == "L2_HANDOFF"
        assert got.reasons == ("l1_low_confidence",)

    def test_s3_margin_rejects_ambiguous(self):
        feats = self._f(semantic_top=(("price_query", 0.80), ("fundamental_valuation", 0.79)))
        assert pol.decide("S2", feats).decision == "L1_DIRECT"
        got = pol.decide("S3", feats, pol.Params(margin_delta=0.05))
        assert got.decision == "L2_HANDOFF"
        assert got.reasons == ("l1_ambiguous_intent",)

    def test_s3_margin_accepts_clear_winner(self):
        feats = self._f(semantic_top=(("price_query", 0.80), ("fundamental_valuation", 0.70)))
        assert pol.decide("S3", feats, pol.Params(margin_delta=0.05)).decision == "L1_DIRECT"

    def test_s4_arbitration_adopts_near_threshold(self):
        feats = self._f(
            semantic_top=(("price_query", 0.63),),
            recall_memories=(_mem(0.9), _mem(0.9), _mem(0.9)),
        )
        assert pol.decide("S3", feats).decision == "L2_HANDOFF"
        got = pol.decide("S4", feats)
        assert got.decision == "L1_DIRECT"
        assert got.reasons == ("cognition_arbitration_adopt",)

    def test_s4_arbitration_requires_recall_evidence(self):
        feats = self._f(semantic_top=(("price_query", 0.63),), recall_memories=())
        assert pol.decide("S4", feats).decision == "L2_HANDOFF"

    def test_s5_ignores_regex_only_cases(self):
        feats = self._f(regex_intent="price_query", semantic_top=())
        assert pol.decide("S1", feats).decision == "L1_DIRECT"
        got = pol.decide("S5", feats)
        assert got.decision == "L2_HANDOFF"


class TestGates:
    def test_no_executor_intent_handoff(self):
        feats = pol.Features(message="搜索一下记忆系统的SPEC", regex_intent="doc_search")
        for s in ("S1", "S2", "S3"):
            got = pol.decide(s, feats)
            assert got.decision == "L2_HANDOFF"
            assert got.reasons == ("l1_no_executor",)
        # S5 关正则后连意图都识别不出 → 仍是 L2（原因不同）
        assert pol.decide("S5", feats).decision == "L2_HANDOFF"

    def test_semantic_metric_series_requires_deterministic_series(self):
        feats = pol.Features(
            message="这个指标最近走势如何", semantic_top=(("metric_series", 0.8),), series_ok=False
        )
        assert pol.decide("S2", feats).decision == "L2_HANDOFF"
        feats_ok = pol.Features(
            message="这个指标最近走势如何", semantic_top=(("metric_series", 0.8),), series_ok=True
        )
        assert pol.decide("S2", feats_ok).decision == "L1_DIRECT"

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError):
            pol.decide("S9", pol.Features(message="x"))
