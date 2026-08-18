#!/usr/bin/env python3
"""
DreamBuddy 全系统 Launchd 统一管理工具
管理所有交易相关系统的 launchd 服务：
- Agent A/B 编排器 (10min)
- 三屏马丁编排器 (10min)
- Agent A/B 监控自进化 (4h)
- 三屏马丁监控自进化 (4h)
- 易经推理监控 (4h)
- 易经推理交易 (1h)
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
OPS_DIR = ROOT_DIR / "deploy" / "ops"
AB_DIR = ROOT_DIR / "experiments" / "ab-trading"
YIJING_DIR = ROOT_DIR / "11-易经推理系统"
HERMES_LOG_DIR = Path.home() / ".hermes" / "logs"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
UID = os.getuid()

SERVICES = [
    {
        "label": "com.dreambuddy.ab_orchestrator",
        "plist_src": AB_DIR / "com.dreambuddy.ab_orchestrator.plist",
        "name": "Agent A/B 编排器",
        "interval": "每10分钟",
        "log_file": AB_DIR / "logs" / "orchestrator_launchd.log",
    },
    {
        "label": "com.dreambuddy.screen_orchestrator",
        "plist_src": AB_DIR / "com.dreambuddy.screen_orchestrator.plist",
        "name": "三屏马丁编排器",
        "interval": "每10分钟",
        "log_file": AB_DIR / "logs" / "screen_orchestrator_launchd.log",
    },
    {
        "label": "com.dreambuddy.ab_monitor",
        "plist_src": AB_DIR / "com.dreambuddy.ab_monitor.plist",
        "name": "Agent A/B 监控自进化",
        "interval": "每4小时",
        "log_file": AB_DIR / "logs" / "auto_monitor_launchd.log",
    },
    {
        "label": "com.dreambuddy.screen_monitor",
        "plist_src": AB_DIR / "com.dreambuddy.screen_monitor.plist",
        "name": "三屏马丁监控自进化",
        "interval": "每4小时",
        "log_file": AB_DIR / "logs" / "screen_monitor_launchd.log",
    },
    {
        "label": "com.dreambuddy.yijing_monitor",
        "plist_src": YIJING_DIR / "com.dreambuddy.yijing_monitor.plist",
        "name": "易经推理监控",
        "interval": "每4小时",
        "log_file": YIJING_DIR / "logs" / "yijing_monitor_launchd.log",
    },
    {
        "label": "com.dreambuddy.yijing_trading",
        "plist_src": YIJING_DIR / "com.dreambuddy.yijing_trading.plist",
        "name": "易经推理交易",
        "interval": "每1小时",
        "log_file": YIJING_DIR / "logs" / "trading_stdout.log",
    },
    # ── Hermes 三件套 (macOS 替代 systemd) ──
    {
        "label": "com.dreambuddy.hermes_gateway",
        "plist_src": OPS_DIR / "com.dreambuddy.hermes_gateway.plist",
        "name": "Hermes Gateway",
        "interval": "常驻",
        "log_file": HERMES_LOG_DIR / "gateway.log",
    },
    {
        "label": "com.dreambuddy.hermes_group_poller",
        "plist_src": OPS_DIR / "com.dreambuddy.hermes_group_poller.plist",
        "name": "Hermes Group Poller",
        "interval": "常驻",
        "log_file": HERMES_LOG_DIR / "poller.log",
    },
    {
        "label": "com.dreambuddy.hermes_dashboard",
        "plist_src": OPS_DIR / "com.dreambuddy.hermes_dashboard.plist",
        "name": "Hermes Dashboard",
        "interval": "常驻",
        "log_file": HERMES_LOG_DIR / "dashboard.log",
    },
]

OLD_SERVICES = [
    "com.yijing.trading",
]


def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  失败: {result.stderr.strip()}")
    return result


def install_service(svc):
    print(f"\n  安装: {svc['name']} ({svc['label']})")

    plist_dst = LAUNCH_AGENTS_DIR / f"{svc['label']}.plist"

    svc["log_file"].parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    content = svc["plist_src"].read_text(encoding="utf-8")
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp.write(f'''
import pathlib
p = pathlib.Path("{plist_dst}")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text({repr(content)}, encoding="utf-8")
print("ok")
''')
    tmp.close()
    subprocess.run([sys.executable, tmp.name], check=True, capture_output=True)
    os.unlink(tmp.name)
    print(f"    plist 已复制到 LaunchAgents")

    run(["plutil", "-lint", str(plist_dst)], check=False)

    run(["launchctl", "bootout", f"gui/{UID}/{svc['label']}"], check=False)
    run(["launchctl", "unload", str(plist_dst)], check=False)

    r = run(["launchctl", "bootstrap", f"gui/{UID}", str(plist_dst)], check=False)
    if r.returncode != 0:
        print(f"    ⚠️ bootstrap 警告: {r.stderr.strip()}")

    run(["launchctl", "enable", f"gui/{UID}/{svc['label']}"], check=False)
    run(["launchctl", "kickstart", f"gui/{UID}/{svc['label']}"], check=False)
    print(f"    ✅ 已加载并触发首次运行")


def uninstall_service(svc):
    print(f"\n  卸载: {svc['name']} ({svc['label']})")
    plist_dst = LAUNCH_AGENTS_DIR / f"{svc['label']}.plist"

    run(["launchctl", "bootout", f"gui/{UID}/{svc['label']}"], check=False)
    run(["launchctl", "unload", str(plist_dst)], check=False)

    if plist_dst.exists():
        try:
            import os
            os.remove(str(plist_dst))
        except:
            pass
        print(f"    已删除 plist")
    print(f"    ✅ 已卸载")


def status_service(svc):
    result = run(
        ["launchctl", "print", f"gui/{UID}/{svc['label']}"],
        check=False
    )
    state = "未运行"
    active = "0"
    interval = "-"

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("state ="):
            state = line.split("=")[1].strip()
        if line.startswith("active count ="):
            active = line.split("=")[1].strip()
        if line.startswith("run interval ="):
            interval = line.split("=")[1].strip()

    status_icon = "🟢" if state in ("running", "active", "not running") else "🔴"
    print(f"  {status_icon} {svc['name']:<20} 状态:{state:<12} 活跃:{active:<3} 间隔:{svc['interval']}")


def cmd_install():
    print("=" * 60)
    print("  DreamBuddy 全系统 Launchd 安装")
    print("=" * 60)

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    import os
    for old in OLD_SERVICES:
        old_plist = LAUNCH_AGENTS_DIR / f"{old}.plist"
        if old_plist.exists():
            print(f"\n  清理旧服务: {old}")
            run(["launchctl", "bootout", f"gui/{UID}/{old}"], check=False)
            run(["launchctl", "unload", str(old_plist)], check=False)
            try:
                os.remove(str(old_plist))
            except:
                pass
            print(f"    ✅ 已清理")

    for svc in SERVICES:
        install_service(svc)

    print("\n" + "=" * 60)
    print("  ✅ 全部安装完成！")
    print("=" * 60)
    print()
    cmd_status()


def cmd_uninstall():
    print("=" * 60)
    print("  DreamBuddy 全系统 Launchd 卸载")
    print("=" * 60)

    for svc in SERVICES:
        uninstall_service(svc)

    for old in OLD_SERVICES:
        old_plist = LAUNCH_AGENTS_DIR / f"{old}.plist"
        if old_plist.exists():
            print(f"\n  清理旧服务: {old}")
            run(["launchctl", "bootout", f"gui/{UID}/{old}"], check=False)
            run(["launchctl", "unload", str(old_plist)], check=False)
            old_plist.unlink()

    print("\n" + "=" * 60)
    print("  ✅ 全部卸载完成")
    print("=" * 60)


def cmd_status():
    print("=" * 60)
    print("  DreamBuddy 全系统 Launchd 状态")
    print("=" * 60)

    for svc in SERVICES:
        status_service(svc)

    print()
    print("  常用命令:")
    print(f"    查看某服务详情: launchctl print gui/{UID}/<label>")
    print(f"    手动触发:       launchctl kickstart gui/{UID}/<label>")
    print(f"    查看实时日志:   tail -f <log_file>")
    print()


def cmd_restart():
    print("=" * 60)
    print("  DreamBuddy 全系统 Launchd 重启")
    print("=" * 60)

    for svc in SERVICES:
        print(f"\n  重启: {svc['name']}")
        run(["launchctl", "kickstart", "-k", f"gui/{UID}/{svc['label']}"], check=False)
        print(f"    ✅ 已重启")

    print("\n" + "=" * 60)
    print("  ✅ 全部重启完成")
    print("=" * 60)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "install":
        cmd_install()
    elif action == "uninstall":
        cmd_uninstall()
    elif action == "status":
        cmd_status()
    elif action == "restart":
        cmd_restart()
    else:
        print(f"用法: {sys.argv[0]} [install|uninstall|status|restart]")
        sys.exit(1)


if __name__ == "__main__":
    main()
