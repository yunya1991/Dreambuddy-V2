#!/usr/bin/env python3
"""
认知自动接入层 — 安装脚本

一键安装三层自动接入：
  1. 触发层：git post-commit hook
  2. 协议层：MCP server配置
  3. 宿主层：Claude Code hooks + TRAE MCP配置

用法:
  python3 cognitive_install.py              # 安装全部
  python3 cognitive_install.py --trigger    # 仅安装git hook
  python3 cognitive_install.py --mcp        # 仅配置MCP
  python3 cognitive_install.py --claude     # 仅配置Claude Code hooks
  python3 cognitive_install.py --uninstall  # 卸载
"""

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # dreambuddy-v2/
TOOLS_DIR = PROJECT_ROOT / "4-MEMORY" / "9-工具与接口"
HOOK_SCRIPT = TOOLS_DIR / "cognitive_hook.py"
MCP_SCRIPT = TOOLS_DIR / "cognitive_mcp_server.py"
DAEMON_SCRIPT = TOOLS_DIR / "cognitive_daemon.py"


# ============================================================
# 1. 触发层：安装 git post-commit hook
# ============================================================

GIT_HOOK_CONTENT = f"""#!/bin/sh
# 认知闭环自动触发 — git post-commit hook
# 自动从commit提取经验 → record → verify → 贝叶斯更新
# 静默失败，不阻塞git操作

COGNITIVE_HOOK="{HOOK_SCRIPT}"

if [ -x "$(command -v python3)" ] && [ -f "$COGNITIVE_HOOK" ]; then
    python3 "$COGNITIVE_HOOK" --post-commit 2>/dev/null &
else
    # Windows fallback
    if command -v py >/dev/null 2>&1; then
        py "$COGNITIVE_HOOK" --post-commit 2>/dev/null &
    fi
fi
"""


def install_git_hook(verbose=True):
    """安装 git post-commit hook"""
    hooks_dir = PROJECT_ROOT / ".git" / "hooks"
    if not hooks_dir.exists():
        if verbose:
            print("⚠️  .git/hooks/ 不存在，跳过git hook安装")
        return False

    hook_file = hooks_dir / "post-commit"

    # 备份已有hook（如果不是我们的）
    if hook_file.exists():
        existing = hook_file.read_text()
        if "cognitive_hook" not in existing:
            backup = hooks_dir / "post-commit.bak"
            shutil.copy2(hook_file, backup)
            if verbose:
                print(f"   已备份原有hook到 {backup.name}")

    hook_file.write_text(GIT_HOOK_CONTENT)
    hook_file.chmod(hook_file.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    if verbose:
        print(f"✅ git post-commit hook 已安装: {hook_file}")
    return True


# ============================================================
# 2. 协议层：MCP server配置模板
# ============================================================

def get_mcp_config() -> dict:
    """返回MCP server配置（供各IDE使用）"""
    return {
        "mcpServers": {
            "cognitive": {
                "command": "python3",
                "args": [str(MCP_SCRIPT)],
                "env": {},
            }
        }
    }


# ============================================================
# 3. 宿主层：Claude Code hooks配置
# ============================================================

def get_claude_hooks_config() -> dict:
    """返回Claude Code hooks配置"""
    return {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python3 "{HOOK_SCRIPT}" --post-commit --dry-run 2>/dev/null',
                        }
                    ],
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python3 "{MCP_SCRIPT}" --warmup_process "$CLAUDE_SESSION_CONTEXT" 2>/dev/null || true',
                        }
                    ],
                }
            ],
        },
        "mcpServers": {
            "cognitive": {
                "command": "python3",
                "args": [str(MCP_SCRIPT)],
            }
        },
    }


