"""51 OKX Venue Adapter error model."""

from __future__ import annotations

from typing import Any, Dict, Optional


class VenueError(Exception):
    """Base error for the OKX venue adapter."""

    code = "venue_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}


class VenueConfigError(VenueError):
    code = "venue_config_error"


class CliNotInstalled(VenueError):
    code = "cli_not_installed"


class CommandNotAllowed(VenueError):
    code = "command_not_allowed"


class LiveTradingForbidden(VenueError):
    code = "live_trading_forbidden"


class LiveReadForbidden(VenueError):
    code = "live_read_forbidden"


class LiveUnlockDenied(VenueError):
    code = "live_unlock_denied"


class CredentialsMissing(VenueError):
    code = "venue_credentials_missing"


class CliTimeout(VenueError):
    code = "cli_timeout"


class CliNonZeroExit(VenueError):
    code = "cli_nonzero_exit"


class CliAuthError(CliNonZeroExit):
    code = "cli_auth_error"


class CliRateLimit(CliNonZeroExit):
    code = "cli_rate_limit"


class CliInvalidResponse(VenueError):
    code = "cli_invalid_json"
