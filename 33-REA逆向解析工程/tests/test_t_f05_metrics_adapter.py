"""SPEC-33-F T-F05 度量适配测试（RED）：radon/vulture 真实输出 + 缺失降级 + jscpd 注入。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.metrics_adapter import scan_metrics  # noqa: E402


def _py_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text(
        "import os\n\n\ndef branchy(x):\n"
        "    if x > 0:\n"
        "        if x > 10:\n"
        "            return 1\n"
        "        return 2\n"
        "    return 3\n",
        encoding="utf-8",
    )
    return root


def test_real_tools_metrics_shape(tmp_path: Path) -> None:
    root = _py_project(tmp_path)
    report = scan_metrics(str(root))

    assert report["section"] == "metrics"
    assert report["tools"]["radon"]["available"] is True, report["tools"]
    assert report["tools"]["vulture"]["available"] is True, report["tools"]
    assert report["complexity"]["max_cc"] >= 2
    assert report["complexity"]["top"]
    top = report["complexity"]["top"][0]
    assert top["file"] == "mod.py"
    assert {"file", "function", "cc"} <= set(top)

    dead = report["dead_code"]
    assert any(item["symbol"] == "os" for item in dead), dead

    summary_ev = report["evidence"][0]
    assert summary_ev["provenance"]["analysis"] == "metrics_scan"
    assert summary_ev["level"] == "observation"
    assert report["degraded"] is True  # jscpd 不可用（无本地 node_modules）


def test_all_tools_missing_fail_open(tmp_path: Path) -> None:
    root = _py_project(tmp_path)

    def fake_runner(cmd, timeout, cwd=None):
        return 127, "", "not found"

    report = scan_metrics(str(root), runner=fake_runner)
    assert report["degraded"] is True
    assert report["complexity"]["max_cc"] == 0.0
    assert report["known_gaps"]
    assert report["tools"]["radon"]["available"] is False


def test_jscpd_injection(tmp_path: Path) -> None:
    root = tmp_path / "ts"
    root.mkdir()
    (root / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")

    def fake_runner(cmd, timeout, cwd=None):
        if cmd[0] == "fake-jscpd":
            out_dir = Path(cmd[cmd.index("--output") + 1])
            (out_dir / "jscpd-report.json").write_text(
                json.dumps(
                    {
                        "statistics": {
                            "total": {
                                "percentage": 7.5,
                                "duplicates": 12,
                                "duplicatedLines": 48,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return 0, "", ""
        return 127, "", "not found"

    report = scan_metrics(str(root), runner=fake_runner, jscpd_cmd=["fake-jscpd"])
    assert report["tools"]["jscpd"]["available"] is True
    assert report["duplication"] == {"ratio": 0.075, "blocks": 12, "lines": 48}


def test_snapshot_metrics_section(tmp_path: Path) -> None:
    import dsh_nodes

    root = _py_project(tmp_path)
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(root), "force": True})
    snapshot_id = analyzed["result"]["snapshot_id"]
    out = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "metrics"})
    assert out["ok"] is True, out
    result = out["result"]
    assert result["section"] == "metrics"
    assert result["report"]["tools"]["radon"]["available"] is True
    assert result["total"] == len(result["report"]["complexity"]["top"])
    assert result["items"]


def test_radon_single_tool_switch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REA_ADAPTER_RADON", "0")
    report = scan_metrics(str(_py_project(tmp_path)))
    assert report["tools"]["radon"]["available"] is False
    assert "REA_ADAPTER_RADON" in report["tools"]["radon"]["reason"]


def test_disable_switch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REA_ADAPTER_METRICS", "0")
    report = scan_metrics(str(_py_project(tmp_path)))
    assert report["degraded"] is True
    assert any("禁用" in gap for gap in report["known_gaps"])
