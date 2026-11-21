"""调度回归：对时采样、虚拟时钟、唤醒检测、退避熔断、节拍下限。"""

from __future__ import annotations

import unittest

import _support  # noqa: F401  (设置 sys.path)
from adapters import get_adapter
from scheduler import (
    Backoff,
    Sample,
    VirtualClock,
    detect_wake,
    effective_interval,
    estimate_offset,
    in_window,
)


def sample(server: int, local: int, rtt: int) -> Sample:
    return Sample(server_ms=server, sent_ms=local, recv_ms=local + rtt)


class SchedulerTest(unittest.TestCase):
    def test_estimate_accepts_tight_samples(self):
        est = estimate_offset([sample(500 + rtt // 2, 0, rtt) for rtt in (40, 30, 60, 20, 36)])
        self.assertTrue(est.accepted)
        self.assertLessEqual(est.confidence_ms, 50)
        self.assertEqual(est.offset_ms, 500)

    def test_estimate_rejects_spread(self):
        est = estimate_offset(
            [
                sample(1_000_000, 1000, 30),
                sample(1_002_000, 1000, 30),
                sample(1_004_000, 1000, 30),
            ]
        )
        self.assertFalse(est.accepted)
        self.assertEqual(est.reason, "spread_too_large")
        self.assertTrue(est.blind)

    def test_estimate_rejects_insufficient(self):
        est = estimate_offset([sample(1000, 1000, 30)])
        self.assertFalse(est.accepted)
        self.assertEqual(est.reason, "insufficient_samples")

    def test_virtual_clock_applies_accepted_offset_only(self):
        clock = VirtualClock(offset_ms=0, mono=lambda: 10.0, wall=lambda: 1000.0)
        before = clock.now_ms()
        self.assertFalse(clock.sync(estimate_offset([sample(1000, 1000, 30)])))
        self.assertEqual(clock.now_ms(), before)
        est = estimate_offset([sample(500 + rtt // 2, 0, rtt) for rtt in (20, 30, 24)])
        self.assertTrue(clock.sync(est))
        self.assertEqual(clock.offset_ms, 500)

    def test_detect_wake(self):
        self.assertFalse(detect_wake(0, 0, 1000, 1000))
        self.assertTrue(detect_wake(0, 0, 30_000, 1_000))
        self.assertFalse(detect_wake(0, 0, 6_000, 1_000))

    def test_backoff_sequence_and_breaker(self):
        backoff = Backoff()
        self.assertEqual([backoff.record_failure(0) for _ in range(4)], [1000, 2000, 4000, 8000])
        self.assertEqual(backoff.record_failure(0), 8000)
        backoff.record_success()
        self.assertEqual(backoff.record_failure(0), 1000)

        breaker = Backoff()
        for _ in range(19):
            breaker.record_failure(1000)
        self.assertEqual(breaker.record_failure(1000), 300000)
        self.assertEqual(breaker.remaining_block_ms(1000), 300000)

    def test_effective_interval_floor(self):
        railway = get_adapter("railway")
        self.assertEqual(effective_interval(railway, 100), 1500)
        self.assertEqual(effective_interval(railway, 5000), 5000)

        self.assertEqual(effective_interval(get_adapter("medical"), 100), 3000)
        self.assertEqual(effective_interval(get_adapter("gov"), 100), 5000)

        damai = get_adapter("damai")
        self.assertEqual(effective_interval(damai, 300, browser=True), 5000)
        with self.assertRaises(ValueError):
            effective_interval(railway, 300, unsafe=True)
        self.assertEqual(effective_interval(damai, 600, unsafe=True), 1000)

    def test_in_window(self):
        self.assertTrue(in_window(1500, 1000, 2000))
        self.assertFalse(in_window(999, 1000, 2000))
        self.assertFalse(in_window(2001, 1000, 2000))
        self.assertTrue(in_window(1500, None, None))


if __name__ == "__main__":
    unittest.main()
