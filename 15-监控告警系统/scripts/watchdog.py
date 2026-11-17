#!/usr/bin/env python3
"""2 周 alert_only 期间的轻量 watchdog：只告警，不干预交易。

检查项：
  1. dreambuddy-entry23 / dreambuddy-exit23 是否 active
  2. entry23 / exit23 日志是否 10min 内有更新
  3. 22 账本 position_ledger.db 是否 24h 内有写入（仅 exit23 active 时）
  4. execution_decisions.jsonl 是否 24h 内有写入（仅提示）
  5. 磁盘根分区使用率 <90%
异常经本机 receiver 发飞书；同一检查项 30min 内只发一次。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path("/home/luke/dreambuddy")
LOG = Path("/home/luke/logs/yijing/entry23.log")
EXIT_LOG = Path("/home/luke/logs/yijing/exit23.log")
DECISIONS = REPO / "23-四层闭环自进化交易架构/runtime/execution_decisions.jsonl"
LEDGER = REPO / "22-执行引擎中心/runtime/position_ledger.db"
STATE = Path.home() / ".cache/dreambuddy-watchdog.json"
RECEIVER = "http://127.0.0.1:9098/notify"
COOLDOWN = 1800


def _age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return 10**9


def _active(unit: str) -> bool:
    out = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, check=False
    ).stdout.strip()
    return out == "active"


def check() -> list[dict]:
    problems: list[dict] = []
    for unit in ("dreambuddy-entry23", "dreambuddy-exit23"):
        if not _active(unit):
            problems.append(
                {"key": unit, "level": "P1", "text": f"**服务停止**: `{unit}` 不是 active"}
            )

    log_age = _age(LOG)
    if log_age > 600:
        problems.append(
            {
                "key": "entry23_log",
                "level": "P1",
                "text": f"**日志静默**: `entry23.log` 已 {int(log_age/60)}min 无更新",
            }
        )

    exit_log_age = _age(EXIT_LOG)
    if exit_log_age > 600:
        problems.append(
            {
                "key": "exit23_log",
                "level": "P1",
                "text": f"**日志静默**: `exit23.log` 已 {int(exit_log_age/60)}min 无更新",
            }
        )

    # 账本 24h 无任何写入（无成交、无对账变更）才提示；稳定持仓不写账本属正常
    if _active("dreambuddy-exit23") and _age(LEDGER) > 86400:
        problems.append(
            {
                "key": "ledger_db",
                "level": "P2",
                "text": "**账本异常**: `position_ledger.db` 24h 无写入或缺失",
            }
        )

    dec_age = _age(DECISIONS)
    if dec_age > 86400:
        problems.append(
            {
                "key": "decisions_file",
                "level": "P2",
                "text": f"**审计文件陈旧**: `execution_decisions.jsonl` 已 {int(dec_age/3600)}h 无写入",
            }
        )

    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100
    if pct >= 90:
        problems.append(
            {"key": "disk", "level": "P2", "text": f"**磁盘告警**: 根分区使用率 {pct:.0f}%"}
        )
    return problems


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def _notify(text: str, level: str = "P1") -> bool:
    payload = json.dumps({"level": level, "text": text}).encode()
    req = urllib.request.Request(
        RECEIVER, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except OSError:
        return False


def main() -> int:
    state = _load_state()
    now = time.time()
    sent = 0
    for item in check():
        if now - float(state.get(item["key"], 0)) < COOLDOWN:
            continue
        if _notify(item["text"], item.get("level", "P1")):
            state[item["key"]] = now
            sent += 1
    _save_state({k: v for k, v in state.items() if now - float(v) < 86400})
    print(f"[watchdog] sent={sent}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
