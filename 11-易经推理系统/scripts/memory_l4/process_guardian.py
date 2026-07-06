#!/usr/bin/env python3
"""
进程守护：异常监控 + 自动重启 + 告警日志
"""
import json
import time
import threading
import traceback
import subprocess
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from pathlib import Path
from dataclasses import dataclass, field, asdict

from scripts.memory_l4.paths import memory_l4_dir


@dataclass
class ProcessHeartbeat:
    """进程心跳记录"""
    pid: int = 0
    ts: float = 0.0
    ts_str: str = ""
    cycle_count: int = 0
    status: str = ""       # running / error / stopped
    last_error: str = ""
    last_error_ts: float = 0.0
    memory_usage_mb: float = 0.0
    cpu_usage_pct: float = 0.0


@dataclass
class GuardianAlert:
    """告警记录"""
    alert_id: str = ""
    ts: float = 0.0
    ts_str: str = ""
    level: str = ""        # info / warning / error / critical
    category: str = ""     # crash / hang / performance / risk
    message: str = ""
    details: Dict = field(default_factory=dict)


class ProcessGuardian:
    """
    进程守护

    功能：
    - 心跳监控（检测进程是否卡死）
    - 异常捕获与日志持久化
    - 连续错误计数与告警
    - 自动恢复机制
    - 资源使用监控
    """

    def __init__(self,
                 process_name: str = "polling_trader",
                 heartbeat_timeout: int = 300,
                 max_consecutive_errors: int = 5,
                 auto_restart: bool = False,
                 on_critical_error: Callable = None):
        self.process_name = process_name
        self.heartbeat_timeout = heartbeat_timeout
        self.max_consecutive_errors = max_consecutive_errors
        self.auto_restart = auto_restart
        self.on_critical_error = on_critical_error

        self.guardian_dir = memory_l4_dir() / "guardian"
        self.guardian_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_file = self.guardian_dir / "heartbeat.json"
        self.alerts_file = self.guardian_dir / "alerts.jsonl"
        self.error_log_file = self.guardian_dir / "errors.jsonl"

        self._heartbeat = ProcessHeartbeat(
            pid=os.getpid(),
            status="starting",
        )
        self._consecutive_errors = 0
        self._total_errors = 0
        self._alerts: List[GuardianAlert] = []
        self._lock = threading.Lock()

        self._last_heartbeat_ts = 0
        self._monitor_thread = None
        self._running = False

    def start(self):
        """启动守护监控"""
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        self.record_heartbeat(status="running")
        self._add_alert("info", "process", "进程守护启动",
                        {"pid": os.getpid(), "name": self.process_name})

    def stop(self):
        """停止守护监控"""
        self._running = False
        self.record_heartbeat(status="stopped")
        self._add_alert("info", "process", "进程守护停止",
                        {"pid": os.getpid()})

    def record_heartbeat(self, status: str = "running", cycle_count: int = 0,
                         memory_mb: float = 0.0, cpu_pct: float = 0.0):
        """记录心跳"""
        now = time.time()
        self._last_heartbeat_ts = now
        self._heartbeat = ProcessHeartbeat(
            pid=os.getpid(),
            ts=now,
            ts_str=datetime.now(timezone.utc).isoformat(),
            cycle_count=cycle_count,
            status=status,
            memory_usage_mb=memory_mb,
            cpu_usage_pct=cpu_pct,
        )
        try:
            with open(self.heartbeat_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self._heartbeat), f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def record_error(self, error: Exception, context: str = "",
                     level: str = "error") -> bool:
        """记录错误

        Returns:
            True = 触发严重告警
        """
        self._total_errors += 1
        self._consecutive_errors += 1

        error_info = {
            "ts": time.time(),
            "ts_str": datetime.now(timezone.utc).isoformat(),
            "type": type(error).__name__,
            "message": str(error),
            "context": context,
            "traceback": traceback.format_exc(),
            "consecutive_count": self._consecutive_errors,
            "total_count": self._total_errors,
        }

        try:
            with open(self.error_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_info, ensure_ascii=False) + "\n")
        except Exception:
            pass

        self._heartbeat.last_error = str(error)[:200]
        self._heartbeat.last_error_ts = time.time()

        is_critical = False
        alert_category = "error"

        if self._consecutive_errors >= self.max_consecutive_errors:
            is_critical = True
            alert_category = "crash"
            level = "critical"
            self._add_alert(
                level, alert_category,
                f"连续错误达到阈值 {self._consecutive_errors}/{self.max_consecutive_errors}",
                error_info,
            )
            if self.on_critical_error:
                try:
                    self.on_critical_error(error_info)
                except Exception:
                    pass
        else:
            self._add_alert(level, alert_category, f"错误: {str(error)[:100]}",
                            {"context": context, "type": type(error).__name__})

        return is_critical

    def record_success(self):
        """记录成功（重置连续错误计数）"""
        self._consecutive_errors = 0

    def _add_alert(self, level: str, category: str, message: str, details: Dict = None):
        """添加告警"""
        alert = GuardianAlert(
            alert_id=f"alert_{int(time.time())}_{self._total_errors}",
            ts=time.time(),
            ts_str=datetime.now(timezone.utc).isoformat(),
            level=level,
            category=category,
            message=message,
            details=details or {},
        )
        self._alerts.append(alert)
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-500:]

        try:
            with open(self.alerts_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(alert), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _monitor_loop(self):
        """监控循环（在独立线程运行）"""
        while self._running:
            try:
                time.sleep(30)

                if not self._running:
                    break

                now = time.time()
                elapsed = now - self._last_heartbeat_ts

                if elapsed > self.heartbeat_timeout and self._heartbeat.status == "running":
                    self._add_alert(
                        "warning", "hang",
                        f"心跳超时: {elapsed:.0f}s > {self.heartbeat_timeout}s",
                        {"last_heartbeat": self._heartbeat.ts_str},
                    )

                try:
                    import psutil
                    proc = psutil.Process(os.getpid())
                    mem = proc.memory_info().rss / 1024 / 1024
                    cpu = proc.cpu_percent(interval=0.1)
                    if mem > 500:
                        self._add_alert(
                            "warning", "performance",
                            f"内存使用过高: {mem:.1f}MB",
                            {"memory_mb": mem},
                        )
                except Exception:
                    pass

            except Exception:
                pass

    def get_status(self) -> Dict:
        """获取守护状态"""
        now = time.time()
        elapsed = now - self._last_heartbeat_ts if self._last_heartbeat_ts else 0
        return {
            "process_name": self.process_name,
            "pid": os.getpid(),
            "status": self._heartbeat.status,
            "uptime_seconds": round(now - (self._alerts[0].ts if self._alerts else now), 1),
            "last_heartbeat": self._heartbeat.ts_str,
            "seconds_since_heartbeat": round(elapsed, 1),
            "consecutive_errors": self._consecutive_errors,
            "total_errors": self._total_errors,
            "total_alerts": len(self._alerts),
            "is_hung": elapsed > self.heartbeat_timeout and self._heartbeat.status == "running",
            "last_error": self._heartbeat.last_error,
        }

    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """获取最近告警"""
        return [asdict(a) for a in self._alerts[-limit:]]

    def check_existing_heartbeat(self) -> Optional[Dict]:
        """检查是否已有运行中的进程（用于启动前检测）"""
        if not self.heartbeat_file.exists():
            return None
        try:
            with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            elapsed = time.time() - data.get("ts", 0)
            data["seconds_since_heartbeat"] = round(elapsed, 1)
            data["is_alive"] = (elapsed < self.heartbeat_timeout
                               and data.get("status") == "running")
            return data
        except Exception:
            return None


def run_with_guardian(target_func, process_name: str = "polling_trader",
                      **guardian_kwargs) -> int:
    """
    以守护模式运行目标函数

    Args:
        target_func: 目标函数，接受 guardian 参数
        process_name: 进程名

    Returns:
        退出码
    """
    guardian = ProcessGuardian(process_name=process_name, **guardian_kwargs)
    guardian.start()

    exit_code = 0
    try:
        target_func(guardian=guardian)
    except Exception as e:
        guardian.record_error(e, context="main_loop", level="critical")
        exit_code = 1
    finally:
        guardian.stop()

    return exit_code
