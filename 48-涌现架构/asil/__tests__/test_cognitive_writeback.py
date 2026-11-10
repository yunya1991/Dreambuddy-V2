# ruff: noqa: E402  (sys.path 必须先于 asil 导入)
"""P0-1 真实认知回写 pytest：record → recall → verify 全链。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from asil.cognitive_writeback import CognitiveWriteback
from asil.orchestrator import ASILOrchestrator
from asil.trigger_scanner import PipelineTrigger


def _verdict(label: str = "candidate", confidence: float = 0.83) -> dict:
    return {
        "verdict": label,
        "oracle_confidence": confidence,
        "test_coverage": 0.8,
        "survival_passed": True,
        "violations": [],
        "trace_id": "asil-sim",
    }


def _plan() -> dict:
    return {
        "gap_id": "GAP-SIM",
        "gap_type": "architecture_gap",
        "architecture_graph": {"nodes": ["33-REA/x.py"], "edges": []},
        "modules": ["33-REA/x.py"],
        "code_skeleton": "def run():\n    return 1\n",
        "design_rationale": "chain test",
    }


class TestWritebackCore:
    def test_record_then_recall_and_verify(self, tmp_path):
        wb = CognitiveWriteback(storage_path=tmp_path / "cog.db", enable_distill=False)
        out = wb.record_verdict(_verdict(), "pipe-1", tags=["D2"])

        assert out["backend"] == "cognitive_db"
        assert out["memory_id"].startswith("VM-")

        hits = wb.search("ASIL 自改进闭环")
        assert hits, "写入的记忆应可被 recall 检索到"
        assert any(out["memory_id"] in json.dumps(h, ensure_ascii=False, default=str) for h in hits)

        verified = wb.verify_memory(out["memory_id"], success=True)
        assert verified["backend"] == "cognitive_db"
        assert verified["success"] is True
        assert wb.stats() == {
            "records": 1,
            "verifies": 1,
            "failures": 0,
            "backend": "cognitive_db",
        }

    def test_idempotent_by_pipeline_id(self, tmp_path):
        wb = CognitiveWriteback(storage_path=tmp_path / "cog.db", enable_distill=False)
        first = wb.record_verdict(_verdict(), "pipe-dup")
        second = wb.record_verdict(_verdict(), "pipe-dup")
        assert first["memory_id"] == second["memory_id"]  # 重跑不产生重复记忆

    def test_fail_open_to_local_mirror(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        mirror = tmp_path / "mirror.jsonl"
        wb = CognitiveWriteback(
            storage_path=blocker / "cog.db",
            enable_distill=False,
            mirror_path=mirror,
        )
        out = wb.record_verdict(_verdict(), "pipe-fail")

        assert out["backend"] == "local_mirror"
        assert out["fallback"] is True
        assert mirror.exists() and "pipe-fail" in mirror.read_text()
        assert wb.stats()["failures"] == 1


class TestOrchestratorWriteback:
    def test_pipeline_writes_to_cognitive_db(self, tmp_path):
        wb = CognitiveWriteback(storage_path=tmp_path / "cog.db", enable_distill=False)
        orch = ASILOrchestrator(writeback=wb)
        out = orch.run_pipeline(
            PipelineTrigger(
                type="low_confidence_memory",
                source="chain-sim",
                evidence={"ratio": 0.7},
            ),
            mock_build_plan=_plan(),
        )

        assert out["verdict"]["verdict"] == "candidate"
        assert out["writeback"]["backend"] == "cognitive_db"
        assert out["writeback"]["verify"]["backend"] == "cognitive_db"

        snap = orch.metrics_snapshot()
        assert snap["verify_writebacks"] == 1
        assert snap["writeback_fallbacks"] == 0

        hits = wb.search("ASIL 自改进闭环")
        assert any(
            out["writeback"]["memory_id"] in json.dumps(h, ensure_ascii=False, default=str)
            for h in hits
        )

    def test_pipeline_counts_fallback_without_breaking(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        wb = CognitiveWriteback(
            storage_path=blocker / "cog.db",
            enable_distill=False,
            mirror_path=tmp_path / "m.jsonl",
        )
        orch = ASILOrchestrator(writeback=wb)
        out = orch.run_pipeline(
            PipelineTrigger(
                type="low_confidence_memory",
                source="chain-sim",
                evidence={"ratio": 0.7},
            ),
            mock_build_plan=_plan(),
        )

        assert out["verdict"]["verdict"] == "candidate"  # FAIL-OPEN：管道不受影响
        assert out["writeback"]["backend"] == "local_mirror"
        snap = orch.metrics_snapshot()
        assert snap["verify_writebacks"] == 0
        assert snap["writeback_fallbacks"] == 1
