"""SPEC-33-F T-F09：pyright/Jedi 与 tsserver 的限时、可降级适配环。

外部工具均通过无 shell 子进程调用。tsserver 按项目懒启动并复用，
Jedi 在隔离 Python 子进程中执行，主进程不 import 任何语言分析包。
"""

from __future__ import annotations

import atexit
import json
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from core.evidence import Evidence

STARTUP_TIMEOUT = 20
REQUEST_TIMEOUT = 5
MAX_REFERENCES = 50
MAX_DIAGNOSTIC_FILES = 50
_SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".venv", "venv"}
_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
Runner = Callable[..., "tuple[int, str, str]"]


def _run(
    cmd: Sequence[str], timeout: int, cwd: str | None = None, input_text: str | None = None
) -> tuple[int, str, str]:
    env = {"PATH": os.environ.get("PATH", os.defpath), "NO_COLOR": "1"}
    try:
        proc = subprocess.run(
            list(cmd),
            input=input_text,
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


def _root(target: str) -> Path:
    requested = Path(target).expanduser().resolve()
    return requested if requested.is_dir() else requested.parent


def _language(target: str) -> str:
    path = Path(target)
    if path.suffix == ".py":
        return "python"
    if path.suffix in _TS_EXTS:
        return "typescript"
    root = _root(target)
    if (root / "tsconfig.json").is_file() or (root / "package.json").is_file():
        return "typescript"
    return "python" if any(root.rglob("*.py")) else "typescript"


def _files(root: Path, suffixes: tuple[str, ...], *, limit: int | None = None) -> list[Path]:
    found: list[Path] = []
    if root.is_file():
        return [root] if root.suffix in suffixes else []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(suffixes):
                found.append(Path(dirpath) / name)
                if limit is not None and len(found) >= limit:
                    return found
    return found


def _rel(path: str | Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return Path(path).as_posix()


def _query(raw: Any) -> tuple[str, str, str]:
    text = str(raw).strip().replace("\\", "/")
    file_hint = ""
    if "::" in text:
        file_hint, text = text.rsplit("::", 1)
    symbol = text.rsplit(".", 1)[-1].strip()
    return str(raw), file_hint, symbol


def _location(path: str | Path, root: Path, line: int, column: int, symbol: str, kind: str):
    return {
        "file": _rel(path, root),
        "line": int(line or 0),
        "column": int(column or 0),
        "kind": kind,
        "symbol": symbol,
    }


_JEDI_WORKER = r"""
import itertools
import json
import sys
from pathlib import Path

import jedi

payload = json.load(sys.stdin)
root = Path(payload["root"]).resolve()
project = jedi.Project(str(root))
result = {}
for item in payload["queries"]:
    raw, file_hint, symbol = item["raw"], item["file_hint"], item["symbol"]
    definitions = []
    references = []
    seen = set()
    try:
        names = itertools.islice(project.search(symbol, all_scopes=True), 10)
        for name in names:
            if not name.module_path or name.line is None or name.column is None:
                continue
            module_path = Path(name.module_path).resolve()
            try:
                rel = module_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if file_hint and not (rel == file_hint or rel.endswith("/" + file_hint)):
                continue
            definition = {
                "file": rel,
                "line": name.line,
                "column": name.column + 1,
                "kind": "definition",
                "symbol": symbol,
            }
            key = (rel, name.line, name.column + 1, "definition")
            if key not in seen:
                seen.add(key)
                definitions.append(definition)
            script = jedi.Script(path=str(module_path), project=project)
            for reference in script.get_references(name.line, name.column):
                if not reference.module_path or reference.line is None or reference.column is None:
                    continue
                ref_path = Path(reference.module_path).resolve()
                try:
                    ref_rel = ref_path.relative_to(root).as_posix()
                except ValueError:
                    continue
                ref_key = (ref_rel, reference.line, reference.column + 1)
                if ref_key == key[:3]:
                    continue
                location = {
                    "file": ref_rel,
                    "line": reference.line,
                    "column": reference.column + 1,
                    "kind": "reference",
                    "symbol": symbol,
                }
                dedup = (*ref_key, "reference")
                if dedup not in seen:
                    seen.add(dedup)
                    references.append(location)
    except Exception as exc:
        result[raw] = {"error": f"{type(exc).__name__}: {exc}", "definitions": [], "references": []}
        continue
    result[raw] = {
        "definitions": definitions[:50],
        "references": references[:50],
    }
print(json.dumps(result, ensure_ascii=False))
"""


def _degraded_symbols(root: Path, language: str, refs: Sequence[Any], reason: str, tool: str):
    locations = {str(ref): [] for ref in refs}
    return {
        "section": "symbols",
        "target": str(root),
        "language": language,
        "locations": locations,
        "definitions": {key: [] for key in locations},
        "references": {key: [] for key in locations},
        "tools": {tool: {"status": "degraded", "reason": reason}},
        "degraded": True,
        "known_gaps": [reason],
        "evidence": [
            Evidence(
                result=f"符号引用降级: {reason}",
                level="unknown",
                provenance={"analysis": "symbol_references", "target": str(root), "tool": tool},
                confidence=0.0,
                known_gaps=[reason],
            ).to_dict()
        ],
    }


def _symbol_report(root: Path, language: str, refs: Sequence[Any], tool: str):
    return {
        "section": "symbols",
        "target": str(root),
        "language": language,
        "locations": {str(ref): [] for ref in refs},
        "definitions": {str(ref): [] for ref in refs},
        "references": {str(ref): [] for ref in refs},
        "tools": {tool: {"status": "ok"}},
        "degraded": False,
        "known_gaps": [],
    }


def _finalize_symbols(report: dict[str, Any]) -> dict[str, Any]:
    for raw in report["locations"]:
        definitions = report["definitions"].get(raw) or []
        references = report["references"].get(raw) or []
        combined = {
            (x["file"], x["line"], x["column"], x["kind"]): x for x in definitions + references
        }
        report["locations"][raw] = [combined[key] for key in sorted(combined)][:MAX_REFERENCES]
        if not combined:
            report["known_gaps"].append(f"符号未定位: {raw}")
    gaps = list(report["known_gaps"])
    report["evidence"] = [
        Evidence(
            result=(
                f"符号引用: {sum(bool(v) for v in report['locations'].values())}/"
                f"{len(report['locations'])} 个引用命中"
            ),
            level="unknown" if report["degraded"] else "observation",
            provenance={
                "analysis": "symbol_references",
                "target": report["target"],
                "language": report["language"],
                "tools": report["tools"],
            },
            confidence=0.0 if report["degraded"] else 0.95,
            known_gaps=gaps,
        ).to_dict()
    ]
    return report


def _jedi_symbols(root: Path, refs: Sequence[Any], runner: Runner):
    code, out, err = runner(
        [sys.executable, "-c", "import jedi; print(jedi.__version__)"],
        STARTUP_TIMEOUT,
        str(root),
    )
    if code != 0:
        return _degraded_symbols(
            root, "python", refs, (err or out or "jedi unavailable")[:300], "jedi"
        )
    report = _symbol_report(root, "python", refs, "jedi")
    report["tools"]["jedi"]["version"] = out.strip().splitlines()[0] if out.strip() else "unknown"
    queries = [
        {"raw": raw, "file_hint": file_hint, "symbol": symbol}
        for raw, file_hint, symbol in map(_query, refs)
        if symbol
    ]
    code, out, err = runner(
        [sys.executable, "-c", _JEDI_WORKER],
        REQUEST_TIMEOUT,
        str(root),
        json.dumps({"root": str(root), "queries": queries}, ensure_ascii=False),
    )
    if code != 0:
        return _degraded_symbols(
            root, "python", refs, (err or out or "jedi lookup failed")[:300], "jedi"
        )
    try:
        payload = json.loads(out or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Jedi output must be an object")
    except (json.JSONDecodeError, ValueError) as exc:
        return _degraded_symbols(root, "python", refs, f"Jedi output parse error: {exc}", "jedi")
    for raw in report["locations"]:
        item = payload.get(raw) or {}
        report["definitions"][raw] = item.get("definitions") or []
        report["references"][raw] = item.get("references") or []
        if item.get("error"):
            report["known_gaps"].append(f"{raw}: {item['error']}")
    return _finalize_symbols(report)


class TSServerPool:
    """每项目一个懒启动 tsserver；顺序请求，空闲 60 秒回收。"""

    idle_seconds = 60
    _entries: dict[tuple[str, str], "TSServerPool"] = {}
    _entries_lock = threading.Lock()

    def __init__(self, command: Sequence[str], cwd: str):
        self.command = list(command)
        self.cwd = cwd
        self.process: subprocess.Popen[bytes] | None = None
        self.seq = 0
        self.last_used = 0.0
        self._lock = threading.RLock()

    @classmethod
    def for_project(cls, command: Sequence[str], cwd: str) -> "TSServerPool":
        key = (str(Path(cwd).resolve()), "\0".join(command))
        with cls._entries_lock:
            entry = cls._entries.get(key)
            if entry is None:
                entry = cls(command, cwd)
                cls._entries[key] = entry
            return entry

    @classmethod
    def close_all(cls) -> None:
        with cls._entries_lock:
            entries = list(cls._entries.values())
            cls._entries.clear()
        for entry in entries:
            entry.close()

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.cwd,
            bufsize=0,
            shell=False,
            env={"PATH": os.environ.get("PATH", os.defpath), "NO_COLOR": "1"},
        )
        self.last_used = time.monotonic()
        self._roundtrip("configure", {"hostInfo": "33-rea"}, STARTUP_TIMEOUT)

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=1)
        except Exception:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _read_message(self, timeout: int) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        deadline = time.monotonic() + timeout
        headers: dict[str, str] = {}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"tsserver request timeout after {timeout}s")
            ready, _, _ = select.select([stream], [], [], remaining)
            if not ready:
                raise TimeoutError(f"tsserver request timeout after {timeout}s")
            line = stream.readline()
            if not line:
                raise RuntimeError("tsserver closed stdout")
            if line in (b"\r\n", b"\n"):
                break
            key, _, value = line.decode("ascii", errors="replace").partition(":")
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        if length <= 0:
            raise ValueError("tsserver response missing Content-Length")
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], max(0, remaining))
        if not ready:
            raise TimeoutError(f"tsserver body timeout after {timeout}s")
        body = stream.read(length)
        if len(body) != length:
            raise RuntimeError("truncated tsserver response")
        return json.loads(body.decode("utf-8"))

    def _roundtrip(self, command: str, arguments: dict[str, Any], timeout: int) -> Any:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("tsserver is not running")
        assert self.process.stdin is not None
        self.seq += 1
        request_seq = self.seq
        payload = json.dumps(
            {"seq": request_seq, "type": "request", "command": command, "arguments": arguments}
        ).encode("utf-8")
        self.process.stdin.write(payload + b"\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            message = self._read_message(max(0.001, deadline - time.monotonic()))
            if message.get("type") != "response" or message.get("request_seq") != request_seq:
                continue
            if not message.get("success"):
                raise RuntimeError(str(message.get("message") or f"{command} failed"))
            return message.get("body")

    def request(self, command: str, arguments: dict[str, Any]) -> Any:
        with self._lock:
            if time.monotonic() - self.last_used > self.idle_seconds:
                self.close()
            self.start()
            body = self._roundtrip(command, arguments, REQUEST_TIMEOUT)
            self.last_used = time.monotonic()
            return body

    def open_file(self, path: Path) -> None:
        if self.process is None or self.process.poll() is not None:
            self.start()
        assert self.process.stdin is not None
        self.seq += 1
        payload = json.dumps(
            {
                "seq": self.seq,
                "type": "request",
                "command": "open",
                "arguments": {
                    "file": str(path.resolve()),
                    "fileContent": path.read_text(encoding="utf-8"),
                    "projectRootPath": self.cwd,
                },
            }
        ).encode("utf-8")
        self.process.stdin.write(payload + b"\n")
        self.process.stdin.flush()

    def references(self, path: Path, line: int, column: int) -> dict[str, Any]:
        with self._lock:
            self.start()
            self.open_file(path)
            return (
                self.request(
                    "references", {"file": str(path.resolve()), "line": line, "offset": column}
                )
                or {}
            )

    def diagnostics(self, path: Path) -> list[dict[str, Any]]:
        with self._lock:
            self.start()
            self.open_file(path)
            return self.request("semanticDiagnosticsSync", {"file": str(path.resolve())}) or []


atexit.register(TSServerPool.close_all)


def _tsserver_command(root: Path) -> list[str] | None:
    for base in (root, *root.parents):
        candidate = base / "node_modules" / ".bin" / "tsserver"
        if candidate.is_file():
            return [str(candidate), "--useInferredProjectPerProjectRoot"]
    executable = shutil.which("tsserver")
    return [executable, "--useInferredProjectPerProjectRoot"] if executable else None


def _ts_position(root: Path, raw: Any) -> tuple[Path, int, int, str] | None:
    _, file_hint, symbol = _query(raw)
    if not symbol:
        return None
    candidates: list[tuple[int, str, Path, int, int]] = []
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    declaration = re.compile(
        rf"\b(?:function|class|const|let|var|interface|type|enum)\s+{re.escape(symbol)}\b"
    )
    for path in _files(root, _TS_EXTS):
        rel = _rel(path, root)
        if file_hint and not (rel == file_hint or rel.endswith("/" + file_hint)):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                candidates.append(
                    (
                        0 if declaration.search(line) else 1,
                        rel,
                        path,
                        line_number,
                        match.start() + 1,
                    )
                )
    if not candidates:
        return None
    _, _, path, line, column = sorted(
        candidates, key=lambda item: (item[0], item[1], item[3], item[4])
    )[0]
    return path, line, column, symbol


def _ts_symbols(root: Path, refs: Sequence[Any]):
    command = _tsserver_command(root)
    if command is None:
        return _degraded_symbols(root, "typescript", refs, "tsserver unavailable", "tsserver")
    report = _symbol_report(root, "typescript", refs, "tsserver")
    try:
        client = TSServerPool.for_project(command, str(root))
        for raw in refs:
            position = _ts_position(root, raw)
            if position is None:
                continue
            path, line, column, symbol = position
            body = client.references(path, line, column)
            for item in body.get("refs") or []:
                start = item.get("start") or {}
                loc = _location(
                    item.get("file") or path,
                    root,
                    start.get("line") or item.get("line"),
                    start.get("offset") or item.get("offset"),
                    symbol,
                    "definition" if item.get("isDefinition") else "reference",
                )
                target = "definitions" if loc["kind"] == "definition" else "references"
                report[target][str(raw)].append(loc)
    except Exception as exc:
        return _degraded_symbols(root, "typescript", refs, f"tsserver: {exc}"[:300], "tsserver")
    return _finalize_symbols(report)


def inspect_symbols(
    target: str,
    refs: Sequence[Any],
    *,
    language: str | None = None,
    runner: Runner = _run,
) -> dict[str, Any]:
    """只用符号引用增强既有 target_refs/trace；不引入任何 LLM。"""
    root = _root(target)
    lang = language or _language(target)
    if os.getenv("REA_LSP_ENABLED", "1").strip() == "0":
        tool = "jedi" if lang == "python" else "tsserver"
        return _degraded_symbols(root, lang, refs, "REA_LSP_ENABLED=0", tool)
    if lang == "python":
        return _jedi_symbols(root, refs, runner)
    return _ts_symbols(root, refs)


def _parse_pyright(stdout: str, root: Path) -> list[dict[str, Any]]:
    payload = json.loads(stdout or "{}")
    diagnostics = payload.get("generalDiagnostics")
    if not isinstance(diagnostics, list):
        raise ValueError("pyright output missing generalDiagnostics")
    result = []
    for item in diagnostics:
        start = (item.get("range") or {}).get("start") or {}
        result.append(
            {
                "engine": "pyright",
                "file": _rel(item.get("file") or "", root),
                "line": int(start.get("line") or 0) + 1,
                "column": int(start.get("character") or 0) + 1,
                "severity": str(item.get("severity") or "warning"),
                "rule": str(item.get("rule") or ""),
                "message": str(item.get("message") or ""),
            }
        )
    return sorted(result, key=lambda x: (x["file"], x["line"], x["column"], x["rule"]))


def _pyright_command(root: Path) -> list[str] | None:
    for base in (root, *root.parents):
        candidate = base / "node_modules" / ".bin" / "pyright"
        if candidate.is_file():
            return [str(candidate)]
    executable = shutil.which("pyright")
    return [executable] if executable else None


def _diagnostic_report(root: Path, language: str):
    return {
        "section": "diagnostics",
        "target": str(root),
        "language": language,
        "diagnostics": [],
        "tools": {},
        "degraded": False,
        "known_gaps": [],
        "evidence": [],
    }


def scan_diagnostics(
    target: str, *, language: str | None = None, runner: Runner = _run
) -> dict[str, Any]:
    """pyright/tsserver 诊断归一为 Evidence；工具失败不阻断静态分析。"""
    root = _root(target)
    lang = language or _language(target)
    report = _diagnostic_report(root, lang)
    tool = "pyright" if lang == "python" else "tsserver"
    if os.getenv("REA_LSP_ENABLED", "1").strip() == "0":
        report["degraded"] = True
        report["known_gaps"].append("REA_LSP_ENABLED=0")
        report["tools"][tool] = {"status": "degraded", "reason": "disabled"}
    elif lang == "python":
        command = _pyright_command(root)
        if command is None:
            report["degraded"] = True
            report["known_gaps"].append("pyright unavailable")
            report["tools"][tool] = {"status": "degraded", "reason": "command not found"}
        else:
            code, out, err = runner([*command, "--version"], STARTUP_TIMEOUT, str(root))
            if code != 0:
                report["degraded"] = True
                report["known_gaps"].append((err or out or "pyright unavailable")[:300])
                report["tools"][tool] = {"status": "degraded", "reason": report["known_gaps"][-1]}
            else:
                code, out, err = runner(
                    [*command, "--outputjson", str(root)], REQUEST_TIMEOUT, str(root)
                )
                try:
                    if code not in (0, 1):
                        raise RuntimeError((err or out or f"exit code {code}")[:300])
                    report["diagnostics"] = _parse_pyright(out, root)
                    report["tools"][tool] = {"status": "ok", "exit_code": code}
                except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
                    report["degraded"] = True
                    report["known_gaps"].append(f"pyright: {exc}")
                    report["tools"][tool] = {"status": "degraded", "reason": str(exc)[:300]}
    else:
        command = _tsserver_command(root)
        if command is None:
            report["degraded"] = True
            report["known_gaps"].append("tsserver unavailable")
            report["tools"][tool] = {"status": "degraded", "reason": "command not found"}
        else:
            try:
                client = TSServerPool.for_project(command, str(root))
                files = _files(root, _TS_EXTS, limit=MAX_DIAGNOSTIC_FILES)
                for path in files:
                    for item in client.diagnostics(path):
                        start = item.get("start") or {}
                        report["diagnostics"].append(
                            {
                                "engine": "tsserver",
                                "file": _rel(path, root),
                                "line": int(start.get("line") or 0),
                                "column": int(start.get("offset") or 0),
                                "severity": str(item.get("category") or "warning"),
                                "rule": str(item.get("code") or ""),
                                "message": str(item.get("text") or ""),
                            }
                        )
                report["tools"][tool] = {"status": "ok", "files": len(files)}
                if len(files) == MAX_DIAGNOSTIC_FILES:
                    report["known_gaps"].append(f"诊断文件封顶 {MAX_DIAGNOSTIC_FILES}")
            except Exception as exc:
                report["degraded"] = True
                report["known_gaps"].append(f"tsserver: {exc}"[:300])
                report["tools"][tool] = {"status": "degraded", "reason": str(exc)[:300]}
    report["diagnostics"].sort(key=lambda x: (x["file"], x["line"], x["column"], x["rule"]))
    report["evidence"] = [
        Evidence(
            result=f"类型诊断: {len(report['diagnostics'])} 条",
            level="unknown" if report["degraded"] else "observation",
            provenance={
                "analysis": "type_diagnostics",
                "target": str(root),
                "language": lang,
                "tools": report["tools"],
                "diagnostics": len(report["diagnostics"]),
            },
            confidence=0.0 if report["degraded"] else 0.95,
            known_gaps=list(report["known_gaps"]),
        ).to_dict()
    ]
    return report
