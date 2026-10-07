"""同赛道估值对比 §4.6 — 顶层编排器 TDD RED 测试。

验证 sector_valuation_orchestrator.py：
  - SectorValuationOrchestrator / SectorValuationResult / SectorOverheatSignal dataclass
  - _compute_overvalued_ratio 纯函数
  - _should_trigger_overheat 纯函数（三重条件 AND）
  - run() 主函数：整合 waterline + scanner + overheat → G1/G2/G3
  - FAIL-OPEN：异常返回中性结果
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

from force_vector.sector_valuation_orchestrator import (
    SectorValuationOrchestrator,
    SectorValuationResult,
    SectorOverheatSignal,
    compute_overvalued_ratio,
    should_trigger_overheat,
)
from force_vector.sector_waterline import SectorWaterline
from force_vector.sector_undervalued_scanner import SectorUndervaluedScan


# ---------------------------------------------------------------------------
# 1. Import & Dataclass
# ---------------------------------------------------------------------------

class TestImport:
    """模块可导入且关键符号存在。"""

    def test_import_orchestrator(self):
        assert SectorValuationOrchestrator is not None

    def test_import_result_dataclass(self):
        assert SectorValuationResult is not None

    def test_import_overheat_signal_dataclass(self):
        assert SectorOverheatSignal is not None

    def test_import_compute_overvalued_ratio(self):
        assert callable(compute_overvalued_ratio)

    def test_import_should_trigger_overheat(self):
        assert callable(should_trigger_overheat)


class TestDataclassFields:
    """验证 dataclass 字段完整性（SPEC §4.6 + §5.3）。"""

    def test_sector_overheat_signal_has_five_fields(self):
        """SectorOverheatSignal 应有 5 字段：sector/waterline/leader_momentum/overvalued_ratio/confidence。"""
        names = {f.name for f in dataclass_fields(SectorOverheatSignal)}
        assert names == {
            "sector", "waterline", "leader_momentum",
            "overvalued_ratio", "confidence",
        }

    def test_sector_valuation_result_has_four_fields(self):
        """SectorValuationResult 应有 4 字段：timestamp/waterlines/undervalued_scan/overheat_signals。"""
        names = {f.name for f in dataclass_fields(SectorValuationResult)}
        assert names == {"timestamp", "waterlines", "undervalued_scan", "overheat_signals"}


# ---------------------------------------------------------------------------
# 2. compute_overvalued_ratio 纯函数
# ---------------------------------------------------------------------------

class TestComputeOvervaluedRatio:
    """计算赛道内 undervalued_score < -0.3 的币占比。"""

    def test_ratio_normal(self):
        """5 币中 3 个 < -0.3 → 0.6"""
        scores = [0.5, -0.4, -0.5, -0.6, 0.2]
        ratio = compute_overvalued_ratio(scores)
        assert abs(ratio - 0.6) < 1e-6

    def test_ratio_zero_when_none_overvalued(self):
        """所有币都非高估 → 0.0"""
        scores = [0.5, 0.2, -0.1, 0.0]
        assert compute_overvalued_ratio(scores) == 0.0

    def test_ratio_one_when_all_overvalued(self):
        """所有币都高估 → 1.0"""
        scores = [-0.4, -0.5, -0.6]
        assert compute_overvalued_ratio(scores) == 1.0

    def test_ratio_empty_returns_zero(self):
        """空列表 → 0.0（FAIL-OPEN）"""
        assert compute_overvalued_ratio([]) == 0.0

    def test_ratio_threshold_boundary(self):
        """-0.3 边界：-0.3 不计入（必须 < -0.3）"""
        scores = [-0.3, -0.31]
        ratio = compute_overvalued_ratio(scores)
        assert abs(ratio - 0.5) < 1e-6  # 仅 -0.31 计入


# ---------------------------------------------------------------------------
# 3. should_trigger_overheat 纯函数（三重条件 AND）
# ---------------------------------------------------------------------------

class TestShouldTriggerOverheat:
    """验证 G3 做空信号三重确认（SPEC §5.3 AND）。"""

    def test_trigger_all_conditions_met(self):
        """waterline=90, leader_momentum=-0.2, ratio=0.7 → True"""
        assert should_trigger_overheat(
            waterline=90.0, leader_momentum=-0.2, overvalued_ratio=0.7
        ) is True

    def test_no_trigger_low_waterline(self):
        """waterline=70 → False（条件1不满足）"""
        assert should_trigger_overheat(
            waterline=70.0, leader_momentum=-0.2, overvalued_ratio=0.7
        ) is False

    def test_no_trigger_strong_leader(self):
        """leader_momentum=0.1 → False（条件2不满足，需 < -0.1）"""
        assert should_trigger_overheat(
            waterline=90.0, leader_momentum=0.1, overvalued_ratio=0.7
        ) is False

    def test_no_trigger_low_ratio(self):
        """overvalued_ratio=0.5 → False（条件3不满足，需 >= 0.6）"""
        assert should_trigger_overheat(
            waterline=90.0, leader_momentum=-0.2, overvalued_ratio=0.5
        ) is False

    def test_trigger_at_threshold_boundary(self):
        """边界：waterline=85, lm=-0.11, ratio=0.6 → True（SPEC §5.3 严格 < -0.1）"""
        assert should_trigger_overheat(
            waterline=85.0, leader_momentum=-0.11, overvalued_ratio=0.6
        ) is True

    def test_no_trigger_leader_at_zero(self):
        """leader_momentum=0 → False"""
        assert should_trigger_overheat(
            waterline=90.0, leader_momentum=0.0, overvalued_ratio=0.7
        ) is False


# ---------------------------------------------------------------------------
# 4. SectorValuationOrchestrator.run 集成测试
# ---------------------------------------------------------------------------

_TEST_SECTOR_MAP = {
    "DEX": ["UNI", "1INCH", "SUSHI"],
    "L1": ["ETH", "SOL"],
}


def _mock_waterline_overheated(sector, db_path=None):
    """返回过热水位（DEX=90 触发，L1=60 不触发）。"""
    table = {
        "DEX": SectorWaterline(
            sector="DEX", median_percentile=90.0, member_count=3,
            overheated=True, undervalued=False,
            leader="UNI", leader_momentum_7d=-0.2,
            timestamp="2026-10-07T00:00:00+00:00",
        ),
        "L1": SectorWaterline(
            sector="L1", median_percentile=60.0, member_count=2,
            overheated=False, undervalued=False,
            leader="ETH", leader_momentum_7d=0.3,
            timestamp="2026-10-07T00:00:00+00:00",
        ),
    }
    return table.get(sector)


def _mock_waterline_neutral(sector, db_path=None):
    """返回中性水位（无过热）。"""
    return SectorWaterline(
        sector=sector, median_percentile=50.0, member_count=3,
        overheated=False, undervalued=False,
        leader="UNI", leader_momentum_7d=0.1,
        timestamp="2026-10-07T00:00:00+00:00",
    )


def _mock_multi_dim_for_overheat(coin, db_path=None):
    """让 DEX 大部分币高估，L1 不高估。"""
    table = {
        "UNI": {"multi_dim_score": -0.4, "mc_fees_pct": 80.0, "mc_tvl_pct": 85.0, "peg_pct": 75.0, "confirmed_low": False, "dimensions_available": 3},
        "1INCH": {"multi_dim_score": -0.5, "mc_fees_pct": 85.0, "mc_tvl_pct": 90.0, "peg_pct": 80.0, "confirmed_low": False, "dimensions_available": 3},
        "SUSHI": {"multi_dim_score": 0.2, "mc_fees_pct": 50.0, "mc_tvl_pct": 55.0, "peg_pct": 45.0, "confirmed_low": False, "dimensions_available": 3},
        "ETH": {"multi_dim_score": 0.3, "mc_fees_pct": 40.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 1},
        "SOL": {"multi_dim_score": 0.1, "mc_fees_pct": 50.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 1},
    }
    return table.get(coin, {"multi_dim_score": 0.0, "mc_fees_pct": 0.0, "mc_tvl_pct": 0.0, "peg_pct": 0.0, "confirmed_low": False, "dimensions_available": 0})


def _mock_empty_scan(db_path=None, top_n=20):
    """空扫描结果。"""
    return SectorUndervaluedScan(
        timestamp="2026-10-07T00:00:00+00:00",
        sectors={},
        top_opportunities=[],
    )


class TestOrchestratorRun:
    """验证 run() 编排逻辑。"""

    def test_run_returns_dataclass(self):
        """run() 应返回 SectorValuationResult。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_neutral), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        assert isinstance(result, SectorValuationResult)

    def test_run_aggregates_waterlines(self):
        """waterlines 应包含所有赛道的水位（G2）。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_neutral), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        assert len(result.waterlines) == 2  # DEX + L1
        sectors = {w.sector for w in result.waterlines}
        assert sectors == {"DEX", "L1"}

    def test_run_includes_undervalued_scan(self):
        """undervalued_scan 应为 SectorUndervaluedScan 实例（G1）。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_neutral), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        assert isinstance(result.undervalued_scan, SectorUndervaluedScan)

    def test_run_detects_overheat_signal(self):
        """DEX 赛道满足三重条件 → 应在 overheat_signals 中。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_overheated), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        # DEX 应触发过热信号（waterline=90, lm=-0.2, 2/3 高估 → ratio=0.67 >= 0.6）
        overheat_sectors = {s.sector for s in result.overheat_signals}
        assert "DEX" in overheat_sectors

    def test_run_no_overheat_when_waterline_low(self):
        """L1 水位=60 不应触发过热信号。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_neutral), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        # 中性水位（50），无过热
        assert result.overheat_signals == []

    def test_run_overheat_signal_has_confidence(self):
        """过热信号应有 confidence 字段且 > 0。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_overheated), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        dex_signal = next((s for s in result.overheat_signals if s.sector == "DEX"), None)
        assert dex_signal is not None
        assert 0.0 < dex_signal.confidence <= 1.0

    def test_run_overheat_signal_has_fields(self):
        """过热信号应包含完整字段：waterline/leader_momentum/overvalued_ratio。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_overheated), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        dex_signal = next((s for s in result.overheat_signals if s.sector == "DEX"), None)
        assert dex_signal is not None
        assert dex_signal.waterline == 90.0
        assert dex_signal.leader_momentum == -0.2
        assert 0.0 <= dex_signal.overvalued_ratio <= 1.0

    def test_run_timestamp_present(self):
        """结果应包含 ISO timestamp。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_waterline_neutral), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        assert result.timestamp
        assert "T" in result.timestamp

    def test_run_failopen_on_exception(self):
        """异常时返回中性 SectorValuationResult（FAIL-OPEN）。"""
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=RuntimeError("boom")):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        assert isinstance(result, SectorValuationResult)
        assert result.waterlines == []
        assert result.overheat_signals == []

    def test_run_skips_none_waterline(self):
        """compute_sector_waterline 返回 None 时跳过该赛道。"""
        def _mock_none_for_l1(sector, db_path=None):
            if sector == "L1":
                return None
            return _mock_waterline_neutral(sector, db_path)
        with patch("force_vector.sector_valuation_orchestrator.SECTOR_MAP", _TEST_SECTOR_MAP), \
             patch("force_vector.sector_valuation_orchestrator.compute_sector_waterline", side_effect=_mock_none_for_l1), \
             patch("force_vector.sector_valuation_orchestrator.scan_sector_undervalued", side_effect=_mock_empty_scan), \
             patch("force_vector.sector_valuation_orchestrator.compute_multi_dim_valuation", side_effect=_mock_multi_dim_for_overheat):
            orch = SectorValuationOrchestrator()
            result = orch.run(db_path="/fake/db.db")
        # 只有 DEX 有水位，L1 返回 None 被跳过
        sectors = {w.sector for w in result.waterlines}
        assert sectors == {"DEX"}
