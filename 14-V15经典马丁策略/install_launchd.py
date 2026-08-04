#!/usr/bin/env python3
"""
V15 经典马丁策略 - Launchd 服务安装脚本
支持两个服务：
  - com.dreambuddy.v15_trader: 每小时完整轮询（信号+交易）
  - com.dreambuddy.v15_light_poll: 每5分钟轻量轮询（持仓同步）
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = PROJECT_DIR / "logs"
UID = os.getuid()

SERVICES = {
    "trader": {
        "plist": PROJECT_DIR / "com.dreambuddy.v15_trader.plist",
        "label": "com.dreambuddy.v15_trader",
        "desc": "完整轮询（每小时）",
    },
    "light_poll": {
        "plist": PROJECT_DIR / "com.dreambuddy.v15_light_poll.plist",
        "label": "com.dreambuddy.v15_light_poll",
        "desc": "轻量轮询（每5分钟）",
    },
    "orchestrator": {
        "plist": PROJECT_DIR / "com.dreambuddy.v15_orchestrator.plist",
        "label": "com.dreambuddy.v15_orchestrator",
        "desc": "自主编排器（每15分钟）",
    },
}


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


def install_service(name):
    svc = SERVICES[name]
    label = svc["label"]
    plist_src = svc["plist"]
    plist_dst = LAUNCH_AGENTS_DIR / f"{label}.plist"

    print(f"\n--- 安装 {name}: {svc['desc']} ---")

    if not plist_src.exists():
        print(f"  ⚠️  plist 源文件不存在: {plist_src}")
        return False

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("  [1/5] 复制 plist 到 LaunchAgents...")
    shutil.copy2(plist_src, plist_dst)
    print(f"    → {plist_dst}")

    print("  [2/5] 验证 plist 语法...")
    run(["plutil", "-lint", str(plist_dst)])

    print("  [3/5] 卸载旧服务（如果存在）...")
    run(["launchctl", "bootout", f"gui/{UID}/{label}"], check=False)
    run(["launchctl", "unload", str(plist_dst)], check=False)

    print("  [4/5] 加载服务...")
    result = run(["launchctl", "bootstrap", f"gui/{UID}", str(plist_dst)])
    if result.returncode != 0:
        print("  ❌ 加载失败")
        return False

    print("  [5/5] 启用服务...")
    run(["launchctl", "enable", f"gui/{UID}/{label}"], check=False)

    print(f"  ✅ {name} 服务安装成功")
    return True


def uninstall_service(name):
    svc = SERVICES[name]
    label = svc["label"]
    plist_dst = LAUNCH_AGENTS_DIR / f"{label}.plist"

    print(f"\n--- 卸载 {name}: {svc['desc']} ---")

    print("  [1/2] 停止服务...")
    run(["launchctl", "bootout", f"gui/{UID}/{label}"], check=False)
    run(["launchctl", "unload", str(plist_dst)], check=False)

    print("  [2/2] 删除 plist...")
    if plist_dst.exists():
        plist_dst.unlink()
        print(f"    已删除 {plist_dst}")
    else:
        print("    plist 不存在，跳过")

    print(f"  ✅ {name} 服务已卸载")


def status_service(name):
    svc = SERVICES[name]
    label = svc["label"]
    print(f"\n--- {name}: {svc['desc']} ---")
    result = subprocess.run(
        ["launchctl", "print", f"gui/{UID}/{label}"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if any(k in line for k in ["state = ", "run count", "last exit code", "path = "]):
                print(f"  {line.strip()}")
        print("  ✅ 服务已加载")
    else:
        print("  ⚠️  服务未加载")


def install_all():
    print("=" * 60)
    print("  V15 经典马丁策略 - Launchd 服务安装")
    print("=" * 60)

    success = 0
    for name in SERVICES:
        if install_service(name):
            success += 1

    print(f"\n{'=' * 60}")
    print(f"  安装完成: {success}/{len(SERVICES)} 个服务成功")
    print("=" * 60)
    print("\n常用命令:")
    for name, svc in SERVICES.items():
        label = svc["label"]
        print(f"  {name} 状态: launchctl print gui/{UID}/{label}")
        print(f"  {name} 手动触发: launchctl kickstart -k gui/{UID}/{label}")
    print(f"\n  查看完整日志: tail -f {LOG_DIR / 'v15_launchd.log'}")
    print()


def uninstall_all():
    print("=" * 60)
    print("  V15 经典马丁策略 - Launchd 服务卸载")
    print("=" * 60)

    for name in SERVICES:
        uninstall_service(name)

    print(f"\n{'=' * 60}")
    print("  卸载完成")
    print("=" * 60)


def status_all():
    print("=" * 60)
    print("  V15 经典马丁策略 - Launchd 服务状态")
    print("=" * 60)

    for name in SERVICES:
        status_service(name)

    print()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"

    if cmd == "uninstall":
        uninstall_all()
    elif cmd == "status":
        status_all()
    elif cmd == "install":
        install_all()
    elif cmd in SERVICES:
        install_service(cmd)
    else:
        print(f"用法: python3 {sys.argv[0]} [install|uninstall|status|<service_name>]")
        print(f"  服务名称: {', '.join(SERVICES.keys())}")
