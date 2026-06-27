#!/usr/bin/env python3
"""
本地兜底轮询脚本：检查 Agent A/B 是否有新的执行记录
- 如果最近 6 小时内有新的日志 → 跳过（上游正常执行）
- 如果没有 → 接管执行（兜底）
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

REPO_DIR = Path(__file__).parent.parent
LOG_DIRS = {
    "agent_a": REPO_DIR / "logs" / "agent_a",
    "agent_b": REPO_DIR / "logs" / "agent_b",
}
RUNNERS = {
    "agent_a": REPO_DIR / "agents" / "agent_a_runner.py",
    "agent_b": REPO_DIR / "agents" / "agent_b_runner.py",
}
ENV_FILE = REPO_DIR / "config" / ".env"
POLL_INTERVAL_HOURS = 6
STATE_FILE = REPO_DIR / "data" / "cron_poll_state.json"


def load_env():
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_latest_log_time(agent_id: str) -> datetime | None:
    log_dir = LOG_DIRS[agent_id]
    if not log_dir.exists():
        return None
    latest = None
    for f in log_dir.glob("*.json"):
        try:
            with open(f) as fp:
                data = json.load(fp)
            ts = data.get("ts_utc") or data.get("timestamp")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if latest is None or dt > latest:
                    latest = dt
        except Exception:
            continue
    if latest is None:
        candidates = sorted(log_dir.glob("*_run.log"))
        if candidates:
            latest = datetime.fromtimestamp(candidates[-1].stat().st_mtime, tz=timezone.utc)
    return latest


def run_agent(agent_id: str) -> bool:
    runner = RUNNERS[agent_id]
    if not runner.exists():
        print(f"[Poll/{agent_id}] runner 不存在: {runner}")
        return False
    print(f"[Poll/{agent_id}] 接管执行: {runner}")
    env = os.environ.copy()
    env["CRON_FALLBACK"] = "true"
    try:
        result = subprocess.run(
            [sys.executable, str(runner)],
            cwd=str(REPO_DIR),
            env=env,
            timeout=600,
            capture_output=True,
            text=True,
        )
        log_file = LOG_DIRS[agent_id] / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_cron_fallback.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(result.stdout + result.stderr)
        print(f"[Poll/{agent_id}] 执行完成，退出码: {result.returncode}，日志: {log_file}")
        return result.returncode == 0
    except Exception as e:
        print(f"[Poll/{agent_id}] 执行失败: {e}")
        return False


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_poll": None, "agents": {}}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main():
    load_env()
    state = load_state()
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=POLL_INTERVAL_HOURS)

    print(f"[Poll] {now.isoformat()} 开始轮询（阈值: {threshold.isoformat()}）")

    for agent_id in ["agent_a", "agent_b"]:
        latest = get_latest_log_time(agent_id)
        if latest and latest >= threshold:
            print(f"[Poll/{agent_id}] ✅ 上游正常（最新: {latest.isoformat()}），跳过")
            state["agents"][agent_id] = {
                "status": "upstream_ok",
                "latest_log": latest.isoformat(),
                "last_check": now.isoformat(),
            }
        else:
            reason = f"最近 {POLL_INTERVAL_HOURS}h 无新日志" if latest else "无任何日志"
            print(f"[Poll/{agent_id}] ⚠️ {reason}，接管执行")
            state["agents"][agent_id] = {
                "status": "fallback_triggered",
                "reason": reason,
                "last_check": now.isoformat(),
            }
            success = run_agent(agent_id)
            state["agents"][agent_id]["fallback_success"] = success
            state["agents"][agent_id]["fallback_time"] = now.isoformat()

    state["last_poll"] = now.isoformat()
    save_state(state)
    print("[Poll] 完成")


if __name__ == "__main__":
    main()
