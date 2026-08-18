#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import plistlib
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
PLIST_SRC = PROJECT_DIR / "com.dreambuddy.screen_orchestrator.plist"
LABEL = "com.dreambuddy.screen_orchestrator"
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
        raise RuntimeError(f"命令失败: {result.returncode}")
    return result

def install():
    print("=" * 50)
    print("  三屏马丁编排器 - Launchd 安装")
    print("=" * 50)
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

    print("[6/6] 触发首次运行...")
    run(["launchctl", "kickstart", f"gui/{UID}/{LABEL}"])
    print("  完成")
    print()

    print("=" * 50)
    print("  ✅ 安装完成！")
    print("=" * 50)
    print()
    print(f"服务标签: {LABEL}")
    print(f"运行间隔: 每 10 分钟")
    print(f"开机自启: 是 (RunAtLoad=true)")
    print(f"日志文件: {LOG_DIR}/screen_orchestrator_launchd.log")
    print()
    print("常用命令：")
    print(f"  查看状态: launchctl list | grep {LABEL}")
    print(f"  手动触发: launchctl kickstart gui/{UID}/{LABEL}")
    print(f"  查看日志: tail -f {LOG_DIR}/screen_orchestrator_launchd.log")
    print(f"  停止服务: launchctl bootout gui/{UID}/{LABEL}")
    print(f"  卸载服务: launchctl unload {PLIST_DST}")
    print()

def uninstall():
    print("卸载服务...")
    run(["launchctl", "bootout", f"gui/{UID}/{LABEL}"], check=False)
    run(["launchctl", "unload", str(PLIST_DST)], check=False)
    if PLIST_DST.exists():
        PLIST_DST.unlink()
        print(f"  已删除: {PLIST_DST}")
    print("✅ 已卸载")

def status():
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True
    )
    found = False
    for line in result.stdout.splitlines():
        if LABEL in line:
            print(f"服务状态: {line.strip()}")
            found = True
    if not found:
        print("服务状态: 未运行")

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    elif action == "status":
        status()
    else:
        print(f"用法: {sys.argv[0]} [install|uninstall|status]")
        sys.exit(1)
