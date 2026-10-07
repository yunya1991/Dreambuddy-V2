"""TDD-SVC 集成（SPEC §6）：bdsm_snapshot_writer 注入 sector_valuation 4 字段 + summary。

验证：
  1. _neutral_coin_entry() 返回 dict 含 4 新字段且为中性默认值
  2. neutral_snapshot() 返回 dict 含 sector_valuation_summary 中性默认
  3. _build_coin_entry() 调用后 entry 含 4 字段（mock SectorValuationOrchestrator.run）
  4. write_snapshot(dry_run=False) 生成快照含 sector_valuation_summary

mock 路径必须指向 force_vector.bdsm_snapshot_writer.SectorValuationOrchestrator
（from import 在 bdsm_snapshot_writer 模块内消费，mock 需消费方路径）。

铁律（SPEC §0.2 §7.2）：
  R4 FAIL-OPEN：DB 查询失败整模块返回中性结果，不阻塞快照生成
  开关关闭 → 对应字段返回中性默认值
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))


@pytest.fixture(autouse=True)
def _clear_sector_valuation_cache():
    """每个测试前后清除 sector_valuation 缓存，避免 mock 间数据污染。"""
    from force_vector import bdsm_snapshot_writer
    bdsm_snapshot_writer._SECTOR_VALUATION_CACHE.clear()
    yield
    bdsm_snapshot_writer._SECTOR_VALUATION_CACHE.clear()


# ---------------------------------------------------------------------------
# 测试 1: _neutral_coin_entry 含 4 新字段且为中性默认
# ---------------------------------------------------------------------------

class TestNeutralCoinEntryFields:
    """RED: 中性 coin entry 必须含 sector_valuation 4 字段且为中性默认值。"""

    def test_neutral_entry_contains_sector_waterline(self):
        from force_vector.bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test_insufficient")
        assert "sector_waterline" in entry
        wl = entry["sector_waterline"]
        # 中性默认：sector 空字符串，median_percentile 50.0，bool False，leader 空字符串
        assert wl["sector"] == ""
        assert wl["median_percentile"] == 50.0
        assert wl["overheated"] is False
        assert wl["undervalued"] is False
        assert wl["leader"] == ""
        assert wl["leader_momentum_7d"] == 0.0

    def test_neutral_entry_contains_multi_dim_valuation(self):
        from force_vector.bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test_insufficient")
        assert "multi_dim_valuation" in entry
        md = entry["multi_dim_valuation"]
        # 中性默认：所有维度百分位 50.0，合成分 0.0
        assert md["mc_fees_pct"] == 50.0
        assert md["mc_tvl_pct"] == 50.0
        assert md["peg_pct"] == 50.0
        assert md["multi_dim_score"] == 0.0

    def test_neutral_entry_contains_undervalued_peers(self):
        from force_vector.bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test_insufficient")
        assert "undervalued_peers" in entry
        # 中性默认：空列表
        assert entry["undervalued_peers"] == []

    def test_neutral_entry_contains_overheat_signal(self):
        from force_vector.bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test_insufficient")
        assert "overheat_signal" in entry
        oh = entry["overheat_signal"]
        # 中性默认：不触发，水位 50.0，置信度 0.0
        assert oh["triggered"] is False
        assert oh["waterline"] == 50.0
        assert oh["confidence"] == 0.0


# ---------------------------------------------------------------------------
# 测试 2: neutral_snapshot 含 sector_valuation_summary 中性默认
# ---------------------------------------------------------------------------

class TestNeutralSnapshotSummary:
    """RED: neutral_snapshot 必须含 sector_valuation_summary 中性默认。"""

    def test_neutral_snapshot_contains_summary(self):
        from force_vector.bdsm_snapshot_writer import neutral_snapshot
        snap = neutral_snapshot("fallback_test")
        assert "sector_valuation_summary" in snap
        summary = snap["sector_valuation_summary"]
        assert "generated_at" in summary
        assert summary["waterlines"] == []
        assert summary["top_opportunities"] == []
        assert summary["overheat_sectors"] == []

    def test_neutral_snapshot_summary_generated_at_is_iso(self):
        """summary.generated_at 应是 ISO 格式时间戳。"""
        from force_vector.bdsm_snapshot_writer import neutral_snapshot
        snap = neutral_snapshot("fallback_test")
        ga = snap["sector_valuation_summary"]["generated_at"]
        assert isinstance(ga, str)
        assert len(ga) > 10  # 非空字符串


# ---------------------------------------------------------------------------
# 测试 3: _build_coin_entry 注入 4 字段真实值（mock SectorValuationOrchestrator）
# ---------------------------------------------------------------------------

def _make_mock_orchestrator_result():
    """构造模拟 SectorValuationResult 返回值。

    模拟一个 DEX 赛道水位 + UNI 币的 multi_dim_valuation + 低估伙伴 + 过热信号。
    """
    # 用 SimpleNamespace 模拟 dataclass
    from types import SimpleNamespace

    waterline = SimpleNamespace(
        sector="DEX",
        median_percentile=88.0,
        member_count=4,
        overheated=True,
        undervalued=False,
        leader="UNI",
        leader_momentum_7d=-0.5,
        timestamp="2026-10-07T00:00:00+00:00",
    )

    peer1 = SimpleNamespace(coin="1INCH", sector="DEX", undervalued_score=0.6,
                            multi_dim_details={"mc_fees_pct": 30.0, "mc_tvl_pct": 25.0, "peg_pct": 40.0},
                            leader_momentum=-0.5, opportunity_score=0.62, rank="A")
    peer2 = SimpleNamespace(coin="SUSHI", sector="DEX", undervalued_score=0.5,
                            multi_dim_details={"mc_fees_pct": 35.0, "mc_tvl_pct": 28.0, "peg_pct": 45.0},
                            leader_momentum=-0.5, opportunity_score=0.48, rank="B")

    scan = SimpleNamespace(
        timestamp="2026-10-07T00:00:00+00:00",
        sectors={"DEX": [peer1, peer2]},
        top_opportunities=[peer1, peer2],
    )

    overheat = SimpleNamespace(
        sector="DEX",
        waterline=88.0,
        leader_momentum=-0.5,
        overvalued_ratio=0.7,
        confidence=0.2,
    )

    result = SimpleNamespace(
        timestamp="2026-10-07T00:00:00+00:00",
        waterlines=[waterline],
        undervalued_scan=scan,
        overheat_signals=[overheat],
    )
    return result


class TestBuildCoinEntrySectorValuation:
    """RED: _build_coin_entry 注入 4 字段真实值（mock orchestrator + compute_multi_dim）。"""

    def test_build_entry_contains_sector_waterline_from_orchestrator(self):
        """_build_coin_entry 调用后 entry 含 sector_waterline（来自 orchestrator.waterlines）。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            # 同时 mock compute_signal 避免真实 DB 访问
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                entry = bdsm_snapshot_writer._build_coin_entry("UNI", db_path="/fake.db")
        assert "sector_waterline" in entry
        wl = entry["sector_waterline"]
        assert wl["sector"] == "DEX"
        assert wl["median_percentile"] == 88.0
        assert wl["overheated"] is True
        assert wl["undervalued"] is False
        assert wl["leader"] == "UNI"
        assert wl["leader_momentum_7d"] == -0.5

    def test_build_entry_contains_multi_dim_valuation(self):
        """_build_coin_entry 调用后 entry 含 multi_dim_valuation。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                entry = bdsm_snapshot_writer._build_coin_entry("UNI", db_path="/fake.db")
        assert "multi_dim_valuation" in entry
        md = entry["multi_dim_valuation"]
        # 中性默认或真实值（取决于 mock compute_multi_dim_valuation 是否被调用）
        # 由于 orchestrator 已 mock，compute_multi_dim_valuation 不会被 orchestrator 内部调用
        # 这里只断言字段存在且结构正确
        assert "mc_fees_pct" in md
        assert "mc_tvl_pct" in md
        assert "peg_pct" in md
        assert "multi_dim_score" in md

    def test_build_entry_contains_undervalued_peers_from_scan(self):
        """_build_coin_entry 调用后 entry 含 undervalued_peers（来自 orchestrator.undervalued_scan）。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                entry = bdsm_snapshot_writer._build_coin_entry("UNI", db_path="/fake.db")
        assert "undervalued_peers" in entry
        peers = entry["undervalued_peers"]
        # 应包含 1INCH 和 SUSHI（UNI 自己应排除）
        coins_in_peers = [p["coin"] for p in peers]
        assert "1INCH" in coins_in_peers
        assert "SUSHI" in coins_in_peers
        assert "UNI" not in coins_in_peers  # 自己排除
        # 检查 opportunity_score 字段
        for p in peers:
            assert "coin" in p
            assert "opportunity_score" in p

    def test_build_entry_contains_overheat_signal(self):
        """_build_coin_entry 调用后 entry 含 overheat_signal（来自 orchestrator.overheat_signals）。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                entry = bdsm_snapshot_writer._build_coin_entry("UNI", db_path="/fake.db")
        assert "overheat_signal" in entry
        oh = entry["overheat_signal"]
        # DEX 触发了过热信号
        assert oh["triggered"] is True
        assert oh["waterline"] == 88.0
        assert oh["confidence"] == 0.2

    def test_build_entry_overheat_signal_not_triggered_for_other_sector(self):
        """非过热赛道的币 overheat_signal.triggered=False。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                # SOL 属 L1 赛道（非 DEX），orchestrator 内只有 DEX 过热信号
                entry = bdsm_snapshot_writer._build_coin_entry("SOL", db_path="/fake.db")
        oh = entry["overheat_signal"]
        assert oh["triggered"] is False


