"""28-策略信号触发模块 - Freqtrade Webhook 处理

接收 Freqtrade 的 webhook 事件（entry/exit/filled/rejected），
解析并路由到对应的处理函数。

Webhook 协议参考：https://www.freqtrade.io/en/stable/webhook/

Freqtrade webhook 配置示例（user_data/config.json）：
    "webhook": {
        "enabled": true,
        "url": "http://127.0.0.1:8096/webhook/freqtrade",
        "webhookentry": "...",
        "webhookexit": "...",
        "webhookexitcancel": "...",
        "webhookstatus": "...",
    }

事件类型：
- entry: 开仓信号（buy/long）
- exit: 平仓信号（sell/close）
- exit_cancel: 取消平仓
- entry_fill: 开仓成交
- exit_fill: 平仓成交
- status: 状态心跳

本模块只做事件接收与转发，不直接执行交易。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

# 28 模块数据根目录
_MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _MODULE_ROOT / "data"
_WEBHOOK_DIR = _DATA_DIR / "webhook"
_WEBHOOK_DIR.mkdir(parents=True, exist_ok=True)

# 事件日志文件
_WEBHOOK_LOG = _WEBHOOK_DIR / "events.jsonl"

# M26 策略管理模块地址（用于策略版本归因）
_STRATEGY_LIB_BASE = os.environ.get("STRATEGY_LIB_BASE", "http://127.0.0.1:8093")

# 归因缓存（策略名 -> 归因信息，60 秒）
_ATTR_CACHE_TTL = 60.0
_attr_cache: Dict[str, Any] = {"ts": 0.0, "data": {}}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _http_get_json(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """发送 GET 请求并解析 JSON。失败返回 None（FAIL-OPEN）。"""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError):
        return None


def _resolve_strategy_attribution(strategy_name: str) -> Dict[str, Any]:
    """根据策略名从 M26 registry 解析策略版本归因信息。

    Returns:
        {"strategy_id": ..., "bundle_id": ..., "eval_policy_hash": ...}
        查找失败时字段为 None（FAIL-OPEN）。
    """
    result: Dict[str, Any] = {
        "strategy_id": None,
        "bundle_id": None,
        "eval_policy_hash": None,
    }
    if not strategy_name:
        return result

    # 缓存
    now = time.time()
    if now - _attr_cache["ts"] < _ATTR_CACHE_TTL:
        cached = _attr_cache["data"].get(strategy_name)
        if cached is not None:
            return dict(cached)

    url = f"{_STRATEGY_LIB_BASE}/api/v1/lib/strategies"
    data = _http_get_json(url)
    if not data or not data.get("ok"):
        return result

    entries = data.get("entries") or []
    matched = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("strategy_id") == strategy_name:
            matched = entry
            break
    if matched is None:
        # 宽松匹配：strategy_id 包含 strategy_name
        for entry in entries:
            if isinstance(entry, dict) and strategy_name in str(entry.get("strategy_id") or ""):
                matched = entry
                break

    if matched:
        result["strategy_id"] = matched.get("strategy_id")
        result["bundle_id"] = matched.get("bundle_id")
        result["eval_policy_hash"] = matched.get("eval_policy_hash")

    # 更新缓存
    _attr_cache["data"][strategy_name] = dict(result)
    _attr_cache["ts"] = now
    return result


def _append_event(event: Dict[str, Any]) -> None:
    """追加事件到 jsonl 日志（FAIL-OPEN）。"""
    try:
        with open(_WEBHOOK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def parse_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """解析 Freqtrade webhook payload。

    Freqtrade webhook 通常包含以下字段：
        - type: 事件类型（entry/exit/...）
        - pair: 交易对
        - action: 操作（buy/sell/...）
        - price: 价格
        - amount: 数量
        - strategy: 策略名
        - tag: 标签
        - timestamp: 时间戳

    Returns:
        统一格式的事件字典
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_payload"}

    event_type = str(payload.get("type") or payload.get("event") or "").strip().lower()
    pair = str(payload.get("pair") or "").strip()
    action = str(payload.get("action") or "").strip().lower()
    price = payload.get("price")
    amount = payload.get("amount")
    strategy = str(payload.get("strategy") or payload.get("strategy_name") or "").strip()
    tag = str(payload.get("tag") or payload.get("order_id") or "").strip()
    ts = payload.get("timestamp") or _now_ms()
    profit = payload.get("profit")
    pnl = payload.get("pnl") or payload.get("realized_profit")

    # 标准化事件类型
    if event_type in ("entry", "buy", "long", "enter_long"):
        event_type = "entry"
    elif event_type in ("exit", "sell", "close", "exit_long"):
        event_type = "exit"
    elif event_type in ("exit_cancel", "cancel_exit", "cancel"):
        event_type = "exit_cancel"
    elif event_type in ("entry_fill", "buy_fill", "filled"):
        event_type = "entry_fill"
    elif event_type in ("exit_fill", "sell_fill"):
        event_type = "exit_fill"
    elif event_type in ("status", "heartbeat"):
        event_type = "status"

    return {
        "ok": True,
        "type": event_type,
        "pair": pair,
        "action": action,
        "price": (float(price) if price is not None else None),
        "amount": (float(amount) if amount is not None else None),
        "profit": (float(profit) if profit is not None else None),
        "pnl": (float(pnl) if pnl is not None else None),
        "strategy_name": strategy,
        "tag": tag,
        "ts": int(ts) if ts is not None else _now_ms(),
        "raw": payload,
    }


