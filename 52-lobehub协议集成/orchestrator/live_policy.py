#!/usr/bin/env python3
"""ADR-001 脑暴出关（live）的策略门禁与预算账本 — 纯标准库。

三道门（全部 fail-closed）：
  ① 策略文件：`enabled` / `allowed_roles` / `allowed_routes` / `max_per_week`
  ② 角色：只有 `allowed_roles` 内的角色可实盘（默认仅 auditor）
  ③ 预算：按自然周（周一起算）计数，超额即拒绝

设计约束（SPEC-33-G §2.11.6）：
  - 策略文件缺失时默认**关闭**，绝不隐式开启实盘
  - 预算按「尝试执行」计数（失败也占额），避免失败重试无限放大
  - 账本 append-only JSONL，禁外发
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
DEFAULT_POLICY_PATH = ORCHESTRATOR_DIR / "live_policy.json"
DEFAULT_LEDGER_PATH = ORCHESTRATOR_DIR / "traces" / "live_executions.jsonl"

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "adr": "ADR-001",
    "enabled": False,
    "allowed_roles": ["auditor"],
    "allowed_routes": ["workers"],
    "max_per_week": 1,
}


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """读取实盘策略；文件缺失或解析失败一律返回默认（关闭）。"""
    policy = dict(DEFAULT_POLICY)
    p = Path(path) if path else DEFAULT_POLICY_PATH
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return policy
    if not isinstance(loaded, dict):
        return policy
    for key in ("version", "adr", "enabled", "max_per_week"):
        if key in loaded:
            policy[key] = loaded[key]
    for key in ("allowed_roles", "allowed_routes"):
        value = loaded.get(key)
        if isinstance(value, list):
            policy[key] = [str(v) for v in value]
    return policy


def week_start(now: float | None = None) -> float:
    """自然周起点（本地时区周一 00:00）的 epoch 秒。"""
    ts = time.time() if now is None else now
    today = datetime.fromtimestamp(ts).date()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day).timestamp()


def count_this_week(ledger_path: str | Path | None = None, now: float | None = None) -> int:
    """统计本周已尝试的实盘次数（坏行忽略，不抛异常）。"""
    p = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH
    start = week_start(now)
    count = 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = float(record.get("ts") or 0)
                except (ValueError, TypeError):
                    continue
                if ts >= start:
                    count += 1
    except OSError:
        return 0
    return count


def check_live_allowed(
    policy: dict[str, Any],
    *,
    role: str,
    route: str,
    ledger_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """三道门依次校验，返回可写入 trace 的判定结果。"""
    used = count_this_week(ledger_path, now)
    max_per_week = int(policy.get("max_per_week") or 0)
    result: dict[str, Any] = {
        "enabled": bool(policy.get("enabled")),
        "role": role,
        "route": route,
        "used": used,
        "max_per_week": max_per_week,
        "adr": policy.get("adr"),
        "allowed": False,
        "reason": "",
    }
    if not result["enabled"]:
        result["reason"] = "live disabled by policy (live_policy.json enabled=false)"
    elif role not in (policy.get("allowed_roles") or []):
        result["reason"] = f"role '{role}' not in allowed_roles {policy.get('allowed_roles')}"
    elif route not in (policy.get("allowed_routes") or []):
        result["reason"] = f"route '{route}' not in allowed_routes {policy.get('allowed_routes')}"
    elif used >= max_per_week:
        result["reason"] = f"weekly budget exhausted ({used}/{max_per_week})"
    else:
        result["allowed"] = True
        result["reason"] = "ok"
    return result


def record_execution(ledger_path: str | Path | None, record: dict[str, Any]) -> None:
    """append-only 记录一次实盘尝试（失败也必须记，占预算）。"""
    p = Path(ledger_path) if ledger_path else DEFAULT_LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
