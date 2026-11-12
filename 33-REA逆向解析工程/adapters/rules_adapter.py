"""规则扫描适配层（SPEC-33-F §2.6 / T-F04）。

硬性边界（SPEC-F §2.1）：只以子进程方式调用成熟工具，不在主进程 import 其包；
工具缺失 / 超时 / 输出不可解析时 FAIL-OPEN：`degraded=true` 且不抛异常。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_TIMEOUT = 20
MAX_FINDINGS = 200
MAX_EVIDENCE = 50
_SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".venv", "venv"}


def _iter_files(root: Path, suffixes: tuple[str, ...]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def _run(cmd: Sequence[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:  # pragma: no cover - 环境级异常
        return 125, "", str(exc)


def _rel(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def _enabled(env_name: str) -> bool:
    return os.getenv(env_name, "1").strip() != "0"


def _finding(
    engine: str,
    path: str,
    root: Path,
    line: int,
    column: int,
    rule: str,
    message: str,
    severity: str,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "file": _rel(path, root),
        "line": int(line or 0),
        "column": int(column or 0),
        "rule": rule,
        "severity": severity,
        "message": message,
    }


def _parse_ruff(stdout: str, root: Path) -> list[dict[str, Any]]:
    data = json.loads(stdout or "[]")
    findings = []
    for item in data:
        loc = item.get("location") or {}
        findings.append(
            _finding(
                "ruff",
                str(item.get("filename") or ""),
                root,
                loc.get("row", 0),
                loc.get("column", 0),
                str(item.get("code") or ""),
                str(item.get("message") or ""),
                "notify",
            )
        )
    return findings


def _parse_eslint(stdout: str, root: Path) -> list[dict[str, Any]]:
    data = json.loads(stdout or "[]")
    findings = []
    for file_result in data:
        file_path = str(file_result.get("filePath") or "")
        for msg in file_result.get("messages") or []:
            severity = "error" if int(msg.get("severity") or 1) >= 2 else "notify"
            findings.append(
                _finding(
                    "eslint",
                    file_path,
                    root,
                    msg.get("line", 0),
                    msg.get("column", 0),
                    str(msg.get("ruleId") or "parse-error"),
                    str(msg.get("message") or ""),
                    severity,
                )
            )
    return findings


def _resolve_eslint_cmd(root: Path, override: Sequence[str] | None) -> list[str] | None:
    if override:
        return list(override)
    for base in (root, *root.parents):
        candidate = base / "node_modules" / ".bin" / "eslint"
        if candidate.is_file():
            return [str(candidate)]
    return None


def scan_rules(
    target: str,
    *,
    include_python: bool = True,
    include_ts: bool = True,
    eslint_cmd: Sequence[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """对 target 运行 ruff（Python）与 ESLint（TS），归一为统一 Evidence。"""
    root = Path(target).expanduser()
    tools: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, Any]] = []
    known_gaps: list[str] = []

    if os.getenv("REA_ADAPTER_RULES", "1").strip() == "0":
        return {
            "section": "rules",
            "tools": {},
            "findings": [],
            "summary": {"total": 0, "by_engine": {}, "by_rule": {}},
            "degraded": True,
            "evidence": [],
            "known_gaps": ["REA_ADAPTER_RULES=0，规则扫描已禁用"],
        }

    if not root.exists():
        return {
            "section": "rules",
            "tools": {},
            "findings": [],
            "summary": {"total": 0, "by_engine": {}, "by_rule": {}},
            "degraded": True,
            "evidence": [],
            "known_gaps": [f"目标不存在: {target}"],
        }

    if include_python and any(_iter_files(root, (".py",))):
        if not _enabled("REA_ADAPTER_RUFF"):
            tools["ruff"] = {"available": False, "reason": "disabled by REA_ADAPTER_RUFF=0"}
        else:
            code, out, err = _run([sys.executable, "-m", "ruff", "--version"], timeout=timeout)
            if code != 0:
                tools["ruff"] = {
                    "available": False,
                    "reason": (err or out or "ruff not found").strip()[:200],
                }
            else:
                version = (out or "").strip().splitlines()[0] if out.strip() else ""
                code, out, err = _run(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "check",
                        "--output-format=json",
                        "--quiet",
                        str(root),
                    ],
                    timeout=timeout,
                )
                # ruff 有告警时 exit=1，属正常结果；只有输出不可解析才算失败
                try:
                    engine_findings = _parse_ruff(out, root)
                    findings.extend(engine_findings)
                    tools["ruff"] = {
                        "available": True,
                        "version": version,
                        "findings": len(engine_findings),
                    }
                except (json.JSONDecodeError, TypeError) as exc:
                    tools["ruff"] = {"available": False, "reason": f"output parse error: {exc}"}

    if include_ts:
        cmd = None if not _enabled("REA_ADAPTER_ESLINT") else _resolve_eslint_cmd(root, eslint_cmd)
        if not _enabled("REA_ADAPTER_ESLINT"):
            tools["eslint"] = {"available": False, "reason": "disabled by REA_ADAPTER_ESLINT=0"}
        elif cmd is None:
            tools["eslint"] = {"available": False, "reason": "local eslint not installed"}
        else:
            code, out, err = _run([*cmd, "-f", "json", str(root)], timeout=timeout, cwd=str(root))
            try:
                engine_findings = _parse_eslint(out, root)
                findings.extend(engine_findings)
                tools["eslint"] = {"available": code in (0, 1), "findings": len(engine_findings)}
            except (json.JSONDecodeError, TypeError) as exc:
                tools["eslint"] = {"available": False, "reason": f"output parse error: {exc}"}

    findings.sort(key=lambda f: (f["file"], f["line"], f["column"], f["rule"]))
    total = len(findings)
    shown = findings[:MAX_FINDINGS]
    if total > MAX_FINDINGS:
        known_gaps.append(f"findings 超过上限，仅保留前 {MAX_FINDINGS}/{total} 条")
    by_engine: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for item in shown:
        by_engine[item["engine"]] = by_engine.get(item["engine"], 0) + 1
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1

    degraded = any(not info.get("available") for info in tools.values()) or not tools
    evidence: list[dict[str, Any]] = [
        {
            "result": f"规则扫描: total={total}, by_engine={by_engine}",
            "level": "observation",
            "provenance": {
                "analysis": "rules_scan",
                "target": str(root.resolve()),
                "tools": tools,
                "total": total,
                "truncated": total > MAX_FINDINGS,
            },
            "confidence": 0.95,
            "known_gaps": list(known_gaps),
        }
    ]
    for item in shown[:MAX_EVIDENCE]:
        evidence.append(
            {
                "result": (
                    f"[{item['engine']}] {item['rule']} {item['file']}:{item['line']}:{item['column']}"
                    f" {item['message']}"
                ),
                "level": "observation",
                "provenance": {
                    "analysis": "rules_scan",
                    "engine": item["engine"],
                    "file": item["file"],
                    "line": item["line"],
                    "column": item["column"],
                    "rule": item["rule"],
                    "severity": item["severity"],
                },
                "confidence": 0.95,
                "known_gaps": [],
            }
        )
    if total > MAX_EVIDENCE:
        known_gaps.append(f"evidence 只保留前 {MAX_EVIDENCE}/{total} 条告警")

    return {
        "section": "rules",
        "target": str(root.resolve()),
        "tools": tools,
        "findings": shown,
        "summary": {"total": total, "by_engine": by_engine, "by_rule": by_rule},
        "degraded": degraded,
        "evidence": evidence,
        "known_gaps": known_gaps,
    }
