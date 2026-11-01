"""data_center_scheduler — 持续采集调度器独立进程入口。

用法：
  python3 data_center_scheduler.py              # 前台运行
  python3 data_center_scheduler.py --once       # 只跑一次各任务（调试用）
  python3 data_center_scheduler.py --dry-run    # 不真正采集，只打印任务清单

launchd 托管：
  cp launchd/com.dreambuddy.data-center-scheduler.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.dreambuddy.data-center-scheduler.plist
  launchctl unload ~/Library/LaunchAgents/com.dreambuddy.data-center-scheduler.plist  # 停止

日志：logs/scheduler.log（launchd 标准输出）+ logs/scheduler.err.log（标准错误）
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# 确保 data_center + data_cleaning 包可导入（脚本可能在任意 cwd 被调用）
_BASE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BASE_DIR.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))
# Silver 清洗链依赖 20-数据清洗中心
_CLEANING_DIR = _REPO_ROOT / "20-数据清洗中心"
if _CLEANING_DIR.exists() and str(_CLEANING_DIR) not in sys.path:
    sys.path.insert(0, str(_CLEANING_DIR))
# 18→19 backfill 脚本
_BACKFILL_DIR = _REPO_ROOT / "19-数据访问层" / "scripts"
if _BACKFILL_DIR.exists() and str(_BACKFILL_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKFILL_DIR))
# C9 调度记账（dreambuddy_l0 顶层包）
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_center import DataCenter  # noqa: E402
from data_center.monitoring.quality import QualityChecker  # noqa: E402
from data_center.scheduler import CollectionScheduler  # noqa: E402
from data_center.storage.sink_postgres import get_sink  # noqa: E402

# ── 路径配置 ──────────────────────────────────────────────────────────────────
DB_PATH = str(_BASE_DIR / "data_center.db")
LOGS_DIR = _BASE_DIR / "logs"
LOG_FILE = str(LOGS_DIR / "scheduler.log")

logger = logging.getLogger("dc.scheduler")


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _build_recorder():
    """C9：构造 job_runs 记账器（经 L0 Store/Event port，失败则降级为 None）。"""
    if os.environ.get("JOB_RUNS_ENABLED", "1") != "1":
        return None
    try:
        from dreambuddy_l0.adapters.jsonl import JsonlEvent, JsonlStore
        from dreambuddy_l0.scheduling import JobRunRecorder, load_registry

        path = os.environ.get("JOB_RUNS_PATH") or str(LOGS_DIR / "job_runs.jsonl")
        return JobRunRecorder(
            store=JsonlStore(path), event=JsonlEvent(path), registry=load_registry()
        )
    except Exception as e:
        logger.error("job_runs 记账器初始化失败（降级为不记账）: %s: %s", type(e).__name__, e)
        return None


def _run_task_key() -> str:
    """本地/云端分别对应注册表中的 dc.collect.local / dc.collect.cloud。"""
    explicit = os.environ.get("JOB_TASK_KEY")
    if explicit:
        return explicit
    return (
        "dc.collect.cloud"
        if os.environ.get("DATA_CENTER_BACKEND") == "postgres"
        else "dc.collect.local"
    )


def _build_scheduler() -> CollectionScheduler:
    """构造调度器：DataCenter + SqliteSink + QualityChecker + 默认任务清单。"""
    dc = DataCenter()
    sink = get_sink(DB_PATH)
    quality = QualityChecker()
    sched = CollectionScheduler(
        dc=dc,
        sink=sink,
        quality=quality,
        tasks=CollectionScheduler.default_tasks(),
        alerts_router=dc.monitoring.alerts,  # 复用 DataCenter 默认 AlertRouter
        run_recorder=_build_recorder(),
        run_task_key=_run_task_key(),
    )
    return sched


def _run_once(sched: CollectionScheduler) -> None:
    """调试模式：对所有任务跑一次 collect_once。"""
    for task in sched.tasks:
        logger.info("collect_once: %s (%s/%s) ...", task.name, task.category, task.source)
        metric = sched.collect_once(task)
        logger.info(
            "  → status=%s duration=%.1fms records=%d err=%s",
            metric.status,
            metric.duration_ms,
            metric.records_count,
            metric.error_type or "-",
        )


def _run_daemon(sched: CollectionScheduler) -> None:
    """守护模式：启动后台线程 + 主线程阻塞等信号。"""
    stop_event = sched._stop_flag  # 复用 scheduler 的 stop flag

    def _handle_signal(signum, _frame):
        logger.info("收到信号 %d，停止调度器...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("启动持续采集调度器，%d 个任务", len(sched.tasks))
    for t in sched.tasks:
        logger.info("  - %s: %s/%s 每 %ds", t.name, t.category, t.source, t.interval_sec)
    sched.start()
    logger.info("调度器已启动，主线程阻塞等待 SIGTERM/SIGINT")

    # 主线程阻塞（daemon 线程会随主线程退出）
    while not stop_event.is_set():
        time.sleep(1.0)

    sched.stop(timeout=5.0)
    logger.info("调度器已停止，进程退出")


def main() -> int:
    _setup_logging()
    args = sys.argv[1:]
    try:
        sched = _build_scheduler()
    except Exception as e:
        logger.error("调度器初始化失败: %s: %s", type(e).__name__, e)
        return 1

    if "--dry-run" in args:
        logger.info("=== DRY RUN: %d 个任务 ===", len(sched.tasks))
        for t in sched.tasks:
            logger.info(
                "  - %s: %s/%s params=%s interval=%ds",
                t.name,
                t.category,
                t.source,
                t.params,
                t.interval_sec,
            )
        return 0

    if "--once" in args:
        logger.info("=== ONCE: 对所有任务跑一次 ===")
        _run_once(sched)
        return 0

    _run_daemon(sched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
