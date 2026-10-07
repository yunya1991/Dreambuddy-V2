"""同赛道估值对比 §4.3 — 全赛道低估扫描器 TDD RED 测试。

验证 sector_undervalued_scanner.py：
  - UndervaluedCoin / SectorUndervaluedScan dataclass
  - compute_opportunity_score 纯函数：opportunity = u*0.6 + c*0.4（仅当 u>0 且 c>0）
  - compute_rank 纯函数：S(>=0.7)/A(>=0.5)/B(>=0.3)/C(其他)
  - scan_sector_undervalued 主函数：遍历 SECTOR_MAP，编排 multi_dim_valuation + follow_up_catalyst
  - 过滤 undervalued_score > 0.3，按 opportunity_score 降序输出 Top N
  - FAIL-OPEN：异常返回空 scan
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch
from dataclasses import fields as dataclass_fields

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.sector_undervalued_scanner import (
    UndervaluedCoin,
    SectorUndervaluedScan,
    scan_sector_undervalued,
    compute_opportunity_score,
    compute_rank,
)


# ---------------------------------------------------------------------------
# 1. Import & Dataclass 字段完整性
# ---------------------------------------------------------------------------

class TestImport:
    """模块可导入且关键符号存在。"""

    def test_import_undervalued_coin(self):
        assert UndervaluedCoin is not None

    def test_import_sector_undervalued_scan(self):
        assert SectorUndervaluedScan is not None

    def test_import_scan_sector_undervalued(self):
        assert callable(scan_sector_undervalued)

    def test_import_compute_opportunity_score(self):
        assert callable(compute_opportunity_score)

    def test_import_compute_rank(self):
        assert callable(compute_rank)


class TestDataclassFields:
    """验证 dataclass 字段完整性（SPEC §4.3）。"""

    def test_undervalued_coin_has_seven_fields(self):
        """UndervaluedCoin 应有 7 个字段：coin/sector/undervalued_score/multi_dim_details/leader_momentum/opportunity_score/rank。"""
        names = {f.name for f in dataclass_fields(UndervaluedCoin)}
        assert names == {
            "coin", "sector", "undervalued_score",
            "multi_dim_details", "leader_momentum",
            "opportunity_score", "rank",
        }

    def test_sector_undervalued_scan_has_three_fields(self):
        """SectorUndervaluedScan 应有 3 个字段：timestamp/sectors/top_opportunities。"""
        names = {f.name for f in dataclass_fields(SectorUndervaluedScan)}
        assert names == {"timestamp", "sectors", "top_opportunities"}


# ---------------------------------------------------------------------------
# 2. compute_opportunity_score 纯函数
# ---------------------------------------------------------------------------

class TestComputeOpportunityScore:
    """验证机会分计算（SPEC §4.3 公式 4）。

    opportunity_score = undervalued_score * 0.6 + catalyst * 0.4
    仅当 undervalued_score > 0 且 catalyst > 0 时计算，否则返回 0.0
    """

    def test_opportunity_normal(self):
        """u=0.7, c=0.6 → 0.7*0.6 + 0.6*0.4 = 0.42 + 0.24 = 0.66"""
        score = compute_opportunity_score(undervalued_score=0.7, catalyst=0.6)
        assert abs(score - 0.66) < 1e-6

    def test_opportunity_zero_when_undervalued_negative(self):
        """低估分为负 → 不构成跟涨机会 → 0.0"""
        assert compute_opportunity_score(undervalued_score=-0.1, catalyst=0.5) == 0.0

    def test_opportunity_zero_when_catalyst_negative(self):
        """catalyst 为负（龙头下跌） → 0.0"""
        assert compute_opportunity_score(undervalued_score=0.5, catalyst=-0.1) == 0.0

    def test_opportunity_zero_when_both_zero(self):
        assert compute_opportunity_score(undervalued_score=0.0, catalyst=0.0) == 0.0

    def test_opportunity_clamp_to_one(self):
        """u=1.0, c=1.0 → 1.0（满量程）"""
        score = compute_opportunity_score(undervalued_score=1.0, catalyst=1.0)
        assert abs(score - 1.0) < 1e-6

    def test_opportunity_threshold_undervalued_zero(self):
        """undervalued=0 边界 → 0.0（必须 > 0 才计算）"""
        assert compute_opportunity_score(undervalued_score=0.0, catalyst=0.5) == 0.0

    def test_opportunity_threshold_catalyst_zero(self):
        """catalyst=0 边界 → 0.0"""
        assert compute_opportunity_score(undervalued_score=0.5, catalyst=0.0) == 0.0


# ---------------------------------------------------------------------------
# 3. compute_rank 纯函数
# ---------------------------------------------------------------------------

class TestComputeRank:
    """验证 rank 体系（同 BDSM rank：S/A/B/C）。"""

    def test_rank_S_at_threshold(self):
        """score >= 0.7 → S"""
        assert compute_rank(0.7) == "S"
        assert compute_rank(0.85) == "S"
        assert compute_rank(1.0) == "S"

    def test_rank_A(self):
        """0.5 <= score < 0.7 → A"""
        assert compute_rank(0.5) == "A"
        assert compute_rank(0.69) == "A"

    def test_rank_B(self):
        """0.3 <= score < 0.5 → B"""
        assert compute_rank(0.3) == "B"
        assert compute_rank(0.49) == "B"

    def test_rank_C(self):
        """score < 0.3 → C"""
        assert compute_rank(0.29) == "C"
        assert compute_rank(0.0) == "C"
        assert compute_rank(-0.1) == "C"


# ---------------------------------------------------------------------------
# 4. scan_sector_undervalued 集成测试
# ---------------------------------------------------------------------------

# 测试用小型赛道结构
_TEST_SECTOR_MAP = {
    "DEX": ["UNI", "1INCH", "SUSHI"],
    "L1": ["ETH", "SOL"],
}


def _mock_multi_dim(coin, db_path=None):
    """根据币种返回不同低估分。"""
    table = {
        "UNI": {"multi_dim_score": 0.7, "mc_fees_pct": 20.0, "mc_tvl_pct": 25.0, "peg_pct": 30.0, "confirmed_low": True, "dimensions_available": 3},
        "1INCH": {"multi_dim_score": 0.5, "mc_fees_pct": 30.0, "mc_tvl_pct": 35.0, "peg_pct": 40.0, "confirmed_low": True, "dimensions_available": 3},
        "SUSHI": {"multi_dim_score": -0.3, "mc_fees_pct": 75.0, "mc_tvl_pct": 80.0, "peg_pct": 70.0, "confirmed_low": False, "dimensions_available": 3},
        "ETH": {"multi_dim_score": 0.4, "mc_fees_pct": 35.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 1},
        "SOL": {"multi_dim_score": -0.5, "mc_fees_pct": 90.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 1},
    }
    return table.get(coin, {"multi_dim_score": 0.0, "mc_fees_pct": 0.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 0})


def _mock_catalyst(sector, db_path=None):
    """返回固定 catalyst 值。"""
    return {
        "leader": "UNI" if sector == "DEX" else "ETH",
        "leader_momentum": 0.6,
        "sector_breadth": 0.8,
        "catalyst": 0.48,
        "timestamp": "2026-10-07T00:00:00+00:00",
    }


class TestScanSectorUndervalued:
    """验证主函数编排逻辑。"""

    def test_returns_dataclass(self):
        """主函数应返回 SectorUndervaluedScan。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        assert isinstance(result, SectorUndervaluedScan)

    def test_scan_includes_undervalued_coin(self):
        """UNDervalued_score > 0.3 的币应进入 sectors 列表。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        # UNI(0.7) 和 1INCH(0.5) 应在 DEX 赛道
        dex_coins = result.sectors.get("DEX", [])
        coin_names = {c.coin for c in dex_coins}
        assert "UNI" in coin_names
        assert "1INCH" in coin_names

    def test_scan_filters_out_high_valuation(self):
        """undervalued_score <= 0.3 的币不应出现。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        # SUSHI(-0.3) 和 SOL(-0.5) 不应出现
        all_coins = {c.coin for coins in result.sectors.values() for c in coins}
        assert "SUSHI" not in all_coins
        assert "SOL" not in all_coins

    def test_scan_filters_eth_below_threshold(self):
        """ETH(0.4) > 0.3 应在 L1 赛道，但机会分受 catalyst 影响。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        l1_coins = result.sectors.get("L1", [])
        coin_names = {c.coin for c in l1_coins}
        assert "ETH" in coin_names  # 0.4 > 0.3 阈值

    def test_opportunity_score_correct(self):
        """验证 opportunity_score 计算正确：UNI(0.7, catalyst=0.48) → 0.7*0.6 + 0.48*0.4 = 0.42 + 0.192 = 0.612"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        uni = next(c for c in result.top_opportunities if c.coin == "UNI")
        assert abs(uni.opportunity_score - 0.612) < 1e-3

    def test_top_opportunities_sorted_desc(self):
        """top_opportunities 应按 opportunity_score 降序排列。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        scores = [c.opportunity_score for c in result.top_opportunities]
        assert scores == sorted(scores, reverse=True), f"未按降序排列: {scores}"

    def test_top_opportunities_contains_all_undervalued(self):
        """top_opportunities 应包含所有 undervalued_score > 0.3 的币（跨赛道）。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        # UNI(0.7), 1INCH(0.5), ETH(0.4) 共 3 个低估币
        assert len(result.top_opportunities) == 3
        top_names = {c.coin for c in result.top_opportunities}
        assert top_names == {"UNI", "1INCH", "ETH"}

    def test_rank_assigned(self):
        """每个 UndervaluedCoin 应有 rank 字段（S/A/B/C）。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        for coin in result.top_opportunities:
            assert coin.rank in {"S", "A", "B", "C"}, f"非法 rank: {coin.rank}"

    def test_leader_momentum_populated(self):
        """UndervaluedCoin.leader_momentum 应从 catalyst 结果中提取。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        uni = next(c for c in result.top_opportunities if c.coin == "UNI")
        assert abs(uni.leader_momentum - 0.6) < 1e-6

    def test_multi_dim_details_populated(self):
        """UndervaluedCoin.multi_dim_details 应包含三个百分位字段。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        uni = next(c for c in result.top_opportunities if c.coin == "UNI")
        assert "mc_fees_pct" in uni.multi_dim_details
        assert "mc_tvl_pct" in uni.multi_dim_details
        assert "peg_pct" in uni.multi_dim_details

    def test_timestamp_present(self):
        """结果应包含 ISO 格式 timestamp。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_mock_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        assert result.timestamp
        assert "T" in result.timestamp  # ISO 格式

    def test_failopen_on_exception(self):
        """异常时返回空 SectorUndervaluedScan（FAIL-OPEN）。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=RuntimeError("boom")):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        assert isinstance(result, SectorUndervaluedScan)
        assert result.top_opportunities == []
        assert result.sectors == {}

    def test_empty_sector_map(self):
        """SECTOR_MAP 为空时返回空 scan。"""
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", {}):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        assert isinstance(result, SectorUndervaluedScan)
        assert result.top_opportunities == []

    def test_catalyst_zero_excluded_but_kept_if_low_score(self):
        """catalyst=0 时，opportunity_score=0，但若 undervalued_score>0.3 仍应进入 sectors（rank=C）。

        验证：undervalued_score>0.3 是进入 sectors 的硬过滤，opportunity_score 只影响排名
        """
        def _zero_catalyst(sector, db_path=None):
            return {
                "leader": "UNI", "leader_momentum": 0.0,
                "sector_breadth": 0.0, "catalyst": 0.0,
                "timestamp": "2026-10-07T00:00:00+00:00",
            }
        with patch("force_vector.sector_undervalued_scanner.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_undervalued_scanner.compute_multi_dim_valuation", side_effect=_mock_multi_dim), \
             patch("force_vector.sector_undervalued_scanner.compute_follow_up_catalyst", side_effect=_zero_catalyst):
            result = scan_sector_undervalued(db_path="/fake/db.db")
        # UNI(0.7) 仍在 sectors 中（undervalued_score > 0.3）
        dex_coins = {c.coin for c in result.sectors.get("DEX", [])}
        assert "UNI" in dex_coins
        # 但 opportunity_score = 0（因为 catalyst=0）
        uni = next(c for c in result.sectors.get("DEX", []) if c.coin == "UNI")
        assert uni.opportunity_score == 0.0
        assert uni.rank == "C"  # 0.0 < 0.3
