"""SPEC-33-E T-E6：外部源价值评分接口（Q3）。

硬约束：
  - 只有 PoE gate=pass 的打分才允许写入 `relevance_score`。
  - 未过 gate / 分数越界 / 源未登记 → 拒绝并计入 known_gaps。
  - 外部源文件损坏或结构不符 → 不写入（FAIL-OPEN，不伪造数据）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
from core.relevance import apply_relevance_scores, write_relevance_scores  # noqa: E402

SOURCES = [
    {"id": "dlt", "location": "https://github.com/dlt-hub/dlt", "priority": "P0"},
    {"id": "airbyte", "location": "https://github.com/airbytehq/airbyte", "priority": "P1"},
]


def test_pass_score_applied_others_rejected():
    report = apply_relevance_scores(
        SOURCES,
        [
            {"source_id": "dlt", "relevance_score": 0.87, "gate": "pass"},
            {"source_id": "airbyte", "relevance_score": 0.9, "gate": "review"},
            {"source_id": "airbyte", "relevance_score": 1.4, "gate": "pass"},
            {"source_id": "unknown", "relevance_score": 0.5, "gate": "pass"},
        ],
    )
    assert report["updated"] == [{"source_id": "dlt", "relevance_score": 0.87}]
    assert len(report["rejected"]) == 3
    assert len(report["known_gaps"]) == 3
    by_id = {item["id"]: item for item in report["sources"]}
    assert by_id["dlt"]["relevance_score"] == 0.87
    assert "relevance_score" not in by_id["airbyte"]


def test_write_only_persists_passed_scores(tmp_path: Path):
    path = tmp_path / "external_sources.json"
    path.write_text(
        json.dumps({"version": "3", "sources": [dict(item) for item in SOURCES]}),
        encoding="utf-8",
    )
    report = apply_relevance_scores(
        json.loads(path.read_text(encoding="utf-8"))["sources"],
        [
            {"source_id": "dlt", "relevance_score": 0.66, "gate": "pass"},
            {"source_id": "airbyte", "relevance_score": 0.99, "gate": "reject"},
        ],
    )
    written = write_relevance_scores(path, report)
    assert written["written"] == 1
    saved = json.loads(path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in saved["sources"]}
    assert by_id["dlt"]["relevance_score"] == 0.66
    assert "relevance_score" not in by_id["airbyte"]


def test_corrupted_file_not_overwritten(tmp_path: Path):
    path = tmp_path / "external_sources.json"
    path.write_text("{broken json", encoding="utf-8")
    report = apply_relevance_scores(
        SOURCES, [{"source_id": "dlt", "relevance_score": 0.8, "gate": "pass"}]
    )
    written = write_relevance_scores(path, report)
    assert written["written"] == 0
    assert written["known_gaps"]
    assert path.read_text(encoding="utf-8") == "{broken json"


def test_node_scores_without_persist():
    out = dsh_nodes.S33_rea_score_sources(
        {
            "sources": SOURCES,
            "scores": [{"source_id": "dlt", "relevance_score": 0.75, "gate": "pass"}],
        }
    )
    assert out["ok"] is True
    body = out["result"]
    assert body["mode"] == "relevance"
    assert body["stats"] == {"sources": 2, "updated": 1, "rejected": 0}
    assert body["evidence"][0]["level"] == "derivation"
    assert body["written"] is None


def test_node_missing_sources():
    out = dsh_nodes.S33_rea_score_sources({"scores": []})
    assert out["ok"] is False
    assert out["error"] == "missing_sources"
