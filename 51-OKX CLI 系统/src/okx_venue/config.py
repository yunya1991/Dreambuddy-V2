"""Venue configuration and demo/live isolation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .errors import VenueConfigError

_MODULE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = _MODULE_ROOT / "runtime" / "audit" / "venue_calls.jsonl"

_LIVE_TOKENS = ("live", "prod", "real", "main")
_DEMO_TOKENS = ("demo", "paper", "test", "sim")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _looks_live(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _LIVE_TOKENS)


def _looks_demo(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _DEMO_TOKENS)


@dataclass(frozen=True)
class VenueConfig:
    """Runtime configuration for the OKX CLI adapter.

    Defaults are deliberately demo-only. Live writes are rejected by the
    runner regardless of any environment variable.
    """

    cli_path: str = "okx"
    profile: str = "demo"
    mode: str = "demo"
    auth: str = "api_key"
    timeout_s: float = 30.0
    audit_path: Path = field(default=DEFAULT_AUDIT_PATH)
    allow_live_read: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_path", Path(self.audit_path))
        self.validate()

    @classmethod
    def from_env(cls) -> "VenueConfig":
        timeout_raw = os.getenv("OKX_VENUE_TIMEOUT_S", "30")
        try:
            timeout_s = float(timeout_raw)
        except ValueError as exc:
            raise VenueConfigError(
                f"OKX_VENUE_TIMEOUT_S must be numeric, got {timeout_raw!r}"
            ) from exc
        return cls(
            cli_path=os.getenv("OKX_VENUE_CLI", "okx").strip() or "okx",
            profile=os.getenv("OKX_VENUE_PROFILE", "demo").strip() or "demo",
            mode=os.getenv("OKX_VENUE_MODE", "demo").strip().lower(),
            auth=os.getenv("OKX_VENUE_AUTH", "api_key").strip().lower(),
            timeout_s=timeout_s,
            audit_path=Path(
                os.getenv("OKX_VENUE_AUDIT_PATH", str(DEFAULT_AUDIT_PATH))
            ),
            allow_live_read=_env_bool("OKX_VENUE_ALLOW_LIVE_READ", False),
        )

    def validate(self) -> None:
        if self.mode not in {"demo", "live"}:
            raise VenueConfigError(
                f"OKX_VENUE_MODE must be demo|live, got {self.mode!r}"
            )
        if self.auth not in {"api_key", "oauth"}:
            raise VenueConfigError(
                f"OKX_VENUE_AUTH must be api_key|oauth, got {self.auth!r}"
            )
        if self.timeout_s <= 0:
            raise VenueConfigError("OKX_VENUE_TIMEOUT_S must be > 0")
        if not self.cli_path:
            raise VenueConfigError("OKX_VENUE_CLI must not be empty")
        if self.auth == "api_key" and not self.profile:
            raise VenueConfigError("OKX_VENUE_PROFILE is required for api_key auth")
        if self.mode == "demo" and _looks_live(self.profile):
            raise VenueConfigError(
                f"profile {self.profile!r} looks live but OKX_VENUE_MODE=demo"
            )
        if self.mode == "live" and _looks_demo(self.profile):
            raise VenueConfigError(
                f"profile {self.profile!r} looks demo but OKX_VENUE_MODE=live"
            )

    @property
    def read_allowed(self) -> bool:
        return self.mode == "demo" or self.allow_live_read

    @property
    def write_allowed(self) -> bool:
        return self.mode == "demo"

    def mode_flags(self) -> List[str]:
        """Profile/mode flags injected before the subcommand."""
        if self.auth == "api_key":
            return ["--profile", self.profile]
        if self.mode == "demo":
            return ["--demo"]
        return []

    def describe(self) -> dict:
        return {
            "cli_path": self.cli_path,
            "profile": self.profile,
            "mode": self.mode,
            "auth": self.auth,
            "read_allowed": self.read_allowed,
            "write_allowed": self.write_allowed,
        }