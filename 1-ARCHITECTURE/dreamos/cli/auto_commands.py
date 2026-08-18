"""
自动交易命令 — auto, trade 等自动化交易管理命令
"""

from __future__ import annotations

import argparse
import json
from typing import Optional

from .base import Command, CommandContext, register_command
from .auto_trader import AutoTrader


@register_command
class AutoCommand(Command):
    name = "auto"
    description = "自动化交易管理"
    aliases = ["trade"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        subparsers = parser.add_subparsers(dest="action", help="子命令")

        scan_parser = subparsers.add_parser("scan", help="扫描单个币种并分析")
        scan_parser.add_argument("symbol", help="币种 (如 BTC, ETH, SOL)")
        scan_parser.add_argument("--live", action="store_true", help="实盘交易模式")
        scan_parser.add_argument("--exchange", "-e", default="hyperliquid",
                                choices=["hyperliquid", "okx"], help="交易所 (默认: hyperliquid)")

        multi_parser = subparsers.add_parser("scan-all", help="扫描多个币种")
        multi_parser.add_argument("--symbols", "-s", action="append", help="币种列表")
        multi_parser.add_argument("--all", action="store_true", help="扫描全部默认币种")
        multi_parser.add_argument("--live", action="store_true", help="实盘交易模式")
        multi_parser.add_argument("--exchange", "-e", default="hyperliquid",
                                choices=["hyperliquid", "okx"], help="交易所 (默认: hyperliquid)")

        status_parser = subparsers.add_parser("status", help="查看账户状态")
        status_parser.add_argument("--exchange", "-e", default="hyperliquid",
                                choices=["hyperliquid", "okx"], help="交易所 (默认: hyperliquid)")

        enable_parser = subparsers.add_parser("enable", help="启用自动交易")

        disable_parser = subparsers.add_parser("disable", help="禁用自动交易")

        test_parser = subparsers.add_parser("test", help="测试自动化交易流程")
        test_parser.add_argument("symbol", help="测试币种")
        test_parser.add_argument("--exchange", "-e", default="hyperliquid",
                                choices=["hyperliquid", "okx"], help="交易所 (默认: hyperliquid)")

        exit_parser = subparsers.add_parser("exit", help="检查离场条件")
        exit_parser.add_argument("symbol", help="币种")
        exit_parser.add_argument("entry_price", type=float, help="入场价")
        exit_parser.add_argument("direction", choices=["LONG", "SHORT"], help="方向")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        action = getattr(args, "action", "scan")

        if action == "scan":
            return self._scan(ctx, args)
        elif action == "scan-all":
            return self._scan_all(ctx, args)
        elif action == "status":
            return self._show_status(ctx, args)
        elif action == "enable":
            return self._enable(ctx)
        elif action == "disable":
            return self._disable(ctx)
        elif action == "test":
            return self._test(ctx, args)
        elif action == "exit":
            return self._check_exit(ctx, args)
        else:
            return self._scan(ctx, args)

    def _get_trader(self, ctx: CommandContext, dry_run: bool = True, exchange: str = "hyperliquid") -> AutoTrader:
        if (not hasattr(ctx, "auto_trader") or ctx.auto_trader is None
                or getattr(ctx.auto_trader, "exchange", "") != exchange):
            ctx.auto_trader = AutoTrader(dry_run=dry_run, exchange=exchange)
        else:
            ctx.auto_trader.dry_run = dry_run
            ctx.auto_trader.exchange = exchange
        return ctx.auto_trader

    def _scan(self, ctx: CommandContext, args: argparse.Namespace) -> int:
        symbol = args.symbol
        dry_run = not getattr(args, "live", False)
        exchange = getattr(args, "exchange", "hyperliquid")
        trader = self._get_trader(ctx, dry_run=dry_run, exchange=exchange)

        print(f"\n{'🚀' if not dry_run else '🔍'} 开始 {'实盘' if not dry_run else '模拟'}扫描 {symbol}...")
        print(f"   交易所: {exchange}")
        print("-" * 50)

        result = trader.run_auto_trade(symbol)

        self._print_result(result)
        return 0

    def _scan_all(self, ctx: CommandContext, args: argparse.Namespace) -> int:
        symbols = getattr(args, "symbols", [])
        dry_run = not getattr(args, "live", False)
        exchange = getattr(args, "exchange", "hyperliquid")
        trader = self._get_trader(ctx, dry_run=dry_run, exchange=exchange)

        if args.all or not symbols:
            symbols = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "OP", "ARB"]

        print(f"\n{'🚀' if not dry_run else '🔍'} 开始 {'实盘' if not dry_run else '模拟'}扫描 {len(symbols)} 个币种...")
        print(f"   交易所: {exchange}")
        print("-" * 50)

        for symbol in symbols:
            print(f"\n📊 正在分析 {symbol}...")
            result = trader.run_auto_trade(symbol)
            final = result.get("final_result")
            status_icon = {
                "TRADE_EXECUTED": "✅",
                "DRY_RUN": "🔍",
                "HOLD": "⏸️",
                "CONFIDENCE_TOO_LOW": "⚠️",
                "RISK_REJECTED": "🛡️",
                "ANALYSIS_FAILED": "❌",
                "EXECUTION_FAILED": "❌",
            }.get(final, "❓")
            print(f"   {status_icon} {symbol}: {final}")

        print("\n扫描完成!")
        return 0

    def _show_status(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None) -> int:
        exchange = getattr(args, "exchange", "hyperliquid") if args else "hyperliquid"
        trader = self._get_trader(ctx, exchange=exchange)
        status = trader.get_account_status()

        print("\n🏦 账户状态")
        print("-" * 30)

        if status.get("error"):
            print(f"  ❌ 错误: {status['error']}")
        else:
            exchange = status.get("exchange", "unknown")
            print(f"  交易所: {exchange}")
            print(f"  总资产: ${status['total_eq']}")

            if "assets" in status:
                print("  资产明细:")
                for asset, info in status["assets"].items():
                    print(f"    {asset}: {info['total']:.4f} (可用: {info['avail']:.4f})")

            if "positions" in status:
                positions = status["positions"]
                if positions:
                    print("  当前持仓:")
                    for pos in positions:
                        side = "LONG" if float(pos.get("size", 0)) > 0 else "SHORT"
                        print(f"    {pos['coin']}: {pos['size']} @ {pos.get('entry_px', 0)} ({side})")
                else:
                    print("  当前持仓: 无")

        print(f"  自动交易: {'✅ 已启用' if trader.is_enabled() else '❌ 已禁用'}")
        print(f"  模式: {'实盘' if not trader.dry_run else '模拟'}")
        print()
        return 0

    def _enable(self, ctx: CommandContext) -> int:
        trader = self._get_trader(ctx)
        trader.set_enabled(True)
        print("\n  ✅ 自动交易已启用")
        print()
        return 0

    def _disable(self, ctx: CommandContext) -> int:
        trader = self._get_trader(ctx)
        trader.set_enabled(False)
        print("\n  ❌ 自动交易已禁用")
        print()
        return 0

    def _test(self, ctx: CommandContext, args: argparse.Namespace) -> int:
        symbol = args.symbol
        trader = self._get_trader(ctx, dry_run=True)

        print(f"\n🧪 测试 {symbol} 自动化交易流程...")
        print("-" * 50)

        result = trader.run_auto_trade(symbol)

        print("\n📋 测试报告")
        print("-" * 30)
        print(f"  最终结果: {result.get('final_result')}")
        print(f"  执行时间: {result.get('execution_time', 0):.2f}s")
        print(f"  时间戳: {result.get('timestamp')}")

        if result.get("steps"):
            print("\n  执行步骤:")
            for step in result["steps"]:
                status_icon = {
                    "completed": "✅",
                    "passed": "✅",
                    "approved": "✅",
                    "failed": "❌",
                    "rejected": "❌",
                    "dry_run": "🔍",
                    "hold": "⏸️",
                    "running": "🔄",
                }.get(step.get("status"), "➡️")
                print(f"    {status_icon} {step.get('step')}: {step.get('status')}")
                if step.get("reason"):
                    print(f"         原因: {step['reason']}")

        if result.get("error"):
            print(f"\n  ❌ 错误: {result['error']}")

        print()
        return 0

    def _check_exit(self, ctx: CommandContext, args: argparse.Namespace) -> int:
        symbol = args.symbol
        entry_price = args.entry_price
        direction = args.direction
        trader = self._get_trader(ctx)

        print(f"\n📉 检查 {symbol} 离场条件")
        print(f"  入场价: ${entry_price:.2f}")
        print(f"  方向: {direction}")
        print("-" * 30)

        result = trader.run_exit_check(symbol, entry_price, direction)

        if result.get("exit"):
            print(f"  ✅ 需要离场")
            print(f"  原因: {result.get('reason')}")
            print(f"  离场价: ${result.get('exit_price', 0):.2f}")
            if result.get("execution"):
                exec_result = result["execution"]
                if exec_result.get("dry_run"):
                    print(f"  模式: 模拟交易")
                    print(f"  动作: {exec_result.get('action')}")
        else:
            print(f"  ⏸️ 无需离场")
            print(f"  原因: {result.get('reason')}")

        print()
        return 0

    def _print_result(self, result: dict):
        print(f"\n📊 交易结果: {result.get('final_result')}")

        if result.get("steps"):
            print("\n执行步骤:")
            for step in result["steps"]:
                status_icon = {
                    "completed": "✅",
                    "passed": "✅",
                    "approved": "✅",
                    "failed": "❌",
                    "rejected": "❌",
                    "dry_run": "🔍",
                    "hold": "⏸️",
                    "running": "🔄",
                }.get(step.get("status"), "➡️")
                print(f"  {status_icon} {step.get('step')}: {step.get('status')}")
                if step.get("reason"):
                    print(f"       原因: {step['reason']}")
                if step.get("confidence"):
                    print(f"       置信度: {step['confidence']:.2f}")

        if result.get("execution_time"):
            print(f"\n⏱️ 执行时间: {result['execution_time']:.2f}s")

        if result.get("error"):
            print(f"\n❌ 错误: {result['error']}")

        print()
