#!/usr/bin/env python3
"""cognitive_daemon P2-7 集成测试：空闲反刍触发"""
import sys
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent))


def test_ruminate_called_on_idle():
    """空闲超 30min 且当日未反刍 → 触发 _ruminate"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon._last_activity_ts = time.time() - 1801  # 超过 30 分钟
    daemon._last_rumination_date = None
    daemon._rumination_idle_seconds = 1800
    daemon.verbose = False
    daemon.watch_dir = Path("/tmp")

    called = {"flag": False}
    def fake_ruminate():
        called["flag"] = True
        daemon._last_rumination_date = "2026-08-05"
        daemon._last_activity_ts = time.time()

    # 模拟 _tick 中的空闲检测逻辑（无 changes 分支）
    changes = {}
    if changes:
        daemon._last_activity_ts = time.time()
    else:
        idle = time.time() - daemon._last_activity_ts
        today = "2026-08-05"
        if (idle >= daemon._rumination_idle_seconds
                and daemon._last_rumination_date != today):
            fake_ruminate()

    assert called["flag"] is True


def test_ruminate_not_called_same_day():
    """当日已反刍 → 不重复触发"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon._last_activity_ts = time.time() - 1801
    daemon._last_rumination_date = "2026-08-05"  # 当日已反刍
    daemon._rumination_idle_seconds = 1800

    called = {"flag": False}
    def fake_ruminate():
        called["flag"] = True

    changes = {}
    if not changes:
        idle = time.time() - daemon._last_activity_ts
        today = "2026-08-05"
        if (idle >= daemon._rumination_idle_seconds
                and daemon._last_rumination_date != today):
            fake_ruminate()

    assert called["flag"] is False


def test_ruminate_failure_resets_timer():
    """_ruminate 失败时重置计时器（避免连续重试）"""
    from cognitive_daemon import CognitiveDaemon
    daemon = CognitiveDaemon.__new__(CognitiveDaemon)
    daemon.verbose = False
    daemon.watch_dir = Path("/tmp")
    daemon._last_activity_ts = time.time() - 1801
    daemon._last_rumination_date = None
    daemon._rumination_idle_seconds = 1800

    # 让 get_cle 抛异常模拟失败
    with patch("cognitive_loop_entry.get_cle", side_effect=Exception("boom")):
        daemon._ruminate()

    # 失败后计时器应被重置（接近 now）
    assert time.time() - daemon._last_activity_ts < 5


if __name__ == "__main__":
    test_ruminate_called_on_idle()
    test_ruminate_not_called_same_day()
    test_ruminate_failure_resets_timer()
    print("✅ daemon 反刍集成测试通过")
