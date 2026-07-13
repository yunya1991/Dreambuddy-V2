"""
Dream OS 定时调度器

支持:
    - cron 表达式配置定时任务
    - 多币种扫描调度
    - 任务状态管理
    - 执行历史记录
    - 邮件/通知提醒

用法:
    scheduler = DreamOSScheduler()
    scheduler.add_job('scan_btc', '*/5 * * * *', lambda: analyze('BTC'))
    scheduler.start()
"""

from __future__ import annotations

import time
import threading
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Optional, List
from enum import Enum
from pathlib import Path
from collections import defaultdict

try:
    import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class ScheduledJob:
    def __init__(
        self,
        name: str,
        cron_expr: str,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ):
        self.name = name
        self.cron_expr = cron_expr
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.enabled = enabled
        self.status = JobStatus.STOPPED
        self.last_run = None
        self.next_run = None
        self.run_count = 0
        self.error_count = 0
        self.last_error = None
        self._thread = None
        self._stop_event = threading.Event()

    def _calculate_next_run(self) -> Optional[datetime]:
        if not HAS_CRONITER:
            return None
        try:
            cron = croniter.croniter(self.cron_expr, datetime.now())
            return cron.get_next(datetime)
        except Exception:
            return None

    def _run_once(self):
        try:
            self.status = JobStatus.RUNNING
            self.func(*self.args, **self.kwargs)
            self.run_count += 1
            self.last_run = datetime.now()
            self.last_error = None
            logger.info(f"Job '{self.name}' completed successfully")
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            logger.error(f"Job '{self.name}' failed: {e}")
        finally:
            self.status = JobStatus.STOPPED
            self.next_run = self._calculate_next_run()

    def _scheduler_loop(self):
        while not self._stop_event.is_set():
            if not self.enabled:
                time.sleep(5)
                continue

            now = datetime.now()
            if self.next_run and now >= self.next_run:
                self._run_once()

            sleep_time = 1
            if self.next_run:
                diff = (self.next_run - now).total_seconds()
                sleep_time = max(1, min(diff, 60))

            time.sleep(sleep_time)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.next_run = self._calculate_next_run()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info(f"Job '{self.name}' started with cron: {self.cron_expr}")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.status = JobStatus.STOPPED
        logger.info(f"Job '{self.name}' stopped")

    def pause(self):
        self.enabled = False
        self.status = JobStatus.PAUSED

    def resume(self):
        self.enabled = True
        self.status = JobStatus.RUNNING

    def run_now(self):
        threading.Thread(target=self._run_once, daemon=True).start()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cron_expr": self.cron_expr,
            "enabled": self.enabled,
            "status": self.status,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


