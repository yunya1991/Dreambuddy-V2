"""
L2 自检测: DSH Subagent 心跳监控器
=====================================
每分钟自检:
  1. 9 个 subagent 心跳 - 最近调用时间在阈值内
  2. SubagentOutput 4 字段非空率 - module/summary/signals/charts

异常自动写认知库 tags=["auto-detected","anomaly"]
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class HeartbeatStatus(str, Enum):
    ALIVE = "alive"
    STALE = "stale"
    DEAD = "dead"


@dataclass
class SubagentHeartbeat:
    """单个 subagent 心跳记录"""
    subagent_type: str
    last_call_ts: Optional[str] = None
    last_call_duration_ms: Optional[float] = None
    last_status: str = "unknown"
    total_calls: int = 0
    error_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_call(self, duration_ms: float, status: str) -> None:
        """记录一次调用"""
        with self._lock:
            self.last_call_ts = datetime.utcnow().isoformat() + "Z"
            self.last_call_duration_ms = duration_ms
            self.last_status = status
            self.total_calls += 1
            if status != "ok":
                self.error_count += 1

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "subagent_type": self.subagent_type,
                "last_call_ts": self.last_call_ts,
                "last_call_duration_ms": self.last_call_duration_ms,
                "last_status": self.last_status,
                "total_calls": self.total_calls,
                "error_count": self.error_count,
            }


@dataclass
class SubagentOutputStats:
    """SubagentOutput 字段非空统计"""
    total_outputs: int = 0
    module_non_empty: int = 0
    summary_non_empty: int = 0
    signals_non_empty: int = 0
    charts_non_empty: int = 0

    def record_output(self, output: Dict[str, Any]) -> None:
        """记录一次 SubagentOutput 的字段非空情况"""
        self.total_outputs += 1
        if output.get("module"):
            self.module_non_empty += 1
        if output.get("summary"):
            self.summary_non_empty += 1
        if output.get("signals"):
            self.signals_non_empty += 1
        if output.get("charts"):
            self.charts_non_empty += 1

    @property
    def module_rate(self) -> float:
        return self.module_non_empty / self.total_outputs if self.total_outputs > 0 else 0.0

    @property
    def summary_rate(self) -> float:
        return self.summary_non_empty / self.total_outputs if self.total_outputs > 0 else 0.0

    @property
    def signals_rate(self) -> float:
        return self.signals_non_empty / self.total_outputs if self.total_outputs > 0 else 0.0

    @property
    def charts_rate(self) -> float:
        return self.charts_non_empty / self.total_outputs if self.total_outputs > 0 else 0.0


# 9 个 DSH subagent 类型
DSH_SUBAGENT_TYPES = [
    "technical", "sentiment", "macro", "flow",
    "onchain", "valuation", "risk", "portfolio",
    "synthesizer",
]


class DSHHeartbeatMonitor:
    """DSH Subagent 心跳监控器

    用法:
        monitor = DSHHeartbeatMonitor()
        monitor.record_call("technical", 150.0, "ok")
        monitor.record_output({"module": "technical", "summary": "...", "signals": [...], "charts": [...]})
        report = monitor.run_health_check()
    """

    def __init__(
        self,
        stale_threshold_seconds: int = 300,
        dead_threshold_seconds: int = 600,
        min_field_non_empty_rate: float = 0.9,
    ):
        self.stale_threshold_seconds = stale_threshold_seconds
        self.dead_threshold_seconds = dead_threshold_seconds
        self.min_field_non_empty_rate = min_field_non_empty_rate

        self.heartbeats: Dict[str, SubagentHeartbeat] = {
            t: SubagentHeartbeat(subagent_type=t) for t in DSH_SUBAGENT_TYPES
        }
        self.output_stats = SubagentOutputStats()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 记录接口
    # ------------------------------------------------------------------
    def record_call(self, subagent_type: str, duration_ms: float, status: str = "ok") -> None:
        """记录一次 subagent 调用"""
        if subagent_type not in self.heartbeats:
            with self._lock:
                self.heartbeats[subagent_type] = SubagentHeartbeat(subagent_type=subagent_type)
        self.heartbeats[subagent_type].record_call(duration_ms, status)

    def record_output(self, output: Dict[str, Any]) -> None:
        """记录一次 SubagentOutput 的字段统计"""
        with self._lock:
            self.output_stats.record_output(output)

    # ------------------------------------------------------------------
    # 检查 1: subagent 心跳
    # ------------------------------------------------------------------
    def check_subagent_heartbeats(self) -> Dict[str, Any]:
        """检查所有 subagent 心跳状态"""
        now = datetime.utcnow()
        results = {}
        alive_count = 0
        stale_count = 0
        dead_count = 0

        for subagent_type, hb in self.heartbeats.items():
            if hb.last_call_ts is None:
                status = HeartbeatStatus.DEAD
                dead_count += 1
            else:
                last_call = datetime.fromisoformat(hb.last_call_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                elapsed = (now - last_call).total_seconds()
                if elapsed > self.dead_threshold_seconds:
                    status = HeartbeatStatus.DEAD
                    dead_count += 1
                elif elapsed > self.stale_threshold_seconds:
                    status = HeartbeatStatus.STALE
                    stale_count += 1
                else:
                    status = HeartbeatStatus.ALIVE
                    alive_count += 1

            results[subagent_type] = {
                "status": status.value,
                "last_call_ts": hb.last_call_ts,
                "total_calls": hb.total_calls,
                "error_count": hb.error_count,
            }

        return {
            "alive": alive_count,
            "stale": stale_count,
            "dead": dead_count,
            "total": len(self.heartbeats),
            "subagents": results,
        }

    # ------------------------------------------------------------------
    # 检查 2: SubagentOutput 字段非空率
    # ------------------------------------------------------------------
    def check_output_field_non_empty_rate(self) -> Dict[str, Any]:
        """检查 SubagentOutput 4 字段非空率"""
        stats = self.output_stats
        rates = {
            "module": stats.module_rate,
            "summary": stats.summary_rate,
            "signals": stats.signals_rate,
            "charts": stats.charts_rate,
        }
        # 取最低字段的非空率作为整体指标
        min_rate = min(rates.values()) if rates else 0.0
        # 无 output 记录时视为达标（系统刚启动）
        if stats.total_outputs == 0:
            all_above_threshold = True
        else:
            all_above_threshold = all(r >= self.min_field_non_empty_rate for r in rates.values())

        return {
            "total_outputs": stats.total_outputs,
            "field_rates": rates,
            "min_rate": min_rate,
            "threshold": self.min_field_non_empty_rate,
            "all_above_threshold": all_above_threshold,
        }

    # ------------------------------------------------------------------
    # 汇总执行
    # ------------------------------------------------------------------
    def run_health_check(self) -> Dict[str, Any]:
        """执行全部检查并返回汇总报告"""
        heartbeat_result = self.check_subagent_heartbeats()
        output_result = self.check_output_field_non_empty_rate()

        # 整体状态判定
        if heartbeat_result["dead"] > 0:
            overall = "unhealthy"
        elif heartbeat_result["stale"] > 0 or not output_result["all_above_threshold"]:
            overall = "degraded"
        else:
            overall = "healthy"

        return {
            "overall_status": overall,
            "checked_at": datetime.utcnow().isoformat() + "Z",
            "heartbeats": heartbeat_result,
            "output_fields": output_result,
        }


def record_dsh_anomaly_to_cognitive(
    anomaly_msg: str,
    record_fn: Optional[Callable] = None,
) -> None:
    """将 DSH 异常写入认知库"""
    content = f"[auto-detected][anomaly] DSH 心跳异常: {anomaly_msg}"
    logger.warning(content)
    if record_fn is not None:
        try:
            record_fn(content=content, tags="auto-detected,anomaly,dsh")
        except Exception as e:
            logger.warning(f"认知库记录失败: {e}")
