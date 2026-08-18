"""
CLI 基础类 — 命令插件接口

设计:
    - Command: 所有命令的基类
    - CommandContext: 命令执行上下文（包含 agent、配置、输出工具等）
    - 命令通过 register_command 装饰器注册
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dreamos.apps.trading_agent import TradingAgent


@dataclass
class CommandContext:
    """命令执行上下文"""
    app: Any = None  # CLIApp
    agent: Optional["TradingAgent"] = None
    verbose: bool = False
    budget_mode: str = "standard"
    extra: Dict[str, Any] = field(default_factory=dict)

    def print(self, *args, **kwargs):
        """打印输出"""
        print(*args, **kwargs)

    def info(self, msg: str):
        """信息输出（蓝色）"""
        print(f"\033[94mℹ\033[0m {msg}")

    def success(self, msg: str):
        """成功输出（绿色）"""
        print(f"\033[92m✓\033[0m {msg}")

    def warning(self, msg: str):
        """警告输出（黄色）"""
        print(f"\033[93m⚠\033[0m {msg}")

    def error(self, msg: str):
        """错误输出（红色）"""
        print(f"\033[91m✗\033[0m {msg}")


class Command(ABC):
    """命令基类

    子类需实现:
        - name: 命令名（用于子命令和 slash 命令）
        - description: 命令描述
        - execute(): 执行命令
    """

    name: str = ""
    description: str = ""
    aliases: List[str] = []
    hidden: bool = False

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """添加命令行参数（子命令模式使用）"""
        pass

    @abstractmethod
    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        """执行命令

        Args:
            ctx: 执行上下文
            args: argparse 解析的参数（子命令模式时有）
            **kwargs: 关键字参数（REPL/slash 模式时传入）

        Returns:
            退出码（0 = 成功）
        """
        ...

    def help_text(self) -> str:
        """帮助文本"""
        return self.description


# 全局命令注册表
_command_registry: Dict[str, Command] = {}


def register_command(cls: type) -> type:
    """命令注册装饰器"""
    cmd = cls()
    _command_registry[cmd.name] = cmd
    for alias in cmd.aliases:
        _command_registry[alias] = cmd
    return cls


def get_command(name: str) -> Optional[Command]:
    """获取命令"""
    return _command_registry.get(name)


def list_commands() -> List[Command]:
    """列出所有命令（去重）"""
    seen = set()
    result = []
    for cmd in _command_registry.values():
        if id(cmd) not in seen:
            seen.add(id(cmd))
            result.append(cmd)
    return sorted(result, key=lambda c: c.name)
