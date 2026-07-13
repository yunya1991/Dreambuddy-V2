"""
调度器命令 — schedule, cron, job 等定时任务管理命令
"""

from __future__ import annotations

import argparse
import json
from typing import Optional, List

from .base import Command, CommandContext, register_command
from .scheduler import DreamOSScheduler, PRESET_CRON, DEFAULT_SYMBOLS
from .auto_trader import AutoTrader


@register_command
class ScheduleCommand(Command):
    name = "schedule"
    description = "定时任务管理"
    aliases = ["cron", "job"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        subparsers = parser.add_subparsers(dest="action", help="子命令")

        list_parser = subparsers.add_parser("list", help="列出所有定时任务")
        list_parser.add_argument("-v", "--verbose", action="store_true", help="详细信息")

        add_parser = subparsers.add_parser("add", help="添加定时任务")
        add_parser.add_argument("name", help="任务名称")
        add_parser.add_argument("cron", help=f"cron 表达式 (预设: {', '.join(PRESET_CRON.keys())})")
        add_parser.add_argument("--symbol", "-s", action="append", help="扫描币种")
        add_parser.add_argument("--now", action="store_true", help="立即执行一次")

        remove_parser = subparsers.add_parser("remove", help="删除定时任务")
        remove_parser.add_argument("name", help="任务名称")

        start_parser = subparsers.add_parser("start", help="启动定时任务")
        start_parser.add_argument("name", help="任务名称")

        stop_parser = subparsers.add_parser("stop", help="停止定时任务")
        stop_parser.add_argument("name", help="任务名称")

        run_parser = subparsers.add_parser("run", help="立即执行任务")
        run_parser.add_argument("name", help="任务名称")

        scan_parser = subparsers.add_parser("scan", help="添加多币种扫描任务")
        scan_parser.add_argument("name", help="任务名称")
        scan_parser.add_argument("cron", help=f"cron 表达式")
        scan_parser.add_argument("--symbol", "-s", action="append", help="扫描币种，可多次")
        scan_parser.add_argument("--all", action="store_true", help="使用默认币种列表")

        stats_parser = subparsers.add_parser("stats", help="查看调度器统计")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None,
                **kwargs) -> int:
        scheduler = self._get_scheduler(ctx)
        action = getattr(args, "action", "list")

        if action == "list":
            return self._list_jobs(ctx, scheduler, args)
        elif action == "add":
            return self._add_job(ctx, scheduler, args)
        elif action == "remove":
            return self._remove_job(ctx, scheduler, args)
        elif action == "start":
            return self._start_job(ctx, scheduler, args)
        elif action == "stop":
            return self._stop_job(ctx, scheduler, args)
        elif action == "run":
            return self._run_job(ctx, scheduler, args)
        elif action == "scan":
            return self._add_scan_job(ctx, scheduler, args)
        elif action == "stats":
            return self._show_stats(ctx, scheduler)
        else:
            return self._list_jobs(ctx, scheduler, args)

    def _get_scheduler(self, ctx: CommandContext) -> DreamOSScheduler:
        if not hasattr(ctx, "scheduler") or ctx.scheduler is None:
            ctx.scheduler = DreamOSScheduler()
        return ctx.scheduler

    def _list_jobs(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                   args: argparse.Namespace) -> int:
        jobs = scheduler.list_jobs()
        verbose = getattr(args, "verbose", False)

        print()
        print(f"  🕐 定时任务: {len(jobs)} 个")
        print("  " + "-" * 50)

        if not jobs:
            print("    暂无定时任务")
        else:
            for job in jobs:
                status_icon = {
                    "running": "🔄",
                    "stopped": "⏹️",
                    "paused": "⏸️",
                    "error": "❌",
                }.get(job["status"], "❓")
                print(f"    {status_icon} {job['name']:20s}")
                print(f"        Cron: {job['cron_expr']}")
                print(f"        Status: {job['status']}")
                print(f"        Runs: {job['run_count']} | Errors: {job['error_count']}")
                if job["last_run"]:
                    print(f"        Last: {job['last_run']}")
                if job["next_run"]:
                    print(f"        Next: {job['next_run']}")
                if job["last_error"] and verbose:
                    print(f"        Error: {job['last_error']}")

        print()
        return 0

    def _add_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                 args: argparse.Namespace) -> int:
        name = args.name
        cron = args.cron
        run_now = getattr(args, "now", False)

        cron = PRESET_CRON.get(cron, cron)

        def _dummy_task():
            ctx.info(f"任务 '{name}' 执行")

        scheduler.add_job(name, cron, _dummy_task, run_now=run_now)
        print(f"\n  ✅ 任务 '{name}' 已添加 (cron: {cron})")
        if run_now:
            print(f"     已立即执行一次")
        print()
        return 0

    def _remove_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                    args: argparse.Namespace) -> int:
        name = args.name
        if scheduler.get_job(name):
            scheduler.remove_job(name)
            print(f"\n  ✅ 任务 '{name}' 已删除")
        else:
            print(f"\n  ❌ 任务 '{name}' 不存在")
        print()
        return 0

    def _start_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                   args: argparse.Namespace) -> int:
        name = args.name
        job = scheduler.get_job(name)
        if job:
            job.start()
            print(f"\n  ✅ 任务 '{name}' 已启动")
        else:
            print(f"\n  ❌ 任务 '{name}' 不存在")
        print()
        return 0

    def _stop_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                  args: argparse.Namespace) -> int:
        name = args.name
        job = scheduler.get_job(name)
        if job:
            job.stop()
            print(f"\n  ✅ 任务 '{name}' 已停止")
        else:
            print(f"\n  ❌ 任务 '{name}' 不存在")
        print()
        return 0

    def _run_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                 args: argparse.Namespace) -> int:
        name = args.name
        job = scheduler.get_job(name)
        if job:
            job.run_now()
            print(f"\n  ✅ 任务 '{name}' 正在执行...")
        else:
            print(f"\n  ❌ 任务 '{name}' 不存在")
        print()
        return 0

    def _add_scan_job(self, ctx: CommandContext, scheduler: DreamOSScheduler,
                      args: argparse.Namespace) -> int:
        name = args.name
        cron = args.cron
        symbols = getattr(args, "symbol", [])

        if args.all or not symbols:
            symbols = DEFAULT_SYMBOLS

        cron = PRESET_CRON.get(cron, cron)

        auto_trader = AutoTrader(dry_run=True)

        def _scan_task(symbol: str):
            ctx.info(f"🚀 开始扫描 {symbol}...")
            try:
                result = auto_trader.run_auto_trade(symbol)
                ctx.info(f"📊 {symbol} 扫描结果: {result.get('final_result')}")
                if result.get("steps"):
                    for step in result["steps"]:
                        status_icon = {
                            "completed": "✅",
                            "passed": "✅",
                            "approved": "✅",
                            "failed": "❌",
                            "rejected": "❌",
                            "dry_run": "🔍",
                            "hold": "⏸️",
                        }.get(step.get("status"), "➡️")
                        ctx.info(f"   {status_icon} {step.get('step')}: {step.get('status')}")
                        if step.get("reason"):
                            ctx.info(f"      原因: {step['reason']}")
            except Exception as e:
                ctx.error(f"❌ {symbol} 扫描失败: {e}")

        scheduler.add_scan_job(name, cron, symbols, _scan_task)
        print(f"\n  ✅ 扫描任务 '{name}' 已添加")
        print(f"     Cron: {cron}")
        print(f"     Symbols: {', '.join(symbols)}")
        print(f"     模式: dry_run (模拟交易)")
        print()
        return 0

    def _show_stats(self, ctx: CommandContext, scheduler: DreamOSScheduler) -> int:
        stats = scheduler.get_stats()
        print()
        print("  📊 调度器统计")
        print("  " + "-" * 30)
        print(f"    总任务数:   {stats['total_jobs']}")
        print(f"    运行中:     {stats['running_jobs']}")
        print(f"    已暂停:     {stats['paused_jobs']}")
        print(f"    总执行次数: {stats['total_runs']}")
        print(f"    总错误数:   {stats['total_errors']}")
        print(f"    历史记录:   {stats['history_count']}")
        print()
        return 0