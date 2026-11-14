# -*- coding: utf-8 -*-
"""S1.0-2 资产池配置与加载器测试。"""

import os
import sys

import pytest
import yaml

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.asset_pool import AssetPoolError, load  # noqa: E402

EXPECTED_IDS = {"BTC", "ETH", "SOL", "IXIC", "SPX", "XAU", "WTI", "US10Y"}


@pytest.fixture(scope="module")
def pool():
    return load()


class TestAnchors:
    def test_exactly_eight_anchors(self, pool):
        assert {a.id for a in pool.anchors} == EXPECTED_IDS
        assert len(pool.anchors) == 8

    def test_all_have_storage_and_instrument(self, pool):
        for anchor in pool.anchors:
            assert anchor.storage_sub_category and anchor.storage_metric
            assert anchor.instrument_id
            assert anchor.years >= 3

    def test_timezone_present(self, pool):
        for anchor in pool.anchors:
            assert anchor.timezone


class TestClassesAndLeaders:
    def test_classes(self, pool):
        assert pool.classes() == ["crypto", "equity_us", "commodity", "rates"]

    @pytest.mark.parametrize(
        "asset_class,leader",
        [
            ("crypto", "BTC"),
            ("equity_us", "SPX"),
            ("commodity", "XAU"),
            ("rates", "US10Y"),
        ],
    )
    def test_leader(self, pool, asset_class, leader):
        assert pool.leader_of(asset_class).id == leader


class TestResolve:
    @pytest.mark.parametrize(
        "key,expected",
        [
            ("BTC", "BTC"),
            ("btc", "BTC"),
            ("比特币", "BTC"),
            ("大饼", "BTC"),
            ("纳指", "IXIC"),
            ("NDX", "IXIC"),
            ("标普500", "SPX"),
            ("黄金", "XAU"),
            ("原油", "WTI"),
            ("美债", "US10Y"),
            ("  eth  ", "ETH"),
        ],
    )
    def test_resolve_aliases(self, pool, key, expected):
        assert pool.resolve(key).id == expected

    def test_resolve_unknown(self, pool):
        assert pool.resolve("DOGE") is None
        assert pool.resolve("") is None


class TestStorageKey:
    @pytest.mark.parametrize(
        "asset_id,expected",
        [
            ("SPX", ("SP500", "value")),
            ("IXIC", ("NASDAQCOM", "value")),
            ("US10Y", ("DGS10", "value")),
            ("BTC", ("BTC", "close_usd")),
        ],
    )
    def test_storage_key(self, pool, asset_id, expected):
        assert pool.resolve(asset_id).storage_key == expected


class TestDynamicSection:
    def test_dynamic_rules(self, pool):
        dyn = pool.dynamic
        assert dyn["enabled"] is True
        assert dyn["provider"] == "okx"
        assert dyn["universe"]["on_demand_only"] is True
        assert dyn["relation"]["benchmarks"] == ["BTC", "ETH"]
        assert dyn["relation"]["min_samples"] == 90
        assert "L2" in dyn["boundary"]

    def test_quality_thresholds(self, pool):
        assert pool.quality["min_rows_3y"] == 1090
        assert pool.quality["stale_days"] == 3


class TestValidation:
    def _write(self, tmp_path, data):
        path = tmp_path / "pool.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return str(path)

    def _minimal(self):
        return {
            "version": 1,
            "anchors": [
                {
                    "id": "BTC",
                    "name": "比特币",
                    "asset_class": "crypto",
                    "role": "leader",
                    "aliases": ["BTC"],
                    "instrument": {"venue": "okx", "inst_id": "BTC-USDT"},
                    "storage": {"sub_category": "BTC", "metric": "close_usd"},
                    "history": {"years": 3, "backfill": "okx_history_candles"},
                },
                {
                    "id": "ETH",
                    "name": "以太坊",
                    "asset_class": "crypto",
                    "role": "member",
                    "aliases": ["ETH"],
                    "instrument": {"venue": "okx", "inst_id": "ETH-USDT"},
                    "storage": {"sub_category": "ETH", "metric": "close_usd"},
                    "history": {"years": 3, "backfill": "okx_history_candles"},
                },
            ],
        }

    def test_minimal_valid(self, tmp_path):
        pool = load(self._write(tmp_path, self._minimal()))
        assert len(pool.anchors) == 2

    def test_duplicate_id_rejected(self, tmp_path):
        data = self._minimal()
        data["anchors"][1]["id"] = "BTC"
        with pytest.raises(AssetPoolError, match="重复 id"):
            load(self._write(tmp_path, data))

    def test_missing_leader_rejected(self, tmp_path):
        data = self._minimal()
        data["anchors"][0]["role"] = "member"
        with pytest.raises(AssetPoolError, match="龙头数量"):
            load(self._write(tmp_path, data))

    def test_two_leaders_rejected(self, tmp_path):
        data = self._minimal()
        data["anchors"][1]["role"] = "leader"
        with pytest.raises(AssetPoolError, match="龙头数量"):
            load(self._write(tmp_path, data))

    def test_short_history_rejected(self, tmp_path):
        data = self._minimal()
        data["anchors"][0]["history"]["years"] = 1
        with pytest.raises(AssetPoolError, match="years=1"):
            load(self._write(tmp_path, data))

    def test_unknown_benchmark_rejected(self, tmp_path):
        data = self._minimal()
        data["dynamic"] = {"relation": {"benchmarks": ["DOGE"]}}
        with pytest.raises(AssetPoolError, match="benchmarks"):
            load(self._write(tmp_path, data))

    def test_missing_file(self):
        with pytest.raises(AssetPoolError, match="不存在"):
            load("/nonexistent/asset_pool.yaml")
