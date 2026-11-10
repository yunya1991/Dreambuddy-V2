"""gap_audit 与 D2-B 模板扩覆盖的验证用例。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
if str(_PKG_ROOT / "registry") not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT / "registry"))

import gap_audit  # noqa: E402  (registry 目录内含同名风险模块，按文件目录导入)
from experiments.d2b_engineering.generator import generate  # noqa: E402


def _graph(module: str, py_count: int, doc_count: int = 0) -> dict:
    nodes = [{"id": f"{module}/lib/f{i}.py", "type": "python_file"} for i in range(py_count)]
    nodes += [{"id": f"{module}/lib/f{i}.md", "type": "markdown_doc"} for i in range(doc_count)]
    return {"nodes": nodes, "edges": []}


class TestDocCoverageAudit:
    def test_emits_gap_for_low_coverage_module(self):
        gaps = gap_audit.audit_doc_coverage(_graph("M", py_count=20, doc_count=2))
        assert len(gaps) == 1
        ev = gaps[0]["evidence"]
        assert ev["py_files"] == 20 and ev["documented_files"] == 2
        assert ev["coverage"] == 0.1
        assert ev["source"] == "gap_audit"
        assert gaps[0]["status"] == "open"

    def test_skips_module_meeting_target(self):
        assert gap_audit.audit_doc_coverage(_graph("M", py_count=20, doc_count=18)) == []

    def test_skips_small_module(self):
        assert gap_audit.audit_doc_coverage(_graph("M", py_count=19, doc_count=0)) == []

    def test_never_emits_non_measurable_types(self):
        gaps = gap_audit.audit_doc_coverage(_graph("M", py_count=20, doc_count=0))
        assert {g["gap_type"] for g in gaps} == {"doc_debt"}


class TestIdempotentAppend:
    def test_second_append_is_noop(self, tmp_path):
        gaps_path = tmp_path / "gaps.jsonl"
        gaps = gap_audit.audit_doc_coverage(_graph("M", py_count=20, doc_count=0))
        assert gap_audit.append_gaps(gaps, gaps_path) == 1
        assert gap_audit.append_gaps(gaps, gaps_path) == 0
        assert len(gaps_path.read_text().strip().splitlines()) == 1

    def test_dedupe_survives_date_change(self, tmp_path):
        gaps_path = tmp_path / "gaps.jsonl"
        first = gap_audit.audit_doc_coverage(_graph("M", py_count=20, doc_count=0))
        gap_audit.append_gaps(first, gaps_path)
        later = json.loads(json.dumps(first))
        later[0]["gap_id"] = "GAP-20991231-deadbeef"  # 模拟隔天重跑
        assert gap_audit.append_gaps(later, gaps_path) == 0


class TestGeneratorCoverage:
    def test_backtest_evaluator_has_plan(self):
        plan = generate(
            {
                "gap_id": "G1",
                "gap_type": "backtest_evaluator_missing",
                "evidence": {"need": "config 级回测评估器"},
                "expected_value": "M2 可判定",
            }
        )
        assert plan.steps and plan.dependencies
        assert "def evaluate_configs" in plan.code_skeleton
        assert "45-评测系统" in plan.module_name

    def test_domain_state_series_has_plan(self):
        plan = generate(
            {
                "gap_id": "G2",
                "gap_type": "domain_state_series_missing",
                "evidence": {"needs": "带时间戳的域状态窗口"},
                "expected_value": "E3 可判定",
            }
        )
        assert plan.steps and plan.dependencies
        assert "def collect_series" in plan.code_skeleton
        assert "domain_state_series" in plan.module_name

    def test_unknown_type_still_empty(self):
        plan = generate({"gap_id": "G3", "gap_type": "totally_new_type", "evidence": {}})
        assert plan.steps == [] and plan.code_skeleton == ""


def _write_module(root: Path, module: str, filename: str, body: str) -> str:
    mod_dir = root / module
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / filename).write_text(body)
    return f"{module}/{filename}"


class TestArchitectureAmbiguityAudit:
    def test_flags_module_with_duplicate_function_names(self, tmp_path):
        dup = "\n".join(f"def dup{i}():\n    return {i}" for i in range(20))
        ids = [_write_module(tmp_path, m, "mod.py", dup) for m in ("A", "B")]
        unique = "\n".join(f"def only_b{i}():\n    return {i}" for i in range(20))
        ids.append(_write_module(tmp_path, "C", "mod.py", unique))
        graph = {"nodes": [{"id": i, "type": "python_file"} for i in ids]}

        gaps = gap_audit.audit_architecture_ambiguity(graph, root=tmp_path)
        assert {g["evidence"]["module"] for g in gaps} == {"A", "B"}
        for g in gaps:
            assert g["gap_type"] == "architecture_gap"
            assert g["evidence"]["ambiguity_ratio"] == 1.0
            assert g["evidence"]["sample_ambiguous"]

    def test_skips_module_below_function_threshold(self, tmp_path):
        body = "\n".join(f"def dup{i}():\n    return {i}" for i in range(19))
        ids = [_write_module(tmp_path, m, "mod.py", body) for m in ("A", "B")]
        graph = {"nodes": [{"id": i, "type": "python_file"} for i in ids]}
        assert gap_audit.audit_architecture_ambiguity(graph, root=tmp_path) == []


class TestInterfaceAnnotationAudit:
    def test_flags_module_without_signature_annotations(self, tmp_path):
        bare = "\n".join(f"def pub{i}(a, b):\n    return a" for i in range(100))
        ids = [_write_module(tmp_path, "BARE", "mod.py", bare)]
        typed = "\n".join(f"def pub{i}(a: int, b: int) -> int:\n    return a" for i in range(100))
        ids.append(_write_module(tmp_path, "TYPED", "mod.py", typed))
        graph = {"nodes": [{"id": i, "type": "python_file"} for i in ids]}

        gaps = gap_audit.audit_interface_annotations(graph, root=tmp_path)
        assert [g["evidence"]["module"] for g in gaps] == ["BARE"]
        ev = gaps[0]["evidence"]
        assert ev["public_functions"] == 100
        assert ev["no_annotation_ratio"] == 1.0
        assert gaps[0]["gap_type"] == "interface_mismatch"
