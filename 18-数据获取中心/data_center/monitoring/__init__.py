"""data_center.monitoring — 调用统计 / 数据质量 / 告警通道。"""
from data_center.monitoring.metrics import (
    InvocationMetric,
    MetricsStore,
)
from data_center.monitoring.alerting import (
    Alert,
    AlertChannel,
    AlertLevel,
    AlertRouter,
    FileAlertChannel,
    LarkAlertChannel,
    LogAlertChannel,
)
from data_center.monitoring.quality import (
    QualityChecker,
    QualityIssue,
    QualityIssueCode,
)
from dataclasses import dataclass
from typing import Optional


@dataclass
class MonitoringBundle:
    """DataCenter 监控三件套聚合，方便一次注入。"""

    metrics: MetricsStore
    quality: QualityChecker
    alerts: AlertRouter

    def close(self) -> None:
        """释放资源（FileChannel flush 等）。"""
        try:
            self.alerts.close()
        except Exception:
            pass


_DEFAULT_BUNDLE: Optional[MonitoringBundle] = None


def default_monitoring_bundle(
    *,
    alerts_file: Optional[str] = None,
    lark_webhook: Optional[str] = None,
) -> MonitoringBundle:
    """默认 bundle：LogChannel 必开；File/Lark 按需。

    调用方未传 monitoring 时 DataCenter 使用此函数构造默认值。
    """
    import os

    channels: list[AlertChannel] = [LogAlertChannel()]
    file_path = alerts_file or os.environ.get("DATA_CENTER_ALERTS_FILE")
    if file_path:
        channels.append(FileAlertChannel(file_path))
    if lark_webhook:
        channels.append(LarkAlertChannel(lark_webhook))

    router = AlertRouter(channels)
    return MonitoringBundle(
        metrics=MetricsStore(),
        quality=QualityChecker(),
        alerts=router,
    )


__all__ = [
    "InvocationMetric",
    "MetricsStore",
    "Alert",
    "AlertLevel",
    "AlertChannel",
    "LogAlertChannel",
    "FileAlertChannel",
    "LarkAlertChannel",
    "AlertRouter",
    "QualityIssue",
    "QualityIssueCode",
    "QualityChecker",
    "MonitoringBundle",
    "default_monitoring_bundle",
]
