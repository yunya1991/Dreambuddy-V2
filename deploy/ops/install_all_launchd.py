#!/usr/bin/env python3
"""
DreamBuddy 全系统 Launchd 统一安装脚本

管理 7 个 launchd 服务：
  1. com.dreambuddy.ab_orchestrator   — Agent A/B 调度 (600s)
  2. com.dreambuddy.ab_monitor        — Agent A/B 监控 (4h)
  3. com.dreambuddy.screen_orchestrator — 三屏调度 (600s)
  4. com.dreambuddy.screen_monitor     — 三屏监控 (4h)
  5. com.dreambuddy.yijing_trading     — 易经推理交易 (1h)
  6. com.dreambuddy.yijing_monitor     — 易经推理监控 (4h)
  7. com.dreambuddy.dreamos            — DreamOS 自动交易 (1h)
  8. com.dreambuddy.v15_trader         — V15 马丁策略 (1h)

用法:
  python3 install_all_launchd.py              # 安装全部
  python3 install_all_launchd.py install      # 安装全部
  python3 install_all_launchd.py uninstall    # 卸载全部
  python3 install_all_launchd.py status       # 查看状态
  python3 install_all_launchd.py install dreamos  # 仅安装 dreamos
"""
import os
import sys
import subprocess
from pathlib import Path

UID = os.getuid()
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

# 所有服务的 plist 源文件路径
SERVICES = {
    "com.dreambuddy.ab_orchestrator": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/com.dreambuddy.ab_orchestrator.plist"
    ),
    "com.dreambuddy.ab_monitor": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/com.dreambuddy.ab_monitor.plist"
    ),
    "com.dreambuddy.screen_orchestrator": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/com.dreambuddy.screen_orchestrator.plist"
    ),
    "com.dreambuddy.screen_monitor": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/com.dreambuddy.screen_monitor.plist"
    ),
    "com.dreambuddy.yijing_trading": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/com.dreambuddy.yijing_trading.plist"
    ),
    "com.dreambuddy.yijing_monitor": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/com.dreambuddy.yijing_monitor.plist"
    ),
    "com.dreambuddy.dreamos": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/com.dreambuddy.dreamos.plist"
    ),
    "com.dreambuddy.v15_trader": Path(
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/com.dreambuddy.v15_trader.plist"
    ),
}

# 如果源 plist 不在项目目录，检查 LaunchAgents 里是否已有
for label, src in list(SERVICES.items()):
    if not src.exists():
        alt = LAUNCH_AGENTS_DIR / f"{label}.plist"
        if alt.exists():
            SERVICES[label] = alt


def run(cmd, check=False):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def install_service(label, src_plist):
    dst = LAUNCH_AGENTS_DIR / f"{label}.plist"

    # 复制 plist
    import shutil
    shutil.copy2(src_plist, dst)

    # 验证语法
    result = run(["plutil", "-lint", str(dst)])
    if result.returncode != 0:
        print(f"  [错误] plist 语法无效: {result.stderr.strip()}")
        return False

    # 卸载旧实例
    run(["launchctl", "bootout", f"gui/{UID}/{label}"], check=False)

    # 加载
    result = run(["launchctl", "bootstrap", f"gui/{UID}", str(dst)])
    if result.returncode != 0 and "already" not in (result.stderr or "").lower():
        # 尝试先 unload 再 load
        run(["launchctl", "unload", str(dst)], check=False)
        result = run(["launchctl", "load", str(dst)], check=False)

    # 启用
    run(["launchctl", "enable", f"gui/{UID}/{label}"], check=False)

    # 验证
    result = run(["launchctl", "print", f"gui/{UID}/{label}"], check=False)
    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            if "state" in line and "=" in line:
                print(f"  {line.strip()}")
                break
        return True
    else:
        print(f"  [警告] 服务可能未正常加载")
        return False


def uninstall_service(label):
    run(["launchctl", "bootout", f"gui/{UID}/{label}"], check=False)
    run(["launchctl", "unload", str(LAUNCH_AGENTS_DIR / f"{label}.plist")], check=False)
    dst = LAUNCH_AGENTS_DIR / f"{label}.plist"
    if dst.exists():
        dst.unlink()


def status_service(label):
    result = run(["launchctl", "print", f"gui/{UID}/{label}"], check=False)
    if result.returncode != 0:
        return "未加载"

    state = "未知"
    runs = "0"
    last_exit = "无"
    interval = "?"

    for line in result.stdout.split("\n"):
        line = line.strip()
        if line.startswith("state ="):
            state = line.split("=", 1)[1].strip()
        elif line.startswith("runs ="):
            runs = line.split("=", 1)[1].strip()
        elif line.startswith("last exit code ="):
            last_exit = line.split("=", 1)[1].strip()
        elif line.startswith("run interval ="):
            interval = line.split("=", 1)[1].strip()

    return f"state={state} runs={runs} exit={last_exit} interval={interval}s"


def do_install(targets=None):
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  DreamBuddy 全系统 Launchd 安装")
    print("=" * 70)
    print()

    labels = targets or list(SERVICES.keys())
    success = 0
    failed = 0

    for label in labels:
        src = SERVICES.get(label)
        if not src or not src.exists():
            print(f"  [跳过] {label} — plist 源文件不存在")
            failed += 1
            continue

        print(f"  [{label}]")
        if install_service(label, src):
            print(f"  → 安装成功")
            success += 1
        else:
            print(f"  → 安装失败")
            failed += 1
        print()

    print("=" * 70)
    print(f"  完成: {success} 成功, {failed} 失败")
    print("=" * 70)


def do_uninstall(targets=None):
    print("=" * 70)
    print("  DreamBuddy 全系统 Launchd 卸载")
    print("=" * 70)
    print()

    labels = targets or list(SERVICES.keys())
    for label in labels:
        print(f"  [{label}]")
        uninstall_service(label)
        print(f"  → 已卸载")
    print()
    print("  全部卸载完成")


def do_status(targets=None):
    print("=" * 70)
    print("  DreamBuddy 全系统 Launchd 状态")
    print("=" * 70)
    print()

    labels = targets or list(SERVICES.keys())
    print(f"  {'服务名':<40} {'状态'}")
    print(f"  {'-'*40} {'-'*50}")
    for label in labels:
        s = status_service(label)
        print(f"  {label:<40} {s}")
    print()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    targets = [a for a in sys.argv[2:] if not a.startswith("-")]
    # 支持 short label (如 dreamos → com.dreambuddy.dreamos)
    if targets:
        expanded = []
        for t in targets:
            if t.startswith("com.dreambuddy."):
                expanded.append(t)
            else:
                found = [k for k in SERVICES if k.endswith(t)]
                if found:
                    expanded.append(found[0])
                else:
                    print(f"  未知服务: {t}")
        targets = expanded

    if action == "install":
        do_install(targets or None)
    elif action == "uninstall":
        do_uninstall(targets or None)
    elif action == "status":
        do_status(targets or None)
    else:
        print(__doc__)
