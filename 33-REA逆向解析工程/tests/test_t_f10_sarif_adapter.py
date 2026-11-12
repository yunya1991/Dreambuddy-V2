"""SPEC-33-F T-F10：SARIF 2.1.0 归一、落盘与快照 section（RED）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.sarif_adapter import build_sarif, write_sarif  # noqa: E402
from core.evidence import Evidence  # noqa: E402

_SARIF_SCHEMA = {
    "type": "object",
    "required": ["version", "runs"],
    "properties": {
        "version": {"const": "2.1.0"},
        "$schema": {"type": "string"},
        "runs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool", "results"],
                "properties": {
                    "tool": {
                        "type": "object",
                        "required": ["driver"],
                        "properties": {
                            "driver": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {"name": {"const": "33-REA"}},
                            }
                        },
                    },
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["ruleId", "level", "message"],
                            "properties": {
                                "ruleId": {"type": "string", "minLength": 1},
                                "level": {"enum": ["note", "warning", "error"]},
                                "message": {
                                    "type": "object",
                                    "required": ["text"],
                                    "properties": {"text": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _isolate_reflection_dirs(monkeypatch, tmp_path: Path) -> Path:
    import adapters.sarif_adapter as sarif_adapter
    import dsh_nodes

    snapshot_dir = tmp_path / "reflection_data" / "snapshots"
    sarif_dir = tmp_path / "reflection_data" / "sarif"
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(dsh_nodes, "_CACHE_DIR", tmp_path / "reflection_data" / "cache")
    monkeypatch.setattr(sarif_adapter, "DEFAULT_SARIF_DIR", sarif_dir)
    return sarif_dir


def test_sarif_structure_passes_schema_validation() -> None:
    report = build_sarif({"target": "/repo"})

    assert report["version"] == "2.1.0"
    assert report["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    assert report["runs"][0]["tool"]["driver"]["name"] == "33-REA"
    assert report["runs"][0]["results"] == []
    jsonschema.validate(report, _SARIF_SCHEMA)


@pytest.mark.parametrize(
    ("gate", "expected"),
    [("pass", "note"), ("review", "warning"), ("reject", "error")],
)
def test_cognitive_debt_maps_gate_and_relative_location(
    tmp_path: Path, gate: str, expected: str
) -> None:
    source = tmp_path / "src" / "debt.py"
    evidence = Evidence(
        result="复杂逻辑缺少注释",
        provenance={"file": str(source), "line": 7, "column": 3},
    )
    report = build_sarif(
        {
            "target": str(tmp_path),
            "gate_decision": gate,
            "cognitive_debt": [
                {"type": "missing-comment", "description": "缺少注释", "evidence": evidence}
            ],
        }
    )

    result = report["runs"][0]["results"][0]
    assert result["ruleId"] == "missing-comment"
    assert result["level"] == expected
    physical = result["locations"][0]["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "src/debt.py"
    assert physical["region"] == {"startLine": 7, "startColumn": 3}
    json.dumps(report, ensure_ascii=False)


def test_rules_and_known_gaps_are_normalized(tmp_path: Path) -> None:
    report = build_sarif(
        {
            "target": str(tmp_path),
            "findings": [
                {
                    "file": "src/bad.py",
                    "line": 4,
                    "column": 1,
                    "rule": "F401",
                    "severity": "error",
                    "message": "unused import",
                }
            ],
            "evidence": [
                {
                    "result": "store 不得依赖 ui",
                    "provenance": {
                        "analysis": "rules_engine",
                        "rule_id": "no-store-to-ui",
                        "file": "src/stores/cart.ts",
                        "line": 0,
                    },
                }
            ],
            "known_gaps": ["ESLint 不可用"],
        }
    )

    results = {item["ruleId"]: item for item in report["runs"][0]["results"]}
    assert results["F401"]["level"] == "error"
    assert results["no-store-to-ui"]["level"] == "note"
    constraint_location = results["no-store-to-ui"]["locations"][0]["physicalLocation"]
    assert constraint_location["artifactLocation"]["uri"] == "src/stores/cart.ts"
    assert "region" not in constraint_location
    assert results["known-gap"]["level"] == "note"
    assert (
        results["known-gap"]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "."
    )


def test_write_sarif_persists_schema_valid_artifact(tmp_path: Path) -> None:
    path = write_sarif(
        "snapshot-1",
        {"target": str(tmp_path), "known_gaps": ["静态分析局限"]},
        output_dir=tmp_path / "sarif",
    )

    assert path == tmp_path / "sarif" / "snapshot-1.sarif"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(persisted, _SARIF_SCHEMA)
    assert persisted["runs"][0]["results"][0]["message"]["text"] == "静态分析局限"


def test_snapshot_sarif_section_scans_rules_and_writes_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    import dsh_nodes

    sarif_dir = _isolate_reflection_dirs(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "bad.py").write_text("import os\n", encoding="utf-8")
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(project), "force": True})
    snapshot_id = analyzed["result"]["snapshot_id"]

    output = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "sarif"})

    assert output["ok"] is True, output
    result = output["result"]
    assert result["section"] == "sarif"
    assert result["total"] >= 1
    artifact = sarif_dir / f"{snapshot_id}.sarif"
    assert Path(result["path"]) == artifact
    persisted = json.loads(artifact.read_text(encoding="utf-8"))
    assert any(item["ruleId"] == "F401" for item in persisted["runs"][0]["results"])


def test_snapshot_sarif_includes_architecture_constraint(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    sarif_dir = _isolate_reflection_dirs(monkeypatch, tmp_path)
    project = tmp_path / "project"
    (project / "src" / "stores").mkdir(parents=True)
    (project / "src" / "components").mkdir(parents=True)
    (project / "src" / "stores" / "cart.ts").write_text(
        'import { Cart } from "../components/Cart";\nexport const cart = 1;\n',
        encoding="utf-8",
    )
    (project / "src" / "components" / "Cart.tsx").write_text(
        "export const Cart = () => null;\n", encoding="utf-8"
    )
    (project / "rea_rules.yaml").write_text(
        """version: 1
layers:
  ui: ["src/components/**"]
  store: ["src/stores/**"]
rules:
  - id: no-store-to-ui
    type: forbid_edge
    from: store
    to: ui
    message: "store 不得依赖 ui"
""",
        encoding="utf-8",
    )
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(project), "force": True})
    snapshot_id = analyzed["result"]["snapshot_id"]

    output = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "sarif"})

    assert output["ok"] is True, output
    artifact = sarif_dir / f"{snapshot_id}.sarif"
    persisted = json.loads(artifact.read_text(encoding="utf-8"))
    assert any(item["ruleId"] == "no-store-to-ui" for item in persisted["runs"][0]["results"])


def test_snapshot_sarif_section_respects_byte_budget(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    _isolate_reflection_dirs(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    snapshot_id = "large-sarif"
    payload = {
        "snapshot_id": snapshot_id,
        "target": str(project),
        "known_gaps": [f"局限 {index}: " + "x" * 500 for index in range(30)],
        "evidence": [],
        "raw": {},
    }
    (dsh_nodes._SNAPSHOT_DIR).mkdir(parents=True)
    (dsh_nodes._SNAPSHOT_DIR / f"{snapshot_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    output = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "sarif"})

    assert output["ok"] is True, output
    result = output["result"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 8192
    assert result["trimmed"]["results"]["kept"] < 30
    assert result["next_cursor"] == result["trimmed"]["results"]["kept"]
