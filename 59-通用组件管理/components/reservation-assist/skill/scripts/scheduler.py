"""对时、虚拟时钟、节拍、退避与熔断；不依赖任何平台名。"""

from __future__ import annotations

import time
from dataclasses import dataclass

MAX_SPREAD_MS = 50
MAX_RTT_MS = 300
BLIND_CONFIDENCE_MS = 1500
WAKE_THRESHOLD_MS = 5000
API_FLOOR_MS = 500
BROWSER_FLOOR_MS = 3000


@dataclass
class Sample:
    """一次对时采样：发出/收到本机时间与服务端 ms 时间。"""

    server_ms: int
    sent_ms: int
    recv_ms: int

    @property
    def rtt_ms(self) -> int:
        return max(0, self.recv_ms - self.sent_ms)

    @property
    def offset_ms(self) -> int:
        return int(self.server_ms - (self.sent_ms + self.recv_ms) / 2)


@dataclass
class ClockEstimate:
    offset_ms: int
    confidence_ms: int
    accepted: bool
    reason: str = ""

    @property
    def blind(self) -> bool:
        return not self.accepted or self.confidence_ms > BLIND_CONFIDENCE_MS


def estimate_offset(samples: list[Sample]) -> ClockEstimate:
    """取 RTT 最小的 3 次；离散度 ≤50ms 且 RTT ≤300ms 才采信。"""
    usable = [s for s in samples if s.recv_ms >= s.sent_ms]
    if len(usable) < 3:
        return ClockEstimate(0, 10**9, False, "insufficient_samples")
    best = sorted(usable, key=lambda s: s.rtt_ms)[:3]
    offsets = sorted(s.offset_ms for s in best)
    spread = offsets[-1] - offsets[0]
    if spread > MAX_SPREAD_MS:
        return ClockEstimate(offsets[1], spread, False, "spread_too_large")
    if max(s.rtt_ms for s in best) > MAX_RTT_MS:
        return ClockEstimate(offsets[1], max(s.rtt_ms for s in best), False, "rtt_too_large")
    return ClockEstimate(offsets[1], spread, True, "ok")


class VirtualClock:
    """t_v = monotonic + offset；倒计时一律用 t_v，offset 定期刷新。"""

    def __init__(self, offset_ms: int = 0, mono=time.monotonic, wall=time.time) -> None:
        self._mono = mono
        self._wall = wall
        self.offset_ms = int(offset_ms)
        self._base = self._wall() * 1000 + self.offset_ms - self._mono() * 1000

    def sync(self, estimate: ClockEstimate) -> bool:
        if estimate.accepted:
            self.offset_ms = estimate.offset_ms
            self._base = self._wall() * 1000 + self.offset_ms - self._mono() * 1000
            return True
        return False

    def now_ms(self) -> int:
        return int(self._base + self._mono() * 1000)


def detect_wake(prev_wall_ms: int, prev_mono_ms: int, wall_ms: int, mono_ms: int) -> bool:
    """墙钟增量显著大于单调钟增量 → 判为休眠唤醒。"""
    return (wall_ms - prev_wall_ms) - (mono_ms - prev_mono_ms) > WAKE_THRESHOLD_MS


@dataclass
class TickState:
    wall_ms: int
    mono_ms: int


class WakeDetector:
    def __init__(self, wall=time.time, mono=time.monotonic) -> None:
        self._wall = wall
        self._mono = mono
        self.last = TickState(int(wall() * 1000), int(mono() * 1000))

    def tick(self) -> bool:
        wall_ms = int(self._wall() * 1000)
        mono_ms = int(self._mono() * 1000)
        woke = detect_wake(self.last.wall_ms, self.last.mono_ms, wall_ms, mono_ms)
        self.last = TickState(wall_ms, mono_ms)
        return woke


class Backoff:
    """1s/2s/4s/8s；20 次失败熔断 300s；风控页由调用方冷却 24h。"""

    def __init__(
        self,
        delays: tuple[int, ...] = (1000, 2000, 4000, 8000),
        breaker_after: int = 20,
        breaker_ms: int = 300000,
    ) -> None:
        self.delays = delays
        self.breaker_after = breaker_after
        self.breaker_ms = breaker_ms
        self.failures = 0
        self.step = 0
        self.blocked_until = 0

    def record_failure(self, now_ms: int) -> int:
        self.failures += 1
        if self.failures >= self.breaker_after:
            self.blocked_until = max(self.blocked_until, now_ms + self.breaker_ms)
            self.failures = 0
            self.step = 0
            return self.breaker_ms
        delay = self.delays[min(self.step, len(self.delays) - 1)]
        self.step += 1
        return delay

    def record_success(self) -> None:
        self.failures = 0
        self.step = 0

    def cooldown(self, now_ms: int, ms: int) -> None:
        self.blocked_until = max(self.blocked_until, now_ms + ms)

    def remaining_block_ms(self, now_ms: int) -> int:
        return max(0, self.blocked_until - now_ms)


def effective_interval(
    adapter, requested_ms: int | None, browser: bool = False, unsafe: bool = False
) -> int:
    """取「请求值 / 默认值 / 下限 / 平台最低间隔」的最大值。"""
    floor = BROWSER_FLOOR_MS if browser else API_FLOOR_MS
    default = 5000 if browser else 1000
    wanted = int(requested_ms or default)
    if unsafe and not getattr(adapter, "PERFORMANCE", False):
        raise ValueError("unsafe_interval 仅允许演出票适配器使用")
    floor = max(floor, int(getattr(adapter, "MIN_INTERVAL_MS", 0) or 0))
    return max(wanted, default, floor)


def in_window(now_ms: int, start_ms: int | None, end_ms: int | None) -> bool:
    if start_ms is not None and now_ms < start_ms:
        return False
    if end_ms is not None and now_ms > end_ms:
        return False
    return True
