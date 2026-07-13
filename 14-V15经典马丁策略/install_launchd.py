#!/usr/bin/env python3
"""
V15 经典马丁策略 - Launchd 服务安装脚本
安装 com.dreambuddy.v15_trader 服务，每小时执行一次轮询
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
PLIST_SRC = PROJECT_DIR / "com.dreambuddy.v15_trader.plist"
LABEL = "com.dreambuddy.v15_trader"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_DST = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LOG_DIR = PROJECT_DIR / "logs"
UID = os.getuid()


def run(cmd, check=True):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(f"  {result.stdout.strip()}")
    if result.stderr:
        print(f"  {result.stderr.strip()}")
    if check and result.returncode != 0:
        print(f"  [警告] 命令返回码: {result.returncode}")
    return result


def install():
    print("=" * 60)
    print("  V15 经典马丁策略 - Launchd 安装")
    print("=" * 60)
    print()

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/6] 复制 plist 到 LaunchAgents...")
    shutil.copy2(PLIST_SRC, PLIST_DST)
    print(f"  → {PLIST_DST}")
    print()

    print("[2/6] 验证 plist 语法...")
    run(["plutil", "-lint", str(PLIST_DST)])
    print()

    print("[3/6] 卸载旧服务（如果存在）...")
    run(["launchctl", "bootout", f"gui/{UID}/{LABEL}"], check=False)
    run(["launchctl", "unload", str(PLIST_DST)], check=False)
    print("  完成")
    print()

    print("[4/6] 加载服务...")
    run(["launchctl", "bootstrap", f"gui/{UID}", str(PLIST_DST)])
    print("  完成")
    print()

    print("[5/6] 启用服务...")
    run(["launchctl", "enable", f"gui/{UID}/{LABEL}"], check=False)
    print("  完成")
    print()

    print("[6/6] 验证服务状态...")
    result = run(["launchctl", "print", f"gui/{UID}/{LABEL}"], check=False)
    if result.returncode == 0:
        print("  ✅ 服务已加载并运行")
    else:
        print("  ⚠️  服务可能未正常加载，请检查日志")
    print()

    print("=" * 60)
    print("  安装完成！")
    print("=" * 60)
    print()
    print("常用命令:")
    print(f"  查看状态: launchctl print gui/{UID}/{LABEL}")
    print(f"  手动触发: launchctl kickstart -k gui/{UID}/{LABEL}")
    print(f"  停止服务: launchctl bootout gui/{UID}/{LABEL}")
    print(f"  查看日志: tail -f {LOG_DIR / 'v15_launchd.log'}")
    print(f"  交易日志: tail -f {LOG_DIR / 'v15' / 'v15_YYYYMMDD.log'}")
    print()


def uninstall():
    print("=" * 60)
    print("  V15 经典马丁策略 - Launchd 卸载")
    print("=" * 60)
    print()

    print("[1/3] 停止服务...")
    run(["launchctl", "bootout", f"gui/{UID}/{LABEL}"], check=False)
    run(["launchctl", "unload", str(PLIST_DST)], check=False)
    print("  完成")
    print()

    print("[2/3] 删除 plist...")
    if PLIST_DST.exists():
        PLIST_DST.unlink()
        print(f"  已删除 {PLIST_DST}")
    else:
        print("  plist 不存在，跳过")
    print()

    print("[3/3] 验证...")
    result = run(["launchctl", "print", f"gui/{UID}/{LABEL}"], check=False)
    if result.returncode != 0:
        print("  ✅ 服务已卸载")
    else:
        print("  ⚠️  服务可能仍在运行")
    print()


def status():
    print(f"服务: {LABEL}")
    print()
    result = subprocess.run(
        ["launchctl", "print", f"gui/{UID}/{LABEL}"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(result.stdout[:1000])
    else:
        print("  服务未加载")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        uninstall()
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        status()
    else:
        install()