def route_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """路由事件到对应处理器。

    本函数返回路由结果，不直接执行交易。下游系统可读取路由结果做后续动作。
    """
    etype = str(event.get("type") or "").strip().lower()
    if not etype:
        return {"ok": False, "error": "missing_type"}

    # 路由表
    routes = {
        "entry": "strategy_signal_trigger",
        "exit": "strategy_signal_trigger",
        "exit_cancel": "strategy_signal_cancel",
        "entry_fill": "trade_record",
        "exit_fill": "trade_record",
        "status": "heartbeat_record",
    }
    target = routes.get(etype)
    if target is None:
        return {"ok": False, "error": f"unknown_event_type:{etype}"}

    # 策略版本归因（FAIL-OPEN：M26 不可用时字段为 null）
    strategy_name = str(event.get("strategy_name") or "")
    attr = _resolve_strategy_attribution(strategy_name)

    # 记录到日志
    _append_event({
        "type": etype,
        "pair": event.get("pair"),
        "action": event.get("action"),
        "price": event.get("price"),
        "amount": event.get("amount"),
        "profit": event.get("profit"),
        "pnl": event.get("pnl"),
        "strategy_name": strategy_name,
        "strategy_id": attr["strategy_id"],
        "bundle_id": attr["bundle_id"],
        "eval_policy_hash": attr["eval_policy_hash"],
        "tag": event.get("tag"),
        "ts": event.get("ts"),
        "route": target,
    })

    # 36-通信系统层：开/平仓事件上报（FAIL-OPEN，失败不影响主流程）
    _emit_to_signal_bus(etype, event, strategy_name)

    return {
        "ok": True,
        "event_type": etype,
        "route": target,
        "pair": event.get("pair"),
        "ts": event.get("ts"),
    }


def handle_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Freqtrade webhook 主入口。

    流程：parse_event → route_event → 返回路由结果
    """
    parsed = parse_event(payload)
    if not parsed.get("ok"):
        return parsed
    return route_event(parsed)


def query_events(
    *,
    event_type: Optional[str] = None,
    pair: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """查询 webhook 事件日志。"""
    if not _WEBHOOK_LOG.exists():
        return {"ok": True, "count": 0, "events": []}
    events: List[Dict[str, Any]] = []
    try:
        with open(_WEBHOOK_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {"ok": False, "error": "read_failed"}
    # 反向遍历，取最近 limit 条
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if event_type and ev.get("type") != event_type:
            continue
        if pair and ev.get("pair") != pair:
            continue
        events.append(ev)
        if len(events) >= int(limit):
            break
    events.reverse()
    return {"ok": True, "count": len(events), "events": events}


def _emit_to_signal_bus(etype: str, event: Dict[str, Any], strategy_name: str) -> None:
    """将开/平仓事件上报到 36-通信系统层（Signal Bus）。

    FAIL-OPEN：上报失败仅记录，不影响 webhook 主流程。
    仅上报 entry / exit 两类事件（开仓/平仓信号）。
    """
    if etype not in ("entry", "exit"):
        return
    signal_type = "trade_signal.open" if etype == "entry" else "trade_signal.close"
    action = str(event.get("action") or "").lower()
    direction = "SHORT" if action in ("sell", "short", "close") else "LONG"
    envelope = {
        "type": signal_type,
        "severity": "info",
        "source": "m28-freqtrade",
        "ts": event.get("ts") or _now_ms(),
        "payload": {
            "symbol": event.get("pair") or "",
            "direction": direction,
            "entryPrice": event.get("price") if etype == "entry" else None,
            "exitPrice": event.get("price") if etype == "exit" else None,
            "strategyName": strategy_name,
            "orderId": event.get("tag") or None,
        },
        "dedupKey": f"m28:{etype}:{event.get('tag') or ''}:{event.get('ts')}",
    }
    base = os.environ.get("SIGNAL_BUS_BASE", "http://127.0.0.1:3000")
    token = os.environ.get("SIGNAL_BUS_TOKEN", "")
    try:
        req = urllib.request.Request(
            f"{base}/api/signal-bus/emit",
            data=json.dumps(envelope).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status != 200:
                _append_event({"type": "signal_bus_emit_failed", "status": resp.status, "ts": _now_ms()})
    except Exception as exc:
        _append_event({"type": "signal_bus_emit_failed", "error": str(exc), "ts": _now_ms()})
