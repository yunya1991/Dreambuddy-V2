"""E5: 阶段闭环回放脚本测试 — TDD 先红后绿。

验证 coin_fundamental_phase_replay.py：
  - 回放三案例完整阶段流转，验证系统在每个切换点是否及时识别
  - CRCL：P1（主网预期）→ P2（落地后盈收跟踪）
  - UNI：P2（Robinhood 接入盈收扩张）→ P3（估值到高位）
  - HYPE：P3（大跌后修复力）
  - 输入：合成事件时间线 + E5/E6 信号序列 + 估值分位序列
  - 输出：回放报告，含每个切换点的识别延迟、置信度、策略提示变化

合成数据策略：
  E5 回放先用合成快照序列（事件时间线 + E5/E6 序列 + 估值分位序列），
  真实历史数据接入留待 Phase F 数据源扩展。
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 和 scripts 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

_SCRIPTS_DIR = _L4_DIR / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from force_vector.coin_fundamental_phase_classifier import (
    P1_EXPECTATION,
    P2_REVENUE_EXPANSION,
    P3_VALUATION_RECOVERY,
)

from coin_fundamental_phase_replay import (
    PhaseSnapshot,
    CRCL_REPLAY_TIMELINE,
    UNI_REPLAY_TIMELINE,
    HYPE_REPLAY_TIMELINE,
    replay_case,
    replay_all_cases,
)


# ---------------------------------------------------------------------------
# 1. 数据结构
# ---------------------------------------------------------------------------

class TestPhaseSnapshotDataclass:
    """合成快照数据结构。"""

    def test_snapshot_has_required_fields(self):
        """快照必须含 ts, e5, e6, valuation_percentile, events 字段。"""
        snap = PhaseSnapshot(
            ts="2026-09-01",
            e5=0.5,
            e6=0.3,
            valuation_percentile=50.0,
            events=[{"type": "mainnet_launch", "status": "pending"}],
        )
        assert snap.ts == "2026-09-01"
        assert snap.e5 == 0.5
        assert snap.e6 == 0.3
        assert snap.valuation_percentile == 50.0
        assert len(snap.events) == 1


# ---------------------------------------------------------------------------
# 2. CRCL 案例：P1 → P2 流转
# ---------------------------------------------------------------------------

class TestReplayCRCL:
    """CRCL 案例：主网预期（P1）→ 落地后盈收跟踪（P2）。"""

    def test_crcl_timeline_starts_at_p1(self):
        """CRCL 时间线首快照必须识别为 P1。"""
        result = replay_case("CRCL", CRCL_REPLAY_TIMELINE)
        assert result.snapshots[0].phase == P1_EXPECTATION

    def test_replay_crcl_p1_to_p2_on_mainnet_launch(self):
        """主网落地事件触发 P1→P2 切换。"""
        result = replay_case("CRCL", CRCL_REPLAY_TIMELINE)
        # 必须出现 P1→P2 切换
        p1_to_p2_switch = [
            sw for sw in result.switches
            if sw.from_phase == P1_EXPECTATION and sw.to_phase == P2_REVENUE_EXPANSION
        ]
        assert len(p1_to_p2_switch) >= 1, "CRCL 必须出现 P1→P2 切换"
        # 切换触发器应含 event_landed_switch_p1_to_p2
        assert any(
            "event_landed_switch_p1_to_p2" in sw.triggers
            for sw in p1_to_p2_switch
        )

    def test_crcl_final_phase_is_p2(self):
        """CRCL 最终阶段为 P2（落地后进入盈收跟踪）。"""
        result = replay_case("CRCL", CRCL_REPLAY_TIMELINE)
        assert result.snapshots[-1].phase == P2_REVENUE_EXPANSION


# ---------------------------------------------------------------------------
# 3. UNI 案例：P2 → P3 流转
# ---------------------------------------------------------------------------

class TestReplayUNI:
    """UNI 案例：盈收扩张（P2）→ 估值到高位（P3）。"""

    def test_uni_timeline_starts_at_p2(self):
        """UNI 时间线首快照必须识别为 P2。"""
        result = replay_case("UNI", UNI_REPLAY_TIMELINE)
        assert result.snapshots[0].phase == P2_REVENUE_EXPANSION

    def test_replay_uni_p2_to_p3_on_valuation_peak(self):
        """估值到高位（>80）触发 P2→P3 切换。"""
        result = replay_case("UNI", UNI_REPLAY_TIMELINE)
        p2_to_p3_switch = [
            sw for sw in result.switches
            if sw.from_phase == P2_REVENUE_EXPANSION and sw.to_phase == P3_VALUATION_RECOVERY
        ]
        assert len(p2_to_p3_switch) >= 1, "UNI 必须出现 P2→P3 切换"

    def test_uni_final_phase_is_p3(self):
        """UNI 最终阶段为 P3。"""
        result = replay_case("UNI", UNI_REPLAY_TIMELINE)
        assert result.snapshots[-1].phase == P3_VALUATION_RECOVERY


# ---------------------------------------------------------------------------
# 4. HYPE 案例：P3 持续修复
# ---------------------------------------------------------------------------

class TestReplayHYPE:
    """HYPE 案例：盈收强+估值稳，P3 持续修复力。"""

    def test_hype_timeline_all_p3(self):
        """HYPE 全程应稳定在 P3。"""
        result = replay_case("HYPE", HYPE_REPLAY_TIMELINE)
        phases = [s.phase for s in result.snapshots]
        assert all(p == P3_VALUATION_RECOVERY for p in phases), (
            f"HYPE 全程必须为 P3，实际: {phases}"
        )
        # 无切换发生
        assert len(result.switches) == 0

    def test_replay_hype_p3_recovery_signal(self):
        """HYPE P3 阶段 E5 持续 > 0.3（修复力信号）。"""
        result = replay_case("HYPE", HYPE_REPLAY_TIMELINE)
        for snap in result.snapshots:
            assert snap.evidence["e5"] > 0.3, f"HYPE 快照 {snap.ts} E5 必须 > 0.3"


# ---------------------------------------------------------------------------
# 5. 切换检测延迟报告
# ---------------------------------------------------------------------------

class TestSwitchDetectionLatency:
    """回放报告必须含切换检测延迟和策略提示变化。"""

    def test_replay_reports_switch_detection_latency(self):
        """每个切换必须记录 from/to/triggers/confidence/strategy_hint_delta。"""
        result = replay_case("CRCL", CRCL_REPLAY_TIMELINE)
        assert len(result.switches) >= 1
        for sw in result.switches:
            assert sw.from_phase is not None
            assert sw.to_phase is not None
            assert isinstance(sw.triggers, list)
            assert 0.0 <= sw.confidence <= 1.0
            # strategy_hint_delta 记录切换前后策略提示变化
            assert "from_case_anchor" in sw.strategy_hint_delta
            assert "to_case_anchor" in sw.strategy_hint_delta

    def test_replay_result_has_summary(self):
        """回放结果含 summary：案例名、快照数、切换数、最终阶段。"""
        result = replay_case("UNI", UNI_REPLAY_TIMELINE)
        assert result.case_name == "UNI"
        assert result.total_snapshots == len(UNI_REPLAY_TIMELINE)
        assert result.total_switches == len(result.switches)
        assert result.final_phase == P3_VALUATION_RECOVERY


# ---------------------------------------------------------------------------
# 6. 全案例回放
# ---------------------------------------------------------------------------

class TestReplayAllCases:
    """三个案例批量回放。"""

    def test_replay_all_cases_returns_three_results(self):
        """批量回放必须返回 3 个案例结果。"""
        results = replay_all_cases()
        assert len(results) == 3
        case_names = {r.case_name for r in results}
        assert case_names == {"CRCL", "UNI", "HYPE"}

    def test_replay_all_cases_phase_flow_consistent(self):
        """三案例阶段流转符合闭环：CRCL P1→P2, UNI P2→P3, HYPE P3 持续。"""
        results = {r.case_name: r for r in replay_all_cases()}
        # CRCL: P1 → P2
        assert results["CRCL"].snapshots[0].phase == P1_EXPECTATION
        assert results["CRCL"].final_phase == P2_REVENUE_EXPANSION
        # UNI: P2 → P3
        assert results["UNI"].snapshots[0].phase == P2_REVENUE_EXPANSION
        assert results["UNI"].final_phase == P3_VALUATION_RECOVERY
        # HYPE: P3 持续
        assert results["HYPE"].snapshots[0].phase == P3_VALUATION_RECOVERY
        assert results["HYPE"].final_phase == P3_VALUATION_RECOVERY


# ---------------------------------------------------------------------------
# 7. FAIL-OPEN
# ---------------------------------------------------------------------------

class TestReplayFailOpen:
    """异常输入的 FAIL-OPEN。"""

    def test_empty_timeline_returns_empty_result(self):
        """空时间线返回空结果（不抛异常）。"""
        result = replay_case("EMPTY", [])
        assert result.case_name == "EMPTY"
        assert result.total_snapshots == 0
        assert result.total_switches == 0
        assert result.final_phase is None or result.final_phase == ""

    def test_none_timeline_returns_empty_result(self):
        """None 时间线返回空结果。"""
        result = replay_case("NONE", None)
        assert result.total_snapshots == 0
