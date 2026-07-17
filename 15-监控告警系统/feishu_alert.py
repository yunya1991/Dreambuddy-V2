#!/usr/bin/env python3
"""
统一飞书告警模块
所有监控系统共用此模块发送飞书告警

告警类型: heartbeat/trading/model/position/system/performance
严重级别: critical/error/warning/info

用法:
  from feishu_alert import send_alert, notify_heartbeat_timeout
  send_alert("heartbeat", "critical", "进程异常", {"pid": 123})
"""
import json
import os
import requests
from datetime import datetime
from typing import Dict, Optional


FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "cli_aa9442bde4b89be9")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70")

CHAT_IDS = {
    "risk": "oc_20fcedf0c35035568ea8fa947380f75d",
    "management": "oc_9cf9f141613b4e6a0f34651843cf8b9b",
    "trading": "oc_36c8543cea823b7546fcaad55d111f9f",
    "research": "oc_36c575b6f39a8df3dd75057a96685a21",
}

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

ALERT_COLOR_MAP = {
    "critical": "#ff4d4f",
    "error": "#ff7875",
    "warning": "#faad14",
    "info": "#1890ff",
}

ALERT_EMOJI = {
    "critical": "🔴",
    "error": "🟠",
    "warning": "🟡",
    "info": "🔵",
}

CHANNEL_MAP = {
    "critical": "risk",
    "error": "risk",
    "warning": "trading",
    "info": "management",
}

FEISHU_CREDENTIALS_VALID = bool(FEISHU_APP_ID and FEISHU_APP_SECRET)


def get_token() -> str:
    resp = requests.post(TOKEN_URL, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(f"token error: {data}")
    return data["tenant_access_token"]


def send_message(chat_id: str, msg_type: str, content: dict) -> dict:
    token = get_token()
    resp = requests.post(MSG_URL, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, json={
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": json.dumps(content, ensure_ascii=False),
    }, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    if result["code"] != 0:
        raise RuntimeError(f"send error: {result}")
    return result


def card(title: str, level: str, elements: list) -> dict:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{ALERT_EMOJI.get(level,'🔵')} {title}"},
            "template": ALERT_COLOR_MAP.get(level, "#1890ff"),
        },
        "body": {"elements": elements},
    }


def md(text: str) -> dict:
    return {"tag": "markdown", "content": text}


def hr() -> dict:
    return {"tag": "hr"}


def send_alert(alert_type: str, level: str, message: str, details: Dict = None, system: str = ""):
    if not FEISHU_CREDENTIALS_VALID:
        print(f"[WARN] 飞书凭证未配置，跳过告警: {alert_type} | {level} | {message[:50]}")
        return None

    type_label = {
        "heartbeat": "心跳监控",
        "trading": "交易风控",
        "model": "模型推理",
        "position": "持仓管理",
        "system": "系统错误",
        "performance": "性能告警",
    }.get(alert_type, alert_type)

    channel = CHANNEL_MAP.get(level, "management")
    chat_id = CHAT_IDS[channel]

    prefix = f"[{system}] " if system else ""
    title = f"{prefix}{type_label} 告警"

    elements = [
        md(f"**告警消息**\n{message}"),
    ]

    if details:
        elements.append(hr())
        detail_lines = []
        for k, v in details.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)[:200]
            detail_lines.append(f"- **{k}**: `{v}`")
        elements.append(md("\n".join(detail_lines)))

    elements.append(hr())
    elements.append(md(f"_时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 级别: {level}_"))

    result = send_message(chat_id, "interactive", card(title, level, elements))
    msg_id = result["data"]["message_id"]
    print(f"[OK] 飞书告警已发送 -> #{channel} (msg_id: {msg_id})")
    return msg_id


def notify_heartbeat_timeout(system: str, idle_minutes: float, threshold: float = 30):
    details = {"空闲时间": f"{idle_minutes:.1f}分钟", "阈值": f"{threshold}分钟"}
    level = "critical" if idle_minutes > threshold * 2 else "error"
    send_alert("heartbeat", level,
               f"进程心跳超时！已空闲 {idle_minutes:.0f} 分钟（阈值 {threshold} 分钟）",
               details, system)


