"""SPEC-33-E T-E8/T-E9：token 预算与成本台账、过 gate 认知回写载荷。

验收：
  - 单次生成 in≤8000 / out≤2000；超限 degraded=true 且提示降级模板。
  - 每次生成追加一行 llm_cost.jsonl（含 model/tokens/gate/degraded/ts）。
  - 回写：gate=reject/unknown 或不可写等级 → 不写入；
    写开关关闭 → status=suspended（不伪造已写入）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
from core.cognitive_writeback import build_writeback_payload, writeback_status  # noqa: E402
from core.llm_budget import check_budget, record_cost  # noqa: E402


def test_budget_limits():
    ok = check_budget(3200, 800)
    assert ok["degraded"] is False
    assert ok["action"] == "allow"

    over = check_budget(9000, 2500)
    assert over["degraded"] is True
    assert over["action"] == "degrade_to_template"
    assert "8000" in over["reason"] and "2000" in over["reason"]


def test_cost_ledger_append_jsonl(tmp_path):
    ledger = tmp_path / "llm_cost.jsonl"
    first = record_cost(
        {"model": "host-llm", "tokens_in": 1200, "tokens_out": 300, "gate": "pass"},
        path=ledger,
    )
    second = record_cost(
        {"model": "host-llm", "tokens_in": 9000, "tokens_out": 100, "gate": "review"},
        path=ledger,
    )
    assert first["recorded"] and second["recorded"]
    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["model"] == "host-llm" and lines[0]["degraded"] is False
    assert lines[1]["degraded"] is True and "8000" in lines[1]["reason"]
    assert lines[0]["ts"]


def test_cost_ledger_requires_model(tmp_path):
    result = record_cost({"tokens_in": 1}, path=tmp_path / "x.jsonl")
    assert result["recorded"] is False
    assert result["known_gaps"]


def test_node_cost_ledger_marks_degraded(tmp_path):
    out = dsh_nodes.S33_rea_cost_ledger(
        {
            "model": "host-llm",
            "tokens_in": 8500,
            "tokens_out": 100,
            "gate": "pass",
            "path": str(tmp_path / "cost.jsonl"),
        }
    )
    assert out["ok"] is True
    body = out["result"]
    assert body["budget"]["degraded"] is True
    assert body["recorded"] is True
    assert any("降级" in gap for gap in body["known_gaps"])


def test_node_cost_ledger_missing_model():
    out = dsh_nodes.S33_rea_cost_ledger({"tokens_in": 1})
    assert out["ok"] is False
    assert out["error"] == "missing_model"


def test_writeback_payload_levels():
    payload = build_writeback_payload(
        [
            {"hypothesis_id": "H-pass", "gate": "pass", "level": "derivation", "content": "A"},
            {"hypothesis_id": "H-review", "gate": "review", "level": "inference", "content": "B"},
            {"hypothesis_id": "H-reject", "gate": "reject", "level": "observation", "content": "C"},
            {
                "hypothesis_id": "H-nofalsifier",
                "gate": "pass",
                "level": "derivation",
                "content": "D",
                "falsifier": "",
            },
        ]
    )
    qualities = {
        item["record"]["external_id"]: item["record"]["quality_level"] for item in payload["writes"]
    }
    assert qualities == {"H-pass": "B", "H-review": "C"}
    assert {item["id"] for item in payload["skipped"]} == {"H-reject", "H-nofalsifier"}


def test_writeback_suspended_when_disabled(monkeypatch):
    monkeypatch.delenv("COGNITIVE_MCP_WRITE_ENABLED", raising=False)
    status = writeback_status(
        [{"hypothesis_id": "H1", "gate": "pass", "level": "derivation", "content": "x"}]
    )
    assert status["status"] == "suspended"
    assert status["enabled"] is False
    assert status["writes"] and any("挂起" in gap for gap in status["known_gaps"])


def test_writeback_ready_when_enabled(monkeypatch):
    monkeypatch.setenv("COGNITIVE_MCP_WRITE_ENABLED", "true")
    status = writeback_status(
        [{"hypothesis_id": "H1", "gate": "pass", "level": "derivation", "content": "x"}]
    )
    assert status["status"] == "ready"
    assert status["writes"][0]["verify"]["success"] is True


def test_node_writeback_requires_items():
    out = dsh_nodes.S33_rea_writeback({})
    assert out["ok"] is False
    assert out["error"] == "missing_items"


def test_node_writeback_nothing_to_write():
    out = dsh_nodes.S33_rea_writeback(
        {
            "items": [
                {"hypothesis_id": "H1", "gate": "reject", "level": "observation", "content": "x"}
            ],
            "enabled": True,
        }
    )
    assert out["ok"] is True
    assert out["result"]["status"] == "nothing_to_write"
