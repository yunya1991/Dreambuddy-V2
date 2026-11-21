"""Auto.js 无障碍保活守护：MIUI 会周期性撤销无障碍服务，这里检测并恢复。

用法：
    python3 skill/scripts/a11y_guard.py            # 常驻，每 15 秒检测
    python3 skill/scripts/a11y_guard.py --once     # 只检测一次并恢复（可用于 doctor）

恢复策略（按成本从低到高）：
1. settings put secure enabled_accessibility_services 追加 AutoJs6（不打断脚本）
2. 20 秒后仍未绑定，才 force-stop + monkey 重启 Auto.js，并在日志提示需人工运行脚本
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

PKG = "org.autojs.autojs6"
SERVICE = f"{PKG}/org.autojs.autojs.core.accessibility.AccessibilityServiceUsher"
MENU_SERVICE = "com.android.settings/.accessibility.accessibilitymenu.AccessibilityMenuService"


def _adb(args: list[str], timeout: int = 12) -> str:
    try:
        done = subprocess.run(
            ["adb"] + args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return done.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def bound() -> bool:
    """无障碍服务是否真的绑定（不只是设置里打开）。"""
    return "AutoJs6" in _adb(["shell", "dumpsys", "accessibility"])


def enabled_list() -> str:
    return _adb(["shell", "settings", "get", "secure", "enabled_accessibility_services"]).strip()


def restore_settings() -> bool:
    """把 AutoJs6 追加回启用列表，不重启 App（对脚本最友好）。"""
    current = enabled_list()
    if current == "null":
        current = ""
    services = [item for item in current.split(":") if item]
    if SERVICE in services:
        return False
    services.append(SERVICE)
    if MENU_SERVICE not in services:
        services.insert(0, MENU_SERVICE)
    _adb(["shell", "settings", "put", "secure", "enabled_accessibility_services", ":".join(services)])
    _adb(["shell", "settings", "put", "secure", "accessibility_enabled", "1"])
    return True


def restart_autojs() -> None:
    _adb(["shell", "am", "force-stop", PKG])
    time.sleep(1)
    _adb(["shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1"])


def ensure(wait: float = 20.0) -> dict:
    """检测并恢复一次；返回 {bound, restored, restarted}。"""
    if bound():
        return {"bound": True, "restored": False, "restarted": False}
    restored = restore_settings()
    deadline = time.time() + wait
    while time.time() < deadline:
        if bound():
            return {"bound": True, "restored": restored, "restarted": False}
        time.sleep(3)
    restart_autojs()
    time.sleep(6)
    return {"bound": bound(), "restored": restored, "restarted": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto.js 无障碍保活守护")
    parser.add_argument("--once", action="store_true", help="只检测/恢复一次")
    parser.add_argument("--interval", type=int, default=15, help="检测间隔秒数（默认 15）")
    parser.add_argument("--quiet", action="store_true", help="仅异常时输出")
    args = parser.parse_args()

    if args.once:
        result = ensure()
        print("bound={bound} restored={restored} restarted={restarted}".format(**result))
        return 0 if result["bound"] else 3

    print("[a11y-guard] 启动，间隔 {}s".format(args.interval), flush=True)
    while True:
        try:
            result = ensure()
            if result["restored"] or result["restarted"]:
                print(
                    "[a11y-guard] {} bound={} restored={} restarted={}（若重启用过，需人工在 Auto.js 里点运行脚本）".format(
                        time.strftime("%H:%M:%S"), result["bound"], result["restored"], result["restarted"]
                    ),
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - 守护进程不能因单次异常退出
            if not args.quiet:
                print("[a11y-guard] 异常：{}".format(exc), flush=True)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
