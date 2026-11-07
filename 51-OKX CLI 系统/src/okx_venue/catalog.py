"""Allowlist for OKX CLI commands exposed by the venue adapter.

The adapter API is operation-based, so this module is defense-in-depth: even a
caller that can shape argv cannot reach credentials, transfers, bots, or live
risk categories.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .errors import CommandNotAllowed

_READ_ACTIONS = {
    "market": {
        "ticker",
        "tickers",
        "candles",
        "instruments",
        "orderbook",
        "funding-rate",
        "open-interest",
        "indicator",
        "list-indicators",
    },
    "account": {"balance", "positions", "config", "fees"},
    "spot": {"get", "orders"},
    "swap": {"get", "positions", "orders"},
}

_WRITE_ACTIONS = {
    "spot": {"place", "cancel"},
    "swap": {"place", "cancel"},
}

_FORBIDDEN_MODULES = {
    "auth",
    "bot",
    "config",
    "diagnose",
    "earn",
    "event",
    "futures",
    "login",
    "logout",
    "mcp",
    "option",
    "pilot",
    "skills",
    "upgrade",
}

_FORBIDDEN_FLAGS = {
    "--api-key",
    "--demo",
    "--force",
    "--passphrase",
    "--profile",
    "--secret",
    "--secret-key",
    "--withdraw",
}

_SHELL_META = set(";&|`$<>\n\r")


def _reject(message: str, argv: Sequence[str]) -> None:
    raise CommandNotAllowed(message, details={"argv": list(argv)})


def _check_tokens(argv: Sequence[str]) -> None:
    for token in argv:
        if not isinstance(token, str):
            _reject(f"non-string argv token: {token!r}", argv)
        if set(token) & _SHELL_META:
            _reject(f"shell metacharacter in argv token: {token!r}", argv)
        if token in _FORBIDDEN_FLAGS:
            _reject(f"caller may not pass {token}; the adapter injects it", argv)
        if token in {"--api-key", "--secret", "--secret-key", "--passphrase"}:
            _reject(f"credential flag is forbidden: {token}", argv)


def validate_argv(argv: Sequence[str], *, write: bool) -> None:
    if not argv:
        _reject("empty argv", argv)
    _check_tokens(argv)

    module = argv[0]
    if module in _FORBIDDEN_MODULES:
        _reject(f"module {module!r} is forbidden in v0.1", argv)

    allowed = _WRITE_ACTIONS if write else _READ_ACTIONS
    actions = allowed.get(module)
    if actions is None:
        _reject(f"module {module!r} is not allowed for {'write' if write else 'read'}", argv)
    if len(argv) < 2 or argv[1] not in actions:
        _reject(
            f"action {argv[1] if len(argv) > 1 else '<missing>'!r} is not allowed "
            f"for {module!r} ({'write' if write else 'read'})",
            argv,
        )


def allowed_operations() -> dict:
    """Return the allowlist for documentation and tests."""
    return {
        "read": {module: sorted(actions) for module, actions in _READ_ACTIONS.items()},
        "write": {module: sorted(actions) for module, actions in _WRITE_ACTIONS.items()},
        "forbidden_modules": sorted(_FORBIDDEN_MODULES),
    }


def iter_forbidden_flags() -> Iterable[str]:
    return iter(sorted(_FORBIDDEN_FLAGS))