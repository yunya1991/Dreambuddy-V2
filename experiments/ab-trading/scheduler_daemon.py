#!/usr/bin/env python3
"""
AB实验后台调度器 — 替代 crontab 的 Python 实现
每4小时触发一次 Agent A + Agent B 交易循环

用法:
  python3 scheduler_daemon.py start    # 后台启动
  python3 scheduler_daemon.py stop     # 停止
  python3 scheduler_daemon.py status   # 查看状态
  python3 scheduler_daemon.py run      # 前台运行（调试用）
  python3 scheduler_daemon.py trigger  # 立即触发一次
"""
import os
import sys
import json
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

BASE_DIR = Path(__file__).parent.resolve()
PID_FILE = BASE_DIR / "data" / "scheduler.pid"
LOG_FILE = BASE_DIR / "logs" / "scheduler.log"
RUN_SCRIPT = BASE_DIR / "run_cycle.sh"
ORCHESTRATOR = BASE_DIR / "orchestrator.py"

POLL_INTERVAL_SECONDS = 900  # 15分钟轮询


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def get_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except ValueError:
        return None


def start_daemon():
    if is_running():
        print(f"调度器已在运行 (PID={get_pid()})")
        return

    BASE_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    BASE_DIR.joinpath("logs").mkdir(parents=True, exist_ok=True)

    pid = os.fork()
    if pid > 0:
        time.sleep(1)
        if is_running():
            print(f"调度器已启动 (PID={get_pid()})")
            print(f"日志: {LOG_FILE}")
        else:
            print("启动失败，请检查日志")
        return

    os.setsid()
    os.umask(0)

    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    sys.stdout.flush()
    sys.stderr.flush()

    run_loop()


def stop_daemon():
    if not is_running():
        print("调度器未运行")
        PID_FILE.unlink(missing_ok=True)
        return

    pid = get_pid()
    print(f"正在停止调度器 (PID={pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            time.sleep(0.5)
            if not is_running():
                break
        if is_running():
            print("强制终止...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
    except OSError:
        pass
    PID_FILE.unlink(missing_ok=True)
    print("已停止")


def maybe_screen_universe():
    """每24h执行一次币种池筛选更新"""
    from datetime import timedelta
    state_file = BASE_DIR / "data" / "universe_screen_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            last = state.get("last_screen")
            if last:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed < 86400:
                    log(f"币种筛选: 距上次 {elapsed/3600:.1f}h，跳过")
                    return
        except Exception:
            pass

    log("币种筛选: 开始24h定期更新...")
    try:
        result = subprocess.run(
            ["python3", str(BASE_DIR / "scripts" / "universe_screener.py"), "--force"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log(f"币种筛选: ✅ 完成\n{result.stdout.strip()[-500:]}")
        else:
            log(f"币种筛选: ❌ 失败\n{result.stderr.strip()[-300:]}")
    except Exception as e:
        log(f"币种筛选: 异常 {e}")


def trigger_once():
    """手动触发一次交易循环（直接执行 run_cycle.sh）"""
    maybe_screen_universe()
    log("手动触发一次交易循环")
    try:
        result = subprocess.run(
            ["bash", str(RUN_SCRIPT)],
            cwd=str(BASE_DIR),
            capture_output=False,
            timeout=1800,
        )
        log(f"交易循环完成，退出码={result.returncode}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log("交易循环超时(30分钟)")
        return False
    except Exception as e:
        log(f"交易循环异常: {e}")
        return False


def poll_once():
    """单次轮询：调用 orchestrator 智能决策是否触发"""
    maybe_screen_universe()
    log("轮询 orchestrator...")
    try:
        result = subprocess.run(
            ["python3", str(ORCHESTRATOR)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        stdout = result.stdout.strip()
        if stdout:
            for line in stdout.split("\n")[-5:]:
                log(f"  orchestrator: {line}")
        if result.returncode != 0:
            log(f"  orchestrator 退出码={result.returncode}: {result.stderr.strip()[-200:]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log("  orchestrator 超时(5分钟)")
        return False
    except Exception as e:
        log(f"  orchestrator 异常: {e}")
        return False


def run_loop():
    log(f"调度器启动 PID={os.getpid()}，轮询间隔={POLL_INTERVAL_SECONDS}秒({POLL_INTERVAL_SECONDS//60}分钟)")
    log(f"工作目录: {BASE_DIR}")
    log(f"轮询脚本: {ORCHESTRATOR}")
    log(f"手动触发脚本: {RUN_SCRIPT}")

    running = True

    def handle_sigterm(signum, frame):
        nonlocal running
        log(f"收到信号 {signum}，准备退出...")
        running = False

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # 首次立即执行一次
    log("首次轮询，立即执行...")
    poll_once()

    while running:
        # 等待到下次轮询
        slept = 0
        while slept < POLL_INTERVAL_SECONDS and running:
            time.sleep(min(60, POLL_INTERVAL_SECONDS - slept))
            slept += 60

        if not running:
            break

        log(f"开始轮询 (每{POLL_INTERVAL_SECONDS//60}分钟)...")
        poll_once()

    log("调度器已停止")
    PID_FILE.unlink(missing_ok=True)


def print_status():
    print("=" * 55)
    print("  AB实验调度器状态")
    print("=" * 55)

    if is_running():
        pid = get_pid()
        print(f"  状态:   🟢 运行中 (PID={pid})")
        print(f"  轮询:   每 {POLL_INTERVAL_SECONDS//60} 分钟 (orchestrator智能决策)")
        print(f"  PID文件: {PID_FILE}")
        print(f"  日志:    {LOG_FILE}")
    else:
        print("  状态:   🔴 未运行")
        print(f"  轮询:   每 {POLL_INTERVAL_SECONDS//60} 分钟 (orchestrator智能决策)")

    print()
    print("── 最近 10 条调度日志 ──")
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            lines = f.readlines()
            for line in lines[-10:]:
                print(f"  {line.rstrip()}")
    else:
        print("  (暂无日志)")

    print()
    print("── 最近一次 Agent 运行 ──")
    log_dirs = {
        "Agent A": BASE_DIR / "logs" / "agent_a",
        "Agent B": BASE_DIR / "logs" / "agent_b",
    }
    for name, ldir in log_dirs.items():
        if ldir.exists():
            files = sorted(ldir.glob("*.json"))
            if files:
                latest = files[-1]
                mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
                print(f"  {name}: {latest.name} ({mtime.strftime('%m-%d %H:%M UTC')})")
            else:
                print(f"  {name}: (无记录)")
        else:
            print(f"  {name}: (无目录)")

    print("=" * 55)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "start":
        start_daemon()
    elif cmd == "stop":
        stop_daemon()
    elif cmd == "status":
        print_status()
    elif cmd == "run":
        run_loop()
    elif cmd == "trigger":
        trigger_once()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