def install_claude_hooks(verbose=True):
    """安装Claude Code hooks配置"""
    claude_dir = PROJECT_ROOT / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_file = claude_dir / "settings.json"

    # 合并已有配置
    existing = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            pass

    new_config = get_claude_hooks_config()

    # 合并mcpServers（不覆盖已有的）
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}
    existing["mcpServers"]["cognitive"] = new_config["mcpServers"]["cognitive"]

    # 设置hooks
    existing["hooks"] = new_config["hooks"]

    settings_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    if verbose:
        print(f"✅ Claude Code hooks 已配置: {settings_file}")
        print(f"   - PostToolUse: 编辑后自动触发认知闭环")
        print(f"   - SessionStart: 会话开始时检索记忆")
        print(f"   - MCP Server: cognitive 已注册")
    return True


# ============================================================
# 4. 宿主层：TRAE MCP配置
# ============================================================

def install_trae_mcp(verbose=True):
    """安装TRAE MCP配置"""
    mcp_config = get_mcp_config()

    # TRAE的MCP配置位置（项目级）
    trae_config_dir = PROJECT_ROOT / ".trae"
    trae_config_dir.mkdir(exist_ok=True)

    trae_config_file = trae_config_dir / "mcp.json"

    # 合并已有配置
    existing = {}
    if trae_config_file.exists():
        try:
            existing = json.loads(trae_config_file.read_text())
        except json.JSONDecodeError:
            pass

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}
    existing["mcpServers"]["cognitive"] = mcp_config["mcpServers"]["cognitive"]

    trae_config_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    if verbose:
        print(f"✅ TRAE MCP 已配置: {trae_config_file}")
        print(f"   - cognitive server: {MCP_SCRIPT}")
    return True


# ============================================================
# 4.5 触发层增强：文件监听daemon + launchd配置
# ============================================================

LAUNCHD_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dreambuddy.cognitive-daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{daemon_script}</string>
        <string>--watch</string>
        <string>{project_root}</string>
        <string>--interval</string>
        <string>5</string>
        <string>--debounce</string>
        <string>10</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{project_root}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/cognitive-daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/cognitive-daemon.err</string>
