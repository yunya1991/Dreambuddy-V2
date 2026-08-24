"""P2 GoldReader 测试 — 从 19-DAL 读取 Gold 数据，组装 FeaturePipeline 输入。

GoldReader 调用 MarketMacroRepo.query_*_by_time()，
将结果合并为 macro_df，供 FeaturePipeline.run() 使用。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from feature_hub.gold_reader import GoldReader


# ── 工具 ──────────────────────────────────────────────
def _mock_repo():
    """构造 mock MarketMacroRepository。"""
    repo = MagicMock()
    # fear_greed: List[Tuple[int, str, datetime]]
    repo.query_fear_greed_by_time.return_value = [
        (25, "Extreme Fear", datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
        (45, "Fear", datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)),
    ]
    # funding: List[Tuple[str, Decimal, datetime]]
    repo.query_funding_by_time.return_value = [
        ("BTC", Decimal("0.0001"), datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
    ]
    # open_interest: List[Tuple[str, Decimal, Decimal, datetime]]
    repo.query_open_interest_by_time.return_value = [
        ("BTC", Decimal("50000"), Decimal("2000000000"), datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
    ]
    # long_short_ratio: List[Tuple[str, Decimal, Decimal, Decimal, datetime]]
    repo.query_long_short_ratio_by_time.return_value = [
        ("BTC", Decimal("0.62"), Decimal("0.38"), Decimal("1.63"), datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
    ]
    # taker_volume: List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]]
    repo.query_taker_volume_by_time.return_value = [
        ("BTC", Decimal("1000"), Decimal("800"), Decimal("200"), Decimal("1.25"), datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)),
    ]
    return repo


# ── T1 · 读取 fear_greed ────────────────────────────
def test_read_fear_greed():
    repo = _mock_repo()
    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    df = reader.read_fear_greed(start, end)

    assert len(df) == 2
    assert "value" in df.columns
    assert "value_classification" in df.columns
    assert "timestamp" in df.columns
    repo.query_fear_greed_by_time.assert_called_once_with(start, end)


# ── T2 · 读取 funding_rate ──────────────────────────
def test_read_funding_rate():
    repo = _mock_repo()
    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    df = reader.read_funding_rate("BTC", start, end)

    assert len(df) == 1
    assert "funding_rate" in df.columns
    assert "symbol" in df.columns
    repo.query_funding_by_time.assert_called_once_with("BTC", start, end)


# ── T3 · 合并读取所有宏观指标 ───────────────────────
def test_read_all_macro():
    repo = _mock_repo()
    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    macro_df = reader.read_all_macro("BTC", start, end)

    assert isinstance(macro_df, pd.DataFrame)
    assert len(macro_df) > 0
    # 应包含各指标列
    assert "fear_greed" in macro_df.columns or "value" in macro_df.columns
    assert "funding_rate" in macro_df.columns


# ── T4 · 空 DAL 查询 → 返回空 DataFrame ─────────────
def test_empty_results():
    repo = _mock_repo()
    repo.query_fear_greed_by_time.return_value = []
    repo.query_funding_by_time.return_value = []
    repo.query_open_interest_by_time.return_value = []
    repo.query_long_short_ratio_by_time.return_value = []
    repo.query_taker_volume_by_time.return_value = []

    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    macro_df = reader.read_all_macro("BTC", start, end)

    assert isinstance(macro_df, pd.DataFrame)
    assert len(macro_df) == 0


# ── T5 · DAL 异常 → fail-open 返回空 DF ─────────────
def test_dal_exception_fail_open():
    repo = _mock_repo()
    # 所有查询都抛异常
    for method_name in [
        "query_fear_greed_by_time", "query_funding_by_time",
        "query_open_interest_by_time", "query_long_short_ratio_by_time",
        "query_taker_volume_by_time",
    ]:
        getattr(repo, method_name).side_effect = RuntimeError("DB lock")

    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    macro_df = reader.read_all_macro("BTC", start, end)

    assert isinstance(macro_df, pd.DataFrame)
    assert len(macro_df) == 0


# ── T6 · 读取 OHLCV + 宏观合并 ──────────────────────
def test_read_ohlcv_with_macro():
    repo = _mock_repo()
    reader = GoldReader(mm_repo=repo)

    ohlcv_df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"),
        "open": [40000, 41000, 42000, 41500, 43000],
        "high": [41000, 42000, 43000, 42000, 44000],
        "low": [39000, 40000, 41000, 40000, 42000],
        "close": [41000, 42000, 41500, 43000, 43500],
        "volume": [100, 120, 110, 130, 140],
    })
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    df, macro_df = reader.read_ohlcv_with_macro(
        symbol="BTC", start_ts=start, end_ts=end, ohlcv_df=ohlcv_df,
    )

    assert isinstance(df, pd.DataFrame)
    assert isinstance(macro_df, pd.DataFrame)
    assert len(df) == 5  # OHLCV 行数不变
    assert "close" in df.columns


# ── T7 · 不传 ohlcv_df → 从 18-DataCenter 拉取 ──────
def test_read_ohlcv_auto_fetch():
    repo = _mock_repo()
    reader = GoldReader(mm_repo=repo)
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    # mock _fetch_ohlcv_from_dc 方法
    with patch.object(reader, "_fetch_ohlcv_from_dc", return_value=pd.DataFrame()):
        df, macro_df = reader.read_ohlcv_with_macro(
            symbol="BTC", start_ts=start, end_ts=end,
        )
        assert isinstance(df, pd.DataFrame)
        assert isinstance(macro_df, pd.DataFrame)


# ── T8 · 传入 mm_repo=None 时尝试默认 DAL 工厂 ──────
def test_default_repo_factory():
    reader = GoldReader()
    assert hasattr(reader, "mm_repo")
