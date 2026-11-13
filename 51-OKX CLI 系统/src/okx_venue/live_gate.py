"""Explicit unlock gate for user-venue live trading.

51 默认只允许 demo 写（SPEC §3.2 / D2）。用户 venue 在前端需要实盘下单时，
必须先由人工输入确认短语解锁；解锁态仅存内存，进程重启即失效。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from .errors import LiveUnlockDenied

LIVE_CONFIRM_PHRASE = "UNLOCK LIVE TRADING"
DEFAULT_TTL_S = 1800
MIN_TTL_S = 60
MAX_TTL_S = 8 * 3600


class LiveGate:
    """In-memory, time-boxed live unlock state."""

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._unlocked_until = 0.0
        self._lock = threading.Lock()

    def status(self) -> Dict[str, object]:
        with self._lock:
            remaining = int(self._unlocked_until - self._clock())
        return {"unlocked": remaining > 0, "expires_in_s": max(0, remaining)}

    def is_unlocked(self) -> bool:
        return bool(self.status()["unlocked"])

    def unlock(self, phrase: Optional[str], ttl_s: int = DEFAULT_TTL_S) -> Dict[str, object]:
        if (phrase or "").strip() != LIVE_CONFIRM_PHRASE:
            raise LiveUnlockDenied(
                "confirmation phrase mismatch; live trading stays locked",
                details={"expected": LIVE_CONFIRM_PHRASE},
            )
        ttl = int(ttl_s or DEFAULT_TTL_S)
        ttl = max(MIN_TTL_S, min(MAX_TTL_S, ttl))
        with self._lock:
            self._unlocked_until = self._clock() + ttl
        return self.status()

    def lock(self) -> Dict[str, object]:
        with self._lock:
            self._unlocked_until = 0.0
        return self.status()
