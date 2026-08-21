#!/usr/bin/env python3
"""
启动每日调度守护进程（launchd 沙箱问题兜底）
================================================

用 start_new_session=True (setsid) 启动 daily_scheduler_daemon.py，
脱离工具会话，避免父 shell 退出时子进程被 SIGHUP 杀死。

与 launchd 方案对比：
  launchd：  系统级日历触发，精度高，但 Trae Code 沙箱可能导致 I/O 权限问题
  Python：   进程常驻 24/7，每 30s 检查时钟，完全在用户态运行，无沙箱限制

用法：
  1. 首次 / 更新后启动：  python3 scripts/start_daily_scheduler.py
  2. 查看状态：          tail -f logs/daily_scheduler_daemon.log
  3. 停止：              kill $(cat .workbuddy/daily_scheduler_pid.txt)
  4. 安装 launchd 守护： bash scripts/install_daily_scheduler_launchd.sh
"""
import os
import subprocess
import sys
import time
from pathlib import Path

WORK_DIR = str(Path(__file__).resolve().parent.parent)
LOG_DIR = os.path.join(WORK_DIR, "logs")
PID_DIR = os.path.join(WORK_DIR, ".workbuddy")
PID_FILE = os.path.join(PID_DIR, "daily_scheduler_pid.txt")
DAEMON_LOG = os.path.join(LOG_DIR, "daily_scheduler_stdouterr.log")

# ── 环境变量注入（确保 Python 输出 UTF-8，避免中文日志乱码）─────────────────
env = os.environ.copy()
env.setdefault("PYTHONIOENCODING", "utf-8")
env.setdefault("PYTHONUNBUFFERED", "1")
env.setdefault("LANG", "en_US.UTF-8")
env.setdefault("LC_ALL", "en_US.UTF-8")
# 可选：代理（如需要可取消注释）
# env.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")
# env.setdefault("HTTP_PROXY",  "http://127.0.0.1:7890")

PYTHON = "/opt/homebrew/bin/python3"
if not os.path.exists(PYTHON):
    PYTHON = sys.executable  # fallback 到当前解释器

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PID_DIR, exist_ok=True)


def _pkill_old():
    """尝试杀掉旧的 daily_scheduler 进程（避免重复启动）"""
    # 1. 从 PID 文件杀
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 15)  # SIGTERM
            print(f"[1/4] 终止旧进程 PID={old_pid}（来自 pid 文件）")
            time.sleep(2)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        except OSError as e:
            # 可能进程不存在
            print(f"[1/4] 清理旧 pid 文件: {e}")

    # 2. 兜底：pkill -f 杀匹配命令行
    try:
        subprocess.run(
            ["pgrep", "-f", "daily_scheduler_daemon.py"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["pkill", "-f", "daily_scheduler_daemon.py"],
            capture_output=True, check=False,
        )
        time.sleep(1)
    except FileNotFoundError:
        pass  # pgrep/pkill 不存在（沙箱环境），跳过


def _launch():
    cmd = [
        PYTHON, "-u",
        os.path.join(WORK_DIR, "daily_scheduler_daemon.py"),
    ]
    print(f"[2/4] 启动命令: {' '.join(cmd)}")
    print(f"[2/4] 工作目录: {WORK_DIR}")

    with open(DAEMON_LOG, "a", encoding="utf-8") as log_f:
        proc = subprocess.Popen(
            cmd,
            cwd=WORK_DIR,
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # setsid() — 脱离父会话，PPID=1
        )

    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    print(f"[3/4] 守护进程已启动 PID={proc.pid}，PPID 将变为 1")

    # 等待一小段时间再检查
    time.sleep(5)
    if proc.poll() is None:
        print("[4/4] ✅ OK：守护进程运行中")
    else:
        print(f"[4/4] ❌ FAIL：守护进程已退出，退出码={proc.returncode}")
        print(f"       查看日志：tail -100 {DAEMON_LOG}")
        try:
            with open(DAEMON_LOG, "r", encoding="utf-8") as f:
                tail = f.read()[-3000:]
            print("\n===== stdout/stderr 末尾 =====")
            print(tail)
        except Exception:
            pass
        sys.exit(1)


def _print_status_hint():
    print()
    print("调度配置：")
    print(f"  策略优化 每日 02:00 → logs/agent_b.log")
    print(f"  记忆清理 每日 02:05 → logs/memory_cleanup.log")
    print()
    print("常用命令：")
    print(f"  守护日志（调度心跳/错误）: tail -f {LOG_DIR}/daily_scheduler_daemon.log")
    print(f"  stdout/stderr:           tail -f {DAEMON_LOG}")
    print(f"  策略更新日志:             tail -f {LOG_DIR}/agent_b.log")
    print(f"  记忆清理日志:             tail -f {LOG_DIR}/memory_cleanup.log")
    print(f"  查看进程:                 cat {PID_FILE}")
    print(f"  停止守护:                 kill $(cat {PID_FILE})")
    print(f"  手动冒烟测试（立即执行）:  {PYTHON} daily_scheduler_daemon.py --run-now")


if __name__ == "__main__":
    print("=" * 56)
    print("  Daily Scheduler 守护进程启动器")
    print("=" * 56)
    print()
    _pkill_old()
    _launch()
    _print_status_hint()
