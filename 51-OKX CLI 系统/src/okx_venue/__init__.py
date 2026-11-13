"""51-OKX CLI 系统 — OKX venue adapter."""

from .adapter import OkxCliVenue, build_adapter
from .config import DEFAULT_AUDIT_PATH, DEFAULT_USER_PROFILE, USER_AUDIT_PATH, VenueConfig
from .errors import (
    CliAuthError,
    CliInvalidResponse,
    CliNonZeroExit,
    CliNotInstalled,
    CliRateLimit,
    CliTimeout,
    CommandNotAllowed,
    CredentialsMissing,
    LiveReadForbidden,
    LiveTradingForbidden,
    LiveUnlockDenied,
    VenueConfigError,
    VenueError,
)
from .live_gate import LIVE_CONFIRM_PHRASE, LiveGate
from .runner import AuditLogger, CliRunner, redact_argv
from .selector import ORDER_ADAPTER_ENV, build_order_adapter


def __getattr__(name):
    # 延迟导入：避免 `python -m okx_venue.server` 触发 runpy 重复导入告警。
    if name in {"VenueApp", "make_server"}:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AuditLogger",
    "CliAuthError",
    "CliInvalidResponse",
    "CliNotInstalled",
    "CliNonZeroExit",
    "CliRateLimit",
    "CliRunner",
    "CliTimeout",
    "CommandNotAllowed",
    "CredentialsMissing",
    "DEFAULT_AUDIT_PATH",
    "DEFAULT_USER_PROFILE",
    "LIVE_CONFIRM_PHRASE",
    "LiveGate",
    "LiveReadForbidden",
    "LiveTradingForbidden",
    "LiveUnlockDenied",
    "ORDER_ADAPTER_ENV",
    "OkxCliVenue",
    "USER_AUDIT_PATH",
    "VenueApp",
    "VenueConfig",
    "VenueConfigError",
    "VenueError",
    "build_adapter",
    "build_order_adapter",
    "make_server",
    "redact_argv",
]
