#!/usr/bin/env python3
"""52-LobeHub 每日流水线守护进程（launchd 被 macOS TCC 拦截时的本地替代）。

行为：每天固定时刻执行 `ops/daily_pipeline.sh`（shadow 批量 → 蒸馏桥消费），
写 pidfile 防重复启动，收到 SIGTERM/SIGINT 后退出。

用法：
  python3 ops/supervisor.py --dry-run          # 只打印下一次执行时间
  nohup python3 ops/supervisor.py >> logs/supervisor.log 2>&1 &
  kill "$(cat ops/.supervisor.pid)"            # 停止

局限：进程随宿主环境（本机登录会话）存活；重启后需重新启动，
或改为 launchd（plist 模板见 ops/com.dreambuddy.shadow.plist、bridge/ops/com.dreambuddy.bridge.plist）。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent
ORCH_DIR = OPS_DIR.parent
PIPELINE = OPS_DIR / "daily_pipeline.sh"
PIDFILE = OPS_DIR / ".supervisor.pid"


def next_run(hour: int, minute: int, now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="52 每日 shadow + 蒸馏调度守护")
    parser.add_argument("--hour", type=int, default=22)
    parser.add_argument("--minute", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="只打印下一次执行时间")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(next_run(args.hour, args.minute).isoformat(timespec="seconds"))
        return 0

    if PIDFILE.exists():
        print(f"已有守护进程在运行: {PIDFILE.read_text().strip()}", file=sys.stderr)
        return 1
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")

    stopping = False

    def _stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        while not stopping:
            target = next_run(args.hour, args.minute)
            print(f"[supervisor] next run {target.isoformat(timespec='seconds')}", flush=True)
            while not stopping and datetime.now() < target:
                remaining = (target - datetime.now()).total_seconds()
                time.sleep(max(1.0, min(30.0, remaining)))
            if stopping:
                break
            print(f"[supervisor] start {datetime.now().isoformat(timespec='seconds')}", flush=True)
            result = subprocess.run(["bash", str(PIPELINE)], capture_output=True, text=True)
            tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
            print(
                f"[supervisor] done rc={result.returncode} {tail[0]} "
                f"err={(result.stderr or '').strip()[-200:]}",
                flush=True,
            )
            # 防止同一分钟内重复触发
            time.sleep(61)
    finally:
        PIDFILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
