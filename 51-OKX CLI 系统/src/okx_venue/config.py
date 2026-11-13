"""Venue configuration and demo/live isolation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .errors import VenueConfigError

_MODULE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = _MODULE_ROOT / "runtime" / "audit" / "venue_calls.jsonl"
# 用户 venue（前端/产品专用）使用独立 profile 与独立审计文件，与后端自链路天然隔离。
DEFAULT_USER_PROFILE = "dreambuddy-user"
USER_AUDIT_PATH = _MODULE_ROOT / "runtime" / "audit" / "user_venue_calls.jsonl"

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
    # 默认关闭，保持 D2「live 写恒拒绝」；仅用户 venue 的解锁闸门可显式打开。
    allow_live_write: bool = False
    # profile: 凭证来自 `okx config` 的命名 profile；env: 凭证由用户 venue 注入子进程环境变量，
    # 不落 ~/.okx/config.toml，与后端 22 链路完全隔离。
    credential_source: str = "profile"
    env_credentials: Optional[Dict[str, str]] = field(default=None, repr=False)

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
            audit_path=Path(os.getenv("OKX_VENUE_AUDIT_PATH", str(DEFAULT_AUDIT_PATH))),
            allow_live_read=_env_bool("OKX_VENUE_ALLOW_LIVE_READ", False),
            allow_live_write=_env_bool("OKX_VENUE_ALLOW_LIVE_WRITE", False),
        )

    @classmethod
    def for_user(cls) -> "VenueConfig":
        """用户 venue：前端/产品专用，独立 profile + 独立审计，默认 demo。

        后端自链路（11 旁路 / trade-exec MCP）不读取本配置，二者天然隔离。
        live 写必须另经 LiveGate 解锁后由调用方显式放开 allow_live_write。
        """
        mode = os.getenv("OKX_VENUE_USER_MODE", "demo").strip().lower() or "demo"
        return cls(
            cli_path=os.getenv("OKX_VENUE_CLI", "okx").strip() or "okx",
            profile=os.getenv("OKX_VENUE_USER_PROFILE", DEFAULT_USER_PROFILE).strip()
            or DEFAULT_USER_PROFILE,
            mode=mode,
            auth=os.getenv("OKX_VENUE_USER_AUTH", "api_key").strip().lower() or "api_key",
            timeout_s=float(os.getenv("OKX_VENUE_TIMEOUT_S", "30")),
            audit_path=Path(os.getenv("OKX_VENUE_USER_AUDIT_PATH", str(USER_AUDIT_PATH))),
            allow_live_read=mode == "live",
            allow_live_write=False,
        )

    def validate(self) -> None:
        if self.mode not in {"demo", "live"}:
            raise VenueConfigError(f"OKX_VENUE_MODE must be demo|live, got {self.mode!r}")
        if self.auth not in {"api_key", "oauth"}:
            raise VenueConfigError(f"OKX_VENUE_AUTH must be api_key|oauth, got {self.auth!r}")
        if self.timeout_s <= 0:
            raise VenueConfigError("OKX_VENUE_TIMEOUT_S must be > 0")
        if not self.cli_path:
            raise VenueConfigError("OKX_VENUE_CLI must not be empty")
        if self.auth == "api_key" and not self.profile:
            raise VenueConfigError("OKX_VENUE_PROFILE is required for api_key auth")
        if self.mode == "demo" and _looks_live(self.profile):
            raise VenueConfigError(f"profile {self.profile!r} looks live but OKX_VENUE_MODE=demo")
        if self.mode == "live" and _looks_demo(self.profile):
            raise VenueConfigError(f"profile {self.profile!r} looks demo but OKX_VENUE_MODE=live")
        if self.allow_live_write and self.mode != "live":
            raise VenueConfigError("allow_live_write only makes sense with OKX_VENUE_MODE=live")
        if self.credential_source not in {"profile", "env"}:
            raise VenueConfigError(
                f"credential_source must be profile|env, got {self.credential_source!r}"
            )
        if self.credential_source == "env":
            missing = [
                key
                for key in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE")
                if not (self.env_credentials or {}).get(key)
            ]
            if missing:
                raise VenueConfigError(f"env credentials missing: {', '.join(missing)}")

    @property
    def read_allowed(self) -> bool:
        return self.mode == "demo" or self.allow_live_read

    @property
    def write_allowed(self) -> bool:
        # demo 恒可写；live 写仅当调用方显式解锁（默认 False）。
        return self.mode == "demo" or (self.mode == "live" and self.allow_live_write)

    def mode_flags(self) -> List[str]:
        """Profile/mode flags injected before the subcommand.

        模式一律显式下传（``--demo`` / ``--live``），不依赖 profile 文件里的
        默认值，避免「以为在 demo、实际打到 live」的反向风险。
        """
        demo_flag = "--demo" if self.mode == "demo" else "--live"
        if self.credential_source == "env":
            # 凭证走环境变量时不需要（也不应）绑定 ~/.okx 的 profile。
            return [demo_flag]
        if self.auth == "api_key":
            return ["--profile", self.profile, demo_flag]
        return [demo_flag]

    def describe(self) -> dict:
        return {
            "cli_path": self.cli_path,
            "profile": self.profile,
            "mode": self.mode,
            "auth": self.auth,
            "read_allowed": self.read_allowed,
            "write_allowed": self.write_allowed,
            "allow_live_write": self.allow_live_write,
            "credential_source": self.credential_source,
            "credential_configured": bool(self.env_credentials),
        }
