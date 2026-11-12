"""SPEC-33-F T-F08：依赖清单、deptry/knip、OSV 与 CycloneDX SBOM。

外部工具只通过固定 argv 的限时子进程调用；失败时保留清单与 SBOM 并降级。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import quote

from core.dependency_audit import audit_dependencies
from core.evidence import Evidence

DEFAULT_TIMEOUT = 30
Runner = Callable[[Sequence[str], int, "str | None"], "tuple[int, str, str]"]


def _run(cmd: Sequence[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    """不转发凭据环境，只允许固定 argv 的无 shell 子进程。"""
    env = {"PATH": os.environ.get("PATH", os.defpath), "NO_COLOR": "1"}
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
            shell=False,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:
        return 125, "", str(exc)


def _parse_deptry(stdout: str) -> list[dict[str, Any]]:
    data = json.loads(stdout or "[]")
    if not isinstance(data, list):
        raise ValueError("deptry output must be a list")
    unused: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        error = item.get("error") or {}
        if error.get("code") != "DEP002":
            continue
        location = item.get("location") or {}
        unused.append(
            {
                "name": str(item.get("module") or ""),
                "tool": "deptry",
                "rule": "DEP002",
                "message": str(error.get("message") or ""),
                "file": str(location.get("file") or ""),
                "line": int(location.get("line") or 0),
            }
        )
    return [item for item in unused if item["name"]]


def _parse_knip(stdout: str) -> list[dict[str, Any]]:
    data = json.loads(stdout or "{}")
    if not isinstance(data, dict):
        raise ValueError("knip output must be an object")
    unused: list[dict[str, Any]] = []
    for key in ("dependencies", "devDependencies"):
        for item in data.get(key) or []:
            name = item.get("name") if isinstance(item, dict) else item
            if not name:
                continue
            unused.append(
                {
                    "name": str(name),
                    "tool": "knip",
                    "rule": (
                        "unused_devDependency" if key == "devDependencies" else "unused_dependency"
                    ),
                }
            )
    return unused


def _parse_osv(stdout: str) -> list[dict[str, Any]]:
    data = json.loads(stdout or "{}")
    if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
        raise ValueError("OSV output must contain a results list")
    vulnerabilities: list[dict[str, Any]] = []
    for result in data.get("results") or []:
        if not isinstance(result, dict):
            continue
        for entry in result.get("packages") or []:
            if not isinstance(entry, dict):
                continue
            package = entry.get("package") or {}
            for vulnerability in entry.get("vulnerabilities") or []:
                if not isinstance(vulnerability, dict):
                    continue
                vulnerabilities.append(
                    {
                        "id": str(vulnerability.get("id") or ""),
                        "aliases": sorted(
                            str(alias) for alias in vulnerability.get("aliases") or []
                        ),
                        "summary": str(vulnerability.get("summary") or ""),
                        "package": str(package.get("name") or ""),
                        "version": str(package.get("version") or ""),
                        "ecosystem": str(package.get("ecosystem") or ""),
                    }
                )
    unique = {
        (item["ecosystem"], item["package"], item["version"], item["id"]): item
        for item in vulnerabilities
        if item["id"]
    }
    return [unique[key] for key in sorted(unique)]


def _purl(ecosystem: str, name: str, version: str) -> str:
    prefix = "npm" if ecosystem == "npm" else "pypi"
    suffix = f"@{quote(version, safe='')}" if version else ""
    return f"pkg:{prefix}/{quote(name, safe='/')}{suffix}"


def _build_sbom(declared: list[dict[str, str]], root: Path) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for dep in sorted(declared, key=lambda item: (item["name"], item["source"])):
        ecosystem = "npm" if dep["source"].startswith("package.json") else "PyPI"
        name = dep["name"]
        version = dep.get("version") or ""
        key = (ecosystem, name, version)
        if key in seen:
            continue
        seen.add(key)
        purl = _purl(ecosystem, name, version)
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": name,
                "version": version,
                "purl": purl,
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": root.name}},
        "components": components,
    }


def scan_dependency_hygiene(target: str, *, runner: Runner = _run) -> dict[str, Any]:
    """归一未使用依赖与 CVE；任何工具失败都不阻断清单和 SBOM 输出。"""
    requested = Path(target).expanduser()
    root = requested if requested.is_dir() else requested.parent
    known_gaps: list[str] = []
    degraded = False
    try:
        audit = audit_dependencies(str(root))
    except Exception as exc:
        audit = {"declared": [], "manifests_found": [], "evidence": []}
        known_gaps.append(f"依赖清单解析失败: {exc}")
        degraded = True

    declared = audit.get("declared") or []
    manifests = audit.get("manifests_found") or []
    manifest_names = {Path(path).name for path in manifests}
    tools: dict[str, dict[str, Any]] = {}
    unused: list[dict[str, Any]] = []
    vulnerabilities: list[dict[str, Any]] = []

    def collect(name: str, cmd: list[str], parser: Callable[[str], Any]) -> Any | None:
        nonlocal degraded
        try:
            rc, stdout, stderr = runner(cmd, DEFAULT_TIMEOUT, str(root))
            if rc not in (0, 1):
                raise RuntimeError(stderr.strip()[:300] or f"exit code {rc}")
            parsed = parser(stdout)
        except Exception as exc:
            reason = str(exc)[:300]
            tools[name] = {"status": "degraded", "reason": reason}
            known_gaps.append(f"{name} 不可用: {reason}")
            degraded = True
            return None
        tools[name] = {"status": "ok", "exit_code": rc}
        return parsed

    if manifest_names.intersection({"pyproject.toml", "requirements.txt"}):
        parsed = collect("deptry", ["deptry", "--json-output", "."], _parse_deptry)
        if parsed is not None:
            unused.extend(parsed)
    if "package.json" in manifest_names:
        parsed = collect("knip", ["knip", "--reporter", "json", "--no-exit-code"], _parse_knip)
        if parsed is not None:
            unused.extend(parsed)

    if os.getenv("REA_OSV_ENABLED", "1").strip() == "0":
        tools["osv"] = {"status": "disabled", "reason": "REA_OSV_ENABLED=0"}
        known_gaps.append("OSV 已禁用，未执行联网漏洞扫描")
    elif manifests:
        parsed = collect(
            "osv",
            ["osv-scanner", "scan", "source", "--recursive", "--format", "json", "."],
            _parse_osv,
        )
        if parsed is not None:
            vulnerabilities.extend(parsed)

    unused = sorted(unused, key=lambda item: (item["name"], item["tool"], item["rule"]))
    cves = sorted(
        {
            identifier
            for item in vulnerabilities
            for identifier in [item["id"], *item["aliases"]]
            if identifier.startswith("CVE-")
        }
    )
    audit_evidence = [
        item.to_dict() if hasattr(item, "to_dict") else item for item in audit.get("evidence") or []
    ]
    summary = (
        f"依赖卫生: {len(declared)} 个声明依赖, {len(unused)} 个未使用依赖, "
        f"{len(vulnerabilities)} 条漏洞记录"
    )
    evidence = Evidence(
        result=summary,
        provenance={
            "analysis": "dependency_hygiene",
            "target": str(root),
            "manifests": sorted(manifest_names),
            "network": tools.get("osv", {}).get("status") == "ok",
        },
        known_gaps=known_gaps or ["未展开传递依赖；SBOM 仅覆盖可直接解析的声明依赖"],
        level="observation" if not degraded else "unknown",
    ).to_dict()
    return {
        "section": "dependency_hygiene",
        "target": str(root),
        "summary": summary,
        "declared": declared,
        "manifests_found": manifests,
        "unused_dependencies": unused,
        "vulnerabilities": vulnerabilities,
        "cves": cves,
        "sbom": _build_sbom(declared, root),
        "tools": tools,
        "degraded": degraded,
        "evidence": [evidence, *audit_evidence],
        "known_gaps": known_gaps,
    }