# ---------------------------------------------------------------------------
# 测试 4: write_snapshot(dry_run=False) 生成快照含 sector_valuation_summary
# ---------------------------------------------------------------------------

class TestWriteSnapshotSummary:
    """RED: write_snapshot(dry_run=False) 生成快照含 sector_valuation_summary。"""

    def test_write_snapshot_dry_run_contains_summary(self, tmp_path):
        """dry_run_read_coin_data_from_db=False 模式下，快照顶层含 sector_valuation_summary。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            output_path = bdsm_snapshot_writer.write_snapshot(
                out_dir=str(tmp_path),
                dry_run_read_coin_data_from_db=False,
                target_date="2026-10-07",
            )
        import json
        with open(output_path) as f:
            snap = json.load(f)
        assert "sector_valuation_summary" in snap
        summary = snap["sector_valuation_summary"]
        assert "generated_at" in summary
        assert "waterlines" in summary
        assert "top_opportunities" in summary
        assert "overheat_sectors" in summary

    def test_write_snapshot_dry_run_summary_has_waterlines(self, tmp_path):
        """dry_run=False 模式下，summary.waterlines 来自 orchestrator.waterlines。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            output_path = bdsm_snapshot_writer.write_snapshot(
                out_dir=str(tmp_path),
                dry_run_read_coin_data_from_db=False,
                target_date="2026-10-07",
            )
        import json
        with open(output_path) as f:
            snap = json.load(f)
        summary = snap["sector_valuation_summary"]
        # 应至少包含 DEX 赛道
        sectors = [w.get("sector") for w in summary["waterlines"]]
        assert "DEX" in sectors

    def test_write_snapshot_dry_run_summary_overheat_sectors(self, tmp_path):
        """dry_run=False 模式下，summary.overheat_sectors 含 DEX。"""
        from force_vector import bdsm_snapshot_writer
        mock_result = _make_mock_orchestrator_result()

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = mock_result
            output_path = bdsm_snapshot_writer.write_snapshot(
                out_dir=str(tmp_path),
                dry_run_read_coin_data_from_db=False,
                target_date="2026-10-07",
            )
        import json
        with open(output_path) as f:
            snap = json.load(f)
        summary = snap["sector_valuation_summary"]
        assert "DEX" in summary["overheat_sectors"]


