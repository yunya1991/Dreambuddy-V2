"""
REPL 交互会话 — Claude Code 风格的交互式终端

特性:
    - 自然语言对话（调用 trading agent）
    - Slash 命令（/help, /status, /nodes 等）
    - 思考过程逐步展示
    - 市场数据管理
    - 历史记录
    - 彩色输出
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Optional

from .base import CommandContext, get_command, list_commands


class REPLSession:
    """REPL 交互会话"""

    def __init__(self, app):
        self.app = app
        self.ctx: CommandContext = app.context
        self._running = False
        self._history: list[str] = []
        self._market_data: Dict[str, Any] = {}

    def run(self) -> int:
        """启动 REPL 会话"""
        self._running = True
        self._print_banner()

        while self._running:
            try:
                user_input = self._read_input()
            except (EOFError, KeyboardInterrupt):
                print("\n\n👋 再见！")
                return 0

            if not user_input:
                continue

            self._history.append(user_input)

            # Slash 命令
            if user_input.startswith("/"):
                self._handle_slash_command(user_input)
                continue

            # 自然语言对话
            try:
                self._handle_chat(user_input)
            except Exception as e:
                self.ctx.error(f"处理失败: {e}")
                if self.ctx.verbose:
                    import traceback
                    traceback.print_exc()

        return 0

    def _print_banner(self):
        """打印欢迎横幅"""
        print()
        print("\033[96m" + "=" * 60 + "\033[0m")
        print("  \033[1m\033[96m🤖 Dreambuddy OS\033[0m  —  智能交易分析终端")
        print("\033[96m" + "=" * 60 + "\033[0m")
        print()
        print("  \033[90m输入自然语言进行市场分析，或使用 \033[0m\033[93m/help\033[0m\033[90m 查看命令\033[0m")
        print()

    def _read_input(self) -> str:
        """读取用户输入"""
        prompt = "\033[94m❯\033[0m "
        try:
            return input(prompt).strip()
        except EOFError:
            raise

    def _handle_slash_command(self, user_input: str):
        """处理 slash 命令"""
        # 移除开头的斜杠，然后去除空白
        raw_content = user_input[1:]
        
        # 处理空命令或只有空白的情况
        if not raw_content.strip():
            self.ctx.warning("请输入命令名，如 /help")
            return
        
        # 解析命令名和参数
        parts = raw_content.strip().split(maxsplit=1)
        cmd_name = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        if not cmd_name:
            self.ctx.warning("请输入命令名，如 /help")
            return

        # 内置命令
        if cmd_name in ("quit", "exit", "q"):
            self._running = False
            print("\n👋 再见！")
            return

        if cmd_name == "help":
            self._print_help()
            return

        if cmd_name in ("clear", "cls"):
            print("\033c", end="")
            return

        if cmd_name == "market":
            self._cmd_market(cmd_args)
            return

        if cmd_name == "set":
            self._cmd_set(cmd_args)
            return

        if cmd_name == "verbose":
            self.ctx.verbose = not self.ctx.verbose
            status = "开启" if self.ctx.verbose else "关闭"
            self.ctx.info(f"详细输出已{status}")
            return

        if cmd_name == "budget":
            if cmd_args and cmd_args in ("lean", "standard", "full"):
                self.ctx.budget_mode = cmd_args
                self.ctx.agent = None  # 重置 agent
                self.ctx.success(f"预算模式已切换为: {cmd_args}")
            else:
                self.ctx.info(f"当前预算模式: {self.ctx.budget_mode}")
                self.ctx.info("可用模式: lean, standard, full")
            return

        # 注册的命令
        cmd = get_command(cmd_name)
        if cmd:
            try:
                cmd.execute(self.ctx, args=None, cmd_args=cmd_args)
            except Exception as e:
                self.ctx.error(f"命令执行失败: {e}")
                if self.ctx.verbose:
                    import traceback
                    traceback.print_exc()
            return

        self.ctx.warning(f"未知命令: /{cmd_name}，输入 /help 查看可用命令")

    def _cmd_market(self, args: str):
        """管理市场数据"""
        if not args or args == "show":
            self._show_market_data()
            return

        if args == "clear":
            self._market_data.clear()
            self.ctx.success("市场数据已清空")
            return

        self.ctx.warning("用法: /market [show|clear]")
        self.ctx.info("使用 /set price=65000 设置单个市场数据字段")

    def _cmd_set(self, args: str):
        """设置市场数据字段"""
        if not args or "=" not in args:
            self.ctx.warning("用法: /set key=value")
            self.ctx.info("示例: /set price=65000, /set rsi=55, /set change_24h=3.2")
            return

        key, _, value = args.partition("=")
        key = key.strip()
        value = value.strip()

        # 尝试转换为数字
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            pass

        self._market_data[key] = value
        self.ctx.success(f"已设置: {key} = {value}")

    def _show_market_data(self):
        """显示当前市场数据"""
        if not self._market_data:
            self.ctx.info("当前无市场数据，使用 /set key=value 设置")
            return

        print()
        print("  📊 当前市场数据:")
        print("  " + "-" * 40)
        for k, v in sorted(self._market_data.items()):
            print(f"    {k:15s} = {v}")
        print()

    def _handle_chat(self, user_input: str):
        """处理自然语言对话"""
        agent = self._get_agent()
        if not agent:
            return

        # 显示思考中动画
        print()
        self._print_thinking_indicator()

        start_time = time.time()
        result = agent.chat(
            message=user_input,
            market_data=self._market_data.copy() if self._market_data else None,
        )
        elapsed = time.time() - start_time

        # 清除思考指示器并打印结果
        print("\r\033[K", end="")
        self._print_result(result, elapsed)

    def _print_thinking_indicator(self):
        """显示思考中指示器"""
        print("  \033[90m🧠 思考中...\033[0m", end="", flush=True)

    def _print_result(self, result: dict, elapsed: float = 0):
        """格式化输出分析结果（三层结构）"""
        action = result.get("action", "HOLD")
        confidence = result.get("confidence", 0)

        # 颜色符号
        if action == "LONG":
            action_str = "\033[92m🟢 LONG 做多\033[0m"
        elif action == "SHORT":
            action_str = "\033[91m🔴 SHORT 做空\033[0m"
        else:
            action_str = "\033[93m🟡 HOLD 观望\033[0m"

        print()
        print("\033[95m" + "─" * 60 + "\033[0m")
        print(f"  交易决策: {action_str}  \033[90m(置信度 {confidence:.1%})\033[0m")
        print("\033[95m" + "─" * 60 + "\033[0m")

        # 核心观点（前 3 条 rationale）
        rationale = result.get("rationale", [])
        if rationale:
            print()
            print("  \033[1m📌 核心观点\033[0m")
            for r in rationale[:3]:
                print(f"    \033[92m•\033[0m {r}")

        # 执行摘要
        print()
        intent_info = result.get("intent", {})
        plan_info = result.get("plan", {})
        exec_info = result.get("execution", {})

        print(f"  \033[90m周期ID:\033[0m   {result.get('cycle_id', '-')}")
        print(f"  \033[90m意图:\033[0m     {intent_info.get('type', '-')} "
              f"\033[90m({intent_info.get('confidence', 0):.0%})\033[0m")
        print(f"  \033[90m链路:\033[0m     {plan_info.get('chain', '-')} "
              f"\033[90m({', '.join(plan_info.get('nodes', []))})\033[0m")
        print(f"  \033[90m耗时:\033[0m     {result.get('latency_ms', 0):.0f}ms")
        print(f"  \033[90mToken:\033[0m    {result.get('tokens_used', 0)}")

        # 详细分析
        if len(rationale) > 3:
            print()
            print("  \033[1m📋 详细分析\033[0m")
            for r in rationale[3:8]:
                print(f"    \033[90m•\033[0m {r}")
            if len(rationale) > 8:
                print(f"    \033[90m... 还有 {len(rationale) - 8} 条\033[0m")

        # Verbose 模式显示完整 JSON
        if self.ctx.verbose:
            print()
            print("  \033[1m🔍 完整数据\033[0m")
            print(f"  \033[90m{json.dumps(result, indent=2, ensure_ascii=False, default=str)}\033[0m")

        print(flush=True)  # 确保 stdout flush，让用户看到提示符

    def _print_help(self):
        """打印帮助信息"""
        print()
        print("  \033[1m📖 可用命令\033[0m")
        print()

        # 内置命令
        print("  \033[96m内置命令:\033[0m")
        builtin_cmds = [
            ("/help", "显示帮助信息"),
            ("/status", "查看 Agent 状态"),
            ("/nodes", "列出已注册节点"),
            ("/history", "查看历史记录"),
            ("/market", "管理市场数据"),
            ("/set key=value", "设置市场数据字段"),
            ("/budget [mode]", "切换预算模式 (lean/standard/full)"),
            ("/verbose", "切换详细输出"),
            ("/clear", "清屏"),
            ("/quit", "退出"),
        ]
        for cmd, desc in builtin_cmds:
            print(f"    \033[93m{cmd:<18s}\033[0m {desc}")

        # 注册的命令
        registered = [c for c in list_commands() if not c.hidden]
        if registered:
            print()
            print("  \033[96m插件命令:\033[0m")
            for cmd in registered:
                aliases = f" (/{', /'.join(cmd.aliases)})" if cmd.aliases else ""
                print(f"    \033[93m/{cmd.name:<10s}\033[0m {cmd.description}\033[90m{aliases}\033[0m")

        print()
        print("  \033[90m💡 直接输入自然语言进行对话分析\033[0m")
        print()

    def _get_agent(self):
        """获取或创建 TradingAgent（延迟初始化）"""
        if self.ctx.agent is not None:
            return self.ctx.agent

        print("\r\033[K  \033[90m⚙️  初始化 Agent...\033[0m", end="", flush=True)

        try:
            from dreamos.apps.trading_agent import TradingAgent
            self.ctx.agent = TradingAgent(budget_mode=self.ctx.budget_mode)
            print("\r\033[K", end="", flush=True)
            return self.ctx.agent
        except Exception as e:
            print("\r\033[K", end="", flush=True)
            self.ctx.error(f"初始化 Agent 失败: {e}")
            if self.ctx.verbose:
                import traceback
                traceback.print_exc()
            return None