class DreamOSScheduler:
    """Dream OS 定时调度器"""

    def __init__(self, data_dir: Optional[str] = None):
        self.jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._stop_event = threading.Event()
        self._history: List[Dict[str, Any]] = []
        self._history_lock = threading.Lock()
        self.data_dir = Path(data_dir or "./scheduler_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_history()
        self._load_jobs()

    def add_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        run_now: bool = False,
    ) -> ScheduledJob:
        if name in self.jobs:
            self.remove_job(name)

        job = ScheduledJob(name, cron_expr, func, args, kwargs, enabled)
        self.jobs[name] = job

        if enabled:
            job.start()
        if run_now:
            job.run_now()

        self._save_jobs()
        return job

    def remove_job(self, name: str):
        if name in self.jobs:
            self.jobs[name].stop()
            del self.jobs[name]
            self._save_jobs()

    def get_job(self, name: str) -> Optional[ScheduledJob]:
        return self.jobs.get(name)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [job.to_dict() for job in self.jobs.values()]

    def start(self):
        self._running = True
        logger.info("Dream OS Scheduler started")

    def stop(self):
        self._running = False
        self._stop_event.set()
        for job in self.jobs.values():
            job.stop()
        self._save_history()
        logger.info("Dream OS Scheduler stopped")

    def pause_all(self):
        for job in self.jobs.values():
            job.pause()

    def resume_all(self):
        for job in self.jobs.values():
            job.resume()

    def run_all_now(self):
        for job in self.jobs.values():
            job.run_now()

    def add_scan_job(
        self,
        name: str,
        cron_expr: str,
        symbols: List[str],
        scan_func: Callable[[str], Any],
        enabled: bool = True,
    ) -> ScheduledJob:
        def _scan_all():
            for symbol in symbols:
                try:
                    result = scan_func(symbol)
                    self._record_history(symbol, "scan", result)
                except Exception as e:
                    self._record_history(symbol, "scan_error", {"error": str(e)})

        if name in self.jobs:
            self.remove_job(name)
        job = ScheduledJob(name, cron_expr, _scan_all, (), {}, enabled)
        job.symbols = symbols
        self.jobs[name] = job
        if enabled:
            job.start()
        self._save_jobs()
        return job

    def _record_history(self, symbol: str, action: str, result: Any):
        record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "action": action,
            "result": result,
        }
        with self._history_lock:
            self._history.append(record)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]
        self._save_history()

    def _save_history(self):
        history_file = self.data_dir / "scheduler_history.json"
        with self._history_lock:
            with open(history_file, "w") as f:
                json.dump(self._history, f, indent=2, default=str)

    def _load_history(self):
        history_file = self.data_dir / "scheduler_history.json"
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    self._history = json.load(f)
            except Exception:
                self._history = []

    def _save_jobs(self):
        jobs_file = self.data_dir / "scheduler_jobs.json"
        jobs_data = []
        for job in self.jobs.values():
            jobs_data.append({
                "name": job.name,
                "cron_expr": job.cron_expr,
                "enabled": job.enabled,
                "symbols": getattr(job, "symbols", []),
            })
        with open(jobs_file, "w") as f:
            json.dump(jobs_data, f, indent=2)

    def _load_jobs(self):
        jobs_file = self.data_dir / "scheduler_jobs.json"
        if jobs_file.exists():
            try:
                with open(jobs_file, "r") as f:
                    jobs_data = json.load(f)
                for job_data in jobs_data:
                    name = job_data["name"]
                    cron_expr = job_data["cron_expr"]
                    enabled = job_data.get("enabled", True)
                    symbols = job_data.get("symbols", [])

                    def _scan_single(symbol: str):
                        from dreamos.cli.auto_trader import AutoTrader
                        trader = AutoTrader(dry_run=True)
                        try:
                            return trader.run_auto_trade(symbol)
                        except Exception as e:
                            logger.warning(f"调度扫描 {symbol} 失败: {e}")
                            return {"error": str(e)}

                    if symbols:
                        self.add_scan_job(name, cron_expr, symbols, _scan_single, enabled=enabled)
                    else:
                        self.add_job(name, cron_expr, lambda: None, enabled=enabled)
            except Exception as e:
                logger.warning(f"加载调度任务失败: {e}")

    def get_history(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._history_lock:
            results = self._history.copy()
            if symbol:
                results = [r for r in results if r.get("symbol") == symbol]
            return results[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "total_jobs": len(self.jobs),
            "running_jobs": sum(1 for j in self.jobs.values() if j.status == JobStatus.RUNNING),
            "paused_jobs": sum(1 for j in self.jobs.values() if j.status == JobStatus.PAUSED),
            "total_runs": sum(j.run_count for j in self.jobs.values()),
            "total_errors": sum(j.error_count for j in self.jobs.values()),
            "history_count": len(self._history),
        }
        return stats

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


PRESET_CRON = {
    "every_minute": "* * * * *",
    "every_5_minutes": "*/5 * * * *",
    "every_15_minutes": "*/15 * * * *",
    "every_hour": "0 * * * *",
    "every_4_hours": "0 */4 * * *",
    "daily_9am": "0 9 * * *",
    "daily_9pm": "0 21 * * *",
    "weekly_monday": "0 9 * * 1",
}

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "MATIC"]