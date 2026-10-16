# -*- coding: utf-8 -*-
"""P3: l1_route_signal 门控信号端到端产出测试。

被测脚本位于 3.1-FRONTEND/scripts/l1_route_signal.py（execFile 入口，供 /api/data/query 调用）:
  消息 → 意图识别 → L0 cognitive.recall → route_confidence.evaluate_route
       → L1_DIRECT: 复用 data_query_executor 十意图执行器零 token 直答
       → L2_HANDOFF: 不执行，仅回传 route_signal 供前端透传 l1_intent_hint

FAIL-OPEN: 认知不可用/召回空/执行异常均不抛出，安全降级。
"""
import json
import os
import sys

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "3.1-FRONTEND", "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402


def _mem(score):
    return {"id": f"VM-{score}", "content": "c", "score": score}


class FakeL0:
    """记忆召回假 L0（仅 cognitive.recall scope）。"""

    def __init__(self, memories=None, *, degraded=False):
        self._memories = memories
        self._degraded = degraded
        self.recalls = []

    def fetch_context(self, scope, params=None):
        if scope != "cognitive.recall":
            raise AssertionError(f"unexpected scope: {scope}")
        self.recalls.append(params or {})
        if self._degraded:
            return {"ok": False, "data": [], "source": "cognitive-loop-entry",
                    "timestamp": "", "degraded": True,
                    "meta": {"reason": "cognitive_unavailable"}}
        return {"ok": True, "data": self._memories or [],
                "source": "cognitive-loop-entry", "timestamp": "",
                "degraded": False, "meta": {}}

    def settle(self, result, ctx):
        pass


class TestModuleImport:
    def test_module_and_constants(self):
        assert callable(lrs.route_query)
        assert callable(lrs.detect_intent)
        assert callable(lrs.extract_json)
        # 十意图执行器全部注册
        assert len(lrs.EXECUTORS) == 10
        for name in ("data_query", "data_insight", "contradiction_insight",
                     "path_insight", "technical_analysis", "fundamental_valuation",
                     "asset_class_trend", "event_analysis", "risk_control",
                     "price_query"):
            assert callable(lrs.EXECUTORS[name])


class TestDetectIntent:
    """后端意图识别对齐 TS L1_INTENT_REGISTRY v3（8 fallbackPattern + 2 通用意图）。"""

    @pytest.mark.parametrize("message,expected", [
        ("BTC现在什么价", "price_query"),
        ("ETH最新价格多少", "price_query"),
        ("各维度和资金面有矛盾吗", "contradiction_insight"),
        ("综合看最小阻力路径往哪走", "path_insight"),
        ("BTC技术面和卦象", "technical_analysis"),
        ("ETH估值百分位高不高", "fundamental_valuation"),
        ("美股和加密的跨资产趋势对比", "asset_class_trend"),
        ("这次FOMC事件分析", "event_analysis"),
        ("当前持仓风控和止损位", "risk_control"),
        ("查一下最新CPI", "data_query"),
        ("defillama TVL 查询", "data_query"),
        ("CPI超预期意味着什么", "event_analysis"),  # 与 TS fallback 顺序一致：event 先命中
    ])
    def test_detect_hits(self, message, expected):
        assert lrs.detect_intent(message) == expected

    def test_detect_unknown(self):
        assert lrs.detect_intent("你好，今天天气怎么样") == ""

    def test_data_insight_when_no_event_keyword(self):
        # 同时含指标词+变化问法但不含 event fallback 关键词
        assert lrs.detect_intent("资金费率上升意味着什么") == "data_insight"


class TestRouteQueryL1Direct:
    def test_high_confidence_recall_triggers_l1_direct(self, monkeypatch):
        fake_l0 = FakeL0(memories=[_mem(0.9), _mem(0.9), _mem(0.9)])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)

        called = {}

        def _fake_price(message):
            called["yes"] = message
            return {"success": True, "answer": "BTC 63000 USDT",
                    "data": {"symbol": "BTC", "last": "63000"}}

        monkeypatch.setitem(lrs.EXECUTORS, "price_query", _fake_price)

        out = lrs.route_query("BTC什么价", intent="price_query")

        assert out["handled"] is True
        assert "63000" in out["answer"]
        assert out["data"]["symbol"] == "BTC"
        assert called["yes"] == "BTC什么价"
        sig = out["route_signal"]
        assert sig["decision"] == "L1_DIRECT"
        assert sig["route_confidence"] >= 0.7
        assert set(sig.keys()) == {
            "route_confidence", "decision", "match_score", "case_density",
            "prediction_error", "fast_path", "degraded", "reasons",
        }
        # recall context 带意图先验
        assert "price_query" in fake_l0.recalls[0]["context"]

    def test_frontend_intent_overrides_detection(self, monkeypatch):
        fake_l0 = FakeL0(memories=[_mem(0.95)] * 5)
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        captured = {}

        def _fake(message):
            captured["intent_via_dispatch"] = "risk_control"
            return {"success": True, "answer": "风控正常", "data": {}}

        monkeypatch.setitem(lrs.EXECUTORS, "risk_control", _fake)
        out = lrs.route_query("随便一句看不出意图的话", intent="risk_control")
        assert out["intent"] == "risk_control"
        assert out["handled"] is True
        assert captured["intent_via_dispatch"] == "risk_control"


