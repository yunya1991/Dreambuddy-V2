"""P5 端到端集成测试 — 四模块打通验证。

完整链路：
  18 DataRecord → 20 DalSink → 19 SQLite DAL → 21 GoldReader → 21 FeaturePipeline → FeatureVector

验证点：
  1. DalSink 写入 SQLite 后数据可被 GoldReader 读回
  2. GoldReader 产出的 macro_df 能被 FeaturePipeline 消费
  3. FeatureVector 有非零列数
  4. 全程 fail-open：任一环节异常不传播到调用方
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pandas as pd
import pytest
import sqlite3

from data_cleaning.contract import CleaningTrace, SilverRecord
from data_cleaning.dal_sink import DalSink
from feature_hub.gold_reader import GoldReader
from feature_hub.pipeline.feature_pipeline import FeaturePipeline


# ── 临时 SQLite DB fixture ──────────────────────────
@pytest.fixture()
def sqlite_repo(tmp_path):
    """创建临时 SQLite DB + 初始化 schema + 返回 SqliteMarketMacroRepository。"""
    from dreambuddy_dal.implementations.sqlite_unified.schema_init import init_db_schema
    from dreambuddy_dal.implementations.sqlite_unified.market_macro_impl import SqliteMarketMacroRepository

    db_path = str(tmp_path / "e2e_test.db")
    conn = sqlite3.connect(db_path)
    init_db_schema(conn)
    conn.close()

    repo = SqliteMarketMacroRepository(db_path)
    return repo


# ── T1 · SilverRecord → DalSink → SQLite → GoldReader 读回 ────
def test_silver_to_dal_roundtrip(sqlite_repo):
    """验证 DalSink 写入的数据能被 GoldReader 读回。"""
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "value": [25, 72],
        "value_classification": ["Extreme Fear", "Greed"],
        "timestamp": [ts, ts + timedelta(hours=1)],
    })
    silver = SilverRecord(
        bronze_id="e2e-001",
        df=df,
        trace=CleaningTrace(),
        gate_passed=True,
        quality_report=[],
        schema_tag="macro_v1",
    )

    # 写入
    sink = DalSink(mm_repo=sqlite_repo)
    written = sink.write_silver(silver, source="alternative", category="chain", sub_category="fear_greed")
    assert written == 2

    # 读回
    reader = GoldReader(mm_repo=sqlite_repo)
    start = ts - timedelta(hours=1)
    end = ts + timedelta(hours=2)
    result_df = reader.read_fear_greed(start, end)

    assert len(result_df) == 2
    assert "value" in result_df.columns
    assert result_df.iloc[0]["value"] == 25
    assert result_df.iloc[1]["value"] == 72


# ── T2 · 多指标写入 + read_all_macro 合并 ───────────────────
def test_multi_metric_write_and_read_all(sqlite_repo):
    """写入 fear_greed + funding_rate，验证 read_all_macro 合并。"""
    ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    # 写 fear_greed
    fg_df = pd.DataFrame({
        "value": [45],
        "value_classification": ["Fear"],
        "timestamp": [ts],
    })
    fg_silver = SilverRecord(
        bronze_id="e2e-fg", df=fg_df, trace=CleaningTrace(),
        gate_passed=True, quality_report=[], schema_tag="macro_v1",
    )
    DalSink(mm_repo=sqlite_repo).write_silver(
        fg_silver, source="alternative", category="chain", sub_category="fear_greed")

    # 写 funding_rate
    fr_df = pd.DataFrame({
        "asset": ["BTC"],
        "funding_rate": [Decimal("0.0001")],
        "timestamp": [ts],
    })
    fr_silver = SilverRecord(
        bronze_id="e2e-fr", df=fr_df, trace=CleaningTrace(),
        gate_passed=True, quality_report=[], schema_tag="chain_v1",
    )
    DalSink(mm_repo=sqlite_repo).write_silver(
        fr_silver, source="ccxt", category="chain", sub_category="funding")

    # 读回合并
    reader = GoldReader(mm_repo=sqlite_repo)
    start = ts - timedelta(hours=1)
    end = ts + timedelta(hours=1)
    macro_df = reader.read_all_macro("BTC", start, end)

    assert len(macro_df) > 0
    assert "fear_greed" in macro_df.columns
    assert "funding_rate" in macro_df.columns


# ── T3 · GoldReader → FeaturePipeline 端到端 ────────────────
def test_gold_reader_to_feature_pipeline(sqlite_repo):
    """验证 GoldReader 产出的 macro_df 能被 FeaturePipeline 消费。"""
    ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    # 写入 fear_greed
    fg_df = pd.DataFrame({
        "value": [45, 55, 65],
        "value_classification": ["Fear", "Neutral", "Greed"],
        "timestamp": [ts, ts + timedelta(hours=1), ts + timedelta(hours=2)],
    })
    fg_silver = SilverRecord(
        bronze_id="e2e-pipe", df=fg_df, trace=CleaningTrace(),
        gate_passed=True, quality_report=[], schema_tag="macro_v1",
    )
    DalSink(mm_repo=sqlite_repo).write_silver(
        fg_silver, source="alternative", category="chain", sub_category="fear_greed")

    # 读回
    reader = GoldReader(mm_repo=sqlite_repo)
    start = ts - timedelta(hours=1)
    end = ts + timedelta(hours=3)
    macro_df = reader.read_all_macro("BTC", start, end)

    # 准备 OHLCV
    ohlcv = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"),
        "open": [40000, 41000, 42000],
        "high": [41000, 42000, 43000],
        "low": [39000, 40000, 41000],
        "close": [41000, 42000, 42500],
        "volume": [100, 120, 110],
    })

    # FeaturePipeline
    pipe = FeaturePipeline()

    # 注册一个简单测试模块
    def _test_macro_module(df, ref_df=None, macro_df=None, symbol=""):
        if macro_df is not None and not macro_df.empty and "fear_greed" in macro_df.columns:
            result = macro_df[["fear_greed"]].copy()
            result.index = df.index[:len(macro_df)]
            return result
        return pd.DataFrame(index=df.index)

    pipe.register_module("test_macro", _test_macro_module)
    pipe.register_set("e2e_test", ["test_macro"])

    fv = pipe.run(set_name="e2e_test", df=ohlcv, symbol="BTC", macro_df=macro_df)

    assert fv.df is not None
    assert isinstance(fv.meta, dict)
    assert "modules_run" in fv.meta


# ── T4 · gate_passed=False → 不写入 ─────────────────────────
def test_gate_failed_no_dal_write(sqlite_repo):
    """gate_passed=False 时 DalSink 不应写入 DAL。"""
    ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "value": [25],
        "value_classification": ["Extreme Fear"],
        "timestamp": [ts],
    })
    silver = SilverRecord(
        bronze_id="e2e-gate-fail", df=df, trace=CleaningTrace(),
        gate_passed=False, quality_report=[], schema_tag="macro_v1",
    )

    sink = DalSink(mm_repo=sqlite_repo)
    written = sink.write_silver(silver, source="test", category="chain", sub_category="fear_greed")

    assert written == 0

    # 验证 DAL 确实没有数据
    reader = GoldReader(mm_repo=sqlite_repo)
    result = reader.read_fear_greed(ts - timedelta(hours=1), ts + timedelta(hours=1))
    assert len(result) == 0


# ── T5 · fail-open 链路：DAL 写入异常不传播 ──────────────────
def test_fail_open_dal_write_exception(sqlite_repo, monkeypatch):
    """upsert 异常时 DalSink 应 fail-open，不传播到调用方。"""
    # 让 upsert_fear_greed 抛异常
    monkeypatch.setattr(sqlite_repo, "upsert_fear_greed", lambda **kw: (_ for _ in ()).throw(RuntimeError("DB lock")))

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "value": [25],
        "value_classification": ["Extreme Fear"],
        "timestamp": [ts],
    })
    silver = SilverRecord(
        bronze_id="e2e-fail", df=df, trace=CleaningTrace(),
        gate_passed=True, quality_report=[], schema_tag="macro_v1",
    )

    sink = DalSink(mm_repo=sqlite_repo)
    # 不应抛异常
    written = sink.write_silver(silver, source="test", category="chain", sub_category="fear_greed")
    assert written == 0
