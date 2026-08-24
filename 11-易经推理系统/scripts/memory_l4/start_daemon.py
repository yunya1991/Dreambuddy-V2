#!/usr/bin/env python3
"""启动交易进程为 daemon，脱离工具会话，避免会话退出时被终止"""
import os
import sys
import subprocess
import time

WORK_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"
LOG_FILE = os.path.join(WORK_DIR, "logs", "trading_daemon.log")
PID_FILE = os.path.join(WORK_DIR, ".workbuddy", "memory_l4", "guardian", "trader_pid.txt")

env = os.environ.copy()
env["HTTPS_PROXY"] = "http://127.0.0.1:7890"
env["HTTP_PROXY"] = "http://127.0.0.1:7890"
env["FEISHU_APP_ID"] = "cli_aa9442bde4b89be9"
env["FEISHU_APP_SECRET"] = "dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"
# 修复日志乱码：强制 UTF-8 输出 + 无缓冲
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUNBUFFERED"] = "1"
env["LANG"] = "en_US.UTF-8"
env["LC_ALL"] = "en_US.UTF-8"

# 杀掉旧进程
subprocess.run(["pkill", "-f", "scripts.memory_l4.polling_trader"],
               capture_output=True)
time.sleep(2)

os.makedirs(os.path.join(WORK_DIR, "logs"), exist_ok=True)
os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)

cmd = [
    "/opt/anaconda3/bin/python3", "-u", "-m",
    "scripts.memory_l4.polling_trader",
    "--interval", "300",
    "--confidence", "0.7955",
    "--max-positions", "5",
    "--position-pct", "0.20",
    # ── Phase1（CBR v3.0）三开关 ──
    "--enable-cbr-cycle-log",
    "--enable-elder-ray-c4",
    "--enable-win-prob-factor",
    # ── 方案C v3.0 SW-C3~C8 六个调控开关（影子生效，异常时可独立关断）──
    "--enable-three-layer-weighter",
    "--enable-elastic-gate-3l",
    "--enable-bcrm-continuity-obs",
    "--enable-btc-self-reflex-valve",
    "--enable-portfolio-risk-fuses",
]

with open(LOG_FILE, "w", encoding="utf-8") as log_f:
    proc = subprocess.Popen(
        cmd,
        cwd=WORK_DIR,
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 调用 setsid()，脱离父会话
    )

print(f"daemon PID={proc.pid}")

with open(PID_FILE, "w") as f:
    f.write(str(proc.pid))

# 等待并检查进程状态
time.sleep(15)
if proc.poll() is None:
    print("OK: daemon 进程运行中")
    # 打印最后几行日志
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            for line in lines[-10:]:
                print(line.rstrip())
    except Exception:
        pass
else:
    print(f"FAIL: daemon 进程已退出，退出码={proc.returncode}")
    try:
        with open(LOG_FILE, "r") as f:
            print(f.read()[-2000:])
    except Exception:
        pass
