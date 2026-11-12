"""SPEC-33-F T-F09：LSP/Jedi 引用、诊断与对照实验（RED）。"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters import lsp_adapter  # noqa: E402
from core.hypothesis import audit_hypotheses  # noqa: E402


def _python_project(root: Path) -> list[str]:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "billing.py").write_text(
        "def calculate_total(items):\n    return sum(items)\n\n\ndef tax_rate():\n    return 0.1\n",
        encoding="utf-8",
    )
    (root / "pkg" / "api.py").write_text(
        "from pkg.billing import calculate_total\n\n\ndef handle(items):\n    return calculate_total(items)\n",
        encoding="utf-8",
    )
    return ["pkg.billing", "pkg.api"]


def test_jedi_target_refs_control_improves_resolution_by_at_least_20_points(
    tmp_path: Path,
) -> None:
    nodes = _python_project(tmp_path)
    refs = ["pkg.billing.calculate_total", "pkg.billing.tax_rate"]
    hypotheses = [
        {
            "hypothesis_id": f"H-{index}",
            "claim": "符号引用可以精确定位",
            "target_refs": [ref],
            "falsifier": "若定义与引用文件均不属于静态图则否决",
        }
        for index, ref in enumerate(refs)
    ]

    baseline = audit_hypotheses(hypotheses, nodes)
    report = lsp_adapter.inspect_symbols(str(tmp_path), refs, language="python")
    enhanced = audit_hypotheses(hypotheses, nodes, semantic_locations=report["locations"])

    baseline_rate = sum(bool(item["resolved_refs"]) for item in baseline) / len(refs)
    enhanced_rate = sum(bool(item["resolved_refs"]) for item in enhanced) / len(refs)
    assert report["degraded"] is False, report
    assert report["tools"]["jedi"]["status"] == "ok"
    assert report["definitions"][refs[0]][0]["file"] == "pkg/billing.py"
    assert any(item["file"] == "pkg/api.py" for item in report["references"][refs[0]])
    assert enhanced[0]["lsp_hits"][refs[0]]
    assert baseline_rate == 0.0
    assert enhanced_rate - baseline_rate >= 0.20


def test_pyright_diagnostics_are_normalized_to_evidence(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "bad.py").write_text("value: str = 1\n", encoding="utf-8")
    monkeypatch.setattr(lsp_adapter, "_pyright_command", lambda root: ["pyright"])
    commands: list[tuple[list[str], int]] = []

    def runner(cmd, timeout, cwd=None, input_text=None):
        commands.append((list(cmd), timeout))
        if "--version" in cmd:
            return 0, "pyright 1.1.0\n", ""
        return (
            1,
            json.dumps(
                {
                    "version": "1.1.0",
                    "generalDiagnostics": [
                        {
                            "file": str(tmp_path / "bad.py"),
                            "severity": "error",
                            "message": "Type mismatch",
                            "range": {
                                "start": {"line": 0, "character": 15},
                                "end": {"line": 0, "character": 16},
                            },
                            "rule": "reportAssignmentType",
                        }
                    ],
                }
            ),
            "",
        )

    report = lsp_adapter.scan_diagnostics(str(tmp_path), language="python", runner=runner)

    assert commands[0][1] == lsp_adapter.STARTUP_TIMEOUT == 20
    assert commands[1][1] == lsp_adapter.REQUEST_TIMEOUT == 5
    assert report["section"] == "diagnostics"
    assert report["degraded"] is False
    assert report["diagnostics"] == [
        {
            "engine": "pyright",
            "file": "bad.py",
            "line": 1,
            "column": 16,
            "severity": "error",
            "rule": "reportAssignmentType",
            "message": "Type mismatch",
        }
    ]
    assert report["evidence"][0]["provenance"]["analysis"] == "type_diagnostics"


def test_missing_language_tools_fail_open(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    def missing(cmd, timeout, cwd=None, input_text=None):
        return 127, "", "command not found"

    symbols = lsp_adapter.inspect_symbols(
        str(tmp_path), ["module.f"], language="python", runner=missing
    )
    diagnostics = lsp_adapter.scan_diagnostics(str(tmp_path), language="python", runner=missing)

    assert symbols["degraded"] is True
    assert symbols["locations"] == {"module.f": []}
    assert diagnostics["degraded"] is True
    assert diagnostics["diagnostics"] == []
    assert diagnostics["known_gaps"]


def test_trace_lsp_locations_expand_ts_seeds(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "entry.ts").write_text(
        "import { helper } from './helper';\nexport const run = () => helper();\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.ts").write_text("export const helper = () => 1;\n", encoding="utf-8")
    (tmp_path / "consumer.ts").write_text(
        "import { run } from './entry';\nexport const consume = () => run();\n",
        encoding="utf-8",
    )
    import dsh_nodes

    monkeypatch.setattr(
        lsp_adapter,
        "inspect_symbols",
        lambda *args, **kwargs: {
            "locations": {
                "run": [
                    {
                        "file": "consumer.ts",
                        "line": 2,
                        "column": 31,
                        "kind": "reference",
                        "symbol": "run",
                    }
                ]
            },
            "definitions": {"run": []},
            "references": {"run": []},
            "tools": {"tsserver": {"status": "ok"}},
            "degraded": False,
            "known_gaps": [],
            "evidence": [
                {
                    "result": "tsserver 引用定位完成",
                    "level": "observation",
                    "provenance": {"analysis": "symbol_references"},
                    "confidence": 0.95,
                    "known_gaps": [],
                }
            ],
        },
    )

    output = dsh_nodes.S33_rea_trace(
        {
            "target": str(tmp_path),
            "feature": "run",
            "entry": "entry.ts",
            "lsp": True,
            "budget_bytes": 8192,
        }
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert "consumer.ts" in result["seeds"]
    assert "consumer.ts" in result["call_chain"]["seeds"]
    assert result["lsp"]["degraded"] is False


def test_snapshot_diagnostics_section(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    (snapshot_dir / "types.json").write_text(
        json.dumps({"snapshot_id": "types", "target": str(tmp_path), "raw": {}}),
        encoding="utf-8",
    )
    report = {
        "section": "diagnostics",
        "diagnostics": [{"file": "bad.py", "line": 1, "message": "Type mismatch"}],
        "degraded": False,
        "evidence": [],
        "known_gaps": [],
    }
    monkeypatch.setattr(lsp_adapter, "scan_diagnostics", lambda *args, **kwargs: report)

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "types", "section": "diagnostics", "limit": 1}
    )

    assert output["ok"] is True, output
    assert output["result"]["items"] == report["diagnostics"]
    assert output["result"]["total"] == 1
    assert output["result"]["report"] == report


def test_tsserver_command_framing_and_idle_pool_contract() -> None:
    assert lsp_adapter.TSServerPool.idle_seconds == 60
    assert lsp_adapter.STARTUP_TIMEOUT == 20
    assert lsp_adapter.REQUEST_TIMEOUT == 5
    with pytest.raises((FileNotFoundError, OSError)):
        lsp_adapter.TSServerPool(command=["/definitely/missing/tsserver"], cwd="/tmp").start()


def test_tsserver_requests_are_newline_delimited_json(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "entry.ts"
    source.write_text("export const run = () => 1;\n", encoding="utf-8")
    client = lsp_adapter.TSServerPool(["tsserver"], str(tmp_path))
    client.process = SimpleNamespace(poll=lambda: None, stdin=io.BytesIO())
    monkeypatch.setattr(
        client,
        "_read_message",
        lambda timeout: {
            "type": "response",
            "request_seq": 1,
            "success": True,
            "body": {},
        },
    )

    client._roundtrip("configure", {"hostInfo": "33-rea"}, 1)
    client.open_file(source)

    raw = client.process.stdin.getvalue()
    assert not raw.startswith(b"Content-Length:")
    lines = raw.splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["command"] for line in lines] == ["configure", "open"]


def test_tsserver_reference_call_does_not_deadlock_reentrant_request(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "entry.ts"
    source.write_text("export const run = () => 1;\n", encoding="utf-8")
    client = lsp_adapter.TSServerPool(["tsserver"], str(tmp_path))
    client.last_used = time.monotonic()
    client.process = SimpleNamespace(poll=lambda: None, stdin=io.BytesIO())
    monkeypatch.setattr(client, "start", lambda: None)
    monkeypatch.setattr(client, "_roundtrip", lambda *args: {"refs": []})
    finished = []

    def invoke() -> None:
        client.references(source, 1, 14)
        finished.append(True)

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    thread.join(timeout=1)

    assert finished == [True]
