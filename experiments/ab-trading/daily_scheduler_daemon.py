#!/usr/bin/env python3
"""
每日调度守护进程 — launchd 沙箱问题兜底方案
==============================================

背景：Trae Code 的 macOS 沙箱环境下 launchd 可能遇到 I/O 权限或沙箱隔离问题，
导致 plist 无法正常加载或执行。本脚本提供纯 Python 实现的守护调度，
通过 setsid 独立运行，不依赖系统级 launchd。

调度计划（每日北京时间，可由环境变量覆盖）：
  - 02:00  Agent B 策略参数优化（update_classic_strategy_params）
            日志：logs/agent_b.log（由函数内部写入）
  - 02:05  记忆模块清理（MemoryManager.clean_expired_memories）
            日志：logs/memory_cleanup.log（由函数内部写入）

用法：
  1. 前台运行：  python3 daily_scheduler_daemon.py --foreground
  2. 守护进程：  python3 start_daemon.py daily_scheduler_daemon.py
  3. 立即测试：  python3 daily_scheduler_daemon.py --run-now

停止：
  - kill <PID> 或 SIGTERM（收到后会优雅退出，不会中断正在执行的任务）
"""
import argparse
import logging
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 基础路径 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DAEMON_LOG = LOG_DIR / "daily_scheduler_daemon.log"
sys.path.insert(0, str(PROJECT_ROOT))

# ── 时区：使用 Asia/Shanghai（UTC+8）────────────────────────────────────────
TZ_OFFSET_HOURS = int(os.environ.get("SCHEDULER_TZ_OFFSET", "8"))
TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))

# ── 调度配置 ────────────────────────────────────────────────────────────────
STRATEGY_HOUR = int(os.environ.get("STRATEGY_UPDATE_HOUR", "2"))
STRATEGY_MIN = int(os.environ.get("STRATEGY_UPDATE_MIN", "0"))

MEMORY_HOUR = int(os.environ.get("MEMORY_CLEANUP_HOUR", "2"))
MEMORY_MIN = int(os.environ.get("MEMORY_CLEANUP_MIN", "5"))

CHECK_INTERVAL_SEC = 30  # 每 30 秒检查一次时钟（精度足够，CPU 占用极低）


