from pathlib import Path

from workflows.memory.L1_realtime.entrypoint import (
    run_l1_realtime_relevance,
    run_l1_realtime_retrieval,
)
from workflows.memory.L2_shortterm.entrypoint import (
    run_l2_shortterm_feedback,
    run_l2_shortterm_health_check,
)
from workflows.memory.L3_longterm.entrypoint import run_l3_longterm_maintenance
from workflows.memory.L4_archive.entrypoint import (
    run_l4_cross_market_migration,
    run_l4_failure_analysis,
    run_l4_graph_build,
    run_l4_meta_task_enqueue,
)


class FakeMemoryEngine:
    def retrieve_for_decision(self, context, topk):
        return {"kind": "l1_retrieval", "context": context, "topk": topk}

    def build_relevance_matrix(self, context, topk):
        return {"kind": "l1_relevance", "context": context, "topk": topk}

    def update_bandit_from_episodes(self, events, context, unrealized_discount):
        return {"kind": "l2_feedback", "events": events, "context": context, "discount": unrealized_discount}

    def check_consistency(self):
        return {"pass": True, "errors": []}

    def get_health_score(self):
        return 0.91

    def build_vector_artifacts(self, vector_dir: Path):
        return {"kind": "l3_vector", "vector_dir": str(vector_dir)}

    def analyze_failure_memory(self, snapshot_ts, episodes_by_case_id, output_dir):
        return {"kind": "l4_failure", "snapshot_ts": snapshot_ts, "output_dir": str(output_dir) if output_dir else None}

    def analyze_cross_market_migration(self, snapshot_ts, source_market, target_market, episodes_by_case_id, output_dir):
        return {
            "kind": "l4_migration",
            "snapshot_ts": snapshot_ts,
            "source_market": source_market,
            "target_market": target_market,
        }

    def build_shared_memory_graph(self, snapshot_ts, events, output_dir, require_evidence_refs):
        return {"kind": "l4_graph", "events": events, "require_evidence_refs": require_evidence_refs}

    def enqueue_meta_learning_tasks(self, snapshot_ts, risk_signals, migration_mappings, output_dir):
        return {"kind": "l4_meta", "risk_signals": risk_signals, "migration_mappings": migration_mappings}


def test_l1_entrypoints_delegate_to_memory_engine():
    engine = FakeMemoryEngine()
    assert run_l1_realtime_retrieval({"trace_id": "t1"}, topk=5, engine=engine)["kind"] == "l1_retrieval"
    assert run_l1_realtime_relevance({"trace_id": "t2"}, topk=6, engine=engine)["kind"] == "l1_relevance"


def test_l2_entrypoints_delegate_to_memory_engine():
    engine = FakeMemoryEngine()
    out_feedback = run_l2_shortterm_feedback(events=[{"id": "e1"}], context={"reason": "test"}, engine=engine)
    assert out_feedback["kind"] == "l2_feedback"
    out_health = run_l2_shortterm_health_check(engine=engine)
    assert out_health["consistency_report"]["pass"] is True
    assert out_health["health_score"] == 0.91


def test_l3_entrypoint_delegate_to_memory_engine(tmp_path: Path):
    engine = FakeMemoryEngine()
    out = run_l3_longterm_maintenance(vector_dir=tmp_path / "vector", engine=engine)
    assert out["vector_artifacts"]["kind"] == "l3_vector"
    assert out["health_score"] == 0.91


def test_l4_entrypoints_delegate_to_memory_engine(tmp_path: Path):
    engine = FakeMemoryEngine()
    assert run_l4_failure_analysis(snapshot_ts="2026-01-01T00:00:00Z", output_dir=tmp_path, engine=engine)["kind"] == "l4_failure"
    assert run_l4_cross_market_migration(source_market="crypto", target_market="hk", engine=engine)["kind"] == "l4_migration"
    assert run_l4_graph_build(events=[{"id": "x"}], require_evidence_refs=True, engine=engine)["kind"] == "l4_graph"
    assert run_l4_meta_task_enqueue(risk_signals=[], migration_mappings=[], engine=engine)["kind"] == "l4_meta"