</dict>
</plist>
"""


def install_daemon(verbose=True):
    """安装文件监听daemon（launchd自启动）"""
    import sys as _sys

    plist_content = LAUNCHD_PLIST_TEMPLATE.format(
        python=_sys.executable,
        daemon_script=str(DAEMON_SCRIPT),
        project_root=str(PROJECT_ROOT),
    )

    # 项目级launchd配置
    launch_dir = PROJECT_ROOT / ".cognitive"
    launch_dir.mkdir(exist_ok=True)
    plist_file = launch_dir / "com.dreambuddy.cognitive-daemon.plist"
    plist_file.write_text(plist_content)

    if verbose:
        print(f"✅ 文件监听daemon配置已创建: {plist_file}")
        print(f"   - 监听目录: {PROJECT_ROOT}")
        print(f"   - 轮询间隔: 5秒, 防抖窗口: 10秒")
        print(f"   - 启动方式:")
        print(f"     前台: python3 {DAEMON_SCRIPT} --watch . -v")
        print(f"     后台: python3 {DAEMON_SCRIPT} --watch . --daemon")
        print(f"     launchd: launchctl load {plist_file}")
        print(f"   - 停止: python3 {DAEMON_SCRIPT} --stop")
    return True


# ============================================================
# 5. 通用配置文件
# ============================================================

def install_universal_config(verbose=True):
    """安装通用认知配置文件"""
    config_dir = PROJECT_ROOT / ".cognitive"
    config_dir.mkdir(exist_ok=True)

    config = {
        "version": "1.0.0",
        "description": "认知闭环自动接入层配置",
        "layers": {
            "trigger": {
                "enabled": True,
                "type": "git-post-commit",
                "script": str(HOOK_SCRIPT),
                "auto_record": True,
                "auto_verify": True,
                "default_quality": "C",
                "default_confidence": 0.3,
            },
            "protocol": {
                "enabled": True,
                "type": "mcp-stdio",
                "script": str(MCP_SCRIPT),
                "tools": ["recall", "record", "verify", "stats", "health"],
            },
            "host": {
                "claude_code": {
                    "enabled": True,
                    "config_path": ".claude/settings.json",
                },
                "trae": {
                    "enabled": True,
                    "config_path": ".trae/mcp.json",
                },
                "cursor": {
                    "enabled": False,
                    "config_path": ".cursor/rules",
                    "note": "Cursor无原生hooks，通过MCP server调用",
                },
            },
        },
    }

    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    if verbose:
        print(f"✅ 通用配置已创建: {config_file}")
    return True


# ============================================================
# 6. 卸载
# ============================================================

def uninstall(verbose=True):
    """卸载认知自动接入层"""
    # git hook
    hook_file = PROJECT_ROOT / ".git" / "hooks" / "post-commit"
    if hook_file.exists():
        content = hook_file.read_text()
        if "cognitive_hook" in content:
            hook_file.unlink()
            # 恢复备份
            backup = PROJECT_ROOT / ".git" / "hooks" / "post-commit.bak"
            if backup.exists():
                shutil.move(str(backup), str(hook_file))
                hook_file.chmod(hook_file.stat().st_mode | stat.S_IEXEC)
            if verbose:
                print("✅ git post-commit hook 已卸载")

    # 通用配置
    config_dir = PROJECT_ROOT / ".cognitive"
    if config_dir.exists():
        shutil.rmtree(config_dir)
        if verbose:
            print("✅ .cognitive/ 已移除")

    if verbose:
        print("ℹ️  Claude Code/TRAE的MCP配置需手动移除（避免影响其他MCP server）")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="认知自动接入层安装")
    parser.add_argument("--trigger", action="store_true", help="仅安装git hook触发层")
    parser.add_argument("--daemon", action="store_true", help="仅安装文件监听daemon")
    parser.add_argument("--mcp", action="store_true", help="仅配置MCP协议层")
    parser.add_argument("--claude", action="store_true", help="仅配置Claude Code hooks")
    parser.add_argument("--trae", action="store_true", help="仅配置TRAE MCP")
    parser.add_argument("--uninstall", action="store_true", help="卸载")
    parser.add_argument("-v", "--verbose", action="store_true", default=True)
    args = parser.parse_args()

    if args.uninstall:
        uninstall(args.verbose)
        return

    # 如果没有指定任何选项，安装全部
    install_all = not any([args.trigger, args.daemon, args.mcp, args.claude, args.trae])

    print("=" * 60)
    print("🔧 认知闭环自动接入层安装")
    print("=" * 60)

    if install_all or args.trigger:
        print("\n📌 触发层 (git post-commit hook)")
        install_git_hook(args.verbose)

    if install_all or args.daemon:
        print("\n📌 触发层增强 (文件监听daemon)")
        install_daemon(args.verbose)

    if install_all or args.mcp or args.trae:
        print("\n📌 协议层 (MCP server)")
        if install_all or args.trae:
            install_trae_mcp(args.verbose)
        elif args.mcp:
            config = get_mcp_config()
            print(f"   MCP配置模板:")
            print(f"   {json.dumps(config, indent=2)}")

    if install_all or args.claude:
        print("\n📌 宿主层 (Claude Code hooks)")
        install_claude_hooks(args.verbose)

    if install_all:
        print("\n📌 通用配置")
        install_universal_config(args.verbose)

    print("\n" + "=" * 60)
    print("✨ 安装完成！认知闭环已自动接入")
    print("=" * 60)
    print("\n📋 快速验证:")
    print(f"   1. git hook: git commit -m 'test: 认知闭环测试' → 自动记录经验")
    print(f"   2. MCP server: echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{{}}}}' | python3 {MCP_SCRIPT}")
    print(f"   3. Claude Code: 重启会话 → 自动加载cognitive MCP server")
    print(f"   4. TRAE: 在MCP面板查看cognitive server → 调用recall/record")


if __name__ == "__main__":
    main()
