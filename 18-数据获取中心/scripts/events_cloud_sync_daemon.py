#!/usr/bin/env python3
"""极简常驻同步 daemon（方案 B）：本地采集 → 推送云端 → 触发 39 打分。

不依赖 launchd，人工启动；每 EVENTS_SYNC_INTERVAL_SEC（默认 1800 秒）跑一轮。
只做事件链路，不启动 18 的全套 34 个采集任务。

启动：
  cd 18-数据获取中心
  setsid nohup /opt/anaconda3/bin/python3 scripts/events_cloud_sync_daemon.py \\
      >> logs/events_cloud_sync.log 2>&1 < /dev/null &

停止：
  kill "$(cat logs/events_cloud_sync.pid)"

查看：
  tail -f logs/events_cloud_sync.log
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # 18-数据获取中心
SYNC_SCRIPT = PROJECT / "scripts" / "sync_events_to_cloud.py"
LOGS_DIR = PROJECT / "logs"
PIDFILE = LOGS_DIR / "events_cloud_sync.pid"

INTERVAL = int(os.environ.get("EVENTS_SYNC_INTERVAL_SEC", "1800"))
SYNC_TIMEOUT = int(os.environ.get("EVENTS_SYNC_TIMEOUT_SEC", "900"))

_stop = threading.Event()


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _already_running() -> bool:
    if not PIDFILE.is_file():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _handle_signal(signum, _frame) -> None:
    log(f"收到信号 {signum}，准备退出")
    _stop.set()


def run_once() -> int:
    log("=" * 60)
    log("开始同步轮次")
    try:
        proc = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT)],
            cwd=str(PROJECT),
            timeout=SYNC_TIMEOUT,
        )
        log(f"同步轮次结束 rc={proc.returncode}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        log(f"同步超时（>{SYNC_TIMEOUT}s），本轮跳过")
        return 124
    except Exception as exc:  # noqa: BLE001 — 单轮失败不影响下一轮
        log(f"同步轮次异常：{type(exc).__name__}: {exc}")
        return 1


def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if _already_running():
        log(f"已有 daemon 在运行（pid={PIDFILE.read_text().strip()}），退出")
        return 0

    PIDFILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log(f"daemon 启动 pid={os.getpid()} interval={INTERVAL}s")
    try:
        while not _stop.is_set():
            run_once()
            if _stop.wait(INTERVAL):
                break
    finally:
        try:
            if PIDFILE.read_text().strip() == str(os.getpid()):
                PIDFILE.unlink()
        except (FileNotFoundError, ValueError):
            pass
        log("daemon 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
