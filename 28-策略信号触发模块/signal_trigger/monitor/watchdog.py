"""
28-策略信号触发模块 - 策略性能监控 Watchdog

监控实盘成交事件，当策略性能持续低于阈值时，自动触发 M27 gate 的 rolled_back。

设计原则：
- 基于 JSONL 事件日志分析（exit_fill 事件）
- 胜率低于阈值且连续亏损达到 N 笔 → 触发降级
- FAIL-OPEN：M27 不可用时不阻断信号流程
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# M27 治理审批系统地址
_GOVERNANCE_BASE = os.environ.get("GOVERNANCE_BASE", "http://127.0.0.1:8094")
# M27 admin token
_GOVERNANCE_ADMIN_TOKEN = os.environ.get("GOVERNANCE_ADMIN_TOKEN", "dev-governance-token-2026")

# 降级阈值
_DEGRADATION_MIN_TRADES = int(os.environ.get("WATCHDOG_MIN_TRADES", "5"))
_DEGRADATION_WIN_RATE_THRESHOLD = float(os.environ.get("WATCHDOG_WIN_RATE_THRESHOLD", "0.3"))
_DEGRADATION_CONSECUTIVE_LOSSES = int(os.environ.get("WATCHDOG_CONSECUTIVE_LOSSES", "3"))

# 事件日志路径（与 webhook.py 一致）
_MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
_EVENTS_PATH = _MODULE_ROOT / "data" / "webhook" / "events.jsonl"


def _load_recent_events(limit: int = 200) -> List[Dict[str, Any]]:
    """读取最近的事件日志（倒序取最后 limit 条）。"""
    if not _EVENTS_PATH.exists():
        return []
    try:
        lines = _EVENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-limit:] if len(lines) > limit else lines
        events = []
        for line in recent:
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return events
    except Exception:
        return []


def _extract_pnl(event: Dict[str, Any]) -> Optional[float]:
    """从事件中提取盈亏（正数=盈利，负数=亏损）。

    支持字段：profit / pnl / realized_profit / close_profit
    """
    for key in ("profit", "pnl", "realized_profit", "close_profit", "close_profit_abs"):
        val = event.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def analyze_strategy_performance(strategy_name: str, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """分析指定策略的近期成交表现。

    Returns:
        {
            "strategy": str,
            "total_fills": int,
            "analyzed_trades": int,  # 有盈亏数据的成交数
            "win_rate": float,
            "consecutive_losses": int,
            "degraded": bool,
            "reason": str,
        }
    """
    if events is None:
        events = _load_recent_events()

    # 收集该策略的 exit_fill 事件（按时间正序）
    fills = [
        e for e in events
        if e.get("type") == "exit_fill" and str(e.get("strategy_name") or "") == strategy_name
    ]
    # 按 ts 排序（如果有）
    fills.sort(key=lambda e: e.get("ts") or 0)

    if not fills:
        return {
            "strategy": strategy_name,
            "total_fills": 0,
            "analyzed_trades": 0,
            "win_rate": 0.0,
            "consecutive_losses": 0,
            "degraded": False,
            "reason": "no_exit_fill_events",
        }

    # 计算有盈亏数据的交易
    pnls = []
    for f in fills:
        pnl = _extract_pnl(f)
        if pnl is not None:
            pnls.append(pnl)

    if not pnls:
        return {
            "strategy": strategy_name,
            "total_fills": len(fills),
            "analyzed_trades": 0,
            "win_rate": 0.0,
            "consecutive_losses": 0,
            "degraded": False,
            "reason": "no_pnl_data_in_events",
        }

    # 取最近 N 笔
    recent_pnls = pnls[-_DEGRADATION_MIN_TRADES:] if len(pnls) >= _DEGRADATION_MIN_TRADES else pnls
    wins = sum(1 for p in recent_pnls if p > 0)
    win_rate = wins / len(recent_pnls) if recent_pnls else 0.0

    # 连续亏损数（从最后一笔往前数）
    consecutive_losses = 0
    for p in reversed(pnls):
        if p < 0:
            consecutive_losses += 1
        else:
            break

    # 降级判定
    degraded = False
    reason = ""
    if len(recent_pnls) >= _DEGRADATION_MIN_TRADES and win_rate < _DEGRADATION_WIN_RATE_THRESHOLD:
        degraded = True
        reason = f"win_rate_below_threshold:{win_rate:.2f}<{_DEGRADATION_WIN_RATE_THRESHOLD}"
    elif consecutive_losses >= _DEGRADATION_CONSECUTIVE_LOSSES:
        degraded = True
        reason = f"consecutive_losses:{consecutive_losses}>={_DEGRADATION_CONSECUTIVE_LOSSES}"

    return {
        "strategy": strategy_name,
        "total_fills": len(fills),
        "analyzed_trades": len(pnls),
        "win_rate": round(win_rate, 4),
        "consecutive_losses": consecutive_losses,
        "degraded": degraded,
        "reason": reason,
    }


def trigger_rollback(strategy_name: str, reason: str) -> Dict[str, Any]:
    """调用 M27 gate 触发策略 rolled_back。

    FAIL-OPEN：M27 不可用时返回 ok=False。
    """
    try:
        payload = {
            "strategy_id": strategy_name,
            "reason": reason,
            "actor": "m28_watchdog",
        }
        req = urllib.request.Request(
            f"{_GOVERNANCE_BASE}/api/v1/gate/rollback",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Admin-Token": _GOVERNANCE_ADMIN_TOKEN,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status != 200:
                return {"ok": False, "error": f"http_{resp.status}"}
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": bool(data.get("ok")), "data": data}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError, Exception) as e:
        return {"ok": False, "error": str(e)}


def run_watchdog() -> Dict[str, Any]:
    """运行一次 watchdog 检查：扫描所有有成交的策略，触发降级。

    Returns:
        {"ok": bool, "checked": int, "degraded": int, "rollback_triggered": int, "details": [...]}
    """
    events = _load_recent_events()
    if not events:
        return {"ok": True, "checked": 0, "degraded": 0, "rollback_triggered": 0, "details": []}

    # 收集所有出现过的策略
    strategies = set()
    for e in events:
        name = str(e.get("strategy_name") or "").strip()
        if name:
            strategies.add(name)

    details = []
    rollback_triggered = 0
    degraded_count = 0

    for strategy in sorted(strategies):
        perf = analyze_strategy_performance(strategy, events)
        if perf["degraded"]:
            degraded_count += 1
            rb = trigger_rollback(strategy, perf["reason"])
            if rb.get("ok"):
                rollback_triggered += 1
                perf["rollback"] = "triggered"
            else:
                perf["rollback"] = f"failed:{rb.get('error', 'unknown')}"
        details.append(perf)

    return {
        "ok": True,
        "checked": len(strategies),
        "degraded": degraded_count,
        "rollback_triggered": rollback_triggered,
        "details": details,
    }