# ── 日志 ────────────────────────────────────────────────────────────────────
def _setup_daemon_logger() -> logging.Logger:
    logger = logging.getLogger("daily_scheduler")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(DAEMON_LOG, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


log = _setup_daemon_logger()


# ── 优雅退出 ────────────────────────────────────────────────────────────────
_running = True


def _handle_signal(signum, frame):
    global _running
    sig_name = signal.Signals(signum).name
    log.info(f"收到信号 {sig_name}({signum})，准备优雅退出...")
    _running = False


for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    try:
        signal.signal(_sig, _handle_signal)
    except (ValueError, OSError):
        pass  # 非主线程环境下可能失败，忽略


# ── 任务执行 ────────────────────────────────────────────────────────────────
def run_strategy_update() -> bool:
    """执行 Agent B 策略参数优化"""
    log.info("──▶ 触发 Agent B 策略参数优化 (update_classic_strategy_params)")
    try:
        from agents.agent_b_runner import update_classic_strategy_params
        update_classic_strategy_params()
        log.info("◀── Agent B 策略参数优化完成")
        return True
    except Exception as e:
        log.error(f"Agent B 策略参数优化失败: {e}", exc_info=True)
        return False


def run_memory_cleanup() -> bool:
    """执行记忆模块清理"""
    log.info("──▶ 触发记忆模块清理 (MemoryManager.clean_expired_memories)")
    try:
        from core.memory.memory_manager import MemoryManager
        m = MemoryManager()
        m.clean_expired_memories()
        log.info("◀── 记忆模块清理完成")
        return True
    except Exception as e:
        log.error(f"记忆模块清理失败: {e}", exc_info=True)
        return False


# ── 调度核心 ────────────────────────────────────────────────────────────────
def _now_local() -> datetime:
    return datetime.now(TZ)


def _seconds_until_next(target_hour: int, target_minute: int) -> int:
    """计算距离下一个目标时刻的秒数"""
    now = _now_local()
    target = now.replace(hour=target_hour, minute=target_minute,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())


def _format_next_run(target_hour: int, target_minute: int,
                     label: str) -> str:
    secs = _seconds_until_next(target_hour, target_minute)
    hrs, rem = divmod(secs, 3600)
    mins, _ = divmod(rem, 60)
    return f"下次{label}: {hrs}h{mins:02d}m 后 ({secs}s)"


def scheduler_loop():
    """主调度循环：按日历触发任务，避免重复执行"""
    log.info("=" * 60)
    log.info("Daily Scheduler 守护进程启动")
    log.info(f"  时区: UTC{TZ_OFFSET_HOURS:+d} (本地时间 {_now_local().strftime('%Y-%m-%d %H:%M:%S')})")
    log.info(f"  策略更新:  每日 {STRATEGY_HOUR:02d}:{STRATEGY_MIN:02d} → logs/agent_b.log")
    log.info(f"  记忆清理:  每日 {MEMORY_HOUR:02d}:{MEMORY_MIN:02d} → logs/memory_cleanup.log")
    log.info(f"  检查间隔:  {CHECK_INTERVAL_SEC}s")
    log.info("=" * 60)

    # 记录今日已执行的任务，防止同一日内重复触发
    last_run_date = {"strategy": None, "memory": None}

    while _running:
        try:
            now = _now_local()
            today = now.date()

            # 1. 检查策略更新
            if (last_run_date["strategy"] != today
                    and now.hour == STRATEGY_HOUR
                    and now.minute == STRATEGY_MIN):
                run_strategy_update()
                last_run_date["strategy"] = today

            # 2. 检查记忆清理
            if (last_run_date["memory"] != today
                    and now.hour == MEMORY_HOUR
                    and now.minute == MEMORY_MIN):
                run_memory_cleanup()
                last_run_date["memory"] = today

            # 3. 每 10 分钟输出一次心跳，确认守护进程存活
            if now.second == 0 and now.minute % 10 == 0:
                log.info(
                    f"[心跳] {now.strftime('%Y-%m-%d %H:%M')} | "
                    f"{_format_next_run(STRATEGY_HOUR, STRATEGY_MIN, '策略更新')} | "
                    f"{_format_next_run(MEMORY_HOUR, MEMORY_MIN, '记忆清理')}"
                )

            # 4. 小步 sleep，保证信号响应及时
            for _ in range(CHECK_INTERVAL_SEC):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            log.error(f"调度循环异常: {e}", exc_info=True)
            # 出错后 sleep 30 秒再继续，避免热循环
            for _ in range(30):
                if not _running:
                    break
                time.sleep(1)

    log.info("Daily Scheduler 守护进程已退出")


# ── 入口 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="每日调度守护进程")
    parser.add_argument("--foreground", action="store_true",
                        help="前台运行（默认如果是 start_daemon 会 setsid 后台）")
    parser.add_argument("--run-now", action="store_true",
                        help="立即执行两个任务一次（用于手动冒烟测试）")
    parser.add_argument("--run-strategy-now", action="store_true",
                        help="立即执行策略更新一次")
    parser.add_argument("--run-memory-now", action="store_true",
                        help="立即执行记忆清理一次")
    args = parser.parse_args()

    if args.run_now:
        log.info("[--run-now] 立即执行两个任务...")
        ok1 = run_strategy_update()
        ok2 = run_memory_cleanup()
        sys.exit(0 if (ok1 and ok2) else 1)

    if args.run_strategy_now:
        ok = run_strategy_update()
        sys.exit(0 if ok else 1)

    if args.run_memory_now:
        ok = run_memory_cleanup()
        sys.exit(0 if ok else 1)

    scheduler_loop()


if __name__ == "__main__":
    main()
