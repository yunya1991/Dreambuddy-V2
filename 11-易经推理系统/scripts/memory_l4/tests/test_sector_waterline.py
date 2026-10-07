"""TDD-SVC-001: 赛道整体估值水位（Sector Valuation Waterline）测试 — TDD 先红后绿。

验证 sector_waterline.py：
  - compute_sector_waterline(sector, db_path) -> Optional[SectorWaterline]
  - 赛道水位 = median(各币纵向估值百分位)
  - waterline >= 80 → overheated=True（赛道过热，离场信号）
  - waterline <= 20 → undervalued=True（赛道低估，关注机会）
  - 龙头 = 赛道市值最大币；leader_momentum_7d = 龙头 7d 价格收益率归一化 [-1, +1]
  - FAIL-OPEN：成员 < 3 / 有效数据 < 3 → 返回 None

铁律（SPEC §0.2）：
  - R1 赛道内对比（横向百分位在同赛道内计算）
  - R2 中位数优先于均值（抗异常值）
  - R4 FAIL-OPEN 中性（数据不足不触发信号）

设计决策（SPEC §4.2）：水位用「纵向百分位的中位数」而非「横向百分位的中位数」。
纵向 = 该币自身 MC/Fees 在历史序列中的百分位；中位数反映赛道整体泡沫程度。
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch
from dataclasses import is_dataclass

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))


# ---------------------------------------------------------------------------
# 导入：RED 阶段预期 ImportError（模块尚未实现）
# ---------------------------------------------------------------------------

def _import_sector_waterline():
    """辅助：延迟导入 sector_waterline 模块。"""
    from force_vector.sector_waterline import (
        compute_sector_waterline,
        SectorWaterline,
    )
    return compute_sector_waterline, SectorWaterline


# ---------------------------------------------------------------------------
# 测试数据辅助
# ---------------------------------------------------------------------------

def _fake_query_percentile_map(percentile_map: dict):
    """构造一个 mock query_valuation_percentile，按币种返回固定百分位。

    percentile_map: {"UNI": 30.0, "CRV": 20.0, ...}
    """
    def _mock(coin, db_path=None):
        return percentile_map.get(coin.upper(), 50.0)  # 缺省中性
    return _mock


def _fake_fetch_coin_info_map(info_map: dict):
    """构造一个 mock _fetch_coin_info，按 coin_id 返回 coin_info dict。

    info_map: {"uniswap": {"market_cap_usd": 10_000_000_000, "price_7d_ago": 5.0, "price_now": 6.0}, ...}
    """
    def _mock(db_path, coin_id):
        return info_map.get(coin_id, {})
    return _mock


# ---------------------------------------------------------------------------
# TDD-SVC-001 测试：SectorWaterline
# ---------------------------------------------------------------------------

class TestSectorWaterlineImport:
    """RED: 模块与符号必须可导入。"""

    def test_module_importable(self):
        """模块 force_vector.sector_waterline 必须存在且可导入。"""
        compute_fn, dc = _import_sector_waterline()
        assert callable(compute_fn)
        assert is_dataclass(dc)

    def test_sector_waterline_dataclass_fields(self):
        """SectorWaterline dataclass 字段完整。"""
        _, SectorWaterline = _import_sector_waterline()
        import dataclasses
        fields = {f.name for f in dataclasses.fields(SectorWaterline)}
        expected = {
            "sector", "median_percentile", "member_count",
            "overheated", "undervalued",
            "leader", "leader_momentum_7d", "timestamp",
        }
        assert expected.issubset(fields), f"缺字段: {expected - fields}"


class TestSectorWaterlineMedian:
    """R2: 中位数优先于均值；median_percentile 计算正确。"""

    def test_normal_waterline_three_members(self):
        """3 币纵向百分位 [20, 30, 40] → median=30，中性区间。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 20.0, "CRV": 30.0, "1INCH": 40.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 10_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.median_percentile == pytest.approx(30.0, abs=0.5)
        assert result.member_count == 3
        assert result.overheated is False  # 30 < 80
        assert result.undervalued is False  # 30 > 20

    def test_overheated_waterline(self):
        """3 币纵向百分位 [85, 90, 95] → median=90，overheated=True。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 85.0, "CRV": 90.0, "1INCH": 95.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 10_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.median_percentile == pytest.approx(90.0, abs=0.5)
        assert result.overheated is True  # 90 >= 80
        assert result.undervalued is False

    def test_undervalued_waterline(self):
        """3 币纵向百分位 [10, 15, 20] → median=15，undervalued=True。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 10.0, "CRV": 15.0, "1INCH": 20.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 10_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.median_percentile == pytest.approx(15.0, abs=0.5)
        assert result.undervalued is True  # 15 <= 20
        assert result.overheated is False

    def test_median_resistant_to_outliers(self):
        """R2: 中位数抗异常值。一个极端值不拉偏中位数。"""
        compute_fn, _ = _import_sector_waterline()
        # 一个币 99（极端高估），其余 [40, 45] → median=45（不是均值 61.3）
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 99.0, "CRV": 40.0, "1INCH": 45.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 10_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.median_percentile == pytest.approx(45.0, abs=0.5)


