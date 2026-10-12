"""RED 测试：P3-3 架构健康度 reflection_engine（SPEC-自进化系统逆向解析改进.md P3-3）。

ReflectionEngine 扩展架构反思能力：消费 ArchitectureDebtResult →
架构健康度报告（JSON 持久化 + 控制台摘要）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "23-四层闭环自进化交易架构"))

from dreambuddy_evolution.engines.reflection_engine import (  # noqa: E402
    ReflectionEngine,
    ArchitectureHealthReport,
)
from dreambuddy_evolution.engines.reverse_deriver import ArchitectureDebtResult  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 可导入 + 报告数据结构
# ---------------------------------------------------------------------------

class TestImportAndStructure:
    def test_architecture_health_report_importable(self):
        assert ArchitectureHealthReport is not None

    def test_report_default_fields(self):
        r = ArchitectureHealthReport()
        assert hasattr(r, "overall_score")
        assert hasattr(r, "dimension_scores")
        assert hasattr(r, "triggered_windows")
        assert hasattr(r, "refactor_plan")
        assert hasattr(r, "health_level")


# ---------------------------------------------------------------------------
# 2. reflect_architecture 健康度计算
# ---------------------------------------------------------------------------

class TestReflectArchitecture:
    def setup_method(self):
        self.engine = ReflectionEngine()

    def test_empty_debt_full_health(self):
        debt = ArchitectureDebtResult()
        report = self.engine.reflect_architecture(debt)
        assert report.overall_score == pytest.approx(1.0)
        assert report.health_level == "healthy"
        assert report.triggered_windows == []

    def test_high_debt_low_health(self):
        debt = ArchitectureDebtResult(
            debt_dimensions={"file_size": 1.0, "out_degree": 1.0},
            triggered_windows=["refactor:file_size:big.py"],
            refactor_plan=[{"dimension": "file_size", "priority": "P0", "score": 1.0}],
        )
        report = self.engine.reflect_architecture(debt)
        # 整体健康分 = 1 - 平均债务评分 = 1 - (1.0+1.0)/2 / 4维度? 
        # 实际实现：overall = 1 - mean(dimension_scores)
        assert report.overall_score < 1.0
        assert report.health_level in ("critical", "warning")
        assert "refactor:file_size:big.py" in report.triggered_windows

    def test_health_level_thresholds(self):
        # overall >= 0.8 → healthy
        assert self.engine._health_level(0.9) == "healthy"
        # 0.5 <= overall < 0.8 → warning
        assert self.engine._health_level(0.6) == "warning"
        # overall < 0.5 → critical
        assert self.engine._health_level(0.3) == "critical"


# ---------------------------------------------------------------------------
# 3. JSON 持久化 + 控制台摘要
# ---------------------------------------------------------------------------

class TestReportPersistence:
    def setup_method(self):
        self.engine = ReflectionEngine()
        self.debt = ArchitectureDebtResult(
            debt_dimensions={"file_size": 1.0, "out_degree": 0.5},
            triggered_windows=["refactor:file_size:huge.py"],
            refactor_plan=[{
                "dimension": "file_size", "target": "huge.py",
                "score": 1.0, "action": "拆分", "priority": "P0",
            }],
            confidence=0.5,
        )

    def test_to_dict_serializable(self):
        report = self.engine.reflect_architecture(self.debt)
        d = report.to_dict()
        # 必须可 JSON 序列化
        json.dumps(d, ensure_ascii=False)
        assert d["overall_score"] == report.overall_score

    def test_save_json_creates_file(self, tmp_path):
        report = self.engine.reflect_architecture(self.debt)
        path = tmp_path / "arch_health.json"
        report.save_json(str(path))
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["overall_score"] == report.overall_score

    def test_summary_contains_key_fields(self, tmp_path, capsys):
        report = self.engine.reflect_architecture(self.debt)
        report.print_summary()
        out = capsys.readouterr().out
        assert "架构健康度" in out
        assert report.health_level in out
