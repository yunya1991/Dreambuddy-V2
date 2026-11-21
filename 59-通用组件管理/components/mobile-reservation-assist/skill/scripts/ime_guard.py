#!/usr/bin/env python3
"""输入法守护：u2 自动化会把默认输入法切成 AdbKeyboard。

本脚本每 15 秒检查一次：若停在 AdbKeyboard 且当前没有 mra 自动化在跑，
就切回用户原输入法（默认讯飞），避免手机输入法"卡住"。
"""

from __future__ import annotations

import os
import subprocess
import time

SERIAL = os.environ.get("MRA_DEVICE_SERIAL", "")
DEFAULT_IME = os.environ.get("MRA_DEFAULT_IME", "com.iflytek.inputmethod.miui/.FlyIME")
INTERVAL = int(os.environ.get("MRA_IME_GUARD_INTERVAL", "15"))


def adb(*args: str) -> str:
    command = ["adb"] + (["-s", SERIAL] if SERIAL else []) + list(args)
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def automation_running() -> bool:
    try:
        output = subprocess.run(["pgrep", "-f", "mra.py"], capture_output=True, text=True).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(output.strip())


def main() -> None:
    print("[ime-guard] 启动，间隔 {}s，目标输入法 {}".format(INTERVAL, DEFAULT_IME), flush=True)
    while True:
        current = (adb("shell", "settings get secure default_input_method").splitlines() or [""])[0].strip()
        if "uiautomator" in current and not automation_running():
            adb("shell", "ime set", DEFAULT_IME)
            print("[ime-guard] 已恢复输入法 {}".format(DEFAULT_IME), flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
