"""灰度上线验证 — EN_SILVER=true 端到端链路验证。

完整链路：
  DataCenter.fetch(mock collector) → _fetch_monitored
    → DataCleaningPipeline.clean() → SilverRecord
    → DalSink.write_silver() → SQLite DAL upsert
    → GoldReader.read_all_macro() → macro_df
    → FeaturePipeline.run() → FeatureVector

验证点：
  1. EN_SILVER=true 时 dispatcher 自动调用清洗链
  2. SilverRecord.gate_passed=True 后 DalSink 写入 SQLite
  3. GoldReader 能读回写入的数据
  4. FeaturePipeline 能消费 GoldReader 的输出
  5. EN_SILVER=false 时跳过清洗，直接返回原始 records
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch

import pandas as pd
import pytest

from data_center.core.contract import DataRecord


# ── 临时 SQLite DAL fixture ─────────────────────────
@pytest.fixture()
def sqlite_repo(tmp_path):
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import SqliteMarketMacroRepository

    db_path = str(tmp_path / "silver_e2e.db")
    conn = sqlite3.connect(db_path)
    init_db_schema(conn)
    conn.close()
    return SqliteMarketMacroRepository(db_path)


# ── mock collector 返回 fear_greed DataRecord ────────
def _make_fear_greed_records():
    """构造 fear_greed DataRecord 列表（模拟 alternative collector）。

    时间戳取「now - 2h / now - 1h / now」，保证通过 48h freshness gate。
    """
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=2)
    t1 = now - timedelta(hours=1)
    t2 = now
    return [
        DataRecord(
            source="alternative",
            category="chain",
            sub_category="fear_greed",
            timestamp=t0.isoformat(),
            metrics={},
            events=[],
            timeseries=[
                {"value": 25, "value_classification": "Extreme Fear",
                 "timestamp": t0.isoformat()},
                {"value": 45, "value_classification": "Fear",
                 "timestamp": t1.isoformat()},
                {"value": 72, "value_classification": "Greed",
                 "timestamp": t2.isoformat()},
            ],
            raw={},
        ),
    ]


def _read_window():
    """读取窗口：覆盖 now-3h ~ now+1h，确保能读到三条记录。"""
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=3), now + timedelta(hours=1)


# ── T1 · EN_SILVER=true 完整链路：采集→清洗→DAL写入 ────
def test_silver_chain_writes_to_dal(sqlite_repo, monkeypatch):
    """验证 EN_SILVER=true 时完整链路写入 DAL。"""
    monkeypatch.setenv("EN_SILVER", "true")
    monkeypatch.setenv("SILVER_FAIL_OPEN", "true")

    # patch DalSink 使用我们的 SQLite repo
    from data_cleaning.dal_sink import DalSink
    original_init = DalSink.__init__

    def patched_init(self, mm_repo=None):
        original_init(self, mm_repo=sqlite_repo)

    monkeypatch.setattr(DalSink, "__init__", patched_init)

    # 构造 DataCenter + mock collector
    from data_center.core.dispatcher import DataCenter
    from data_center.core.registry import Registry

    reg = Registry()
    # 注册 mock collector（签名对齐 BaseCollector.fetch(self, params: dict)）
    class MockCollector:
        def __init__(self, config=None):
            self.config = config or {}

        def fetch(self, params: dict) -> list[DataRecord]:
            return _make_fear_greed_records()

    reg.register("chain", "alternative", MockCollector)

    dc = DataCenter(registry=reg, monitoring=None)

    # 执行 fetch
    result = dc.fetch(category="chain", source="alternative")

    # 验证：返回了清洗后的 records
    assert len(result) > 0
    assert result[0].source == "alternative"

    # 验证：DAL 中有数据
    from feature_hub.gold_reader import GoldReader
    reader = GoldReader(mm_repo=sqlite_repo)
    start, end = _read_window()
    macro_df = reader.read_fear_greed(start, end)

    assert len(macro_df) == 3
    assert macro_df.iloc[0]["value"] == 25
    assert macro_df.iloc[2]["value"] == 72


# ── T2 · EN_SILVER=false 跳过清洗 ────────────────────
def test_silver_disabled_skips_cleaning(sqlite_repo, monkeypatch):
    """EN_SILVER=false 时不应写入 DAL。"""
    monkeypatch.setenv("EN_SILVER", "false")

    from data_cleaning.dal_sink import DalSink
    original_init = DalSink.__init__

    def patched_init(self, mm_repo=None):
        original_init(self, mm_repo=sqlite_repo)

    monkeypatch.setattr(DalSink, "__init__", patched_init)

    from data_center.core.dispatcher import DataCenter
    from data_center.core.registry import Registry

    reg = Registry()

    class MockCollector:
        def __init__(self, config=None):
            self.config = config or {}

        def fetch(self, params: dict) -> list[DataRecord]:
            return _make_fear_greed_records()

    reg.register("chain", "alternative", MockCollector)
    dc = DataCenter(registry=reg, monitoring=None)

    result = dc.fetch(category="chain", source="alternative")

    # 验证：返回了原始 records（未清洗）
    assert len(result) == 1
    assert result[0].sub_category == "fear_greed"

    # 验证：DAL 中无数据
    from feature_hub.gold_reader import GoldReader
    reader = GoldReader(mm_repo=sqlite_repo)
    start, end = _read_window()
    macro_df = reader.read_fear_greed(start, end)

    assert len(macro_df) == 0


# ── T3 · 端到端：DAL 读取 → FeaturePipeline ────────────
def test_dal_read_to_feature_pipeline(sqlite_repo, monkeypatch):
    """验证 GoldReader 读取 DAL 后 FeaturePipeline 能消费。"""
    monkeypatch.setenv("EN_SILVER", "true")
    monkeypatch.setenv("SILVER_FAIL_OPEN", "true")

    from data_cleaning.dal_sink import DalSink
    original_init = DalSink.__init__

    def patched_init(self, mm_repo=None):
        original_init(self, mm_repo=sqlite_repo)

    monkeypatch.setattr(DalSink, "__init__", patched_init)

    from data_center.core.dispatcher import DataCenter
    from data_center.core.registry import Registry

    reg = Registry()

    class MockCollector:
        def __init__(self, config=None):
            self.config = config or {}

        def fetch(self, params: dict) -> list[DataRecord]:
            return _make_fear_greed_records()

    reg.register("chain", "alternative", MockCollector)
    dc = DataCenter(registry=reg, monitoring=None)

    # Step 1: 采集 → 清洗 → DAL
    dc.fetch(category="chain", source="alternative")

    # Step 2: DAL 读取
    from feature_hub.gold_reader import GoldReader
    reader = GoldReader(mm_repo=sqlite_repo)
    start, end = _read_window()
    macro_df = reader.read_all_macro("BTC", start, end)

    assert len(macro_df) > 0
    assert "fear_greed" in macro_df.columns

    # Step 3: FeaturePipeline 消费
    from feature_hub.pipeline.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()

    # 注册一个简单的 macro 消费模块
    def _macro_module(df, ref_df=None, macro_df=None, symbol=""):
        if macro_df is not None and not macro_df.empty and "fear_greed" in macro_df.columns:
            result = macro_df[["fear_greed"]].copy()
            result.index = range(len(result))
            return result
        return pd.DataFrame()

    pipe.register_module("test_macro", _macro_module)
    pipe.register_set("e2e_silver", ["test_macro"])

    # 构造 OHLCV
    ohlcv = pd.DataFrame({
        "open": [40000, 41000, 42000],
        "high": [41000, 42000, 43000],
        "low": [39000, 40000, 41000],
        "close": [41000, 42000, 42500],
        "volume": [100, 120, 110],
    })

    fv = pipe.run(set_name="e2e_silver", df=ohlcv, symbol="BTC", macro_df=macro_df)

    assert fv.df is not None
    assert "test_macro:fear_greed" in fv.df.columns or len(fv.df.columns) > 0
    assert "modules_run" in fv.meta


# ── T4 · fail-open：清洗链异常不阻断 ─────────────────
def test_silver_fail_open_on_pipeline_error(sqlite_repo, monkeypatch):
    """DataCleaningPipeline.clean() 抛异常时 fail-open 返回原始 records。"""
    monkeypatch.setenv("EN_SILVER", "true")
    monkeypatch.setenv("SILVER_FAIL_OPEN", "true")

    from data_center.core.dispatcher import DataCenter
    from data_center.core.registry import Registry

    reg = Registry()

    class MockCollector:
        def __init__(self, config=None):
            self.config = config or {}

        def fetch(self, params: dict) -> list[DataRecord]:
            return _make_fear_greed_records()

    reg.register("chain", "alternative", MockCollector)
    dc = DataCenter(registry=reg, monitoring=None)

    # patch DataCleaningPipeline.clean 抛异常
    with patch("data_cleaning.pipeline.DataCleaningPipeline.clean") as mock_clean:
        mock_clean.side_effect = RuntimeError("pipeline boom")
        result = dc.fetch(category="chain", source="alternative")

    # 验证：fail-open 返回原始 records
    assert len(result) == 1
    assert result[0].sub_category == "fear_greed"
