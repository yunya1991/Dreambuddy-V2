from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.runtime_adapter import scan_runtime  # noqa: E402


def _coverage(root: Path, classes: list[tuple[str, list[int]]]) -> None:
    class_xml = []
    for filename, hits in classes:
        lines = "".join(
            f'<line number="{index}" hits="{hit}"/>' for index, hit in enumerate(hits, start=1)
        )
        covered = sum(hit > 0 for hit in hits)
        rate = covered / len(hits) if hits else 0.0
        class_xml.append(
            f'<class name="{Path(filename).name}" filename="{filename}" '
            f'line-rate="{rate}" branch-rate="0"><lines>{lines}</lines></class>'
        )
    (root / "coverage.xml").write_text(
        '<?xml version="1.0"?><coverage line-rate="0.5" branch-rate="0">'
        f'<packages><package name="pkg"><classes>{"".join(class_xml)}</classes>'
        "</package></packages></coverage>",
        encoding="utf-8",
    )


def _span(
    filename: str,
    *,
    function: str = "handle",
    status: int = 1,
    attribute: str = "code.file.path",
) -> dict:
    return {
        "traceId": "trace-1",
        "spanId": f"span-{function}",
        "name": function,
        "attributes": [
            {"key": attribute, "value": {"stringValue": filename}},
            {"key": "code.function.name", "value": {"stringValue": function}},
        ],
        "status": {"code": status},
        "startTimeUnixNano": "100",
        "endTimeUnixNano": "200",
    }


def _nodes(report: dict) -> dict[str, dict]:
    return {item["node"]: item for item in report["reconciled_nodes"]}


def test_real_coverage_and_otel_json_reconcile_static_nodes(tmp_path: Path) -> None:
    _coverage(tmp_path, [("pkg/covered.py", [1, 1]), ("pkg/idle.py", [0, 0])])
    otel = tmp_path / "otel.json"
    otel.write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {"scopeSpans": [{"spans": [_span(str(tmp_path / "pkg/covered.py"))]}]}
                ]
            }
        ),
        encoding="utf-8",
    )

    report = scan_runtime(
        str(tmp_path),
        otel_path=str(otel),
        static_nodes=["pkg.covered", "pkg.idle", "pkg.unobserved"],
    )

    assert report["section"] == "runtime"
    assert report["degraded"] is False
    assert report["coverage"]["available"] is True
    assert report["zero_coverage_modules"] == [
        {
            "module": "pkg/idle.py",
            "line_rate": 0.0,
            "uncovered_lines": 2,
            "total_lines": 2,
        }
    ]
    assert report["spans"][0]["file"] == "pkg/covered.py"
    assert report["spans"][0]["function"] == "handle"
    nodes = _nodes(report)
    assert nodes["pkg.covered"]["status"] == "confirmed"
    assert nodes["pkg.covered"]["sources"] == ["coverage", "otel"]
    assert nodes["pkg.covered"]["span_count"] == 1
    assert nodes["pkg.idle"]["status"] == "contradicted"
    assert nodes["pkg.idle"]["observed"] is False
    assert nodes["pkg.unobserved"]["status"] == "unobserved"
    assert all(isinstance(item, dict) for item in report["evidence"])


def test_otel_jsonl_bare_spans_confirm_nodes_and_keep_error_status(
    tmp_path: Path,
) -> None:
    _coverage(tmp_path, [("pkg/api.py", [1])])
    otel = tmp_path / "otel.jsonl"
    otel.write_text(
        "\n".join(
            [
                json.dumps(_span("pkg/api.py", status=2, attribute="code.filepath")),
                json.dumps(_span("pkg/api.py", function="fallback", status=0)),
            ]
        ),
        encoding="utf-8",
    )

    report = scan_runtime(str(tmp_path), otel_path=str(otel), static_nodes=["pkg.api"])

    assert report["degraded"] is False
    assert len(report["spans"]) == 2
    assert {span["status"] for span in report["spans"]} == {"error", "unset"}
    node = _nodes(report)["pkg.api"]
    assert node["status"] == "confirmed"
    assert node["span_count"] == 2
    assert node["error_span_count"] == 1


