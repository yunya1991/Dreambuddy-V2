"""
内置命令 — status, nodes, history 等基础命令
"""

from __future__ import annotations

import argparse
from typing import Optional

from .base import Command, CommandContext, register_command


@register_command
class StatusCommand(Command):
    name = "status"
    description = "查看 Agent 状态"
    aliases = ["st"]

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        agent = self._get_agent(ctx)
        if not agent:
            return 1

        status = agent.status()
        print()
        print("  🤖 Dreambuddy OS — Agent 状态")
        print("  " + "-" * 40)
        print(f"    执行周期:   {status['cycles_executed']}")
        print(f"    节点数量:   {status['registered_nodes']}")
        print(f"    历史记录:   {status['history_count']}")
        print(f"    检查点数:   {status['checkpoint_count']}")

        budget = status.get("budget", {})
        print()
        print(f"    预算模式:   {budget.get('mode', '-')}")
        print(f"    健康状态:   {budget.get('level', '-')}")
        per_cycle = budget.get("per_cycle", {})
        if per_cycle:
            print(f"    周期预算:   {per_cycle.get('used', 0)}/{per_cycle.get('budget', 0)} "
                  f"({per_cycle.get('usage_ratio', 0):.1%})")
        print()
        return 0

    def _get_agent(self, ctx):
        if ctx.agent:
            return ctx.agent
        try:
            from dreamos.apps.trading_agent import TradingAgent
            ctx.agent = TradingAgent(budget_mode=ctx.budget_mode)
            return ctx.agent
        except Exception as e:
            ctx.error(f"初始化 Agent 失败: {e}")
            return None


@register_command
class NodesCommand(Command):
    name = "nodes"
    description = "列出已注册节点"
    aliases = ["ls"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--chain", "-c", help="按链过滤 (A/C/F)")
        parser.add_argument("--tag", "-t", help="按标签过滤")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        agent = self._get_agent(ctx)
        if not agent:
            return 1

        chain = getattr(args, "chain", None) if args else kwargs.get("chain")
        tag = getattr(args, "tag", None) if args else kwargs.get("tag")

        nodes = agent.registry.list_nodes(chain=chain, tag=tag)
        print()
        print(f"  📦 已注册节点: {len(nodes)} 个")
        print("  " + "-" * 50)

        # 按链分组
        chains: dict = {}
        for n in nodes:
            c = getattr(n, "chain", "?")
            chains.setdefault(c, []).append(n)

        for chain_name, chain_nodes in sorted(chains.items()):
            print(f"\n    [{chain_name} 链]  {len(chain_nodes)} 个节点:")
            for n in chain_nodes:
                tags = ", ".join(n.tags or [])
                print(f"      {n.node_id:4s} {n.name:12s} "
                      f"({n.estimated_latency_ms}ms, {n.estimated_tokens}tok) "
                      f"[{tags}]")
                if n.description and ctx.verbose:
                    print(f"           {n.description}")

        print()
        return 0

    def _get_agent(self, ctx):
        if ctx.agent:
            return ctx.agent
        try:
            from dreamos.apps.trading_agent import TradingAgent
            ctx.agent = TradingAgent(budget_mode=ctx.budget_mode)
            return ctx.agent
        except Exception as e:
            ctx.error(f"初始化 Agent 失败: {e}")
            return None


@register_command
class HistoryCommand(Command):
    name = "history"
    description = "查看历史记录"
    aliases = ["hist"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("-n", "--limit", type=int, default=10,
                            help="显示数量 (默认 10)")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        agent = self._get_agent(ctx)
        if not agent:
            return 1

        limit = getattr(args, "limit", 10) if args else int(kwargs.get("limit", 10))
        entries = agent.history(limit=limit)

        print()
        print(f"  📜 历史记录: {len(entries)} 条")
        print("  " + "-" * 50)

        for i, e in enumerate(entries, 1):
            action = e.get("final_action", "?")
            conf = e.get("final_confidence", 0)
            intent = e.get("intent_type", "?")
            cid = e.get("cycle_id", "?")
            print(f"    {i:2d}. [{cid}] {intent:20s} → {action:5s} ({conf:.0%})")

        print()
        return 0

    def _get_agent(self, ctx):
        if ctx.agent:
            return ctx.agent
        try:
            from dreamos.apps.trading_agent import TradingAgent
            ctx.agent = TradingAgent(budget_mode=ctx.budget_mode)
            return ctx.agent
        except Exception as e:
            ctx.error(f"初始化 Agent 失败: {e}")
            return None
