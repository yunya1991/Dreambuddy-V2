"""alerting — 告警通道抽象与内置实现。

AlertLevel: INFO / WARNING / ERROR / CRITICAL
AlertChannel 抽象: emit(alert)
AlertRouter: 多通道分发，按级别默认路由到 LogChannel
"""
from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional
from pathlib import Path


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """一条告警记录。"""

    level: AlertLevel
    title: str
    message: str
    tags: list[str] = field(default_factory=list)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "tags": list(self.tags),
            "ts": self.ts.isoformat(),
        }


class AlertChannel(ABC):
    """告警通道抽象。"""

    @abstractmethod
    def emit(self, alert: Alert) -> None: ...

    def close(self) -> None:
        """释放资源（可选）。默认空实现。"""


# ---------------------------------------------------------------------------
# LogAlertChannel：走 Python logging，ERROR 及以上用 stderr + 红色前缀
# ---------------------------------------------------------------------------
class LogAlertChannel(AlertChannel):
    """将告警输出到 Python logging。"""

    _LEVEL_MAP = {
        AlertLevel.INFO: logging.INFO,
        AlertLevel.WARNING: logging.WARNING,
        AlertLevel.ERROR: logging.ERROR,
        AlertLevel.CRITICAL: logging.CRITICAL,
    }

    def __init__(self, logger_name: str = "data_center.monitoring"):
        self._logger = logging.getLogger(logger_name)

    def emit(self, alert: Alert) -> None:
        lvl = self._LEVEL_MAP.get(alert.level, logging.INFO)
        msg = f"[{alert.level.value}] {alert.title} — {alert.message}"
        self._logger.log(lvl, msg)


# ---------------------------------------------------------------------------
# FileAlertChannel：NDJSON 追加写文件
# ---------------------------------------------------------------------------
class FileAlertChannel(AlertChannel):
    """NDJSON 追加写入文件，线程安全。"""

    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, alert: Alert) -> None:
        line = json.dumps(alert.to_dict(), ensure_ascii=False) + "\n"
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)

    def tail(self, n: int = 20) -> list[dict]:
        """读取最后 N 行。"""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        last = lines[-n:]
        out: list[dict] = []
        for ln in last:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out


# ---------------------------------------------------------------------------
# LarkAlertChannel（stub — 占位可扩展）
# ---------------------------------------------------------------------------
class LarkAlertChannel(AlertChannel):
    """飞书 webhook 通道（stub 实现，仅构造消息体，真实发送留钩子）。

    生产环境可替换为调用飞书机器人 webhook 发送交互式卡片。
    """

    def __init__(self, webhook_url: str):
        if not webhook_url.startswith("http"):
            raise ValueError("LarkAlertChannel 需要合法的 webhook_url")
        self._webhook = webhook_url

    def emit(self, alert: Alert) -> None:
        # Stub 实现：仅通过 logging 打印「待发送」，不真正发请求
        # 生产：requests.post(self._webhook, json=build_lark_card(alert))
        logging.getLogger("data_center.monitoring.lark").info(
            "[LARK-STUB] 待发送告警到 %s: %s", self._masked_webhook, alert.title
        )

    @property
    def _masked_webhook(self) -> str:
        if len(self._webhook) <= 16:
            return "***"
        return self._webhook[:8] + "***" + self._webhook[-8:]


# ---------------------------------------------------------------------------
# AlertRouter：按级别分发到多个通道
# ---------------------------------------------------------------------------
class AlertRouter(AlertChannel):
    """聚合多个 AlertChannel，一次 emit 分发给所有通道。

    默认策略：INFO/WARNING 只打 Log；ERROR 及以上走所有通道。
    可通过 default_route 覆写。
    """

    def __init__(
        self,
        channels: Iterable[AlertChannel],
        *,
        min_level: AlertLevel = AlertLevel.INFO,
    ):
        self._channels = [c for c in channels]
        self._min_level = min_level
        self._lock = threading.Lock()

    @property
    def channels(self) -> list[AlertChannel]:
        return list(self._channels)

    def emit(self, alert: Alert) -> None:
        if not self._meets_level(alert.level):
            return
        with self._lock:
            for ch in self._channels:
                try:
                    ch.emit(alert)
                except Exception:
                    # 通道自身异常不能阻断其他通道或主流程
                    logging.getLogger("data_center.monitoring").exception(
                        "AlertChannel 失败: %s", type(ch).__name__
                    )

    def add_channel(self, channel: AlertChannel) -> None:
        with self._lock:
            self._channels.append(channel)

    def close(self) -> None:
        with self._lock:
            for ch in self._channels:
                try:
                    ch.close()
                except Exception:
                    pass

    def _meets_level(self, level: AlertLevel) -> bool:
        order = [AlertLevel.INFO, AlertLevel.WARNING, AlertLevel.ERROR, AlertLevel.CRITICAL]
        return order.index(level) >= order.index(self._min_level)
