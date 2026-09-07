"""test_data_pipeline.py — DataPipelineAdapter 集成测试
覆盖: 全字段装配, 部分失败降级, 性能<1s, symbol传递, ripples构造
"""
from __future__ import annotations

import time

import pytest

from dreambuddy_evolution.adapters.data_pipeline import DataPipelineAdapter
from dreambuddy_evolution.adapters.okx_market import OKXMarketAdapter


class MockOKXClient:
    """模拟 OKX 客户端 — 提供 K 线 + ticker + OI"""

    def __init__(self, n_candles=200, open_interest=None):
        candles = []
        for i in range(n_candles):
            p = 50000.0 + i * 5
            candles.append({
                "ts": str(1700000000000 + i * 3600000),
                "o": str(p), "h": str(p + 20),
                "l": str(p - 20), "c": str(p),
                "vol": str(1000 + i * 2),
            })
        self._candles = list(reversed(candles))
        self._oi = open_interest

    def get_kline(self, inst_id, bar="1H", limit=200):
        return {"ok": True, "candles": self._candles}

    def get_ticker(self, inst_id):
        return {"ok": True, "bid": "49998", "ask": "50002"}

    def get_positions(self, inst_id):
        return {"ok": False}

    def _get(self, path, params=None, auth=True):
        if path == "/api/v5/public/open-interest" and self._oi:
            return {"code": "0", "data": [self._oi]}
        return {"code": "1", "data": []}


class MockTrader:
    """模拟 polling_trader — 含子交易系统状态"""
    def __init__(self):
        class FDS:
            war_state = {"crypto_usdt": "ALLOW"}
        self._five_domain_state_shadow = FDS()
        self._last_bcrm2_result = {
            "next_state": {"direction": "UP", "confidence": 0.82}
        }
        self._last_bdsm_snapshot = {"valuation_percentile": 0.65}


class TestDataPipelineAdapter:

    def test_assemble_full_fields(self):
        """全字段装配 — OHLCV + ma_200 + spread + ESS + war_state + ripples"""
        client = MockOKXClient()
        trader = MockTrader()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=trader,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")

        # 基础字段
        assert data["symbol"] == "BTC"
        assert "close" in data
        assert len(data["close"]) == 200
        assert "ma_200" in data
        assert "vol_5" in data
        assert "vol_20" in data

        # ticker
        assert "bid_ask_spread_bps" in data

        # 子系统
        assert data["scale_class"] == "Classical"
        assert data["war_state"] == "ALLOW"
        assert data["bcrm_direction"] == "long"
        assert data["ess_temperature"] == 1.0

        # ripples
        assert "ripples" in data
        assert "R1" in data["ripples"]
        assert data["ripples"]["R1"]["hits"] == 0

    def test_assemble_partial_fail(self):
        """OKX 失败 → 仍返回部分字段（不 crash）"""
        class CrashClient:
            def get_kline(self, *a, **kw):
                raise RuntimeError("network down")
            def get_ticker(self, *a, **kw):
                raise RuntimeError("timeout")
            def get_positions(self, *a, **kw):
                raise RuntimeError("auth fail")
            def _get(self, *a, **kw):
                raise RuntimeError("nope")

        adapter = DataPipelineAdapter(
            okx_client=CrashClient(),
            trader=MockTrader(),
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")

        # symbol 一定有
        assert data["symbol"] == "BTC"
        # close 不应有（获取失败）
        assert "close" not in data
        # 子系统信号仍正常（纯内存读取）
        assert data["war_state"] == "ALLOW"

    def test_assemble_performance(self):
        """装配耗时 <1s"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=MockTrader(),
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        assert data["_assemble_ms"] < 1000

    def test_assemble_symbol_passthrough(self):
        """symbol 正确传递"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("ETH", "ETH-USDT-SWAP")
        assert data["symbol"] == "ETH"
        assert data["scale_class"] == "Classical"

    def test_ripples_structure(self):
        """ripples 结构正确"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("SOL", "SOL-USDT-SWAP")
        r = data["ripples"]
        assert set(r.keys()) == {"R1", "R2", "R3"}
        # R2/R3 Phase 3 全 0
        assert r["R2"]["hits"] == 0
        assert r["R3"]["hits"] == 0
        for key in ("R1", "R2", "R3"):
            assert r[key]["candidates"] == 1

    def test_sentiment_field(self):
        """sentiment 字段映射（kline_event_handler 期望 sentiment key）"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        # SentimentBridge 默认返回 0.5（无引擎/无数据）
        assert data["sentiment"] == 0.5
        assert data["news_sentiment_score"] == 0.5

    def test_narrative_field_none(self):
        """narrative 字段为 None（Phase 2 待实现）"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        assert data["narrative"] is None

    def test_capital_flow_from_oi(self):
        """capital_flow 从 OKX OI 计算（含 regime 乘数）"""
        client = MockOKXClient(open_interest={"oi": "5000000"})
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        assert "capital_flow" in data
        # oi=5e6 → log10=6.7 → (6.7-6)/2=0.35
        # 再经 regime 乘数：mock 数据为 ranging → ×0.7
        base_flow = 0.35
        regime = data.get("regime", "ranging")
        mult = {"trend_up": 1.3, "trend_down": 1.3, "ranging": 0.7, "crisis": 0.3}.get(regime, 1.0)
        expected = max(-1.0, min(1.0, base_flow * mult))
        assert abs(data["capital_flow"] - expected) < 0.02

    def test_r1_hit_direction_match(self):
        """R1 hit: K线方向与 ess_top_direction 一致 → hits=1"""
        from pathlib import Path
        import sys
        evo_pkg = Path(__file__).resolve().parents[1]
        evo_root = evo_pkg.parent
        if str(evo_root) not in sys.path:
            sys.path.insert(0, str(evo_root))
        gene_root = str(evo_pkg / "gene_data")

        # MockOKXClient 生成上涨 K线
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=gene_root,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")

        # 上涨 K线 + ess_top_direction="long" → R1 hits=1
        # 上涨 K线 + ess_top_direction="short" → R1 hits=0
        r1 = data["ripples"]["R1"]
        ess_dir = data.get("ess_top_direction", "")
        if ess_dir == "long":
            assert r1["hits"] == 1
        elif ess_dir == "short":
            assert r1["hits"] == 0

    def test_r1_hit_no_ess(self):
        """无 ess_top_direction → R1 hits=0"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        assert data["ripples"]["R1"]["hits"] == 0

    def test_cognitive_bridge_disabled_default(self):
        """cognitive_enabled 默认 False → bridge 关闭"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        bridge = adapter.get_cognitive_bridge()
        assert bridge is not None
        # 关闭状态下 recall 返回中性
        result = bridge.recall_similar({}, "long")
        assert result["cbr_sim"] == 0.5

    def test_ess_top_direction_missing(self):
        """gene_data_root=None → ess_top_direction=''"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        # 没有 gene_data_root → ess 字段不包含
        assert "ess_top_direction" not in data or data.get("ess_top_direction", "") == ""

    def test_no_trader_no_subsystem(self):
        """trader=None → 子系统字段不包含（但 scale_class 仍包含，它是静态方法）"""
        client = MockOKXClient()
        adapter = DataPipelineAdapter(
            okx_client=client,
            trader=None,
            data_center_db=None,
            gene_data_root=None,
        )
        data = adapter.assemble("BTC", "BTC-USDT-SWAP")
        assert "war_state" not in data
        assert "bcrm_direction" not in data
        # scale_class 是静态方法，不需要 trader
        assert data["scale_class"] == "Classical"
