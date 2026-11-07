"""51-OKX CLI 系统 — OKX venue adapter."""

from .adapter import OkxCliVenue, build_adapter
from .config import DEFAULT_AUDIT_PATH, VenueConfig
from .errors import (
    CliAuthError,
    CliInvalidResponse,
    CliNonZeroExit,
    CliNotInstalled,
    CliRateLimit,
    CliTimeout,
    CommandNotAllowed,
    LiveReadForbidden,
    LiveTradingForbidden,
    VenueConfigError,
    VenueError,
)
from .runner import AuditLogger, CliRunner, redact_argv
from .selector import ORDER_ADAPTER_ENV, build_order_adapter

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
    "DEFAULT_AUDIT_PATH",
    "LiveReadForbidden",
    "LiveTradingForbidden",
    "ORDER_ADAPTER_ENV",
    "OkxCliVenue",
    "VenueConfig",
    "VenueConfigError",
    "VenueError",
    "build_adapter",
    "build_order_adapter",
    "redact_argv",
]
