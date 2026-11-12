"""污点分析适配层（SPEC-33-F T-F15）。

设计边界（SPEC-F §2.1）：
  - 外部引擎（Semgrep）只以子进程方式调用；未安装或未配置本地规则时
    FAIL-OPEN，回退到内置 sink 规则扫描并标 `degraded=true`。
  - 内核零网络：Semgrep 仅接受本地规则路径（`REA_TAINT_SEMGREP_CONFIG`），
    不调用远程 registry。
  - 只做静态行级 source→sink 关联，不做跨文件数据流。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

DEFAULT_TIMEOUT = 20
MAX_FINDINGS = 200
MAX_EVIDENCE = 20
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
}

# 至少三类 sink（command / sql / deserialize），另含前端 xss
SINK_RULES: dict[str, list[re.Pattern[str]]] = {
    "command_exec": [
        re.compile(r"\bos\.system\s*\("),
        re.compile(r"\bos\.popen\s*\("),
        re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
    ],
    "sql_exec": [
        re.compile(r"\.execute\s*\(\s*f[\"']"),
        re.compile(r"\.execute\s*\(\s*[^)\"']*\+"),
        re.compile(r"\.execute\s*\(\s*[\"'][^\"']*%[sd][^\"']*[\"']\s*%"),
    ],
    "unsafe_deserialize": [
        re.compile(r"\bpickle\.loads?\s*\("),
        re.compile(r"\byaml\.load\s*\((?![^)]*Loader)"),
        re.compile(r"\bmarshal\.loads\s*\("),
        re.compile(r"(?<![\w.])eval\s*\("),
        re.compile(r"(?<![\w.])exec\s*\("),
    ],
    "xss": [re.compile(r"dangerouslySetInnerHTML")],
}

SOURCE_MARKERS = re.compile(
    r"request\.|req\.|params\.|query\.|body\.|input\(|argv|os\.environ|form\[", re.IGNORECASE
)
SANITIZER_MARKERS = re.compile(
    r"shlex\.quote|html\.escape|escape\(|sanitize|quote\(|\?\s*,|%s\s*,", re.IGNORECASE
)
_MAX_REGEX_FILES = 2000


def _iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if not name.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                continue
            count += 1
            if count > _MAX_REGEX_FILES:
                return
            yield Path(dirpath) / name


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _run(cmd: list[str], timeout: int, cwd: str) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:  # pragma: no cover - 环境级异常
        return 125, "", str(exc)


def _scan_semgrep(root: Path, config: str, timeout: int) -> dict[str, Any]:
    cmd = ["semgrep", "--config", config, "--sarif", "--quiet", "."]
    code, stdout, stderr = _run(cmd, timeout, str(root))
    if code != 0:
        return {"findings": [], "error": f"semgrep exit={code}: {stderr.strip()[:200]}"}
    try:
        payload = json.loads(stdout or "{}")
    except ValueError as exc:
        return {"findings": [], "error": f"semgrep SARIF 不可解析: {exc}"}

    findings = []
    for run in payload.get("runs") or []:
        for item in run.get("results") or []:
            location = (item.get("locations") or [{}])[0].get("physicalLocation") or {}
            findings.append(
                {
                    "engine": "semgrep",
                    "sink_class": str(
                        (item.get("properties") or {}).get("sink_class") or "semgrep"
                    ),
                    "file": str((location.get("artifactLocation") or {}).get("uri") or ""),
                    "line": int((location.get("region") or {}).get("startLine") or 0),
                    "column": int((location.get("region") or {}).get("startColumn") or 0),
                    "rule": str(item.get("ruleId") or ""),
                    "severity": str(item.get("level") or "warning"),
                    "message": str((item.get("message") or {}).get("text") or ""),
                    "confidence": 0.8,
                }
            )
    return {"findings": findings, "error": ""}


def _scan_builtin(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in _iter_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            for sink_class, patterns in SINK_RULES.items():
                if not any(pattern.search(line) for pattern in patterns):
                    continue
                if SANITIZER_MARKERS.search(line):
                    continue
                has_source = bool(SOURCE_MARKERS.search(line))
                findings.append(
                    {
                        "engine": "builtin",
                        "sink_class": sink_class,
                        "file": _rel(path, root),
                        "line": lineno,
                        "column": line.find("(") + 1 if "(" in line else 1,
                        "rule": f"taint/{sink_class}",
                        "severity": "error" if has_source else "notify",
                        "message": (
                            f"{sink_class}："
                            + (
                                "检测到 source→sink 同行数据流"
                                if has_source
                                else "检测到高危 sink 调用"
                            )
                        ),
                        "confidence": 0.75 if has_source else 0.45,
                    }
                )
                if len(findings) >= MAX_FINDINGS:
                    return findings
    return findings


def scan_taint(target: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """扫描 target 的 source→sink 污点候选，返回统一 Evidence 报告。"""
    root = Path(target).expanduser()
    if not root.is_dir():
        return {
            "section": "taint",
            "engine": "none",
            "findings": [],
            "summary": {"total": 0, "by_sink": {}},
            "degraded": True,
            "evidence": [],
            "known_gaps": [f"目标不存在或不是目录: {target}"],
        }

    if os.getenv("REA_TAINT_ENABLED", "1").strip() == "0":
        return {
            "section": "taint",
            "engine": "none",
            "findings": [],
            "summary": {"total": 0, "by_sink": {}},
            "degraded": True,
            "evidence": [],
            "known_gaps": ["REA_TAINT_ENABLED=0，污点分析已禁用"],
        }

    engine = "builtin"
    known_gaps: list[str] = []
    findings: list[dict[str, Any]] = []
    config = os.getenv("REA_TAINT_SEMGREP_CONFIG", "").strip()
    if shutil.which("semgrep") and config:
        external = _scan_semgrep(root, config, timeout)
        findings = external["findings"]
        if external["error"]:
            known_gaps.append(f"semgrep 降级: {external['error']}")
        elif findings:
            engine = "semgrep"
    else:
        known_gaps.append(
            "semgrep 未安装或未配置本地规则，使用内置 sink 扫描（行级，无跨文件数据流）"
        )

    if engine != "semgrep":
        findings = _scan_builtin(root)

    by_sink: dict[str, int] = {}
    for item in findings:
        by_sink[item["sink_class"]] = by_sink.get(item["sink_class"], 0) + 1

    evidence = []
    if findings:
        evidence.append(
            {
                "result": f"污点候选: {len(findings)} 条（{', '.join(f'{k}={v}' for k, v in sorted(by_sink.items()))}）",
                "level": "observation",
                "provenance": {
                    "target": str(root),
                    "analysis": "taint",
                    "engine": engine,
                    "sink_classes": sorted(by_sink),
                },
                "confidence": 0.7 if engine == "builtin" else 0.85,
                "known_gaps": [],
            }
        )
    return {
        "section": "taint",
        "engine": engine,
        "findings": findings[:MAX_FINDINGS],
        "summary": {"total": len(findings), "by_sink": by_sink},
        "degraded": engine != "semgrep",
        "evidence": evidence[:MAX_EVIDENCE],
        "known_gaps": known_gaps,
    }
