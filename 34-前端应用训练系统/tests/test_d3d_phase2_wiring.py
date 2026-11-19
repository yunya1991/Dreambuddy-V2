# -*- coding: utf-8 -*-
"""P0-D3D Phase 2 RED: GateFlow → 立案 → WorkerInbox / Approval 落盘 / 53 登记。"""

import json
import os
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.approval_bridge import ApprovalBridge, JsonlGateFlowSink  # noqa: E402
from core.brainstorm_dispatcher import dispatch_tasks, enqueue_tasks  # noqa: E402
from core.decision_record import DecisionRecord, adopt_record  # noqa: E402
from core.feishu_authorization_bridge import ApprovalRequest, build_grant  # noqa: E402
from core.gateflow_brainstorm_bridge import consume_once, export_run_events  # noqa: E402

NOW = 1000.0


def _write_events(path, events):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_gateflow_rejected_creates_ticket_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        events_dir = os.path.join(tmp, "events")
        state_path = os.path.join(tmp, "state.json")
        tickets_path = os.path.join(tmp, "tickets.jsonl")
        event = {
            "run_id": "GR-1",
            "flow_id": "FLOW-1",
            "task_id": "TK-1",
            "trace_id": "rp-1",
            "type": "node.rejected",
            "node_id": "G2",
            "at": NOW,
            "detail": {
                "reason": "回测未达标",
                "high_risk": True,
                "rewind_to": "none",
                "evidence_refs": ["EV-1"],
            },
        }
        path = os.path.join(events_dir, "GR-1.jsonl")
        _write_events(path, [event])

        first = consume_once(events_dir, state_path, tickets_path)
        assert first["tickets_created"] == 1
        tickets = _read_jsonl(tickets_path)
        assert len(tickets) == 1
        assert tickets[0]["tier"] == "T3"
        assert tickets[0]["source_layer"] == "GateFlow"

        # 同事件再次追加：游标读到新行，但 gap_key 已存在 → 不重复立案
        _write_events(path, [event])
        second = consume_once(events_dir, state_path, tickets_path)
        assert second["tickets_created"] == 0
        assert second["duplicates"] == 1
        assert len(_read_jsonl(tickets_path)) == 1


def test_gateflow_ignores_rewound_and_bad_lines():
    with tempfile.TemporaryDirectory() as tmp:
        events_dir = os.path.join(tmp, "events")
        state_path = os.path.join(tmp, "state.json")
        tickets_path = os.path.join(tmp, "tickets.jsonl")
        path = os.path.join(events_dir, "GR-2.jsonl")
        _write_events(
            path,
            [
                {
                    "run_id": "GR-2",
                    "type": "node.rewound",
                    "node_id": "G1",
                    "at": NOW,
                }
            ],
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("not-json\n")

        result = consume_once(events_dir, state_path, tickets_path)
        assert result["tickets_created"] == 0
        assert result["bad_lines"] == 1


def test_dispatch_enqueues_worker_inbox():
    with tempfile.TemporaryDirectory() as tmp:
        record = adopt_record(
            DecisionRecord(
                decision_id="DR-1",
                ticket_id="BT-1",
                chosen_option="O-1",
                rationale="回测通过",
                evidence_refs=("EV-1",),
                dissent=("反方：样本不足",),
                confidence=0.8,
                owner="human",
                expires_at=2000.0,
            ),
            now=NOW,
        )
        tasks = dispatch_tasks(
            record,
            ticket_id="BT-1",
            tasks=(
                {
                    "title": "重跑回测",
                    "role": "engineer",
                    "mandate": {"goal": "重跑回测", "acceptance": "回测通过"},
                },
            ),
            now=NOW + 1,
        )
        count = enqueue_tasks(tasks, root=tmp)
        assert count == 1
        inbox_path = os.path.join(tmp, "34-前端应用训练系统", "dsh_worker_inbox.jsonl")
        records = _read_jsonl(inbox_path)
        assert len(records) == 1
        assert records[0]["source"] == "brainstorm"
        assert records[0]["decision_id"] == "DR-1"
        assert records[0]["role"] == "engineer"
        assert records[0]["mandate"]["goal"] == "重跑回测"


def test_approval_bridge_writes_jsonl_gateflow_sink():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gateflow_events.jsonl")
        sink = JsonlGateFlowSink(path)
        bridge = ApprovalBridge(secret="s", gateflow_sink=sink)
        request = ApprovalRequest(
            request_id="AR-1",
            gate_run_id="GR-1",
            node_id="N1",
            action="rework.dispatch",
            scope=("rework.dispatch",),
            ttl_s=3600,
            requested_by="hermes_secretary",
            reason="驳回后重做",
        )
        grant = build_grant(request, subject="u1", secret="s", issued_at=NOW, nonce="n-1")
        assert bridge.write_grant(grant, now=NOW + 1)
        events = _read_jsonl(path)
        assert len(events) == 1
        assert events[0]["type"] == "approval.granted"
        assert events[0]["request_id"] == "AR-1"


def test_export_run_events_writes_rejection_record():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "GR-9.jsonl")
        run = {
            "run_id": "GR-9",
            "flow_id": "FLOW-1",
            "task_id": "TK-9",
            "trace_id": "rp-9",
            "events": [
                {"type": "node.rejected", "node_id": "G2", "at": NOW, "detail": {"reason": "x"}},
                {"type": "node.rewound", "node_id": "G1", "at": NOW},
            ],
        }
        assert export_run_events(run, path) == 2
        events = _read_jsonl(path)
        assert events[0]["run_id"] == "GR-9"
        assert events[0]["type"] == "node.rejected"


def test_external_runtime_registry_denies_hermes_by_default():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "53-DSH插件模块",
        "external_runtimes.yaml",
    )
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert doc["default_deny"] is True
    hermes = next(item for item in doc["external_runtimes"] if item["id"] == "hermes")
    assert hermes["enabled"] is False
    assert hermes["allowed_roles"] == ["research", "engineer"]
    assert hermes["permitted_profiles"] == ["sandbox"]
