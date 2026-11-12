"""SPEC-33-F T-F04 规则扫描适配测试（RED）：ruff 真实输出 + ESLint 注入解析 + 缺失降级。"""

from __future__ import annotations

import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters.rules_adapter import scan_rules  # noqa: E402


def test_ruff_findings_normalized_to_evidence(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    report = scan_rules(str(tmp_path))

    assert report["section"] == "rules"
    assert report["tools"]["ruff"]["available"] is True
    assert report["summary"]["total"] >= 1
    finding = next((f for f in report["findings"] if f["rule"] == "F401"), None)
    assert finding is not None, report["findings"]
    assert finding["file"] == "bad.py"
    assert finding["line"] == 1
    assert finding["engine"] == "ruff"

    rule_evidence = [
        e for e in report["evidence"] if (e.get("provenance") or {}).get("rule") == "F401"
    ]
    assert rule_evidence
    assert rule_evidence[0]["provenance"]["line"] == 1
    assert rule_evidence[0]["level"] == "observation"


def test_eslint_injection_parsed(tmp_path: Path) -> None:
    payload = (
        '[{"filePath": "'
        + str(tmp_path / "a.ts")
        + '", "messages": [{"ruleId": "no-unused-vars", "severity": 2, '
        '"message": "unused", "line": 3, "column": 5}], '
        '"errorCount": 1, "warningCount": 0}]'
    )
    fake = tmp_path / "fake_eslint.py"
    fake.write_text(f"print({payload!r})\nraise SystemExit(1)\n", encoding="utf-8")

    report = scan_rules(str(tmp_path), include_python=False, eslint_cmd=[sys.executable, str(fake)])
    assert report["tools"]["eslint"]["available"] is True
    finding = report["findings"][0]
    assert finding["engine"] == "eslint"
    assert finding["rule"] == "no-unused-vars"
    assert finding["line"] == 3
    assert finding["file"] == "a.ts"


def test_eslint_missing_is_degraded(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    report = scan_rules(str(tmp_path))
    assert report["tools"]["eslint"]["available"] is False
    assert report["degraded"] is True


def test_missing_target_fail_open() -> None:
    report = scan_rules("/nonexistent/rea-rules-target")
    assert report["section"] == "rules"
    assert report["degraded"] is True
    assert report["findings"] == []
    assert report["known_gaps"]


def test_snapshot_rules_section(tmp_path: Path) -> None:
    import dsh_nodes

    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(tmp_path), "force": True})
    snapshot_id = analyzed["result"]["snapshot_id"]
    out = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "rules"})
    assert out["ok"] is True, out
    result = out["result"]
    assert result["section"] == "rules"
    assert result["report"]["summary"]["total"] >= 1
    assert result["items"]


def test_ruff_single_tool_switch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REA_ADAPTER_RUFF", "0")
    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    report = scan_rules(str(tmp_path))
    assert report["tools"]["ruff"]["available"] is False
    assert "REA_ADAPTER_RUFF" in report["tools"]["ruff"]["reason"]


def test_disable_switch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REA_ADAPTER_RULES", "0")
    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    report = scan_rules(str(tmp_path))
    assert report["degraded"] is True
    assert any("disabled" in gap or "禁用" in gap for gap in report["known_gaps"])
