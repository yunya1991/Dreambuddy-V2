"""
分析命令 — analyze 单次市场数据分析、chat 对话式分析
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from .base import Command, CommandContext, register_command


def _print_result(result: Dict[str, Any], verbose: bool = False) -> None:
    """格式化输出分析结果（三层结构）"""
    action = result.get("action", "HOLD")
    confidence = result.get("confidence", 0)

    if action == "LONG":
        action_str = "\033[92m🟢 LONG 做多\033[0m"
    elif action == "SHORT":
        action_str = "\033[91m🔴 SHORT 做空\033[0m"
    else:
        action_str = "\033[93m🟡 HOLD 观望\033[0m"

    print()
    print("=" * 60)
    print(f"  交易决策: {action_str}  (置信度 {confidence:.1%})")
    print("=" * 60)

    rationale = result.get("rationale", [])
    if rationale:
        print()
        print("  📌 核心观点:")
        for r in rationale[:3]:
            print(f"    • {r}")

    print()
    print(f"  周期ID:   {result.get('cycle_id', '-')}")
    print(f"  意图:     {result.get('intent', {}).get('type', '-')} "
          f"({result.get('intent', {}).get('confidence', 0):.0%})")
    print(f"  链路:     {result.get('plan', {}).get('chain', '-')} "
          f"({', '.join(result.get('plan', {}).get('nodes', []))})")
    print(f"  耗时:     {result.get('latency_ms', 0):.0f}ms")
    print(f"  Token:    {result.get('tokens_used', 0)}")
    print("-" * 60)

    if len(rationale) > 3:
        print("  📋 详细分析依据:")
        for r in rationale[3:8]:
            print(f"    • {r}")
        if len(rationale) > 8:
            print(f"    ... 还有 {len(rationale) - 8} 条")
        print("-" * 60)

    if verbose:
        print("  🔍 完整结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    print()


@register_command
class AnalyzeCommand(Command):
    name = "analyze"
    description = "单次市场数据分析"
    aliases = ["a"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--price", type=float, help="当前价格")
        parser.add_argument("--rsi", type=float, help="RSI 14 值")
        parser.add_argument("--ema20", type=float, help="EMA 20")
        parser.add_argument("--ema50", type=float, help="EMA 50")
        parser.add_argument("--ema200", type=float, help="EMA 200")
        parser.add_argument("--change-24h", type=float, help="24h 涨跌幅 %")
        parser.add_argument("--change-4h", type=float, help="4h 涨跌幅 %")
        parser.add_argument("--change-1h", type=float, help="1h 涨跌幅 %")
        parser.add_argument("--vol-ratio", type=float, help="量比")
        parser.add_argument("--regime", default="TREND",
                            choices=["TREND", "RANGE"], help="市场状态")
        parser.add_argument("--funding", type=float, help="资金费率 (如 0.0001)")
        parser.add_argument("--fgi", type=float, help="恐惧贪婪指数 (0-100)")
        parser.add_argument("--atr", type=float, help="ATR 百分比")
        parser.add_argument("-i", "--input", type=str, help="用户输入文本")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        agent = self._get_agent(ctx)
        if not agent:
            return 1

        # 构建市场数据
        market_data = {}
        if args:
            if args.price is not None:
                market_data["price"] = args.price
            if args.rsi is not None:
                market_data["rsi14"] = args.rsi
            if args.ema20 is not None:
                market_data["ema20"] = args.ema20
            if args.ema50 is not None:
                market_data["ema50"] = args.ema50
            if args.ema200 is not None:
                market_data["ema200"] = args.ema200
            if args.change_24h is not None:
                market_data["change_24h"] = args.change_24h
            if args.change_4h is not None:
                market_data["change_4h"] = args.change_4h
            if args.change_1h is not None:
                market_data["change_1h"] = args.change_1h
            if args.vol_ratio is not None:
                market_data["vol_ratio"] = args.vol_ratio
            if args.regime:
                market_data["regime"] = args.regime
            if args.funding is not None:
                market_data["funding_rate"] = args.funding
            if args.fgi is not None:
                market_data["fgi"] = args.fgi
            # 修复: atr 可能为 None，需要判空
            if args.atr is not None:
                market_data["atr_pct"] = args.atr / 100

            user_input = args.input or ""
        else:
            user_input = kwargs.get("cmd_args", "")

        result = agent.run(
            user_input=user_input,
            market_data=market_data,
        )

        _print_result(result, verbose=ctx.verbose)
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
class ChatCommand(Command):
    name = "chat"
    description = "对话式分析"
    aliases = ["c"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("message", help="分析请求")
        parser.add_argument("--price", type=float, help="当前价格")
        parser.add_argument("--rsi", type=float, help="RSI 值")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        agent = self._get_agent(ctx)
        if not agent:
            return 1

        market_data = {}
        message = ""

        if args:
            message = args.message
            if args.price is not None:
                market_data["price"] = args.price
            if args.rsi is not None:
                market_data["rsi14"] = args.rsi
        else:
            message = kwargs.get("cmd_args", "")

        result = agent.chat(
            message=message,
            market_data=market_data,
        )

        _print_result(result, verbose=ctx.verbose)
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
