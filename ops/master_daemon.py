#!/usr/bin/env python3
"""
DreamBuddy Master Daemon - 统一调度守护进程
管理所有交易系统的定时任务：
- Agent A/B 编排器 (10min)
- 三屏趋势编排器 (10min)
- V15 经典马丁策略 (1h)
- Agent A/B 监控自进化 (4h)
- 三屏趋势监控自进化 (4h)
- 易经推理监控 (4h)
- 易经推理交易 (1h)
- 资金管理引擎 (每天检查，每月1号运行优化)

特性：
- 双进程看门狗（监控 + 工作）
- PID 文件锁
- 崩溃自动重启
- 统一日志
"""
import os
import sys
import time
import json
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).parent.parent.resolve()
AB_DIR = ROOT_DIR / "experiments" / "ab-trading"
YIJING_DIR = ROOT_DIR / "11-易经推理系统"
V15_DIR = ROOT_DIR / "14-V15经典马丁策略"
OPS_DIR = ROOT_DIR / "ops"
LOG_DIR = OPS_DIR / "logs"
STATE_DIR = OPS_DIR / "state"
MAIN_PID_FILE = STATE_DIR / "master_daemon_main.pid"
WATCH_PID_FILE = STATE_DIR / "master_daemon_watch.pid"
LOG_FILE = LOG_DIR / "master_daemon.log"
STATE_FILE = STATE_DIR / "master_daemon_state.json"

PYTHON = sys.executable

TASKS = [
    {
        "name": "ab_orchestrator",
        "label": "Agent A/B 编排器",
        "interval": 600,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "orchestrator.py")],
        "log_file": str(AB_DIR / "logs" / "orchestrator_master.log"),
    },
    {
        "name": "screen_orchestrator",
        "label": "三屏趋势编排器",
        "interval": 600,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "screen_orchestrator.py")],
        "log_file": str(AB_DIR / "logs" / "screen_orchestrator_master.log"),
    },
    {
        "name": "v15_martin",
        "label": "V15经典马丁策略",
        "interval": 3600,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "v15ct_trader.py"), "--poll-once"],
        "log_file": str(AB_DIR / "logs" / "v15ct_trader_master.log"),
    },
    {
        "name": "ab_monitor",
        "label": "Agent A/B 监控自进化",
        "interval": 14400,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "auto_monitor.py")],
        "log_file": str(AB_DIR / "logs" / "auto_monitor_master.log"),
    },
    {
        "name": "screen_monitor",
        "label": "三屏趋势监控自进化",
        "interval": 14400,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "screen_monitor.py")],
        "log_file": str(AB_DIR / "logs" / "screen_monitor_master.log"),
    },
    {
        "name": "yijing_monitor",
        "label": "易经推理监控",
        "interval": 14400,
        "work_dir": str(YIJING_DIR),
        "cmd": [PYTHON, "-m", "scripts.memory_l4.yijing_monitor"],
        "log_file": str(YIJING_DIR / "logs" / "yijing_monitor_master.log"),
    },
    {
        "name": "yijing_trading",
        "label": "易经推理交易",
        "interval": 3600,
        "work_dir": str(YIJING_DIR),
        "cmd": [
            PYTHON, "-m", "scripts.memory_l4.polling_trader",
            "--interval", "3600",
            "--coins", "BTC,ETH,SOL,BNB,XRP,DOGE",
            "--confidence", "0.35",
            "--max-positions", "5",
            "--position-pct", "0.10",
        ],
        "log_file": str(YIJING_DIR / "logs" / "trading_master.log"),
    },
    {
        "name": "capital_manager",
        "label": "资金管理引擎（月度优化）",
        "interval": 86400,
        "work_dir": str(AB_DIR),
        "cmd": [PYTHON, str(AB_DIR / "capital_manager_engine.py"), "monthly"],
        "log_file": str(AB_DIR / "logs" / "capital_manager_master.log"),
    },
]


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