def notify_process_error(system: str, error_message: str, context: str = ""):
    details = {"错误信息": error_message[:200], "上下文": context}
    send_alert("heartbeat", "critical",
               f"进程异常终止: {error_message[:100]}", details, system)


def notify_trading_halted(system: str, reason: str, consecutive_losses: int, daily_pnl: float = 0):
    details = {"连续亏损": f"{consecutive_losses}次", "日盈亏": f"{daily_pnl:.2f} USDT", "原因": reason}
    send_alert("trading", "critical", f"交易暂停！{reason}", details, system)


def notify_consecutive_losses(system: str, symbol: str, count: int, max_count: int = 5):
    details = {"币种": symbol, "连续亏损": f"{count}/{max_count}次"}
    level = "critical" if count >= max_count else "warning"
    send_alert("trading", level, f"{symbol} 连续亏损 {count} 次", details, system)


def notify_model_error(system: str, error_message: str, symbol: str = ""):
    details = {"币种": symbol or "ALL", "错误": error_message[:200]}
    send_alert("model", "error", f"模型推理异常: {error_message[:100]}", details, system)


def notify_position_close(system: str, symbol: str, reason: str, pnl: float = 0, pnl_pct: float = 0):
    details = {"币种": symbol, "离场原因": reason, "盈亏": f"{pnl:.2f} USDT ({pnl_pct:.2f}%)"}
    level = "critical" if pnl_pct < -10 else "warning" if pnl_pct < 0 else "info"
    send_alert("position", level, f"{symbol} 已平仓 | {reason} | {pnl_pct:+.2f}%", details, system)


def notify_system_error(system: str, error_message: str, component: str = ""):
    details = {"组件": component, "错误": error_message[:200]}
    send_alert("system", "critical", f"系统错误: {error_message[:100]}", details, system)


def notify_performance_degrade(system: str, metric: str, current: float, threshold: float, direction: str = "below"):
    details = {"指标": metric, "当前值": current, "阈值": threshold, "方向": direction}
    level = "critical" if direction == "below" and current < threshold * 0.5 else "warning"
    send_alert("performance", level,
               f"性能指标 {metric} {direction}阈值！当前={current}, 阈值={threshold}",
               details, system)


def notify_status_summary(system: str, health: bool, status: str, detail: Dict):
    if not FEISHU_CREDENTIALS_VALID:
        print("[WARN] 飞书凭证未配置，跳过状态汇总")
        return None

    level = "info" if health else "critical"
    elements = [
        md(f"**状态**: {'✅ 正常' if health else '🔴 异常'}"),
        md(f"**详情**: {status}"),
        hr(),
    ]

    if detail:
        for k, v in detail.items():
            if isinstance(v, dict):
                continue
            elements.append(md(f"- **{k}**: `{v}`"))

    elements.append(md(f"_时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"))

    chat_id = CHAT_IDS["management"]
    result = send_message(chat_id, "interactive", card(
        f"[{system}] 状态汇总", level, elements
    ))
    print(f"[OK] 状态汇总已发送 -> #management (msg_id: {result['data']['message_id']})")
    return result


def notify_trade_execution(system: str, action: str, symbol: str, price: float, pnl: float = 0, pnl_pct: float = 0):
    details = {"操作": action, "币种": symbol, "价格": f"{price:.2f}", "盈亏": f"{pnl:.2f} USDT ({pnl_pct:+.2f}%)"}
    level = "critical" if action == "CLOSE" and pnl_pct < -10 else "warning" if pnl_pct < 0 else "info"
    send_alert("position", level,
               f"{symbol} {action} | 价格={price:.2f} | {pnl_pct:+.2f}%",
               details, system)


def notify_system_start(system: str, config: Dict = None):
    details = config or {}
    send_alert("system", "info", f"{system} 已启动", details, system)


def notify_system_stop(system: str, reason: str = ""):
    details = {"原因": reason}
    send_alert("system", "warning", f"{system} 已停止: {reason}", details, system)
