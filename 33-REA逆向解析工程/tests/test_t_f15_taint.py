"""SPEC-33-F T-F15：污点分析外挂（≥3 类 sink，SARIF 汇入）。

验收：
  - 至少识别 command_exec / sql_exec / unsafe_deserialize 三类 sink（另含 xss）。
  - 同行 sanitizer 命中时不计入。
  - Semgrep 不可用或未配置本地规则 → FAIL-OPEN（degraded=true，不抛异常）。
  - `section=sarif` 汇入污点 findings（ruleId 前缀 taint/）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
from adapters.taint_adapter import scan_taint  # noqa: E402

PY_SINKS = """
import os, pickle, subprocess

def run(cmd, uid, payload):
    os.system(cmd)
    cursor.execute(f"SELECT * FROM users WHERE id={uid}")
    return pickle.loads(payload)

def safe(cmd):
    subprocess.run(cmd, shell=True)  # shlex.quote(cmd)
"""

TSX_SINK = """
export function Raw({html}) {
  return <div dangerouslySetInnerHTML={{__html: html}} />;
}
"""


def _write_fixture(root: Path) -> None:
    (root / "service.py").write_text(PY_SINKS, encoding="utf-8")
    (root / "Raw.tsx").write_text(TSX_SINK, encoding="utf-8")


def test_scan_detects_three_sink_classes(tmp_path):
    _write_fixture(tmp_path)
    report = scan_taint(str(tmp_path))
    assert report["section"] == "taint"
    assert report["degraded"] is True  # 本机无 semgrep → FAIL-OPEN
    assert report["known_gaps"]
    classes = set(report["summary"]["by_sink"])
    assert {"command_exec", "sql_exec", "unsafe_deserialize"} <= classes
    assert "xss" in classes


def test_sanitized_line_excluded(tmp_path):
    _write_fixture(tmp_path)
    report = scan_taint(str(tmp_path))
    command_lines = [
        item["line"] for item in report["findings"] if item["sink_class"] == "command_exec"
    ]
    # 只有 os.system 命中；带 shlex.quote 的 subprocess shell=True 被排除
    assert len(command_lines) == 1


def test_disabled_env_short_circuits(tmp_path, monkeypatch):
    _write_fixture(tmp_path)
    monkeypatch.setenv("REA_TAINT_ENABLED", "0")
    report = scan_taint(str(tmp_path))
    assert report["findings"] == []
    assert report["degraded"] is True
    assert any("禁用" in gap for gap in report["known_gaps"])


def test_missing_target_fails_open():
    report = scan_taint("/nonexistent/rea-taint-probe")
    assert report["findings"] == []
    assert report["degraded"] is True


def test_snapshot_section_taint_and_sarif_merge(tmp_path, monkeypatch):
    _write_fixture(tmp_path)
    snapshot_id = "snap-test-taint"
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snapshot_id}.json").write_text(
        json.dumps({"target": str(tmp_path), "evidence": [], "raw": {"modules": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", tmp_path / "snapshots")

    taint = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "taint", "target": str(tmp_path)}
    )
    assert taint["ok"] is True
    assert taint["result"]["total"] >= 3
    assert taint["result"]["report"]["degraded"] is True

    sarif = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "sarif", "target": str(tmp_path)}
    )
    assert sarif["ok"] is True
    rule_ids = [item["ruleId"] for item in sarif["result"]["items"]]
    assert any(rule_id.startswith("taint/") for rule_id in rule_ids)
