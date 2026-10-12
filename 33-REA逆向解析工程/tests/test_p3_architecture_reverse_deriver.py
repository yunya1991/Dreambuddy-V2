"""RED 测试：P3-1 架构级 ReverseDeriver（SPEC-P3-1-架构级ReverseDeriver.md）。

从 REA 架构 Evidence（文件行数/出度/豁口数/git演化类型）反推设计债务，
触发 refactor 窗口。与交易域 ReverseDeriver 接口隔离。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "23-四层闭环自进化交易架构"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from dreambuddy_evolution.engines.reverse_deriver import (  # noqa: E402
    ArchitectureReverseDeriver,
    ArchitectureDebtResult,
    ReverseDeriver,
)
from core.evidence import Evidence, EvidenceLevel, reverse_evidence  # noqa: E402


def _ev(result, analysis, level=EvidenceLevel.DERIVATION, file=None):
    prov = {"analysis": analysis}
    if file:
        prov["file"] = file
    return reverse_evidence(result=result, level=level, provenance=prov)


# ---------------------------------------------------------------------------
# 1. 可导入 + 接口隔离
# ---------------------------------------------------------------------------

class TestImportAndIsolation:
    def test_architecture_deriver_importable(self):
        assert ArchitectureReverseDeriver is not None

    def test_result_dataclass_fields(self):
        r = ArchitectureDebtResult()
        assert r.debt_dimensions == {}
        assert r.triggered_windows == []
        assert r.refactor_plan == []
        assert r.known_gaps == []

    def test_isolated_from_trading_domain(self):
        # 架构域方法不应存在于交易域 ReverseDeriver
        assert not hasattr(ReverseDeriver, "derive_architecture_debt")
        # 架构域不应有交易域方法
        assert not hasattr(ArchitectureReverseDeriver, "derive")


# ---------------------------------------------------------------------------
# 2. FAIL-OPEN：空输入
# ---------------------------------------------------------------------------

class TestFailOpen:
    def setup_method(self):
        self.d = ArchitectureReverseDeriver()

    def test_empty_list_returns_empty_with_known_gaps(self):
        r = self.d.derive_architecture_debt([])
        assert r.debt_dimensions == {}
        assert r.triggered_windows == []
        assert r.refactor_plan == []
        assert any("无架构 Evidence" in g for g in r.known_gaps)

    def test_none_list_treated_as_empty(self):
        r = self.d.derive_architecture_debt(None)  # type: ignore
        assert r.debt_dimensions == {}

    def test_unparseable_evidence_skipped(self):
        ev = _ev("完全无法解析的文本 xyz", analysis="line_count")
        r = self.d.derive_architecture_debt([ev])
        # 不崩溃，known_gaps 记录失败
        assert isinstance(r, ArchitectureDebtResult)


# ---------------------------------------------------------------------------
# 3. 四维度数值解析 + 债务评分
# ---------------------------------------------------------------------------

class TestDimensionParsing:
    def setup_method(self):
        self.d = ArchitectureReverseDeriver()

    def test_file_size_under_threshold(self):
        ev = _ev("文件 foo.py: 500 行", analysis="line_count", file="foo.py")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions.get("file_size", 0) == pytest.approx(500 / 800)

    def test_file_size_over_threshold_triggers_window(self):
        ev = _ev("文件 big.py: 1200 行", analysis="line_count", file="big.py")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions["file_size"] == pytest.approx(1.0)  # clamp
        assert any("file_size" in w for w in r.triggered_windows)

    def test_out_degree_under_threshold(self):
        ev = _ev("出度: 5", analysis="out_degree", file="mod.py")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions.get("out_degree", 0) == pytest.approx(0.5)

    def test_out_degree_over_threshold(self):
        ev = _ev("出度: 12", analysis="out_degree", file="god_module.py")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions["out_degree"] == pytest.approx(1.0)
        assert any("out_degree" in w for w in r.triggered_windows)

    def test_known_gaps_dimension(self):
        ev = _ev("豁口: 25 项", analysis="known_gap_audit")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions.get("known_gaps", 0) == pytest.approx(1.0)
        assert any("known_gaps" in w for w in r.triggered_windows)

    def test_git_evolution_no_refactor(self):
        ev = _ev("演化: 8 feat / 0 refactor", analysis="git_history")
        r = self.d.derive_architecture_debt([ev])
        # feat/(feat+refactor) = 8/8 = 1.0
        assert r.debt_dimensions.get("git_evolution", 0) == pytest.approx(1.0)
        assert any("git_evolution" in w for w in r.triggered_windows)

    def test_git_evolution_with_refactors(self):
        ev = _ev("演化: 4 feat / 4 refactor", analysis="git_history")
        r = self.d.derive_architecture_debt([ev])
        assert r.debt_dimensions.get("git_evolution", 0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. refactor_plan 优先级排序
# ---------------------------------------------------------------------------

class TestRefactorPlan:
    def test_priority_p0_for_threshold_exceeded(self):
        d = ArchitectureReverseDeriver()
        ev = _ev("文件 huge.py: 1600 行", analysis="line_count", file="huge.py")
        r = d.derive_architecture_debt([ev])
        plan = r.refactor_plan
        assert len(plan) >= 1
        assert plan[0]["dimension"] == "file_size"
        assert plan[0]["priority"] == "P0"
        assert plan[0]["action"] in ("拆分", "重构")

    def test_multiple_dimensions_sorted_by_score_desc(self):
        d = ArchitectureReverseDeriver()
        evs = [
            _ev("文件 a.py: 900 行", analysis="line_count", file="a.py"),
            _ev("出度: 15", analysis="out_degree", file="b.py"),
        ]
        r = d.derive_architecture_debt(evs)
        scores = [p["score"] for p in r.refactor_plan]
        assert scores == sorted(scores, reverse=True)
