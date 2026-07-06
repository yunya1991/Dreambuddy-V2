"""
Dreambuddy OS CLI — 插件化命令行工具

类似 Claude Code 的交互式 CLI，支持:
    - 子命令模式（一次性命令）
    - REPL 交互模式（持续对话）
    - Slash 命令（/help, /nodes, /status 等）
    - 插件化扩展（新增命令只需注册插件）
"""

from .app import CLIApp, get_default_app
from .base import Command, CommandContext

__all__ = ["CLIApp", "get_default_app", "Command", "CommandContext"]
