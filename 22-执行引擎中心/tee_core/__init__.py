"""Execution Engine Core Package.

Independent reusable trade-execution layer.
- Global switches (safe-off by default).
- No strategy-level imports from V15 / 易经 / 三屏. All dependencies
  enter via Dependency Injection of the ExchangeClient Protocol.
"""

from .core import config  # noqa: F401   (public surface)

__all__ = ["config"]
__version__ = "0.1.0"
