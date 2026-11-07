"""Order-port selection for trade-exec MCP (P2 integration point).

The selector is intentionally fail-closed: unknown values and any live-flavored
adapter are rejected. There is no live branch.
"""

from __future__ import annotations

import os
from typing import Optional

from .adapter import OkxCliVenue
from .config import VenueConfig
from .errors import VenueConfigError
from .runner import CliRunner

ORDER_ADAPTER_ENV = "TRADE_EXEC_ORDER_ADAPTER"
PAPER = "paper"
OKX_CLI_DEMO = "okx-cli-demo"

_ALLOWED = {PAPER, OKX_CLI_DEMO}


def resolve_order_adapter_name(value: Optional[str] = None) -> str:
    name = value if value is not None else os.getenv(ORDER_ADAPTER_ENV, PAPER)
    name = (name or PAPER).strip().lower()
    if name in {"", "none"}:
        return PAPER
    if name not in _ALLOWED:
        raise VenueConfigError(
            f"{ORDER_ADAPTER_ENV} must be one of {sorted(_ALLOWED)}, got {name!r}"
        )
    return name


def build_order_adapter(
    value: Optional[str] = None,
    *,
    config: Optional[VenueConfig] = None,
    runner: Optional[CliRunner] = None,
) -> Optional[OkxCliVenue]:
    """Return None for the paper ledger, or a demo-only OKX CLI adapter."""
    name = resolve_order_adapter_name(value)
    if name == PAPER:
        return None
    venue_config = config or VenueConfig.from_env()
    if venue_config.mode != "demo" or not venue_config.write_allowed:
        raise VenueConfigError("okx-cli-demo requires OKX_VENUE_MODE=demo; live is not wired to 51")
    return OkxCliVenue(config=venue_config, runner=runner)
