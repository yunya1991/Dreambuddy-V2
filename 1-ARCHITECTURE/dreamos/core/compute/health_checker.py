"""
L2 自检测: DreamOS 运行时健康检查器
=====================================
每分钟自检:
  1. 节点注册表完整性 - 所有注册节点都能加载且 validate 通过
  2. Budget 余量 - 剩余 token 预算 > 阈值
  3. Reflector 输出异常率 - 最近 N 次 Reflector 输出中异常比例

异常自动写认知库 tags=["auto-detected","anomaly"]
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """单项检查结果"""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at,
        }


@dataclass
class SystemHealthReport:
    """系统整体健康报告"""
    overall_status: HealthStatus
    checks: List[HealthCheckResult]
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "checks": [c.to_dict() for c in self.checks],
            "checked_at": self.checked_at,
        }

    @property
    def anomaly_count(self) -> int:
        return sum(1 for c in self.checks if c.status != HealthStatus.HEALTHY)


class DreamOSHealthChecker:
    """DreamOS 运行时健康检查器

    用法:
        checker = DreamOSHealthChecker(
            node_registry=registry,
            budget_getter=lambda: state.budget,
            reflector_history_getter=lambda: reflector.history,
        )
        report = checker.run_all_checks()
        if report.anomaly_count > 0:
            for anomaly in report.checks:
                if anomaly.status != HealthStatus.HEALTHY:
                    record_anomaly(anomaly)
    """

    def __init__(
        self,
        node_registry=None,
        budget_getter: Optional[Callable[[], float]] = None,
        reflector_history_getter: Optional[Callable[[], List[Dict]]] = None,
        min_budget_threshold: float = 1000.0,
        reflector_anomaly_rate_threshold: float = 0.3,
        reflector_window_size: int = 20,
    ):
        self.node_registry = node_registry
        self.budget_getter = budget_getter
        self.reflector_history_getter = reflector_history_getter
        self.min_budget_threshold = min_budget_threshold
        self.reflector_anomaly_rate_threshold = reflector_anomaly_rate_threshold
        self.reflector_window_size = reflector_window_size

    # ------------------------------------------------------------------
    # 检查 1: 节点注册表完整性
    # ------------------------------------------------------------------
    def check_node_registry_integrity(self) -> HealthCheckResult:
        """检查所有注册节点都能加载且 validate 通过"""
        if self.node_registry is None:
            return HealthCheckResult(
                name="node_registry_integrity",
                status=HealthStatus.DEGRADED,
                message="node_registry 未配置",
                details={"configured": False},
            )

        try:
            nodes = self.node_registry.list_nodes()
            total = len(nodes)
            valid_count = 0
            invalid_nodes: List[str] = []

            for node in nodes:
                try:
                    error = node.validate()
                    if error is None:
                        valid_count += 1
                    else:
                        invalid_nodes.append(f"{node.node_id}: {error}")
                except Exception as e:
                    invalid_nodes.append(f"{node.node_id}: validate异常 {e}")

            if total == 0:
                return HealthCheckResult(
                    name="node_registry_integrity",
                    status=HealthStatus.UNHEALTHY,
                    message="注册表为空，无任何节点",
                    details={"total": 0},
                )

            if valid_count == total:
                return HealthCheckResult(
                    name="node_registry_integrity",
                    status=HealthStatus.HEALTHY,
                    message=f"全部 {total} 个节点通过完整性检查",
                    details={"total": total, "valid": valid_count},
                )
            elif valid_count > 0:
                return HealthCheckResult(
                    name="node_registry_integrity",
                    status=HealthStatus.DEGRADED,
                    message=f"{valid_count}/{total} 节点有效",
                    details={"total": total, "valid": valid_count, "invalid": invalid_nodes},
                )
            else:
                return HealthCheckResult(
                    name="node_registry_integrity",
                    status=HealthStatus.UNHEALTHY,
                    message=f"全部 {total} 个节点无效",
                    details={"total": total, "valid": 0, "invalid": invalid_nodes},
                )
        except Exception as e:
            return HealthCheckResult(
                name="node_registry_integrity",
                status=HealthStatus.UNHEALTHY,
                message=f"注册表检查异常: {e}",
                details={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # 检查 2: Budget 余量
    # ------------------------------------------------------------------
    def check_budget_remaining(self) -> HealthCheckResult:
        """检查剩余 token 预算是否充足"""
        if self.budget_getter is None:
            return HealthCheckResult(
                name="budget_remaining",
                status=HealthStatus.DEGRADED,
                message="budget_getter 未配置",
                details={"configured": False},
            )

        try:
            remaining = float(self.budget_getter())
            if remaining >= self.min_budget_threshold:
                return HealthCheckResult(
                    name="budget_remaining",
                    status=HealthStatus.HEALTHY,
                    message=f"预算充足: {remaining:.0f} tokens",
                    details={"remaining": remaining, "threshold": self.min_budget_threshold},
                )
            elif remaining > 0:
                return HealthCheckResult(
                    name="budget_remaining",
                    status=HealthStatus.DEGRADED,
                    message=f"预算不足: {remaining:.0f} < {self.min_budget_threshold:.0f}",
                    details={"remaining": remaining, "threshold": self.min_budget_threshold},
                )
            else:
                return HealthCheckResult(
                    name="budget_remaining",
                    status=HealthStatus.UNHEALTHY,
                    message=f"预算耗尽: {remaining:.0f}",
                    details={"remaining": remaining, "threshold": self.min_budget_threshold},
                )
        except Exception as e:
            return HealthCheckResult(
                name="budget_remaining",
                status=HealthStatus.UNHEALTHY,
                message=f"预算检查异常: {e}",
                details={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # 检查 3: Reflector 输出异常率
    # ------------------------------------------------------------------
    def check_reflector_anomaly_rate(self) -> HealthCheckResult:
        """检查最近 N 次 Reflector 输出的异常比例"""
        if self.reflector_history_getter is None:
            return HealthCheckResult(
                name="reflector_anomaly_rate",
                status=HealthStatus.DEGRADED,
                message="reflector_history_getter 未配置",
                details={"configured": False},
            )

        try:
            history = self.reflector_history_getter() or []
            window = history[-self.reflector_window_size:]
            total = len(window)

            if total == 0:
                return HealthCheckResult(
                    name="reflector_anomaly_rate",
                    status=HealthStatus.HEALTHY,
                    message="无 Reflector 历史记录（系统刚启动）",
                    details={"total": 0},
                )

            anomaly_count = sum(
                1 for item in window
                if self._is_reflector_anomaly(item)
            )
            anomaly_rate = anomaly_count / total

            if anomaly_rate <= self.reflector_anomaly_rate_threshold:
                return HealthCheckResult(
                    name="reflector_anomaly_rate",
                    status=HealthStatus.HEALTHY,
                    message=f"Reflector 异常率 {anomaly_rate:.1%} 在阈值内",
                    details={
                        "total": total,
                        "anomalies": anomaly_count,
                        "anomaly_rate": anomaly_rate,
                        "threshold": self.reflector_anomaly_rate_threshold,
                    },
                )
            else:
                return HealthCheckResult(
                    name="reflector_anomaly_rate",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Reflector 异常率 {anomaly_rate:.1%} 超过阈值 {self.reflector_anomaly_rate_threshold:.0%}",
                    details={
                        "total": total,
                        "anomalies": anomaly_count,
                        "anomaly_rate": anomaly_rate,
                        "threshold": self.reflector_anomaly_rate_threshold,
                    },
                )
        except Exception as e:
            return HealthCheckResult(
                name="reflector_anomaly_rate",
                status=HealthStatus.UNHEALTHY,
                message=f"Reflector 检查异常: {e}",
                details={"error": str(e)},
            )

    @staticmethod
    def _is_reflector_anomaly(item: Dict) -> bool:
        """判断一条 Reflector 输出是否异常"""
        if not isinstance(item, dict):
            return True
        # 异常标志：status != success 或 has_error 为真 或 confidence 极低
        status = str(item.get("status", "")).lower()
        if status in ("error", "failed", "exception"):
            return True
        if item.get("has_error") or item.get("error"):
            return True
        confidence = item.get("confidence")
        if confidence is not None and float(confidence) < 0.3:
            return True
        return False

    # ------------------------------------------------------------------
    # 汇总执行
    # ------------------------------------------------------------------
    def run_all_checks(self) -> SystemHealthReport:
        """执行全部检查并返回汇总报告"""
        checks = [
            self.check_node_registry_integrity(),
            self.check_budget_remaining(),
            self.check_reflector_anomaly_rate(),
        ]

        # 整体状态：任何 UNHEALTHY → UNHEALTHY；否则有 DEGRADED → DEGRADED；否则 HEALTHY
        if any(c.status == HealthStatus.UNHEALTHY for c in checks):
            overall = HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in checks):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealthReport(overall_status=overall, checks=checks)


def record_anomaly_to_cognitive(
    anomaly: HealthCheckResult,
    record_fn: Optional[Callable] = None,
) -> None:
    """将异常记录写入认知库

    Args:
        anomaly: 异常检查结果
        record_fn: 认知库 record 函数，签名 (content, tags)
                   若为 None 则仅日志告警
    """
    content = (
        f"[auto-detected][anomaly] DreamOS 健康检查异常: {anomaly.name} | "
        f"status={anomaly.status.value} | {anomaly.message}"
    )
    logger.warning(content)

    if record_fn is not None:
        try:
            record_fn(content=content, tags="auto-detected,anomaly,dreamos")
        except Exception as e:
            logger.warning(f"认知库记录失败: {e}")
