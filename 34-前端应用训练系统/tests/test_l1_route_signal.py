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
    "..",
    "..",
    "3.1-FRONTEND",
    "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import data_query_executor as dqe  # noqa: E402
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
            return {
                "ok": False,
                "data": [],
                "source": "cognitive-loop-entry",
                "timestamp": "",
                "degraded": True,
                "meta": {"reason": "cognitive_unavailable"},
            }
        return {
            "ok": True,
            "data": self._memories or [],
            "source": "cognitive-loop-entry",
            "timestamp": "",
            "degraded": False,
            "meta": {},
        }

    def settle(self, result, ctx):
        pass


class TestModuleImport:
    def test_module_and_constants(self):
        assert callable(lrs.route_query)
        assert callable(lrs.detect_intent)
        assert callable(lrs.extract_json)
        # 十意图执行器 + S1/S2 增量意图（确定性指标、注册表能力、统计关系等）
        # + event_listing（SPEC-41-L1-新闻意图检索 §7，注册 exec_news_search）
        assert len(lrs.EXECUTORS) == 19
        for name in (
            "data_query",
            "data_insight",
            "contradiction_insight",
            "path_insight",
            "technical_analysis",
            "technical_indicator",
            "fundamental_valuation",
            "asset_class_trend",
            "event_analysis",
            "risk_control",
            "price_query",
            "metric_series",
            "whale_flow",
            "calendar_event",
            "leader_compare",
            "top_correlation",
            "persistence_strength",
            "stat_query",
        ):
            assert callable(lrs.EXECUTORS[name])


class TestDetectIntent:
    """后端意图识别对齐 TS L1_INTENT_REGISTRY v3（8 fallbackPattern + 2 通用意图）。"""

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("BTC现在什么价", "price_query"),
            ("ETH最新价格多少", "price_query"),
            ("各维度和资金面有矛盾吗", "contradiction_insight"),
            ("综合看最小阻力路径往哪走", "path_insight"),
            ("BTC技术面和卦象", "technical_analysis"),
            ("比特币目前阻力位在哪", "technical_indicator"),
            ("ETH 现在支撑位多少", "technical_indicator"),
            ("ETH估值百分位高不高", "fundamental_valuation"),
            ("美股和加密的跨资产趋势对比", "asset_class_trend"),
            ("BTC和ETH涨跌幅对比", "leader_compare"),
            ("以太坊和比特币谁更强", "leader_compare"),
            ("这次FOMC事件分析", "event_analysis"),
            ("当前持仓风控和止损位", "risk_control"),
            ("查一下最新CPI", "metric_series"),
            ("defillama TVL 查询", "metric_series"),
            (
                "CPI超预期意味着什么",
                "data_insight",
            ),  # 指标+解读问法优先于 event（"超预期"单独不再算事件）
        ],
    )
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
            return {
                "success": True,
                "answer": "BTC 63000 USDT",
                "data": {"symbol": "BTC", "last": "63000"},
            }

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
            "route_confidence",
            "decision",
            "match_score",
            "case_density",
            "prediction_error",
            "fast_path",
            "degraded",
            "reasons",
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


