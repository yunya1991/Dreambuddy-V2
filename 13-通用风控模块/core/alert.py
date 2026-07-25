"""
风控告警通知模块
================
风控事件触发时，通过飞书发送告警通知。

支持两种模式：
    1. OpenAPI 模式 — 复用 6-TRADING/scripts/feishu_notify.py 的接口
    2. Webhook 模式 — 轻量级 webhook 推送（无需飞书应用）

告警分级：
    - INFO:     信息通知（蓝色）
    - WARNING:  警告（黄色）
    - CRITICAL: 严重告警（红色）

使用方式：
    notifier = RiskAlertNotifier({
        "mode": "webhook",
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
    })
    notifier.alert_gate_block("BTC", "日回撤熔断", details={...})
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class AlertLevel(str, Enum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    """告警类别"""

    GATE_BLOCK = "gate_block"
    GATE_DEGRADE = "gate_degrade"
    EXIT_TRIGGER = "exit_trigger"
    DRAWDOWN = "drawdown"
    CONSECUTIVE_LOSS = "consecutive_loss"
    ML_MODEL = "ml_model"
    SYSTEM = "system"


@dataclass
class AlertEvent:
    """告警事件"""

    level: AlertLevel
    category: AlertCategory
    title: str
    message: str
    coin: str = ""
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def to_card(self) -> Dict[str, Any]:
        """构建飞书卡片消息"""
        color_map = {
            AlertLevel.INFO: "blue",
            AlertLevel.WARNING: "yellow",
            AlertLevel.CRITICAL: "red",
        }
        icon_map = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.CRITICAL: "🔴",
        }

        color = color_map.get(self.level, "blue")
        icon = icon_map.get(self.level, "ℹ️")

        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"{icon} **{self.message}**"}},
            {"tag": "hr"},
        ]

        if self.coin:
            elements.append(
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**币种**\n{self.coin}"},
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**类别**\n{self.category.value}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**级别**\n{self.level.value}"},
                        },
                        {
                            "is_short": True,
                            "text": {"tag": "lark_md", "content": f"**时间**\n{self.timestamp}"},
                        },
                    ],
                }
            )

        if self.details:
            detail_lines = []
            for k, v in self.details.items():
                detail_lines.append(f"  - **{k}**: {v}")
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "**详情**\n" + "\n".join(detail_lines)},
                }
            )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"[风控告警] {self.title}"},
                "template": color,
            },
            "elements": elements,
        }

    def to_text(self) -> str:
        """构建纯文本消息"""
        lines = [
            f"[风控告警] {self.title}",
            f"级别: {self.level.value}",
            f"类别: {self.category.value}",
        ]
        if self.coin:
            lines.append(f"币种: {self.coin}")
        lines.append(f"时间: {self.timestamp}")
        lines.append(f"详情: {self.message}")
        if self.details:
            for k, v in self.details.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


class RiskAlertNotifier:
    """风控告警通知器

    支持多渠道推送：
        - 飞书 Webhook（轻量级，无需应用凭证）
        - 飞书 OpenAPI（复用 feishu_notify.py，需应用凭证）
        - 本地文件日志（兜底）

    使用方式：
        notifier = RiskAlertNotifier({
            "mode": "webhook",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            "min_level": "warning",
        })
        notifier.alert(AlertEvent(
            level=AlertLevel.CRITICAL,
            category=AlertCategory.GATE_BLOCK,
            title="日回撤熔断",
            message="日回撤 12% 超过熔断阈值 10%",
            coin="BTC",
        ))
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.mode = self.config.get("mode", "webhook")
        self.webhook_url = self.config.get("webhook_url", "")
        self.min_level = AlertLevel(self.config.get("min_level", "warning"))
        self.log_file = self.config.get("log_file", "")
        self._feishu_module = None
        self._history: List[AlertEvent] = []
        self._rate_limit: Dict[str, float] = {}
        self._rate_limit_sec = self.config.get("rate_limit_sec", 60)

        self._level_order = {
            AlertLevel.INFO: 0,
            AlertLevel.WARNING: 1,
            AlertLevel.CRITICAL: 2,
        }

    def _should_send(self, level: AlertLevel) -> bool:
        """检查是否满足发送级别"""
        return self._level_order.get(level, 0) >= self._level_order.get(self.min_level, 1)

    def _is_rate_limited(self, key: str) -> bool:
        """检查是否被限频"""
        now = time.time()
        last = self._rate_limit.get(key, 0)
        if now - last < self._rate_limit_sec:
            return True
        self._rate_limit[key] = now
        return False

    def alert(self, event: AlertEvent) -> bool:
        """发送告警

        Args:
            event: 告警事件

        Returns:
            是否发送成功
        """
        self._history.append(event)

        if not self._should_send(event.level):
            return False

        rate_key = f"{event.category.value}:{event.coin}"
        if self._is_rate_limited(rate_key):
            return False

        success = False

        if self.mode == "webhook" and self.webhook_url:
            success = self._send_webhook(event)
        elif self.mode == "openapi":
            success = self._send_openapi(event)
        elif self.mode == "file":
            success = True

        if self.log_file:
            self._log_to_file(event, success)

        return success

    def _send_webhook(self, event: AlertEvent) -> bool:
        """通过 Webhook 发送"""
        try:
            import urllib.request

            payload = {
                "msg_type": "interactive",
                "card": event.to_card(),
            }

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                return result.get("code", -1) == 0 or result.get("StatusCode", -1) == 0

        except Exception:
            return False

    def _send_openapi(self, event: AlertEvent) -> bool:
        """通过飞书 OpenAPI 发送（复用 feishu_notify.py）"""
        if self._feishu_module is None:
            self._feishu_module = self._load_feishu_module()

        if self._feishu_module is None:
            return self._send_webhook(event)

        try:
            fn = self._feishu_module
            channel = self.config.get("feishu_channel", "risk")
            card = event.to_card()

            if hasattr(fn, "send_to"):
                msg_id = fn.send_to(channel, "interactive", card)
                return msg_id is not None
        except Exception:
            pass

        return False

    def _load_feishu_module(self):
        """加载 feishu_notify 模块"""
        candidates = [
            Path(__file__).resolve().parent.parent.parent
            / "6-TRADING"
            / "scripts"
            / "feishu_notify.py",
            Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING/scripts/feishu_notify.py"),
        ]

        for p in candidates:
            if p.exists():
                try:
                    import importlib.util

                    spec = importlib.util.spec_from_file_location("feishu_notify", str(p))
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    return mod
                except Exception:
                    continue

        return None

    def _log_to_file(self, event: AlertEvent, sent: bool):
        """写入本地日志文件"""
        try:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "a") as f:
                f.write(
                    f"[{event.timestamp}] [{event.level.value}] [{event.category.value}] "
                    f"{'[SENT]' if sent else '[LOCAL]'} "
                    f"{event.title} | {event.coin} | {event.message}\n"
                )
                if event.details:
                    for k, v in event.details.items():
                        f.write(f"  {k}: {v}\n")
                f.write("\n")
        except Exception:
            pass

    # ── 便捷方法 ──────────────────────────────────────────

    def alert_gate_block(
        self,
        coin: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
        level: AlertLevel = AlertLevel.CRITICAL,
    ):
        """门禁阻断告警"""
        return self.alert(
            AlertEvent(
                level=level,
                category=AlertCategory.GATE_BLOCK,
                title="交易门禁阻断",
                message=reason,
                coin=coin,
                details=details or {},
            )
        )

    def alert_gate_degrade(
        self,
        coin: str,
        reason: str,
        modifier: float,
        details: Optional[Dict[str, Any]] = None,
    ):
        """门禁降级告警"""
        d = {"position_modifier": modifier}
        if details:
            d.update(details)
        return self.alert(
            AlertEvent(
                level=AlertLevel.WARNING,
                category=AlertCategory.GATE_DEGRADE,
                title="交易门禁降级",
                message=f"{reason} (仓位×{modifier:.2f})",
                coin=coin,
                details=d,
            )
        )

    def alert_exit_trigger(
        self,
        coin: str,
        action: str,
        reason: str,
        priority: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        """离场触发告警"""
        level = AlertLevel.CRITICAL if "p0" in priority.lower() else AlertLevel.WARNING
        d = {"action": action, "priority": priority}
        if details:
            d.update(details)
        return self.alert(
            AlertEvent(
                level=level,
                category=AlertCategory.EXIT_TRIGGER,
                title=f"离场触发: {action.upper()}",
                message=reason,
                coin=coin,
                details=d,
            )
        )

    def alert_drawdown(
        self,
        drawdown_pct: float,
        threshold_pct: float,
        details: Optional[Dict[str, Any]] = None,
    ):
        """回撤告警"""
        level = AlertLevel.CRITICAL if drawdown_pct >= threshold_pct else AlertLevel.WARNING
        d = {"drawdown_pct": f"{drawdown_pct:.2%}", "threshold_pct": f"{threshold_pct:.2%}"}
        if details:
            d.update(details)
        return self.alert(
            AlertEvent(
                level=level,
                category=AlertCategory.DRAWDOWN,
                title="日回撤告警",
                message=f"日回撤 {drawdown_pct:.2%}"
                + (
                    f" 超过阈值 {threshold_pct:.2%}"
                    if drawdown_pct >= threshold_pct
                    else " 接近阈值"
                ),
                details=d,
            )
        )

    def alert_consecutive_loss(
        self,
        count: int,
        threshold: int,
        details: Optional[Dict[str, Any]] = None,
    ):
        """连续亏损告警"""
        level = AlertLevel.CRITICAL if count >= threshold else AlertLevel.WARNING
        d = {"consecutive_losses": count, "threshold": threshold}
        if details:
            d.update(details)
        return self.alert(
            AlertEvent(
                level=level,
                category=AlertCategory.CONSECUTIVE_LOSS,
                title="连续亏损告警",
                message=f"连续亏损 {count} 次"
                + (f"，达到上限 {threshold}" if count >= threshold else ""),
                details=d,
            )
        )

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取告警历史"""
        return [
            {
                "level": e.level.value,
                "category": e.category.value,
                "title": e.title,
                "message": e.message,
                "coin": e.coin,
                "timestamp": e.timestamp,
                "details": e.details,
            }
            for e in self._history[-limit:]
        ]

    def clear_history(self):
        """清空告警历史"""
        self._history.clear()
        self._rate_limit.clear()
