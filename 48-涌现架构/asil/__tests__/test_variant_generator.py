# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""变体生成器 pytest：D3 规则组合 + D2 模板策略。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.emergence_loop import D2EmergenceLoop, D3EmergenceLoop
from asil.variant_generator import (
    D2TemplateGenerator,
    D3VariantGenerator,
    RuleVariant,
    TemplatePolicy,
    plan_diagnostics,
)


def _sig(v: RuleVariant) -> tuple:
    return (v.fallback, round(v.min_conf, 3), v.aggregate)


class TestD3VariantGenerator:
    def test_proposes_unexplored_only(self):
        champion = RuleVariant("base", fallback="general", min_conf=0.0, aggregate="sum")
        history = [
            {
                "decision": "reject",
                "metrics": {
                    "top1": 0.78,
                    "ece": 0.15,
                    "params": {"fallback": "majority", "min_conf": 0.0, "aggregate": "sum"},
                },
                "baseline_metrics": {"top1": 0.78, "ece": 0.15},
            }
        ]
        proposals = D3VariantGenerator().propose(history, champion)
        assert proposals
        assert _sig(champion) not in {_sig(v) for v in proposals}
        assert ("majority", 0.0, "sum") not in {_sig(v) for v in proposals}
        assert len(proposals) <= 4

    def test_prunes_high_conf_after_ece_regression(self):
        champion = RuleVariant("base", fallback="general", min_conf=0.0, aggregate="sum")
        history = [
            {
                "decision": "reject",
                "metrics": {
                    "top1": 0.80,
                    "ece": 0.20,
                    "params": {"fallback": "majority", "min_conf": 0.6, "aggregate": "sum"},
                },
                "baseline_metrics": {"top1": 0.80, "ece": 0.05},
            }
        ]
        proposals = D3VariantGenerator().propose(history, champion, ece_tolerance=0.02)
        assert proposals
        assert all(v.min_conf < 0.6 for v in proposals)

    def test_auto_evolve_extends_rounds(self, tmp_path):
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("second", fallback="majority")],
            auto_evolve=True,
            max_variants=12,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop._train = [{"ok": True}]
        loop._val = [{"ok": True}]
        loop.evaluate = lambda v: {
            "top1": 0.80 if v.name == "base" else 0.79,
            "ece": 0.10,
            "n_val": 10,
            "holdout_top1": 0.80 if v.name == "base" else 0.79,
            "holdout_ece": 0.10,
            "n_holdout": 100,
            "holdout_correct": [1] * 50 + [0] * 50,
        }
        summary = loop.run(rounds=4)
        assert summary["rounds"] == 4  # 初始 1 个候选 + 生成器补充
        names = [h["variant"] for h in summary["history"]]
        assert any(n.startswith("evo_") for n in names)
        assert summary["champion"] == "base"  # 全部未改进 → 冠军不变

    def test_auto_evolve_respects_max_variants(self, tmp_path):
        loop = D3EmergenceLoop(
            events_path=tmp_path / "unused.jsonl",
            variants=[RuleVariant("base"), RuleVariant("second", fallback="majority")],
            auto_evolve=True,
            max_variants=3,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        loop._train = [{"ok": True}]
        loop._val = [{"ok": True}]
        loop.evaluate = lambda v: {
            "top1": 0.5,
            "ece": 0.1,
            "n_val": 10,
            "holdout_top1": 0.5,
            "holdout_ece": 0.1,
            "n_holdout": 100,
            "holdout_correct": [1] * 50 + [0] * 50,
        }
        summary = loop.run(rounds=20)
        assert summary["rounds"] == 2  # 冠军 + 2 个变体上限（max_variants=3）


class TestTemplatePolicy:
    def test_stdlib_to_dependencies(self):
        plan = {"modules": ["33-REA/ast_call_resolver.py", "ast", "json"]}
        out = TemplatePolicy("stdlib_to_dependencies", "").apply(plan)
        assert out["modules"] == ["33-REA/ast_call_resolver.py"]
        assert out["dependencies"] == ["ast", "json"]
        assert plan["modules"] == ["33-REA/ast_call_resolver.py", "ast", "json"]  # 不改原对象

    def test_dedupe_modules(self):
        out = TemplatePolicy("dedupe_modules", "").apply({"modules": ["a", "b", "a"]})
        assert out["modules"] == ["a", "b"]

    def test_flag_missing_skeleton(self):
        out = TemplatePolicy("flag_missing_skeleton", "").apply({"modules": ["a"]})
        assert out["requires_code_skeleton"] is True
        out2 = TemplatePolicy("flag_missing_skeleton", "").apply(
            {"modules": ["a"], "code_skeleton": "def run(): ..."}
        )
        assert out2["requires_code_skeleton"] is False

    def test_attach_acceptance(self):
        out = TemplatePolicy("attach_acceptance", "").apply({"expected_value": "假依赖率 < 5%"})
        assert out["acceptance"]["measurable_required"] is True
        assert out["acceptance"]["expected_value"] == "假依赖率 < 5%"

    def test_plan_diagnostics_detects_stdlib(self):
        diag = plan_diagnostics({"modules": ["a.py", "ast", "a.py"]})
        assert diag["stdlib_modules"] == ["ast"]
        assert diag["module_count"] == 3 and diag["unique_module_count"] == 2
        assert diag["has_code_skeleton"] is False


class TestD2TemplateGenerator:
    def test_proposes_from_diagnostics(self):
        history = [
            {
                "metrics": {
                    "plan_diagnostics": {
                        "stdlib_modules": ["ast"],
                        "module_count": 2,
                        "unique_module_count": 1,
                        "has_code_skeleton": False,
                        "expected_value": "假依赖率 < 5%",
                    }
                }
            }
        ]
        policies = D2TemplateGenerator(max_policies=3).propose(history)
        kinds = [p.kind for p in policies]
        assert "stdlib_to_dependencies" in kinds
        assert "flag_missing_skeleton" in kinds
        assert len(kinds) <= 3

    def test_no_policies_without_signals(self):
        history = [
            {
                "metrics": {
                    "plan_diagnostics": {
                        "stdlib_modules": [],
                        "module_count": 1,
                        "unique_module_count": 1,
                        "has_code_skeleton": True,
                        "expected_value": "",
                    }
                }
            }
        ]
        assert D2TemplateGenerator().propose(history) == []


class TestD2Evolve:
    def _write_gaps(self, path: Path) -> None:
        rows = [
            {
                "gap_id": "GAP-1",
                "gap_type": "architecture_gap",
                "evidence": {},
                "expected_value": "假依赖率 < 5%",
                "status": "open",
            }
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows))

    def test_evolve_round_applies_policies(self, tmp_path):
        gaps = tmp_path / "gaps.jsonl"
        self._write_gaps(gaps)
        before = gaps.read_text()
        loop = D2EmergenceLoop(
            gaps_path=gaps,
            evolve_rounds=2,
            reviewer="auto",
            review_dir=tmp_path / "r",
            loop_dir=tmp_path / "l",
        )
        summary = loop.run()
        assert "policy_round" in summary
        assert summary["policy_round"]["policies"]
        assert "baseline_overall_pass_rate" in summary
        assert gaps.read_text() == before  # 零执行权
        assert (tmp_path / "l" / "d2_policy_rounds.jsonl").exists()
