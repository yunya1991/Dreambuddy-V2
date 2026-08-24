"""P1 DalSink 测试 — SilverRecord → 19-DAL 写入桥。

路由规则：SilverRecord.df 按 sub_category 路由到 MarketMacroRepo.upsert_*。
gate_passed=False → 不写 DAL。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_cleaning.contract import CleaningTrace, SilverRecord
from data_cleaning.dal_sink import DalSink


# ── 工具 ──────────────────────────────────────────────
def _make_silver(df: pd.DataFrame, gate_passed=True, sub_cat="fear_greed"):
    """构造 SilverRecord 用于测试。"""
    return SilverRecord(
        bronze_id="test-bronze-001",
        df=df,
        trace=CleaningTrace(),
        gate_passed=gate_passed,
        quality_report=[],
        schema_tag="macro_v1",
    )


def _mock_repo():
    """构造 mock MarketMacroRepository。"""
    repo = MagicMock()
    repo.upsert_fear_greed.return_value = True
    repo.upsert_funding_rate.return_value = True
    repo.upsert_open_interest.return_value = True
    repo.upsert_long_short_ratio.return_value = True
    repo.upsert_taker_volume.return_value = True
    repo.upsert_liquidation.return_value = True
    return repo


# ── T1 · gate_passed=False → 不写 ──────────────────
def test_gate_failed_no_write():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    df = pd.DataFrame({"value": [25], "value_classification": ["Extreme Fear"],
                       "timestamp": [datetime(2024, 1, 1, tzinfo=timezone.utc)]})
    silver = _make_silver(df, gate_passed=False)

    written = sink.write_silver(silver, source="alternative", category="chain", sub_category="fear_greed")

    assert written == 0
    repo.upsert_fear_greed.assert_not_called()


# ── T2 · 空 DF → 不写 ───────────────────────────────
def test_empty_df_no_write():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    silver = _make_silver(pd.DataFrame())

    written = sink.write_silver(silver, source="ccxt", category="chain", sub_category="fear_greed")

    assert written == 0
    repo.upsert_fear_greed.assert_not_called()


# ── T3 · fear_greed 路由 ────────────────────────────
def test_route_fear_greed():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "value": [25, 72],
        "value_classification": ["Extreme Fear", "Greed"],
        "timestamp": [ts, ts + pd.Timedelta(hours=1)],
    })
    silver = _make_silver(df, sub_cat="fear_greed")

    written = sink.write_silver(silver, source="alternative", category="chain", sub_category="fear_greed")

    assert written == 2
    assert repo.upsert_fear_greed.call_count == 2
    # 验证参数
    first_call = repo.upsert_fear_greed.call_args_list[0]
    assert first_call[0] == (25, "Extreme Fear", ts) or first_call.kwargs.get("value") == 25


# ── T4 · funding_rate 路由 ─────────────────────────
def test_route_funding_rate():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "asset": ["BTC", "ETH"],
        "funding_rate": [Decimal("0.0001"), Decimal("-0.0002")],
        "timestamp": [ts, ts],
    })
    silver = _make_silver(df, sub_cat="funding")

    written = sink.write_silver(silver, source="ccxt", category="chain", sub_category="funding")

    assert written == 2
    assert repo.upsert_funding_rate.call_count == 2


# ── T5 · open_interest 路由 ────────────────────────
def test_route_open_interest():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "asset": ["BTC"],
        "open_interest": [Decimal("50000")],
        "sum_open_interest_value": [Decimal("2000000000")],
        "timestamp": [ts],
    })
    silver = _make_silver(df, sub_cat="open_interest")

    written = sink.write_silver(silver, source="ccxt", category="chain", sub_category="open_interest")

    assert written == 1
    repo.upsert_open_interest.assert_called_once()


# ── T6 · long_short_ratio 路由 ─────────────────────
def test_route_long_short_ratio():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "asset": ["BTC"],
        "long_account": [Decimal("0.62")],
        "short_account": [Decimal("0.38")],
        "long_short_ratio": [Decimal("1.63")],
        "timestamp": [ts],
    })
    silver = _make_silver(df, sub_cat="long_short_ratio")

    written = sink.write_silver(silver, source="ccxt", category="chain", sub_category="long_short_ratio")

    assert written == 1
    repo.upsert_long_short_ratio.assert_called_once()


# ── T7 · taker_volume 路由 ──────────────────────────
def test_route_taker_volume():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "asset": ["BTC"],
        "buy_vol": [Decimal("1000")],
        "sell_vol": [Decimal("800")],
        "buy_sell_volume_diff": [Decimal("200")],
        "buy_sell_volume_ratio": [Decimal("1.25")],
        "timestamp": [ts],
    })
    silver = _make_silver(df, sub_cat="taker_volume")

    written = sink.write_silver(silver, source="ccxt", category="chain", sub_category="taker_volume")

    assert written == 1
    repo.upsert_taker_volume.assert_called_once()


# ── T8 · 未知 sub_category → 跳过 ─────────────────
def test_unknown_sub_category_skipped():
    repo = _mock_repo()
    sink = DalSink(mm_repo=repo)
    df = pd.DataFrame({"some_col": [1], "timestamp": [datetime(2024, 1, 1, tzinfo=timezone.utc)]})
    silver = _make_silver(df, sub_cat="unknown_metric")

    written = sink.write_silver(silver, source="fred", category="macro", sub_category="unknown_metric")

    assert written == 0


# ── T9 · upsert 异常 → fail-open 继续写入 ──────────
def test_upsert_exception_fail_open():
    repo = _mock_repo()
    repo.upsert_fear_greed.side_effect = [RuntimeError("DB lock"), True]
    sink = DalSink(mm_repo=repo)
    ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "value": [25, 72],
        "value_classification": ["Extreme Fear", "Greed"],
        "timestamp": [ts, ts + pd.Timedelta(hours=1)],
    })
    silver = _make_silver(df, sub_cat="fear_greed")

    written = sink.write_silver(silver, source="alternative", category="chain", sub_category="fear_greed")

    # 第1行异常跳过，第2行成功
    assert written == 1


# ── T10 · 传入 mm_repo=None 时使用默认 DAL 工厂 ───
def test_default_repo_factory():
    """mm_repo=None 时应尝试从 dreambuddy_dal 获取默认 repo。"""
    sink = DalSink()  # 不传 mm_repo
    # 验证 sink 有 mm_repo 属性（可能为 None 如果 DAL 不可用，但不应抛异常）
    assert hasattr(sink, "mm_repo")