class TestRouteQueryL2Handoff:
    def test_empty_recall_forces_l2(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)

        def _boom(message):
            raise AssertionError("L2 交接不应执行 L1 执行器")

        monkeypatch.setitem(lrs.EXECUTORS, "price_query", _boom)
        out = lrs.route_query("BTC什么价", intent="price_query")

        assert out["handled"] is False
        assert out["answer"] == ""
        assert out["intent"] == "price_query"
        sig = out["route_signal"]
        assert sig["decision"] == "L2_HANDOFF"
        assert sig["route_confidence"] == 0.0
        assert sig["degraded"] is True
        assert "recall_empty" in sig["reasons"]

    def test_cognitive_unavailable_fails_toward_l2(self, monkeypatch):
        fake_l0 = FakeL0(degraded=True)
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        out = lrs.route_query("BTC什么价", intent="price_query")
        assert out["handled"] is False
        sig = out["route_signal"]
        assert sig["decision"] == "L2_HANDOFF"
        assert sig["degraded"] is True
        assert "cognitive_unavailable_static_fallback" in sig["reasons"]

    def test_recall_exception_fails_open(self, monkeypatch):
        class BoomL0(FakeL0):
            def fetch_context(self, scope, params=None):
                raise RuntimeError("cognitive down")

        monkeypatch.setattr(lrs, "get_l0", lambda: BoomL0())
        out = lrs.route_query("BTC什么价", intent="price_query")
        assert out["handled"] is False
        assert out["route_signal"]["decision"] == "L2_HANDOFF"

    def test_unknown_intent_short_circuits_without_recall(self, monkeypatch):
        fake_l0 = FakeL0(memories=[_mem(0.99)] * 5)
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        out = lrs.route_query("你好", intent="")
        assert out["intent"] == "unknown"
        assert out["handled"] is False
        assert out["route_signal"]["decision"] == "L2_HANDOFF"
        assert fake_l0.recalls == []

    def test_illegal_intent_falls_back_to_detection(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        out = lrs.route_query("BTC现价", intent="not_a_real_intent")
        assert out["intent"] == "price_query"


class TestL1ExecDegrade:
    def test_executor_exception_still_returns_answer(self, monkeypatch):
        fake_l0 = FakeL0(memories=[_mem(0.9)] * 3)
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)

        def _boom(message):
            raise RuntimeError("disk on fire")

        monkeypatch.setitem(lrs.EXECUTORS, "data_query", _boom)
        out = lrs.route_query("查CPI", intent="data_query")
        assert out["handled"] is True
        assert out["degraded"] is True
        assert "执行异常" in out["answer"]


class TestExtractJson:
    def test_picks_last_json_line_through_noise(self):
        raw = (
            "检测到遗留 vec_memories 虚拟表（跳过）\n"
            "recall SLA breach: 1519ms > 200ms\n"
            '{"success": true, "intent": "price_query", "handled": true}\n'
        )
        parsed = lrs.extract_json(raw)
        assert parsed["intent"] == "price_query"
        assert parsed["handled"] is True

    def test_no_json_returns_none(self):
        assert lrs.extract_json("just noise\nmore noise") is None


class TestMain:
    def test_main_prints_single_json(self, monkeypatch, capsys):
        payload = {"success": True, "intent": "price_query", "handled": False,
                   "answer": "", "data": None, "degraded": True,
                   "route_signal": {"route_confidence": 0.0,
                                    "decision": "L2_HANDOFF"}}
        monkeypatch.setattr(lrs, "route_query", lambda message, intent="": payload)
        monkeypatch.setattr(sys, "argv", ["l1_route_signal.py",
                                          json.dumps({"message": "BTC", "intent": "price_query"})])
        lrs.main()
        printed = capsys.readouterr().out.strip().splitlines()
        parsed = json.loads(printed[-1])
        assert parsed["intent"] == "price_query"

    def test_main_bad_args_fail_open(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["l1_route_signal.py", "not-json"])
        lrs.main()
        parsed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert parsed["intent"] == "unknown"
        assert parsed["handled"] is False
