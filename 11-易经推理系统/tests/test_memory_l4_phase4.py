import json
from pathlib import Path


def test_shared_memory_bus_publish_and_read(tmp_path: Path):
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event, read_shared_memory_events

    acl = {"A3": {"publish": True, "read": True}}
    out = publish_shared_memory_event(
        snapshot_ts="2026-05-10T14:00:00+08:00",
        agent_id="A3",
        event_type="memory_publish",
        payload={"memory_id": "TC_1", "kind": "case", "evidence_refs": ["episodes/e1.json"]},
        output_dir=tmp_path,
        acl_config=acl,
    )
    assert Path(out["bus_path"]).exists()
    events = read_shared_memory_events(Path(out["bus_path"]), agent_id="A3", acl_config=acl)
    assert len(events) == 1
    assert events[0]["agent_id"] == "A3"
    assert events[0]["event_type"] == "memory_publish"
    assert events[0]["acl_decision"]["allow"] is True


def test_shared_memory_bus_denies_unauthorized_agent(tmp_path: Path):
    from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event

    acl = {"A3": {"publish": True, "read": True}}
    out = publish_shared_memory_event(
        snapshot_ts="2026-05-10T14:00:00+08:00",
        agent_id="A4",
        event_type="memory_publish",
        payload={"memory_id": "TC_2", "kind": "case", "evidence_refs": ["episodes/e2.json"]},
        output_dir=tmp_path,
        acl_config=acl,
    )
    assert out["ok"] is False
    assert out["denied"] is True
    assert not Path(tmp_path / "events.jsonl").exists()


def test_memory_graph_build_from_events(tmp_path: Path):
    from scripts.memory_l4.memory_graph import build_memory_graph

    events = [
        {
            "ts": "2026-05-10T14:00:00+08:00",
            "agent_id": "A3",
            "event_type": "memory_publish",
            "payload": {"memory_id": "TC_1", "kind": "case", "evidence_refs": ["episodes/e1.json"]},
        },
        {
            "ts": "2026-05-10T14:01:00+08:00",
            "agent_id": "A5",
            "event_type": "memory_reference",
            "payload": {"memory_id": "TC_1", "kind": "case", "evidence_refs": ["artifacts/memory_l4/notes.json"]},
        },
    ]
    out = build_memory_graph(
        snapshot_ts="2026-05-10T14:02:00+08:00",
        events=events,
        output_dir=tmp_path,
    )
    graph_path = Path(out["graph_path"])
    assert graph_path.exists()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["version"] == "v0.1"
    assert len(graph["nodes"]) >= 2
    assert len(graph["edges"]) >= 2
    assert graph["edges"][0]["evidence_refs"]


def test_memory_graph_drops_edge_without_evidence_refs(tmp_path: Path):
    from scripts.memory_l4.memory_graph import build_memory_graph

    events = [
        {
            "ts": "2026-05-10T14:00:00+08:00",
            "agent_id": "A3",
            "event_type": "memory_publish",
            "payload": {"memory_id": "TC_1", "kind": "case"},
        }
    ]
    out = build_memory_graph(
        snapshot_ts="2026-05-10T14:02:00+08:00",
        events=events,
        output_dir=tmp_path,
        require_evidence_refs=True,
    )
    graph = json.loads(Path(out["graph_path"]).read_text(encoding="utf-8"))
    assert len(graph["edges"]) == 0
    assert out["summary"]["dropped_edges"] == 1


def test_meta_learning_tasks_enqueue(tmp_path: Path):
    from scripts.memory_l4.meta_learning_tasks import enqueue_meta_learning_tasks

    out = enqueue_meta_learning_tasks(
        snapshot_ts="2026-05-10T14:05:00+08:00",
        risk_signals=[{"risk_signal_id": "RS_1", "confidence": 0.7}],
        migration_mappings=[{"mapping_id": "MAP_1", "migration_confidence": 0.6}],
        output_dir=tmp_path,
    )
    assert Path(out["tasks_path"]).exists()
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    assert summary["tasks_count"] == 2


def test_memory_engine_phase4_entrypoints(tmp_path: Path):
    from workflows.memory.memory_engine.engine import MemoryEngine

    memory = MemoryEngine()
    acl = {"A4": {"publish": True, "read": True}}
    bus = memory.publish_shared_memory_event(
        snapshot_ts="2026-05-10T15:00:00+08:00",
        agent_id="A4",
        event_type="memory_publish",
        payload={"memory_id": "D_1", "kind": "distill", "evidence_refs": ["distills/D_1.json"]},
        output_dir=tmp_path / "bus",
        acl_config=acl,
    )
    assert Path(bus["bus_path"]).exists()

    graph = memory.build_shared_memory_graph(
        snapshot_ts="2026-05-10T15:01:00+08:00",
        events=[bus["event"]],
        output_dir=tmp_path / "graph",
        require_evidence_refs=True,
    )
    assert Path(graph["graph_path"]).exists()

    tasks = memory.enqueue_meta_learning_tasks(
        snapshot_ts="2026-05-10T15:02:00+08:00",
        risk_signals=[{"risk_signal_id": "RS_2", "confidence": 0.8}],
        migration_mappings=[],
        output_dir=tmp_path / "tasks",
    )
    assert Path(tasks["tasks_path"]).exists()
