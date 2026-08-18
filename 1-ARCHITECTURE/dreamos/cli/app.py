"""
CLI 主应用 — 管理命令注册、REPL 会话、子命令分发
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .base import Command, CommandContext, list_commands, get_command

try:
    from . import scheduler_commands
except Exception:
    pass

try:
    from . import auto_commands
except Exception:
    pass

try:
    from . import orchestration_commands
except Exception:
    pass


class CLIApp:
    """Dreambuddy OS CLI 应用

    负责:
        - 子命令解析与分发
        - REPL 交互会话管理
        - 全局上下文维护
    """

    def __init__(self, name: str = "dreamos", description: str = "Dreambuddy OS CLI"):
        self.name = name
        self.description = description
        self._context = CommandContext(app=self)

    @property
    def context(self) -> CommandContext:
        return self._context

    def build_parser(self) -> argparse.ArgumentParser:
        """构建 argparse 解析器"""
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
        )
        parser.add_argument("--budget", default="standard",
                            choices=["lean", "standard", "full"],
                            help="预算模式 (默认: standard)")
        parser.add_argument("-v", "--verbose", action="store_true",
                            help="详细输出")

        subparsers = parser.add_subparsers(dest="command", help="子命令")

        # 注册所有命令的参数
        for cmd in list_commands():
            if cmd.hidden:
                continue
            sub = subparsers.add_parser(cmd.name, help=cmd.description,
                                        aliases=cmd.aliases)
            cmd.add_arguments(sub)
            sub.set_defaults(_command=cmd)

        # REPL 是默认入口
        p_repl = subparsers.add_parser("repl", help="交互式 REPL（默认）")
        p_repl.set_defaults(_command=None)

        return parser

    def run(self, argv: Optional[List[str]] = None) -> int:
        """运行 CLI

        Args:
            argv: 命令行参数，None 则使用 sys.argv

        Returns:
            退出码
        """
        parser = self.build_parser()
        args = parser.parse_args(argv)

        # 更新上下文
        self._context.verbose = args.verbose
        self._context.budget_mode = args.budget

        # 无命令或 repl 命令 → 进入 REPL
        if not args.command or args.command == "repl":
            return self._run_repl()

        # 子命令模式
        cmd = getattr(args, "_command", None)
        if cmd is None:
            parser.print_help()
            return 1

        try:
            return cmd.execute(self._context, args)
        except KeyboardInterrupt:
            print("\n👋 已中断")
            return 130
        except Exception as e:
            self._context.error(f"命令执行失败: {e}")
            if self._context.verbose:
                import traceback
                traceback.print_exc()
            return 1

    def _run_repl(self) -> int:
        """运行 REPL 交互模式"""
        from .repl import REPLSession
        session = REPLSession(app=self)
        return session.run()


_default_app: Optional[CLIApp] = None


def get_default_app() -> CLIApp:
    """获取全局默认 CLI 应用"""
    global _default_app
    if _default_app is None:
        _default_app = CLIApp()
    return _default_app