# ---------------------------------------------------------------------------
# 测试 5: FAIL-OPEN — orchestrator 异常时仍生成中性字段
# ---------------------------------------------------------------------------

class TestFailOpenOrchestratorException:
    """RED: orchestrator.run() 抛异常 → coin entry 4 字段仍存在（中性默认）。"""

    def test_build_entry_fail_open_on_orchestrator_exception(self):
        """orchestrator.run() 抛异常 → coin entry 4 字段仍为中性默认。"""
        from force_vector import bdsm_snapshot_writer

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("DB unavailable")
            with patch.object(bdsm_snapshot_writer, "_fetch_snapshot_klines", return_value=[]):
                entry = bdsm_snapshot_writer._build_coin_entry("UNI", db_path="/fake.db")
        # 4 字段必须存在（FAIL-OPEN 中性默认）
        assert "sector_waterline" in entry
        assert entry["sector_waterline"]["median_percentile"] == 50.0
        assert "multi_dim_valuation" in entry
        assert entry["multi_dim_valuation"]["multi_dim_score"] == 0.0
        assert "undervalued_peers" in entry
        assert entry["undervalued_peers"] == []
        assert "overheat_signal" in entry
        assert entry["overheat_signal"]["triggered"] is False

    def test_write_snapshot_fail_open_on_orchestrator_exception(self, tmp_path):
        """orchestrator.run() 抛异常 → 顶层 sector_valuation_summary 仍存在（中性默认）。"""
        from force_vector import bdsm_snapshot_writer

        with patch.object(bdsm_snapshot_writer, "SectorValuationOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("DB unavailable")
            output_path = bdsm_snapshot_writer.write_snapshot(
                out_dir=str(tmp_path),
                dry_run_read_coin_data_from_db=False,
                target_date="2026-10-07",
            )
        import json
        with open(output_path) as f:
            snap = json.load(f)
        summary = snap["sector_valuation_summary"]
        assert summary["waterlines"] == []
        assert summary["top_opportunities"] == []
        assert summary["overheat_sectors"] == []
