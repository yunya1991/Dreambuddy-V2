"""Subprocess runner for the OKX CLI with audit, timeout, and fail-closed guards."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .catalog import validate_argv
from .config import VenueConfig
from .errors import (
    CliAuthError,
    CliInvalidResponse,
    CliNonZeroExit,
    CliNotInstalled,
    CliRateLimit,
    CliTimeout,
    CredentialsMissing,
    LiveReadForbidden,
    LiveTradingForbidden,
)

_SECRET_FLAGS = {"--api-key", "--secret", "--secret-key", "--passphrase"}
_MAX_ERROR_CHARS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_argv(argv: Sequence[str]) -> List[str]:
    redacted: List[str] = []
    skip = False
    for token in argv:
        if skip:
            redacted.append("***")
            skip = False
            continue
        redacted.append(token)
        if token in _SECRET_FLAGS:
            skip = True
    return redacted


def _classify_nonzero(returncode: int, stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if "requires api credentials" in text or "configure okx_api_key" in text:
        return "venue_credentials_missing"
    if "401" in text or "session expired" in text or "auth login" in text:
        return "cli_auth_error"
    if "429" in text or "rate limit" in text or "too many requests" in text:
        return "cli_rate_limit"
    return "cli_nonzero_exit"


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class CliRunner:
    """Run allowlisted OKX CLI commands.

    ``run`` is injectable for tests; production uses ``subprocess.run``.
    """

    def __init__(
        self,
        config: VenueConfig,
        *,
        audit: Optional[AuditLogger] = None,
        run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> None:
        self.config = config
        self.audit = audit or AuditLogger(config.audit_path)
        self._run = run or subprocess.run

    def run(
        self,
        argv: Sequence[str],
        *,
        operation: str,
        write: bool = False,
        expect_json: bool = True,
        timeout_s: Optional[float] = None,
        trace_id: Optional[str] = None,
    ) -> Any:
        argv = list(argv)
        trace_id = trace_id or uuid.uuid4().hex
        validate_argv(argv, write=write)

        if write and not self.config.write_allowed:
            raise LiveTradingForbidden(
                "live trading is not exposed by 51; live orders stay on the 11 bypass",
                details={"operation": operation, "profile": self.config.profile},
            )
        if not write and not self.config.read_allowed:
            raise LiveReadForbidden(
                "live read is disabled; set OKX_VENUE_ALLOW_LIVE_READ=1 to enable",
                details={"operation": operation, "profile": self.config.profile},
            )

        full_argv = [self.config.cli_path, *self.config.mode_flags(), *argv]
        if expect_json and "--json" not in full_argv:
            full_argv.append("--json")

        started = time.perf_counter()
        run_kwargs: Dict[str, Any] = {}
        if self.config.env_credentials:
            # 用户 venue：凭证仅注入本次子进程，绝不写入 ~/.okx 或日志。
            run_kwargs["env"] = {**os.environ, **self.config.env_credentials}
        try:
            completed = self._run(
                full_argv,
                capture_output=True,
                text=True,
                timeout=timeout_s or self.config.timeout_s,
                shell=False,
                check=False,
                **run_kwargs,
            )
        except FileNotFoundError as exc:
            self._audit(
                operation=operation,
                argv=full_argv,
                trace_id=trace_id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                ok=False,
                error_code="cli_not_installed",
            )
            raise CliNotInstalled(
                f"OKX CLI not found: {self.config.cli_path!r}",
                details={"operation": operation, "trace_id": trace_id},
            ) from exc
        except subprocess.TimeoutExpired as exc:
            self._audit(
                operation=operation,
                argv=full_argv,
                trace_id=trace_id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                ok=False,
                error_code="cli_timeout",
            )
            raise CliTimeout(
                f"OKX CLI timed out after {timeout_s or self.config.timeout_s}s",
                details={"operation": operation, "trace_id": trace_id},
            ) from exc

        duration_ms = (time.perf_counter() - started) * 1000.0
        if completed.returncode != 0:
            error_code = _classify_nonzero(
                completed.returncode, completed.stdout or "", completed.stderr or ""
            )
            self._audit(
                operation=operation,
                argv=full_argv,
                trace_id=trace_id,
                duration_ms=duration_ms,
                ok=False,
                error_code=error_code,
                returncode=completed.returncode,
                stderr=(completed.stderr or "")[:_MAX_ERROR_CHARS],
            )
            exc_cls = {
                "cli_auth_error": CliAuthError,
                "cli_rate_limit": CliRateLimit,
                "venue_credentials_missing": CredentialsMissing,
            }.get(error_code, CliNonZeroExit)
            raise exc_cls(
                f"OKX CLI failed ({error_code}, rc={completed.returncode}): "
                f"{(completed.stderr or completed.stdout or '').strip()[:_MAX_ERROR_CHARS]}",
                details={
                    "operation": operation,
                    "trace_id": trace_id,
                    "returncode": completed.returncode,
                },
            )

        parsed: Any = None
        if expect_json:
            raw = (completed.stdout or "").strip()
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError as exc:
                self._audit(
                    operation=operation,
                    argv=full_argv,
                    trace_id=trace_id,
                    duration_ms=duration_ms,
                    ok=False,
                    error_code="cli_invalid_json",
                    returncode=completed.returncode,
                    stderr=raw[:_MAX_ERROR_CHARS],
                )
                raise CliInvalidResponse(
                    f"OKX CLI returned non-JSON output: {raw[:_MAX_ERROR_CHARS]!r}",
                    details={"operation": operation, "trace_id": trace_id},
                ) from exc

        self._audit(
            operation=operation,
            argv=full_argv,
            trace_id=trace_id,
            duration_ms=duration_ms,
            ok=True,
            error_code="",
            returncode=completed.returncode,
        )
        return parsed if expect_json else completed.stdout

    def _audit(
        self,
        *,
        operation: str,
        argv: Sequence[str],
        trace_id: str,
        duration_ms: float,
        ok: bool,
        error_code: str,
        returncode: Optional[int] = None,
        stderr: Optional[str] = None,
    ) -> None:
        record: Dict[str, Any] = {
            "ts": _now_iso(),
            "trace_id": trace_id,
            "operation": operation,
            "argv": redact_argv(argv),
            "profile": self.config.profile,
            "mode": self.config.mode,
            "ok": ok,
            "error_code": error_code,
            "duration_ms": round(duration_ms, 3),
        }
        if returncode is not None:
            record["returncode"] = returncode
        if stderr:
            record["stderr"] = stderr
        self.audit.write(record)
