"""
T13: 自进化权重自动调整闭环 TDD 测试
SPEC §5.3 — 案例库统计接口 + weight 自动升降级

规则:
  win_rate >= 0.65 且 sample_count >= 10 → weight *= 1.1 (上限 2.0)
  win_rate < 0.40 → weight *= 0.9 (下限 0.1)
  其他 → 不调整

HC: 开关关断时不调整 weight
HC: FAIL-OPEN 异常不调整
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_auto_weight(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_auto_weight_adjustment", True)
    yield


class TestEventCaseLibraryWinrate:
    """EventCaseLibrary.get_pattern_winrate 接口测试"""

    def test_get_pattern_winrate_module(self):
        from event_driven.event_case_library import EventCaseLibrary
        assert hasattr(EventCaseLibrary, "get_pattern_winrate")

    def test_get_pattern_winrate_basic(self, tmp_path):
        """基本统计: 3 案例 2 胜 → win_rate=0.667"""
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "test_cases.json"))
        lib.add_case(EventCase(
            event_date="2024-01", cycle_phase="event", decision="hike",
            hike_prob_before=0.85, relief_or_reversal="relief", pnl_30d=0.05,
        ))
        lib.add_case(EventCase(
            event_date="2024-02", cycle_phase="event", decision="hike",
            hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.03,
        ))
        lib.add_case(EventCase(
            event_date="2024-03", cycle_phase="event", decision="hike",
            hike_prob_before=0.75, relief_or_reversal="reversal", pnl_30d=-0.02,
        ))
        result = lib.get_pattern_winrate(pattern="event", event_type="hike")
        assert result["sample_count"] == 3
        assert result["win_rate"] == pytest.approx(2/3, abs=0.01)
        assert "avg_pnl_pct" in result

    def test_get_pattern_winrate_empty(self, tmp_path):
        """无案例 → sample_count=0"""
        from event_driven.event_case_library import EventCaseLibrary
        lib = EventCaseLibrary(storage_path=str(tmp_path / "empty.json"))
        result = lib.get_pattern_winrate(pattern="event", event_type="hike")
        assert result["sample_count"] == 0
        assert result["win_rate"] == 0.0


class TestAutoWeightAdjuster:
    """AutoWeightAdjuster 单元测试"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        assert AutoWeightAdjuster is not None

    def test_upgrade_when_high_winrate(self, enable_auto_weight, tmp_path):
        """win_rate >= 0.65 且 sample >= 10 → weight *= 1.1"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        # 添加 10 个胜案例
        for i in range(10):
            lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
            ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.0, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] == pytest.approx(1.1, abs=0.01)

    def test_downgrade_when_low_winrate(self, enable_auto_weight, tmp_path):
        """win_rate < 0.40 → weight *= 0.9"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        # 添加 10 个败案例
        for i in range(10):
            lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="reversal", pnl_30d=-0.05,
            ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.0, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] == pytest.approx(0.9, abs=0.01)

    def test_no_adjust_when_insufficient_sample(self, enable_auto_weight, tmp_path):
        """sample < 10 → 不调整"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        lib.add_case(EventCase(
            event_date="2024-01", cycle_phase="event", decision="hike",
            hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
        ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.0, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] == 1.0  # 不调整

    def test_weight_cap_at_2_0(self, enable_auto_weight, tmp_path):
        """weight 上限 2.0"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        for i in range(15):
            lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
            ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.9, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] <= 2.0

    def test_weight_floor_at_0_1(self, enable_auto_weight, tmp_path):
        """weight 下限 0.1"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        for i in range(15):
            lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="reversal", pnl_30d=-0.05,
            ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 0.15, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] >= 0.1

    def test_switch_off_no_adjust(self, tmp_path):
        """HC: 开关关断时不调整"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_auto_weight_adjustment", True)

        lib = EventCaseLibrary(storage_path=str(tmp_path / "lib.json"))
        for i in range(15):
            lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
            ))

        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.0, "pattern": "event", "event_type": "hike"}}
        result = adjuster.adjust(lib, gene_library)
        assert result["gene_001"]["weight"] == 1.0  # 不调整

    def test_fail_open_on_exception(self, enable_auto_weight):
        """HC: 异常时 FAIL-OPEN 不调整"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        adjuster = AutoWeightAdjuster()
        gene_library = {"gene_001": {"weight": 1.0}}
        # lib=None 应 FAIL-OPEN
        result = adjuster.adjust(None, gene_library)
        assert result == gene_library  # 原样返回


# ============================================================================
# P2-2: AutoWeightAdjuster 持久化链路闭环验证
#   问题：adjust() 期望扁平 dict {gene_id: {weight}} 但 _maybe_auto_adjust_weight()
#   传入完整 library dict（含 combinations），且不调用 persist_library() 持久化
# ============================================================================


class TestAutoWeightLibraryDictCompat:
    """P2-2: adjust() 适配完整 library dict 格式（load_gene_library 返回值）。"""

    def test_adjust_accepts_full_library_dict(self, enable_auto_weight, tmp_path):
        """adjust() 接受含 'combinations' key 的完整 library dict（RED 预期失败）。"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        case_lib = EventCaseLibrary(storage_path=str(tmp_path / "cases.json"))
        for i in range(10):
            case_lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
            ))
        library = {
            "root": str(tmp_path),
            "combinations": [
                {"combo_id": "CB-001", "meta": {"weight": 1.0, "pattern": "event", "event_type": "hike"}},
            ],
        }
        adjuster = AutoWeightAdjuster()
        result = adjuster.adjust(case_lib, library)
        # weight 应升级到 1.1
        assert result["combinations"][0]["meta"]["weight"] == pytest.approx(1.1, abs=0.01), (
            "adjust() 应能处理完整 library dict 格式（含 combinations key）"
        )

    def test_adjust_modifies_combinations_meta_weight(self, enable_auto_weight, tmp_path):
        """adjust() 直接修改 library['combinations'][i]['meta']['weight']。"""
        from dreambuddy_evolution.engines.auto_weight_adjuster import AutoWeightAdjuster
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        case_lib = EventCaseLibrary(storage_path=str(tmp_path / "cases.json"))
        for i in range(10):
            case_lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="reversal", pnl_30d=-0.05,
            ))
        library = {
            "root": str(tmp_path),
            "combinations": [
                {"combo_id": "CB-001", "meta": {"weight": 1.0, "pattern": "event", "event_type": "hike"}},
                {"combo_id": "CB-002", "meta": {"weight": 0.5, "pattern": "event", "event_type": "hike"}},
            ],
        }
        adjuster = AutoWeightAdjuster()
        result = adjuster.adjust(case_lib, library)
        # 低胜率 → 降级 0.9
        assert result["combinations"][0]["meta"]["weight"] == pytest.approx(0.9, abs=0.01)
        assert result["combinations"][1]["meta"]["weight"] == pytest.approx(0.45, abs=0.01)

    def test_maybe_auto_adjust_weight_persists(self, enable_auto_weight, tmp_path):
        """_maybe_auto_adjust_weight() 调用后 persist_library() 写入 library.json（RED 预期失败）。"""
        import json
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        from event_driven.event_case_library import (
            EventCaseLibrary, EventCase,
        )
        from dreambuddy_evolution.core.strategy_gene import persist_library

        case_lib = EventCaseLibrary(storage_path=str(tmp_path / "cases.json"))
        for i in range(10):
            case_lib.add_case(EventCase(
                event_date=f"2024-{i:02d}", cycle_phase="event", decision="hike",
                hike_prob_before=0.80, relief_or_reversal="relief", pnl_30d=0.05,
            ))
        # 构造完整 library dict
        gene_dir = tmp_path / "strategy_combinations"
        gene_dir.mkdir()
        library = {
            "root": str(tmp_path),
            "combinations": [
                {"combo_id": "CB-001", "meta": {"weight": 1.0, "pattern": "event", "event_type": "hike"}},
            ],
        }
        engine = ReflectionEngine(case_library=case_lib, gene_library=library)
        engine._maybe_auto_adjust_weight()
        # 验证 library.json 被写入
        lib_json = gene_dir / "library.json"
        assert lib_json.exists(), "_maybe_auto_adjust_weight 应通过 persist_library 写入 library.json"
        data = json.loads(lib_json.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["meta"]["weight"] == pytest.approx(1.1, abs=0.01), "weight 应升级"