def is_running(pid_file):
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return pid
        except:
            pid_file.unlink(missing_ok=True)
    return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def run_task(task, state):
    name = task["name"]
    label = task["label"]

    if task.get("_running"):
        return
    task["_running"] = True

    log(f"[TASK] 执行: {label}")

    last_run = state.get(name, {}).get("last_run", 0)
    run_count = state.get(name, {}).get("run_count", 0)

    state[name] = {
        **state.get(name, {}),
        "last_run": time.time(),
        "status": "running",
    }
    save_state(state)

    log_path = Path(task["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    start_ts = time.time()
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n{'='*60}\n")
            lf.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] 开始执行\n")
            lf.write(f"{'='*60}\n")
            lf.flush()

            proc = subprocess.Popen(
                task["cmd"],
                cwd=task["work_dir"],
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
            proc.wait()
            duration = time.time() - start_ts

            lf.write(f"\n[完成] 退出码: {proc.returncode}, 耗时: {duration:.1f}s\n")

        if proc.returncode == 0:
            log(f"[TASK] ✅ {label} 完成，耗时 {duration:.1f}s")
        else:
            log(f"[TASK] ⚠️  {label} 退出码 {proc.returncode}，耗时 {duration:.1f}s")

        state[name] = {
            "last_run": time.time(),
            "last_duration": duration,
            "run_count": run_count + 1,
            "last_exit_code": proc.returncode,
            "status": "done",
        }
        save_state(state)

    except Exception as e:
        duration = time.time() - start_ts
        log(f"[TASK] ❌ {label} 异常: {e}，耗时 {duration:.1f}s")
        state[name] = {
            "last_run": time.time(),
            "last_duration": duration,
            "run_count": run_count + 1,
            "last_error": str(e),
            "status": "error",
        }
        save_state(state)

    finally:
        task["_running"] = False


def worker_loop():
    log("[WORKER] 工作进程启动")
    state = load_state()

    for task in TASKS:
        task["_next_run"] = 0

    tick = 0
    while True:
        now = time.time()
        tick += 1

        for task in TASKS:
            name = task["name"]
            last_run = state.get(name, {}).get("last_run", 0)
            interval = task["interval"]

            if now - last_run >= interval:
                t = threading.Thread(target=run_task, args=(task, state), daemon=True)
                t.start()
                task["_next_run"] = now + interval

        if tick % 60 == 0:
            log(f"[WORKER] 心跳 tick={tick}")

        time.sleep(30)


def watchdog_loop():
    WATCH_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_PID_FILE.write_text(str(os.getpid()))
    log("[WATCHDOG] 监控进程启动 (PID %d)" % os.getpid())

    worker_pid = None

    while True:
        main_pid = is_running(MAIN_PID_FILE)

        if not main_pid:
            log("[WATCHDOG] ⚠️  工作进程未运行，启动中...")

            pid = os.fork()
            if pid == 0:
                MAIN_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                MAIN_PID_FILE.write_text(str(os.getpid()))
                worker_loop()
                sys.exit(0)
            else:
                worker_pid = pid
                MAIN_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                MAIN_PID_FILE.write_text(str(pid))
                log(f"[WATCHDOG] ✅ 工作进程已启动 (PID {pid})")

        time.sleep(15)


def cmd_start():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if is_running(WATCH_PID_FILE):
        log("守护进程已在运行")
        return

    log("启动 DreamBuddy Master Daemon...")

    pid = os.fork()
    if pid == 0:
        os.setsid()
        watchdog_loop()
        sys.exit(0)
    else:
        time.sleep(1)
        if is_running(WATCH_PID_FILE):
            log("✅ 守护进程启动成功")
        else:
            log("❌ 守护进程启动失败")
            sys.exit(1)


def cmd_stop():
    log("停止守护进程...")

    main_pid = is_running(MAIN_PID_FILE)
    if main_pid:
        try:
            os.kill(main_pid, 15)
            log(f"  已停止工作进程 (PID {main_pid})")
        except:
            pass
        MAIN_PID_FILE.unlink(missing_ok=True)

    watch_pid = is_running(WATCH_PID_FILE)
    if watch_pid:
        try:
            os.kill(watch_pid, 15)
            log(f"  已停止监控进程 (PID {watch_pid})")
        except:
            pass
        WATCH_PID_FILE.unlink(missing_ok=True)

    log("✅ 已停止")


def cmd_status():
    print("=" * 60)
    print("  DreamBuddy Master Daemon 状态")
    print("=" * 60)

    watch_pid = is_running(WATCH_PID_FILE)
    main_pid = is_running(MAIN_PID_FILE)

    print(f"\n  监控进程: {'运行中 (PID %d)' % watch_pid if watch_pid else '未运行'}")
    print(f"  工作进程: {'运行中 (PID %d)' % main_pid if main_pid else '未运行'}")

    state = load_state()
    print(f"\n  {'任务':<22} {'间隔':<10} {'上次运行':<20} {'运行次数'}")
    print("  " + "-" * 65)

    for task in TASKS:
        name = task["name"]
        label = task["label"]
        interval = task["interval"]
        interval_str = f"{interval//60}min" if interval < 3600 else f"{interval//3600}h"

        task_state = state.get(name, {})
        last_run = task_state.get("last_run", 0)
        run_count = task_state.get("run_count", 0)

        if last_run > 0:
            last_str = datetime.fromtimestamp(last_run, tz=timezone.utc).strftime("%m-%d %H:%M UTC")
        else:
            last_str = "从未运行"

        print(f"  {label:<20} {interval_str:<10} {last_str:<20} {run_count}")

    print(f"\n  日志文件: {LOG_FILE}")
    print()


def cmd_restart():
    cmd_stop()
    time.sleep(1)
    cmd_start()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "start":
        cmd_start()
    elif action == "stop":
        cmd_stop()
    elif action == "status":
        cmd_status()
    elif action == "restart":
        cmd_restart()
    else:
        print(f"用法: {sys.argv[0]} [start|stop|status|restart]")
        sys.exit(1)


if __name__ == "__main__":
    main()
