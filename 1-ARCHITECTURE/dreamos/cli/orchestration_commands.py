"""
编排命令 — 场景编排回测/查询/进化操作

命令:
    orchestration backtest          运行回测，生成/更新编排记忆表
    orchestration memory list       列出所有场景及其最优编排
    orchestration memory show <ID>  显示某场景的详细回测指标
    orchestration query --scenario  查询某场景的最优编排（含降级路径）
    orchestration evolve --scenario 手动触发进化优化
    orchestration feedback --scenario  查看执行反馈统计
"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

from .base import Command, CommandContext, register_command

logger = logging.getLogger(__name__)


@register_command
class OrchestrationBacktestCommand(Command):
    """运行回测，生成/更新编排记忆表"""

    name = "orchestration-backtest"
    description = "运行场景回测，生成/更新编排记忆表"
    aliases = ["orch-backtest"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--window", type=int, default=24, help="滑动窗口K线数 (默认: 24)")
        parser.add_argument("--step", type=int, default=6, help="窗口步长 (默认: 6)")
        parser.add_argument("--hold", type=int, default=12, help="持有K线数 (默认: 12)")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.core.memory.scenario_backtester import ScenarioBacktester
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        window = getattr(args, "window", 24) if args else kwargs.get("window", 24)
        step = getattr(args, "step", 6) if args else kwargs.get("step", 6)
        hold = getattr(args, "hold", 12) if args else kwargs.get("hold", 12)

        ctx.info(f"启动回测: window={window}, step={step}, hold={hold}")

        bt = ScenarioBacktester()
        results = bt.run(window_size=window, step=step, hold_periods=hold)

        mem = OrchestrationMemory()
        mem.load()
        mem.update_from_backtest(results)
        mem.save()

        stats = mem.get_stats()
        ctx.success(f"回测完成: {stats['covered_scenarios']}/36 场景覆盖")
        ctx.print(f"  sparse: {stats['sparse_scenarios']}")
        ctx.print(f"  high confidence: {stats['high_confidence']}")
        ctx.print(f"  medium confidence: {stats['medium_confidence']}")
        ctx.print(f"  记忆表: {mem.path}")
        return 0


@register_command
class OrchestrationMemoryListCommand(Command):
    """列出所有场景及其最优编排"""

    name = "orchestration-memory-list"
    description = "列出编排记忆表中所有场景"
    aliases = ["orch-memory-list"]

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        mem = OrchestrationMemory()
        if not mem.load():
            ctx.warning("编排记忆表为空，请先运行 orchestration-backtest")
            return 1

        scenarios = mem.list_scenarios()
        ctx.info(f"编排记忆表: {len(scenarios)} 场景")
        ctx.print(f"{'场景ID':<35} {'编排':<12} {'评分':>6} {'样本':>6} {'置信度':<8} {'sparse'}")
        ctx.print("-" * 90)
        for s in scenarios:
            sparse = "✓" if s.get("sparse") else " "
            ctx.print(f"{s['scenario_id']:<35} {s['best_pattern']:<12} "
                       f"{s['score']:>6.3f} {s['sample_count']:>6} "
                       f"{s['confidence']:<8} {sparse}")

        stats = mem.get_stats()
        ctx.print(f"\n覆盖率: {stats['coverage_rate']:.0%} | sparse率: {stats['sparse_rate']:.0%}")
        return 0


@register_command
class OrchestrationMemoryShowCommand(Command):
    """显示某场景的详细回测指标"""

    name = "orchestration-memory-show"
    description = "显示某场景的详细编排记忆"
    aliases = ["orch-memory-show"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("scenario_id", help="场景ID (如 BULL_NORMAL_ACCELERATING)")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        scenario_id = getattr(args, "scenario_id", None) if args else kwargs.get("scenario_id")
        if not scenario_id:
            ctx.error("请提供场景ID")
            return 1

        mem = OrchestrationMemory()
        mem.load()
        data = mem.get_scenario(scenario_id)

        if not data:
            ctx.warning(f"场景 {scenario_id} 不在记忆表中")
            # 查询降级路径
            choice = mem.select(scenario_id)
            ctx.info(f"降级查询: L{choice.fallback_level} → {choice.pattern}")
            ctx.print(f"  节点: {choice.nodes}")
            ctx.print(f"  来源场景: {choice.source_scenario}")
            return 0

        ctx.info(f"场景: {scenario_id}")
        ctx.print(f"  最优编排: {data['best_pattern']}")
        ctx.print(f"  节点: {data['nodes']}")
        ctx.print(f"  评分: {data['score']:.4f}")
        ctx.print(f"  样本数: {data['sample_count']}")
        ctx.print(f"  置信度: {data['confidence']}")
        ctx.print(f"  sparse: {data.get('sparse', False)}")
        metrics = data.get("metrics", {})
        ctx.print(f"  指标:")
        ctx.print(f"    夏普: {metrics.get('sharpe', 0):.4f}")
        ctx.print(f"    收益: {metrics.get('return', 0):.4f}")
        ctx.print(f"    最大回撤: {metrics.get('max_dd', 0):.4f}")
        ctx.print(f"    胜率: {metrics.get('win_rate', 0):.4f}")
        return 0


@register_command
class OrchestrationQueryCommand(Command):
    """查询某场景的最优编排（含降级路径）"""

    name = "orchestration-query"
    description = "查询场景的最优编排（含降级路径）"
    aliases = ["orch-query"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--scenario", required=True, help="场景ID")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        scenario_id = getattr(args, "scenario", None) if args else kwargs.get("scenario")
        if not scenario_id:
            ctx.error("请提供 --scenario")
            return 1

        mem = OrchestrationMemory()
        mem.load()
        choice = mem.select(scenario_id)

        ctx.info(f"场景: {scenario_id}")
        ctx.print(f"  编排模式: {choice.pattern}")
        ctx.print(f"  节点: {choice.nodes}")
        ctx.print(f"  评分: {choice.score:.4f}")
        ctx.print(f"  置信度: {choice.confidence}")
        ctx.print(f"  降级级别: {choice.fallback_level}")
        ctx.print(f"  来源场景: {choice.source_scenario}")
        return 0


@register_command
class OrchestrationEvolveCommand(Command):
    """手动触发进化优化"""

    name = "orchestration-evolve"
    description = "手动触发编排进化优化"
    aliases = ["orch-evolve"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--scenario", help="指定场景ID（不指定则检查所有场景）")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.evolution.engine import EvolutionEngine

        scenario_id = getattr(args, "scenario", None) if args else kwargs.get("scenario")
        engine = EvolutionEngine()

        if scenario_id:
            collector = engine.get_feedback_collector()
            feedback = collector.evaluate(scenario_id)
            ctx.info(f"场景: {scenario_id}")
            ctx.print(f"  使用编排: {feedback.pattern_used}")
            ctx.print(f"  实际夏普: {feedback.actual_sharpe:.4f}")
            ctx.print(f"  预期夏普: {feedback.expected_sharpe:.4f}")
            ctx.print(f"  偏差: {feedback.deviation:.2%}")
            ctx.print(f"  方向准确率: {feedback.direction_accuracy:.0%}")
            ctx.print(f"  触发进化: {'是' if feedback.trigger_evolution else '否'}")
        else:
            updates = engine._check_orchestration_optimization()
            if updates:
                ctx.success(f"进化完成: {len(updates)} 场景更新")
                for u in updates:
                    ctx.print(f"  {u['scenario_id']}: {u['old_pattern']} → {u['new_pattern']} "
                               f"(reason: {u['trigger_reason']})")
            else:
                ctx.info("无场景需要优化")
        return 0


@register_command
class OrchestrationFeedbackCommand(Command):
    """查看执行反馈统计"""

    name = "orchestration-feedback"
    description = "查看执行反馈统计"
    aliases = ["orch-feedback"]

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--scenario", help="指定场景ID")

    def execute(self, ctx: CommandContext, args: Optional[argparse.Namespace] = None, **kwargs) -> int:
        from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        scenario_id = getattr(args, "scenario", None) if args else kwargs.get("scenario")
        mem = OrchestrationMemory()
        mem.load()
        collector = ExecutionFeedbackCollector(mem)

        if scenario_id:
            stats = collector.get_stats(scenario_id)
            ctx.info(f"场景: {scenario_id}")
            ctx.print(f"  总交易: {stats.get('total_trades', 0)}")
            ctx.print(f"  胜率: {stats.get('win_rate', 0):.0%}")
            ctx.print(f"  平均收益: {stats.get('avg_return', 0):.4f}")
            ctx.print(f"  总收益: {stats.get('total_return', 0):.4f}")
            ctx.print(f"  使用编排: {stats.get('patterns_used', [])}")
        else:
            feedbacks = collector.get_all_feedbacks()
            if not feedbacks:
                ctx.info("暂无执行反馈记录")
                return 0
            ctx.info(f"执行反馈: {len(feedbacks)} 场景")
            ctx.print(f"{'场景ID':<35} {'编排':<12} {'实际夏普':>10} {'预期夏普':>10} {'偏差':>8} {'触发'}")
            ctx.print("-" * 90)
            for fb in feedbacks:
                trigger = "✓" if fb.trigger_evolution else " "
                ctx.print(f"{fb.scenario_id:<35} {fb.pattern_used:<12} "
                           f"{fb.actual_sharpe:>10.4f} {fb.expected_sharpe:>10.4f} "
                           f"{fb.deviation:>7.1%} {trigger}")
        return 0
