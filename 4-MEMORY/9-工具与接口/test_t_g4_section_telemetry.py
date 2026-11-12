"""T-G4 按 section 遥测（JSONL）— RED 测试

SPEC-33-G §1 G-G4 / §3 T-G4：
  按 section 聚合的调用量 / 命中率 / 采纳率 / 预算命中。

RED 契约：
  - section_telemetry 模块不存在
  - _handle_recall / _handle_verify 未写遥测
"""

from __future__ import annotations

import json
from unittest.mock import patch

from section_telemetry import SectionTelemetry


def _data(result):
    return result.get("data", result)


def test_record_and_aggregate_rates(tmp_path):
    tel = SectionTelemetry(tmp_path / "sections.jsonl")
    tel.record_call("analyze", hit=True)
    tel.record_call("analyze", hit=False, budget_hit=False)
    tel.record_adoption("analyze")

    stats = tel.aggregate()["analyze"]
    assert stats["calls"] == 2
    assert stats["hits"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["adoptions"] == 1
    assert stats["adoption_rate"] == 0.5
    assert stats["budget_hit_rate"] == 0.5


def test_jsonl_schema(tmp_path):
    path = tmp_path / "sections.jsonl"
    SectionTelemetry(path).record_call("trace", hit=True, latency_ms=12)

    event = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert event["section"] == "trace"
    assert event["event"] == "call"
    assert event["hit"] is True
    assert event["schema_version"] == "1"


def test_handle_recall_emits_telemetry(tmp_path, monkeypatch):
    path = tmp_path / "sections.jsonl"
    monkeypatch.setenv("COGNITIVE_SECTION_TELEMETRY_PATH", str(path))
    from cognitive_mcp_server import _handle_recall

    with patch("cognitive_mcp_server._get_cle") as mock_cle:
        mock_cle.return_value.recall.return_value = [{"id": "VM-1"}]
        json.loads(_handle_recall({"context": "x", "include_process": False}))

    events = SectionTelemetry(path).events()
    assert len(events) == 1
    assert events[0]["section"] == "recall"
    assert events[0]["hit"] is True


def test_handle_verify_emits_adoption_telemetry(tmp_path, monkeypatch):
    path = tmp_path / "sections.jsonl"
    monkeypatch.setenv("COGNITIVE_SECTION_TELEMETRY_PATH", str(path))
    monkeypatch.setenv("COGNITIVE_OUTCOME_LEDGER_PATH", str(tmp_path / "events.jsonl"))
    from cognitive_mcp_server import _handle_verify

    with (
        patch("cognitive_mcp_server._get_cle") as mock_cle,
        patch("cognitive_mcp_server._load_skill_indexer", return_value=None),
    ):
        mock_cle.return_value.verify.return_value = {"ok": True}
        json.loads(
            _handle_verify(
                {
                    "memory_id": "VM-T",
                    "success": True,
                    "outcome": {
                        "accepted": True,
                        "tests_pass": True,
                        "reverted": False,
                        "section": "evolution",
                    },
                }
            )
        )

    events = SectionTelemetry(path).events()
    assert [e["event"] for e in events] == ["call", "adoption"]
    assert all(e["section"] == "evolution" for e in events)