class TestRouteQueryExecutorAvailability:
    """A 方案：产物检索型意图不参与 recall 密度门控（SPEC-41-L1 §5.1 修订）。

    新闻检索对象是本地 news_digest/hot_news 产物，不是认知记忆；
    云端 recall_empty 时也必须直答，否则前端表现为"搜了没反应"。
    """

    def test_event_listing_direct_on_empty_recall(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        monkeypatch.setitem(
            lrs.EXECUTORS,
            "event_listing",
            lambda message: {"success": True, "answer": "ok", "data": {"matched": 2}},
        )

        out = lrs.route_query("以太坊 最近新闻", intent="event_listing")

        assert out["handled"] is True
        assert out["route_signal"]["decision"] == "L1_DIRECT"
        assert out["route_signal"]["reasons"] == [lrs.R_EXECUTOR_AVAILABILITY]
        assert out["data"]["matched"] == 2
        # 完全不查认知召回（产物可用性 !== 记忆密度）
        assert fake_l0.recalls == []


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


class TestDeterministicRegistry:
    """S1 确定性关键词注册表：命中即单维直答，不被 recall 密度门控推给 L2。"""

    def test_whale_intent_detected(self):
        assert lrs.detect_intent("查询巨鲸动向") == "whale_flow"

    def test_calendar_intent_detected(self):
        assert lrs.detect_intent("下一次议息会议是什么时候") == "calendar_event"

    def test_interpretation_not_hijacked(self):
        # 「说明什么」是解读，不是数据检索，仍归 data_insight
        assert lrs.detect_intent("巨鲸持续买入说明什么") != "whale_flow"
        # 「结果怎么看」是事件解读，仍归 event_analysis
        assert lrs.detect_intent("议息会议结果怎么看") != "calendar_event"

    def test_whale_bypasses_empty_recall(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        monkeypatch.setitem(
            lrs.EXECUTORS,
            "whale_flow",
            lambda m: {"success": True, "answer": "巨鲸净流入 +1.00亿美元", "data": {}},
        )

        out = lrs.route_query("查询巨鲸动向")

        assert out["intent"] == "whale_flow"
        assert out["handled"] is True
        assert "1.00" in out["answer"]
        sig = out["route_signal"]
        assert sig["decision"] == "L1_DIRECT"
        assert sig["degraded"] is False
        assert lrs.R_DETERMINISTIC_REGISTRY in sig["reasons"]

    def test_calendar_bypasses_empty_recall(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        monkeypatch.setitem(
            lrs.EXECUTORS,
            "calendar_event",
            lambda m: {"success": True, "answer": "下一次议息会议：2026-12-10 03:00", "data": {}},
        )

        out = lrs.route_query("下一次议息会议是什么时候")

        assert out["intent"] == "calendar_event"
        assert out["handled"] is True
        assert out["route_signal"]["decision"] == "L1_DIRECT"

    def test_executor_exception_degrades_not_crashes(self, monkeypatch):
        monkeypatch.setitem(
            lrs.EXECUTORS,
            "whale_flow",
            lambda m: (_ for _ in ()).throw(RuntimeError("db locked")),
        )

        out = lrs.route_query("查询巨鲸动向")

        assert out["handled"] is True
        assert out["degraded"] is True
        assert "执行异常" in out["answer"]

    # ---- 查询类单维数据：注册表命中即索引输出（无需时间词的双条件）----

    def test_series_query_without_period_detected(self):
        # 旧实现要求「指标词 + 时间窗口」双条件，纯数值问法会被漏掉
        assert lrs.detect_intent("稳定币总市值现在多少") == "metric_series"
        assert lrs.detect_intent("RWA 规模多少") == "metric_series"
        assert lrs.detect_intent("24小时爆仓金额多少") == "metric_series"
        assert lrs.detect_intent("上市公司持币总量") == "metric_series"

    def test_series_interpretation_not_hijacked(self):
        assert lrs.detect_intent("MVRV 意味着什么") != "metric_series"
        assert lrs.detect_intent("资金费率上升说明什么") != "metric_series"

    def test_series_bypasses_empty_recall(self, monkeypatch):
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)
        monkeypatch.setitem(
            lrs.EXECUTORS,
            "metric_series",
            lambda m: {"success": True, "answer": "RWA 总规模：最新 34.70亿美元", "data": {}},
        )

        out = lrs.route_query("RWA 规模多少")

        assert out["intent"] == "metric_series"
        assert out["handled"] is True
        sig = out["route_signal"]
        assert sig["decision"] == "L1_DIRECT"
        assert lrs.R_DETERMINISTIC_REGISTRY in sig["reasons"]

    def test_unregistered_series_falls_through(self, monkeypatch):
        # 注册表未命中的查询仍走 recall 门控（记忆为空 → L2_HANDOFF）
        fake_l0 = FakeL0(memories=[])
        monkeypatch.setattr(lrs, "get_l0", lambda: fake_l0)

        out = lrs.route_query("帮我看看这个冷门指标现在多少")

        assert out["handled"] is False
        assert out["route_signal"]["decision"] == "L2_HANDOFF"


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
        payload = {
            "success": True,
            "intent": "price_query",
            "handled": False,
            "answer": "",
            "data": None,
            "degraded": True,
            "route_signal": {"route_confidence": 0.0, "decision": "L2_HANDOFF"},
        }
        monkeypatch.setattr(lrs, "route_query", lambda message, intent="", trace_id="": payload)
        monkeypatch.setattr(
            sys,
            "argv",
            ["l1_route_signal.py", json.dumps({"message": "BTC", "intent": "price_query"})],
        )
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


class _StatCandles:
    def __init__(self, n=90):
        self.close = tuple(100.0 + i for i in range(n))
        self.ts = tuple(1704067200 + i * 86400 for i in range(n))
        self.sample_n = n
        self.close_anchor = "snapshot_last"


def _patch_stat_capabilities(monkeypatch):
    import importlib

    import l1agg.capabilities as capabilities

    manifest = importlib.import_module("l1agg.capabilities.manifest")

    calls = []

    def fake_run(capability_id, **kwargs):
        calls.append((capability_id, kwargs))
        return {
            "ok": True,
            "answer": f"{capability_id} ok",
            "data": {},
            "quality": {},
            "capability": capability_id,
        }

    monkeypatch.setattr(capabilities, "run_capability", fake_run)
    monkeypatch.setattr(manifest, "assert_public", lambda _capability_id: None)
    return calls


@pytest.mark.parametrize(
    "message",
    [
        "CPI 月频历史序列",
        "CPI 区间变化率",
        "MVRV CAGR",
        "MVRV 历史分位",
        "BTC 年化波动率",
        "BTC 单序列回撤画像",
        "CPI 同比",
        "CPI 环比",
        "实际利率是多少",
        "BTC 和 ETH 滚动相关",
        "BTC 和 ETH 领先滞后",
        "VIX 极端事件频率",
        "ETF 净流入滚动和",
        "稳定币规模增速",
        "BTC 趋势斜率",
        "BTC 距历史新高",
        "BTC 12-1 动量",
        "BTC 波动率目标",
    ],
)
def test_new_stat_capability_cues_route_to_stat_query(message):
    assert lrs.detect_intent(message) == "stat_query"


@pytest.mark.parametrize(
    "message,capability_id",
    [
        ("BTC 年化波动率", "D-A06"),
        ("BTC 单序列回撤画像", "D-A07"),
        ("BTC 趋势斜率", "D-B08"),
        ("BTC 距历史新高", "D-B09"),
        ("BTC 12-1 动量", "D-G08"),
        ("BTC 波动率目标", "D-G09"),
    ],
)
def test_price_stat_dispatch_uses_candles_and_dates(monkeypatch, message, capability_id):
    import l1agg.candles as candles

    calls = _patch_stat_capabilities(monkeypatch)
    load_days = []
    monkeypatch.setattr(
        candles,
        "load",
        lambda _symbol, **kwargs: load_days.append(kwargs["days"]) or _StatCandles(),
    )

    out = dqe.exec_stat_query(message)

    assert out["capability"] == capability_id
    assert len(calls) == 1
    called_id, kwargs = calls[0]
    assert called_id == capability_id
    assert len(kwargs["dates"]) == 90
    if capability_id == "D-A06":
        assert len(kwargs["values"]) == 90
        assert "prices" not in kwargs
    else:
        assert len(kwargs["prices"]) == 90
    assert load_days == [1825 if capability_id == "D-B09" else 730]


@pytest.mark.parametrize(
    "message,capability_id,sub_category,metric_name,agg",
    [
        ("CPI 月频历史序列", "D-A01", "CPIAUCSL", "value", "daily"),
        ("CPI 区间变化率", "D-A02", "CPIAUCSL", "value", "daily"),
        ("MVRV CAGR", "D-A03", "btc_metrics", "mvrv", "daily"),
        ("MVRV 历史分位", "D-A04", "btc_metrics", "mvrv", "daily"),
        ("CPI 同比", "D-A08", "CPIAUCSL", "value", "monthly"),
        ("CPI 环比", "D-A09", "CPIAUCSL", "value", "monthly"),
        ("VIX 极端事件频率", "D-A13", "VIXCLS", "value", "daily"),
        ("ETF 净流入滚动和", "D-A15", "etf_flow", "total_flow", "daily"),
        (
            "稳定币规模增速",
            "D-A16",
            "stablecoins_top_10",
            "total_circulating_usd_bln",
            "daily",
        ),
    ],
)
def test_metric_stat_dispatch_preserves_series_contract(
    monkeypatch, message, capability_id, sub_category, metric_name, agg
):
    calls = _patch_stat_capabilities(monkeypatch)
    loads = []

    def fake_load(sub, metric, **kwargs):
        loads.append((sub, metric, kwargs))
        values = [100.0 + i for i in range(40)]
        dates = dqe._stat_dates([1704067200 + i * 86400 for i in range(40)])
        return values, dates

    monkeypatch.setattr(dqe, "_load_stat_series", fake_load)
    out = dqe.exec_stat_query(message)

    assert out["capability"] == capability_id
    assert len(calls) == 1
    called_id, kwargs = calls[0]
    assert called_id == capability_id
    assert len(kwargs["values"]) == len(kwargs["dates"]) == 40
    assert loads[0][0:2] == (sub_category, metric_name)
    assert loads[0][2]["agg"] == agg
    if agg == "monthly":
        assert loads[0][2]["days"] == 1825
    if capability_id == "D-A01":
        assert kwargs["freq"] == "monthly"


def test_real_rate_aligns_dgs10_and_cpi_by_month(monkeypatch):
    calls = _patch_stat_capabilities(monkeypatch)
    series = {
        "DGS10": ([4.1, 4.2, 4.3], ["2024-01-31", "2024-02-29", "2024-03-31"]),
        "CPIAUCSL": ([100.0, 101.0, 102.0], ["2024-01-10", "2024-02-10", "2024-03-10"]),
    }
    monkeypatch.setattr(
        dqe,
        "_load_stat_series",
        lambda sub, _metric, **_kwargs: series[sub],
    )

    out = dqe.exec_stat_query("实际利率是多少")

    assert out["capability"] == "D-A10"
    _, kwargs = calls[0]
    assert kwargs["nominal"] == [4.1, 4.2, 4.3]
    assert kwargs["cpi"] == [100.0, 101.0, 102.0]
    assert kwargs["dates"] == ["2024-01-01", "2024-02-01", "2024-03-01"]
    assert kwargs["period"] == 12


@pytest.mark.parametrize(
    "message,capability_id",
    [("BTC 和 ETH 滚动相关", "D-A11"), ("BTC 和 ETH 领先滞后", "D-A12")],
)
def test_pair_stat_dispatch_uses_aligned_returns(monkeypatch, message, capability_id):
    import l1agg.candles as candles

    calls = _patch_stat_capabilities(monkeypatch)
    monkeypatch.setattr(candles, "load", lambda _symbol, **_kwargs: _StatCandles())

    out = dqe.exec_stat_query(message)

    assert out["capability"] == capability_id
    _, kwargs = calls[0]
    assert len(kwargs["x"]) == len(kwargs["y"]) == len(kwargs["dates"]) == 89
    if capability_id == "D-A11":
        assert kwargs["name"] == "BTC/ETH"
    else:
        assert (kwargs["x_name"], kwargs["y_name"]) == ("BTC", "ETH")


def test_stat_dispatch_missing_data_and_peer_fail_open(monkeypatch):
    calls = _patch_stat_capabilities(monkeypatch)
    monkeypatch.setattr(dqe, "_load_stat_series", lambda *_args, **_kwargs: None)

    missing = dqe.exec_stat_query("CPI 同比")
    no_peer = dqe.exec_stat_query("BTC 滚动相关")

    assert missing["degraded"] is True and missing["capability"] == "D-A08"
    assert no_peer["degraded"] is True and no_peer["capability"] == "D-A11"
    assert calls == []