class TestSectorWaterlineFailOpen:
    """R4: FAIL-OPEN 中性，数据不足不触发信号。"""

    def test_insufficient_members_returns_none(self):
        """赛道成员 < 3 → 返回 None（SPEC §7.2）。"""
        compute_fn, _ = _import_sector_waterline()
        # Meme 赛道 4 成员，但 patch SECTOR_MAP 让某赛道只剩 2 成员
        with patch(
            "force_vector.sector_waterline.SECTOR_MAP",
            {"Tiny": ["A", "B"]},
        ):
            result = compute_fn("Tiny", "/fake/db.db")
        assert result is None

    def test_all_members_neutral_data_returns_none(self):
        """所有成员纵向百分位都是 50（数据不足中性）→ 返回 None。

        query_valuation_percentile 在数据不足时返回 50.0，
        如果赛道内所有币都是 50.0，说明赛道整体数据不足，应 FAIL-OPEN。
        """
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 50.0, "CRV": 50.0, "1INCH": 50.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 10_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is None

    def test_db_path_missing_returns_none(self):
        """db_path 不存在 → 返回 None。"""
        compute_fn, _ = _import_sector_waterline()
        # 不 mock query，让它走真实路径，db 不存在 → query 返回 50 → FAIL-OPEN
        result = compute_fn("DEX", "/nonexistent/path/db.db")
        assert result is None

    def test_unknown_sector_returns_none(self):
        """未知赛道 → 返回 None。"""
        compute_fn, _ = _import_sector_waterline()
        result = compute_fn("UnknownSector", "/fake/db.db")
        assert result is None


class TestSectorWaterlineLeader:
    """龙头识别 + 7d 动量。"""

    def test_leader_is_largest_market_cap(self):
        """龙头 = 赛道市值最大币。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 30.0, "CRV": 40.0, "1INCH": 60.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {
                    "market_cap_usd": 15_000_000_000,
                    "price_now": 10.0,
                    "price_7d_ago": 8.0,
                },
                "curve-dao-token": {
                    "market_cap_usd": 5_000_000_000,
                    "price_now": 5.0,
                    "price_7d_ago": 5.0,
                },
                "1inch": {
                    "market_cap_usd": 1_000_000_000,
                    "price_now": 2.0,
                    "price_7d_ago": 2.0,
                },
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.leader == "UNI"  # 市值最大

    def test_leader_momentum_7d_calculation(self):
        """龙头 7d 动量 = (price_now / price_7d_ago - 1) 归一化到 [-1, +1]。"""
        compute_fn, _ = _import_sector_waterline()
        # UNI 是龙头，price 8.0 → 10.0 = +25% 收益率
        # 归一化：±20% 为满量程，所以 25% 应映射到接近 +1
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 30.0, "CRV": 40.0, "1INCH": 60.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {
                    "market_cap_usd": 15_000_000_000,
                    "price_now": 10.0,
                    "price_7d_ago": 8.0,
                },
                "curve-dao-token": {
                    "market_cap_usd": 5_000_000_000,
                },
                "1inch": {
                    "market_cap_usd": 1_000_000_000,
                },
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        # 25% 收益率，±20% 满量程归一化 → tanh(25/20) ≈ 0.85
        assert 0.5 < result.leader_momentum_7d <= 1.0
        assert -1.0 <= result.leader_momentum_7d <= 1.0

    def test_leader_momentum_negative_when_price_drops(self):
        """龙头价格下跌 → 动量为负。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 30.0, "CRV": 40.0, "1INCH": 60.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {
                    "market_cap_usd": 15_000_000_000,
                    "price_now": 8.0,
                    "price_7d_ago": 10.0,  # -20% 跌幅
                },
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.leader_momentum_7d < 0.0

    def test_leader_momentum_zero_when_price_data_missing(self):
        """龙头价格数据缺失 → 动量 = 0.0（FAIL-OPEN 中性）。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 30.0, "CRV": 40.0, "1INCH": 60.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 15_000_000_000},  # 无 price 字段
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert result.leader_momentum_7d == 0.0


class TestSectorWaterlineTimestamp:
    """时间戳字段。"""

    def test_timestamp_is_iso_string(self):
        """timestamp 是非空 ISO 字符串。"""
        compute_fn, _ = _import_sector_waterline()
        with patch(
            "force_vector.sector_waterline.query_valuation_percentile",
            side_effect=_fake_query_percentile_map({"UNI": 30.0, "CRV": 40.0, "1INCH": 60.0}),
        ), patch(
            "force_vector.sector_waterline._fetch_coin_info",
            side_effect=_fake_fetch_coin_info_map({
                "uniswap": {"market_cap_usd": 15_000_000_000},
                "curve-dao-token": {"market_cap_usd": 5_000_000_000},
                "1inch": {"market_cap_usd": 1_000_000_000},
            }),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result is not None
        assert isinstance(result.timestamp, str)
        assert len(result.timestamp) > 0