def test_malformed_otel_line_is_degraded_without_discarding_valid_spans(
    tmp_path: Path,
) -> None:
    _coverage(tmp_path, [("pkg/api.py", [1])])
    otel = tmp_path / "otel.jsonl"
    otel.write_text(json.dumps(_span("pkg/api.py")) + "\n{not-json}\n", encoding="utf-8")

    report = scan_runtime(str(tmp_path), otel_path=str(otel), static_nodes=["pkg.api"])

    assert report["degraded"] is True
    assert len(report["spans"]) == 1
    assert _nodes(report)["pkg.api"]["status"] == "confirmed"
    assert any("line 2" in gap for gap in report["known_gaps"])


def test_missing_reports_fail_open_without_fabricating_observations(
    tmp_path: Path,
) -> None:
    report = scan_runtime(str(tmp_path), static_nodes=["pkg.absent"])

    assert report["degraded"] is True
    assert report["coverage"]["available"] is False
    assert report["coverage"]["line_rate"] is None
    assert report["spans"] == []
    assert report["zero_coverage_modules"] == []
    assert _nodes(report)["pkg.absent"]["status"] == "unobserved"
    assert report["known_gaps"]
    assert any(item["level"] == "unknown" for item in report["evidence"])


def test_snapshot_runtime_section_uses_snapshot_modules_and_paginates(
    tmp_path: Path, monkeypatch
) -> None:
    import dsh_nodes

    _coverage(tmp_path, [("pkg/covered.py", [1]), ("pkg/idle.py", [0])])
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    (snapshot_dir / "runtime.json").write_text(
        json.dumps(
            {
                "snapshot_id": "runtime",
                "target": str(tmp_path),
                "raw": {"modules": ["pkg.covered", "pkg.idle"]},
            }
        ),
        encoding="utf-8",
    )

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "runtime", "section": "runtime", "limit": 1}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert result["section"] == "runtime"
    assert result["items"] == [
        next(item for item in result["report"]["reconciled_nodes"] if item["node"] == "pkg.covered")
    ]
    assert result["total"] == 2
    assert result["next_cursor"] == 1
    assert result["report"]["zero_coverage_modules"][0]["module"] == "pkg/idle.py"


def test_snapshot_runtime_section_enforces_byte_budget(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    _coverage(tmp_path, [("pkg/api.py", [1])])
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    modules = [f"pkg.module_{index:02d}." + "x" * 160 for index in range(30)]
    (snapshot_dir / "budget.json").write_text(
        json.dumps(
            {
                "snapshot_id": "budget",
                "target": str(tmp_path),
                "raw": {"modules": modules},
            }
        ),
        encoding="utf-8",
    )

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "budget", "section": "runtime", "limit": 20}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 8192
    assert result["trimmed"]
    assert result["next_cursor"] is not None


def test_invalid_coverage_values_degrade_but_keep_valid_otel(tmp_path: Path) -> None:
    (tmp_path / "coverage.xml").write_text(
        '<coverage line-rate="0"><packages><package><classes>'
        '<class filename="pkg/api.py" line-rate="0"><lines>'
        '<line number="1" hits="not-an-int"/>'
        "</lines></class></classes></package></packages></coverage>",
        encoding="utf-8",
    )
    otel = tmp_path / "otel.json"
    otel.write_text(json.dumps(_span("pkg/api.py")), encoding="utf-8")

    report = scan_runtime(str(tmp_path), otel_path=str(otel), static_nodes=["pkg.api"])

    assert report["degraded"] is True
    assert report["coverage"]["available"] is False
    assert report["coverage"]["line_rate"] is None
    assert len(report["spans"]) == 1
    assert _nodes(report)["pkg.api"]["status"] == "confirmed"
    assert any(item["level"] == "unknown" for item in report["evidence"])


def test_runtime_budget_never_repeats_cursor_for_oversized_node(
    tmp_path: Path, monkeypatch
) -> None:
    import dsh_nodes

    _coverage(tmp_path, [("pkg/api.py", [1])])
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    (snapshot_dir / "oversized.json").write_text(
        json.dumps(
            {
                "snapshot_id": "oversized",
                "target": str(tmp_path),
                "raw": {"modules": ["pkg." + "x" * 10_000]},
            }
        ),
        encoding="utf-8",
    )

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "oversized", "section": "runtime", "limit": 1}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 8192
    assert result["next_cursor"] != 0
    assert result["trimmed"]["items"]["kept"] == 0
