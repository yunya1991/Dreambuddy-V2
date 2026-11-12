"""SPEC-33-F T-F08：依赖卫生、OSV 与 CycloneDX SBOM（RED）。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from adapters import dependency_hygiene_adapter as adapter  # noqa: E402


def _manifest(root: Path, name: str, content: str) -> None:
    root.mkdir(exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")


def test_deptry_osv_vulnerabilities_and_cyclonedx_sbom(tmp_path: Path) -> None:
    _manifest(tmp_path, "requirements.txt", "requests==2.31.0\nflask==2.0.0\n")
    commands: list[tuple[list[str], int, str]] = []
    deptry_output = [
        {
            "error": {
                "code": "DEP002",
                "message": "'flask' defined as a dependency but not used",
            },
            "module": "flask",
            "location": {"file": "requirements.txt", "line": 2, "column": 1},
        }
    ]
    osv_output = {
        "results": [
            {
                "packages": [
                    {
                        "package": {
                            "name": "requests",
                            "version": "2.31.0",
                            "ecosystem": "PyPI",
                        },
                        "vulnerabilities": [
                            {
                                "id": "GHSA-j8r2-6x86-q33q",
                                "aliases": ["CVE-2024-35195"],
                                "summary": "Requests certificate verification bypass",
                            }
                        ],
                    }
                ]
            }
        ]
    }

    def runner(cmd, timeout: int, cwd: str | None = None):
        commands.append((list(cmd), timeout, str(cwd)))
        if cmd[0] == "deptry":
            return 1, json.dumps(deptry_output), ""
        if cmd[0] == "osv-scanner":
            return 1, json.dumps(osv_output), ""
        raise AssertionError(f"unexpected command: {cmd}")

    report = adapter.scan_dependency_hygiene(str(tmp_path), runner=runner)

    assert report["section"] == "dependency_hygiene"
    assert report["degraded"] is False
    assert [item["name"] for item in report["unused_dependencies"]] == ["flask"]
    assert report["unused_dependencies"][0]["rule"] == "DEP002"
    assert report["cves"] == ["CVE-2024-35195"]
    assert report["vulnerabilities"][0]["package"] == "requests"
    assert report["vulnerabilities"][0]["id"] == "GHSA-j8r2-6x86-q33q"
    assert report["sbom"]["bomFormat"] == "CycloneDX"
    assert report["sbom"]["specVersion"] == "1.5"
    components = {item["name"]: item for item in report["sbom"]["components"]}
    assert components["requests"]["purl"] == "pkg:pypi/requests@2.31.0"
    assert components["flask"]["version"] == "2.0.0"
    assert [entry[0][0] for entry in commands] == ["deptry", "osv-scanner"]
    assert all(entry[0][-1] == "." for entry in commands)
    assert all(0 < entry[1] <= 30 for entry in commands)
    assert all(entry[2] == str(tmp_path) for entry in commands)
    assert report["evidence"][0]["provenance"]["analysis"] == "dependency_hygiene"


def test_knip_unused_dependencies_and_osv_opt_out(tmp_path: Path, monkeypatch) -> None:
    _manifest(
        tmp_path,
        "package.json",
        json.dumps({"dependencies": {"lodash": "4.17.21"}, "devDependencies": {}}),
    )
    monkeypatch.setenv("REA_OSV_ENABLED", "0")
    commands: list[list[str]] = []

    def runner(cmd, timeout: int, cwd: str | None = None):
        commands.append(list(cmd))
        assert cmd[0] == "knip"
        return 0, json.dumps({"dependencies": [{"name": "lodash", "files": []}]}), ""

    report = adapter.scan_dependency_hygiene(str(tmp_path), runner=runner)

    assert commands == [["knip", "--reporter", "json", "--no-exit-code"]]
    assert report["tools"]["osv"]["status"] == "disabled"
    assert report["degraded"] is False
    assert [item["name"] for item in report["unused_dependencies"]] == ["lodash"]
    assert report["unused_dependencies"][0]["tool"] == "knip"
    assert report["vulnerabilities"] == []
    assert report["sbom"]["components"][0]["purl"] == "pkg:npm/lodash@4.17.21"


def test_tool_failures_are_degraded_without_losing_sbom(tmp_path: Path) -> None:
    _manifest(tmp_path, "requirements.txt", "requests==2.31.0\n")

    def runner(cmd, timeout: int, cwd: str | None = None):
        if cmd[0] == "deptry":
            return 127, "", "command not found"
        raise subprocess.TimeoutExpired(cmd, timeout)

    report = adapter.scan_dependency_hygiene(str(tmp_path), runner=runner)

    assert report["degraded"] is True
    assert report["tools"]["deptry"]["status"] == "degraded"
    assert report["tools"]["osv"]["status"] == "degraded"
    assert len(report["known_gaps"]) >= 2
    assert report["unused_dependencies"] == []
    assert report["vulnerabilities"] == []
    assert report["sbom"]["components"][0]["name"] == "requests"


def test_subprocess_runner_has_no_shell_and_strips_credentials(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-be-forwarded")
    monkeypatch.setattr(adapter.subprocess, "run", fake_run)

    assert adapter._run(["osv-scanner", "scan", "source", "."], 7, "/tmp") == (0, "[]", "")
    assert captured["cmd"] == ["osv-scanner", "scan", "source", "."]
    assert captured["shell"] is False
    assert captured["timeout"] == 7
    assert captured["cwd"] == "/tmp"
    assert captured["env"] == {"PATH": "/usr/bin:/bin", "NO_COLOR": "1"}


def test_snapshot_dependency_hygiene_section(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    (snapshot_dir / "deps.json").write_text(
        json.dumps({"snapshot_id": "deps", "target": str(tmp_path), "raw": {}}),
        encoding="utf-8",
    )
    report = {
        "section": "dependency_hygiene",
        "unused_dependencies": [{"name": "flask", "tool": "deptry"}],
        "vulnerabilities": [],
        "cves": [],
        "sbom": {"bomFormat": "CycloneDX", "components": []},
    }
    monkeypatch.setattr(adapter, "scan_dependency_hygiene", lambda target: report)

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "deps", "section": "dependency_hygiene", "limit": 1}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert result["section"] == "dependency_hygiene"
    assert result["items"] == report["unused_dependencies"]
    assert result["total"] == 1
    assert result["next_cursor"] is None
    assert result["report"]["sbom"]["bomFormat"] == "CycloneDX"
