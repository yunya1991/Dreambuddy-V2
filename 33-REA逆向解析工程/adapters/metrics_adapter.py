"""度量适配层（SPEC-33-F §2.4 / T-F05/T-F11）：采集、阈值门禁与历史趋势。

硬性边界（SPEC-F §2.1）：只通过子进程调用外部工具，import 其包属于违规；
任一工具缺失 → `degraded=true` 并在 `tools.<name>.reason` 说明，绝不抛异常。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

import yaml

DEFAULT_TIMEOUT = 30
TOP_LIMIT = 20
MAX_EVIDENCE = 10
VULTURE_MIN_CONFIDENCE = 80
JSCPD_MIN_TOKENS = 50
_SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".venv", "venv"}

Runner = Callable[[Sequence[str], int, "str | None"], "tuple[int, str, str]"]

_LIZARD_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)@(\d+)-(\d+)@(.+?)\s*$")
_VULTURE_ROW = re.compile(r"^(.+?):(\d+):\s*(.+?)\s*\((\d+)% confidence\)\s*$")


def _run(cmd: Sequence[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:  # pragma: no cover
        return 125, "", str(exc)


def _has_files(root: Path, suffixes: tuple[str, ...]) -> bool:
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        if any(name.endswith(suffixes) for name in filenames):
            return True
    return False


def _rel(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def _enabled(env_name: str) -> bool:
    return os.getenv(env_name, "1").strip() != "0"


def _parse_radon(stdout: str, root: Path) -> tuple[list[dict[str, Any]], dict[str, float]]:
    data = json.loads(stdout or "{}")
    blocks: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for file_path, items in data.items():
            for item in items or []:
                blocks.append(
                    {
                        "file": _rel(str(file_path), root),
                        "function": str(item.get("name") or ""),
                        "cc": int(item.get("complexity") or 0),
                        "line": int(item.get("lineno") or 0),
                        "rank": str(item.get("rank") or ""),
                    }
                )
    if not blocks:
        return [], {"max_cc": 0.0, "avg_cc": 0.0}
    values = [b["cc"] for b in blocks]
    return blocks, {"max_cc": float(max(values)), "avg_cc": round(sum(values) / len(values), 2)}


def _parse_lizard(stdout: str, root: Path) -> list[dict[str, Any]]:
    functions: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        match = _LIZARD_ROW.match(line)
        if not match:
            continue
        nloc, ccn, _tokens, params, length, name, start, _end, location = match.groups()
        functions.append(
            {
                "file": _rel(location.strip(), root),
                "function": name,
                "cc": int(ccn),
                "length": int(length),
                "params": int(params),
                "nloc": int(nloc),
                "line": int(start),
            }
        )
    return functions


def _parse_vulture(stdout: str, root: Path) -> list[dict[str, Any]]:
    dead: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        match = _VULTURE_ROW.match(line.strip())
        if not match:
            continue
        path, lineno, message, confidence = match.groups()
        kind = "unknown"
        symbol = message
        symbol_match = re.search(r"unused (\w+) '([^']+)'", message)
        if symbol_match:
            kind = f"unused_{symbol_match.group(1)}"
            symbol = symbol_match.group(2)
        dead.append(
            {
                "file": _rel(path, root),
                "line": int(lineno),
                "symbol": symbol,
                "kind": kind,
                "confidence": int(confidence),
            }
        )
    return dead


def _find_local_bin(root: Path, name: str) -> str | None:
    for base in (root, *root.parents):
        candidate = base / "node_modules" / ".bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


_METRIC_NAMES = ("max_cc", "avg_cc", "dead_code", "duplication_ratio")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_values(report: dict[str, Any]) -> dict[str, float | None]:
    complexity = report.get("complexity") or {}
    dead_code = report.get("dead_code")
    duplication = report.get("duplication") or {}
    return {
        "max_cc": _number(complexity.get("max_cc")),
        "avg_cc": _number(complexity.get("avg_cc")),
        "dead_code": float(len(dead_code)) if isinstance(dead_code, list) else None,
        "duplication_ratio": _number(duplication.get("ratio")),
    }


def apply_metrics_policy(
    report: dict[str, Any],
    *,
    config_path: str | None = None,
    history_path: str | None = None,
) -> dict[str, Any]:
    """可选应用 metrics 阈值与历史趋势；未指定输入时原报告逐字段不变。"""
    if not config_path and not history_path:
        return report

    result = dict(report)
    result["evidence"] = list(report.get("evidence") or [])
    result["known_gaps"] = list(report.get("known_gaps") or [])
    values = _metric_values(report)
    policy_degraded = False

    if config_path:
        try:
            loaded = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("config must be a mapping")
            thresholds = loaded.get("thresholds") or {}
            if not isinstance(thresholds, dict):
                raise ValueError("thresholds must be a mapping")
        except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
            result["gates"] = {"status": "unknown", "violations": []}
            result["known_gaps"].append(f"metrics 配置不可用: {config_path}: {exc}")
            policy_degraded = True
        else:
            violations: list[dict[str, Any]] = []
            gate_unknown = False
            for metric in _METRIC_NAMES:
                if metric not in thresholds:
                    continue
                try:
                    threshold = float(thresholds[metric])
                except (TypeError, ValueError):
                    result["known_gaps"].append(f"metrics 阈值无效: {metric}")
                    gate_unknown = True
                    continue
                value = values.get(metric)
                if value is None:
                    result["known_gaps"].append(f"metrics 无可用数据，未执行门禁: {metric}")
                    gate_unknown = True
                    continue
                if value <= threshold:
                    continue
                violation = {"metric": metric, "value": value, "threshold": threshold}
                violations.append(violation)
                result["evidence"].append(
                    {
                        "result": (f"度量超阈值: {metric} value={value} threshold={threshold}"),
                        "level": "derivation",
                        "provenance": {"analysis": "metrics_gate", **violation},
                        "confidence": 1.0,
                        "known_gaps": [],
                    }
                )
            status = "unknown" if gate_unknown else ("fail" if violations else "pass")
            result["gates"] = {"status": status, "violations": violations}
            policy_degraded = policy_degraded or gate_unknown

    if history_path:
        try:
            loaded_history = json.loads(Path(history_path).read_text(encoding="utf-8"))
            if not isinstance(loaded_history, dict):
                raise ValueError("history must be a mapping")
            previous = loaded_history.get("report", loaded_history)
            if not isinstance(previous, dict):
                raise ValueError("history.report must be a mapping")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            result["trend"] = {}
            result["known_gaps"].append(f"metrics 历史快照不可用: {history_path}: {exc}")
            policy_degraded = True
        else:
            previous_values = _metric_values(previous)
            trend: dict[str, dict[str, Any]] = {}
            for metric in _METRIC_NAMES:
                current_value = values.get(metric)
                previous_value = previous_values.get(metric)
                if current_value is None or previous_value is None:
                    continue
                delta = round(current_value - previous_value, 4)
                trend[metric] = {
                    "current": current_value,
                    "previous": previous_value,
                    "delta": delta,
                    "direction": "up" if delta > 0 else ("down" if delta < 0 else "unchanged"),
                }
            result["trend"] = trend

    if policy_degraded:
        result["degraded"] = True
    return result


def scan_metrics(
    target: str,
    *,
    runner: Runner = _run,
    timeout: int = DEFAULT_TIMEOUT,
    jscpd_cmd: Sequence[str] | None = None,
    config_path: str | None = None,
    history_path: str | None = None,
) -> dict[str, Any]:
    """采集复杂度 / 死代码 / 重复代码，可选附加阈值门禁与历史趋势。"""
    root = Path(target).expanduser()
    tools: dict[str, dict[str, Any]] = {}
    known_gaps: list[str] = []
    complexity: dict[str, Any] = {"max_cc": 0.0, "avg_cc": 0.0, "top": []}
    functions: list[dict[str, Any]] = []
    dead_code: list[dict[str, Any]] = []
    duplication: dict[str, Any] | None = None

    if os.getenv("REA_ADAPTER_METRICS", "1").strip() == "0":
        return {
            "section": "metrics",
            "target": str(root),
            "tools": {},
            "complexity": complexity,
            "functions": [],
            "dead_code": [],
            "duplication": None,
            "degraded": True,
            "evidence": [],
            "known_gaps": ["REA_ADAPTER_METRICS=0，度量采集已禁用"],
        }

    if not root.exists():
        return {
            "section": "metrics",
            "target": str(root),
            "tools": {},
            "complexity": complexity,
            "functions": [],
            "dead_code": [],
            "duplication": None,
            "degraded": True,
            "evidence": [],
            "known_gaps": [f"目标不存在: {target}"],
        }

    has_python = _has_files(root, (".py",))
    has_ts = _has_files(root, (".ts", ".tsx", ".js", ".jsx"))

    # radon：Python 圈复杂度
    if has_python and not _enabled("REA_ADAPTER_RADON"):
        tools["radon"] = {"available": False, "reason": "disabled by REA_ADAPTER_RADON=0"}
    elif has_python:
        code, out, err = runner([sys.executable, "-m", "radon", "--version"], timeout, None)
        if code != 0:
            tools["radon"] = {
                "available": False,
                "reason": (err or out).strip()[:200] or "not found",
            }
        else:
            version = (out or "").strip().splitlines()[0] if out.strip() else ""
            code, out, err = runner(
                [sys.executable, "-m", "radon", "cc", "-s", "-j", str(root)], timeout, None
            )
            try:
                blocks, stats = _parse_radon(out, root)
                blocks.sort(key=lambda b: (-b["cc"], b["file"], b["line"]))
                complexity.update(stats)
                complexity["top"] = [
                    {"file": b["file"], "function": b["function"], "cc": b["cc"], "line": b["line"]}
                    for b in blocks[:TOP_LIMIT]
                ]
                tools["radon"] = {"available": True, "version": version, "blocks": len(blocks)}
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                tools["radon"] = {"available": False, "reason": f"output parse error: {exc}"}

    # lizard：函数级复杂度 / 长度 / 参数个数（Python 与 TS/JS 各跑一次）
    lizard_rows: list[dict[str, Any]] = []
    lizard_available = False
    lizard_reason = "no supported source files"
    if not _enabled("REA_ADAPTER_LIZARD"):
        tools["lizard"] = {"available": False, "reason": "disabled by REA_ADAPTER_LIZARD=0"}
    for language in (("python", has_python), ("javascript", has_ts)):
        name, enabled = language
        if not enabled or not _enabled("REA_ADAPTER_LIZARD"):
            continue
        code, out, err = runner([sys.executable, "-m", "lizard", "--version"], timeout, None)
        if code != 0:
            lizard_reason = (err or out).strip()[:200] or "not found"
            continue
        code, out, err = runner(
            [sys.executable, "-m", "lizard", "-l", name, "-w", str(root)], timeout, None
        )
        if code == 0:
            lizard_available = True
            lizard_rows.extend(_parse_lizard(out, root))
    if lizard_available:
        lizard_rows.sort(key=lambda f: (-f["cc"], f["file"], f["line"]))
        functions = lizard_rows[:TOP_LIMIT]
        tools["lizard"] = {"available": True, "functions": len(lizard_rows)}
    elif (has_python or has_ts) and "lizard" not in tools:
        tools["lizard"] = {"available": False, "reason": lizard_reason}

    # vulture：Python 死代码（置信度 ≥80）
    if has_python and not _enabled("REA_ADAPTER_VULTURE"):
        tools["vulture"] = {"available": False, "reason": "disabled by REA_ADAPTER_VULTURE=0"}
    elif has_python:
        code, out, err = runner([sys.executable, "-m", "vulture", "--version"], timeout, None)
        if code != 0:
            tools["vulture"] = {
                "available": False,
                "reason": (err or out).strip()[:200] or "not found",
            }
        else:
            code, out, err = runner(
                [
                    sys.executable,
                    "-m",
                    "vulture",
                    str(root),
                    "--min-confidence",
                    str(VULTURE_MIN_CONFIDENCE),
                ],
                timeout,
                None,
            )
            dead_code = sorted(
                (d for d in _parse_vulture(out, root) if d["confidence"] >= VULTURE_MIN_CONFIDENCE),
                key=lambda d: (-d["confidence"], d["file"], d["line"]),
            )
            tools["vulture"] = {"available": True, "findings": len(dead_code)}
    else:
        tools["vulture"] = {"available": False, "reason": "no python files"}

    # jscpd：TS/JS 重复代码（只认本地 node_modules，避免 npx 联网）
    jscpd_bin = None
    if jscpd_cmd:
        jscpd_bin = list(jscpd_cmd)
    elif has_ts:
        found = _find_local_bin(root, "jscpd")
        jscpd_bin = [found] if found else None
    if jscpd_bin and _enabled("REA_ADAPTER_JSCPD"):
        with tempfile.TemporaryDirectory(prefix="rea-jscpd-") as out_dir:
            code, out, err = runner(
                [
                    *jscpd_bin,
                    "--reporters",
                    "json",
                    "--output",
                    out_dir,
                    "--min-tokens",
                    str(JSCPD_MIN_TOKENS),
                    "--silent",
                    str(root),
                ],
                timeout,
                None,
            )
            report_path = Path(out_dir) / "jscpd-report.json"
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                stats = (report.get("statistics") or {}).get("total") or {}
                duplication = {
                    "ratio": round(float(stats.get("percentage") or 0.0) / 100.0, 4),
                    "blocks": int(stats.get("duplicates") or 0),
                    "lines": int(stats.get("duplicatedLines") or 0),
                }
                tools["jscpd"] = {"available": True, "blocks": duplication["blocks"]}
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                tools["jscpd"] = {"available": False, "reason": f"report parse error: {exc}"}
    else:
        if jscpd_bin:
            reason = "disabled by REA_ADAPTER_JSCPD=0"
        else:
            reason = "jscpd not installed" if has_ts else "no ts/js files"
        tools["jscpd"] = {"available": False, "reason": reason}

    if complexity["top"]:
        known_gaps.append("complexity.top 只保留 CC 最高的前 20 个函数")
    if not any(info.get("available") for info in tools.values()):
        known_gaps.append("所有度量工具均不可用，metrics section 为空（FAIL-OPEN）")

    degraded = any(not info.get("available") for info in tools.values()) or not tools
    evidence: list[dict[str, Any]] = [
        {
            "result": (
                f"度量采集: max_cc={complexity['max_cc']}, avg_cc={complexity['avg_cc']}, "
                f"dead_code={len(dead_code)}, duplication={(duplication or {}).get('ratio', 0.0)}"
            ),
            "level": "observation",
            "provenance": {
                "analysis": "metrics_scan",
                "target": str(root.resolve()),
                "tools": tools,
                "complexity": {"max_cc": complexity["max_cc"], "avg_cc": complexity["avg_cc"]},
            },
            "confidence": 0.9,
            "known_gaps": list(known_gaps),
        }
    ]
    for block in complexity["top"][:MAX_EVIDENCE]:
        evidence.append(
            {
                "result": f"高复杂度: {block['file']}:{block['line']} {block['function']} cc={block['cc']}",
                "level": "observation",
                "provenance": {
                    "analysis": "metrics_scan",
                    "engine": "radon",
                    "file": block["file"],
                    "line": block["line"],
                    "function": block["function"],
                    "cc": block["cc"],
                },
                "confidence": 0.9,
                "known_gaps": [],
            }
        )

    report = {
        "section": "metrics",
        "target": str(root.resolve()),
        "tools": tools,
        "complexity": complexity,
        "functions": functions,
        "dead_code": dead_code,
        "duplication": duplication,
        "degraded": degraded,
        "evidence": evidence,
        "known_gaps": known_gaps,
    }
    return apply_metrics_policy(report, config_path=config_path, history_path=history_path)
