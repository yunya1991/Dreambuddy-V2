#!/usr/bin/env python3
"""
三层反思进化调度器
整合A8理论实践验证、做梦部外部反思、GitHub成熟经验搜索
通过回测验证后应用进化参数
"""
import json, os, sys, logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.evolution.evolution_engine import EvolutionEngine, EvolutionSource
from core.evolution.a8_evolution import A8TheoryPracticeEvolution
from core.evolution.dream_evolution import DreamOneirologyEvolution
from core.evolution.github_evolution import GithubBestPracticeEvolution
from core.agent_a_memory import (
    load_memory, save_memory, get_evolution_params,
    update_evolution_params, record_evolution_result,
    set_evolution_timestamp,
)

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "evolution.log"


def _setup_logger() -> logging.Logger:
    """配置进化系统日志，同时输出到文件和控制台"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("evolution_scheduler")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.propagate = False
    return logger


logger = _setup_logger()

A8_CHECK_INTERVAL_HOURS = 24
DREAM_CHECK_INTERVAL_HOURS = 12
GITHUB_CHECK_INTERVAL_HOURS = 48


class EvolutionScheduler:
    """进化调度器 - 管理三层进化系统的执行节奏"""

    def __init__(self):
        self.engine = EvolutionEngine()
        self.a8 = A8TheoryPracticeEvolution(self.engine)
        self.dream = DreamOneirologyEvolution(self.engine)
        self.github = GithubBestPracticeEvolution(self.engine)

    def run_daily_inspection(self, force: bool = False) -> Dict:
        """
        每日进化检查入口 — 基于 Agent A 记忆模块触发 A8 进化流程

        这是外部调用的主入口，执行完整的三层反思进化周期。

        Args:
            force: 是否强制执行（忽略时间间隔）

        Returns:
            检查结果汇总
        """
        logger.info("=" * 60)
        logger.info("[Agent A 进化复盘] 每日进化系统启动")
        logger.info("=" * 60)

        results = self.run_all_evolution_checks(force=force)

        _export_to_shared_knowledge(self)

        logger.info("=" * 60)
        logger.info("[Agent A 进化复盘] 每日进化系统完成")
        logger.info("=" * 60)

        status = self.get_evolution_status()
        logger.info(f"进化状态:")
        logger.info(f"  已采纳参数: {status['adopted_params']}")
        logger.info(f"  进化次数: {status['evolution_count']}")
        logger.info(f"  成功/失败: {status['successful_evolutions']}/{status['failed_evolutions']}")
        logger.info(f"  待处理提议: {status['pending_proposals']}")
        logger.info(f"  已采纳提议: {status['adopted_proposals']}")

        return results

    def run_all_evolution_checks(self, force: bool = False) -> Dict:
        """
        执行所有进化检查（根据时间间隔决定是否执行）

        Args:
            force: 是否强制执行（忽略时间间隔）

        Returns:
            检查结果汇总
        """
        memory = load_memory()
        results = {
            "a8": {"ran": False, "proposals": 0},
            "dream": {"ran": False, "proposals": 0},
            "github": {"ran": False, "proposals": 0},
            "backtest": {"ran": False, "adopted": 0},
        }

        # 1. A8 理论与实践验证
        if force or self._should_run(memory, "a8_last_inspection", A8_CHECK_INTERVAL_HOURS):
            logger.info("[进化调度器] 执行A8理论与实践验证...")
            try:
                recent_decisions = self._get_recent_decisions(memory)
                report = self.a8.run_daily_inspection(memory, recent_decisions)
                proposals = report.get("evolution_proposals", [])
                results["a8"] = {
                    "ran": True,
                    "proposals": len(proposals),
                    "contradictions": len(report.get("contradictions", [])),
                }
                memory = set_evolution_timestamp(memory, "a8_last_inspection")
                save_memory(memory)
            except Exception as e:
                logger.error(f"[进化调度器] A8检查失败: {e}")
                results["a8"]["error"] = str(e)

        # 2. 做梦部外部反思
        if force or self._should_run(memory, "dream_last_analysis", DREAM_CHECK_INTERVAL_HOURS):
            logger.info("[进化调度器] 执行做梦部潜意识分析...")
            try:
                recent_decisions = self._get_recent_decisions(memory)
                report = self.dream.run_dream_analysis(memory, recent_decisions)
                proposals = report.get("evolution_proposals", [])
                results["dream"] = {
                    "ran": True,
                    "proposals": len(proposals),
                    "latent_findings": len(report.get("latent_content", {})),
                }
                memory = set_evolution_timestamp(memory, "dream_last_analysis")
                save_memory(memory)
            except Exception as e:
                logger.error(f"[进化调度器] 做梦部分析失败: {e}")
                results["dream"]["error"] = str(e)

        # 3. GitHub 成熟经验搜索
        if force or self._should_run(memory, "github_last_search", GITHUB_CHECK_INTERVAL_HOURS):
            logger.info("[进化调度器] 执行GitHub成熟经验搜索...")
            try:
                report = self.github.search_and_learn(memory)
                proposals = report.get("evolution_proposals", [])
                results["github"] = {
                    "ran": True,
                    "proposals": len(proposals),
                    "repos_found": len(report.get("repositories_found", [])),
                }
                memory = set_evolution_timestamp(memory, "github_last_search")
                save_memory(memory)
            except Exception as e:
                logger.error(f"[进化调度器] GitHub搜索失败: {e}")
                results["github"]["error"] = str(e)

        # 4. 运行待回测的提议
        pending = self.engine.get_pending_proposals()
        if pending:
            logger.info(f"[进化调度器] 运行{len(pending)}个提议的回测验证...")
            try:
                bt_results = self.github.run_backtest_on_pending()
                adopted = sum(
                    1 for r in bt_results
                    if r.get("overall_improvement", False) is True
                )
                results["backtest"] = {
                    "ran": True,
                    "total": len(bt_results),
                    "adopted": adopted,
                }
                if adopted > 0:
                    memory = load_memory()
                    adopted_params = self.engine.get_adopted_params()
                    if adopted_params:
                        memory = update_evolution_params(memory, adopted_params)
                        memory = record_evolution_result(memory, True)
                        save_memory(memory)
            except Exception as e:
                logger.error(f"[进化调度器] 回测失败: {e}")
                results["backtest"]["error"] = str(e)

        # 5. 评估观察期的提议
        try:
            obs_count = self.engine.evaluate_observation_period()
            if obs_count > 0:
                logger.info(f"[进化调度器] {obs_count}个提议通过观察期评估")
                memory = load_memory()
                adopted_params = self.engine.get_adopted_params()
                memory = update_evolution_params(memory, adopted_params)
                save_memory(memory)
        except Exception as e:
            logger.error(f"[进化调度器] 观察期评估失败: {e}")

        return results

    def get_evolution_status(self) -> Dict:
        """获取进化系统状态"""
        memory = load_memory()
        evo = memory.get("evolution", {})

        return {
            "adopted_params": evo.get("adopted_params", {}),
            "evolution_count": evo.get("evolution_count", 0),
            "successful_evolutions": evo.get("successful_evolutions", 0),
            "failed_evolutions": evo.get("failed_evolutions", 0),
            "a8_last_inspection": evo.get("a8_last_inspection"),
            "dream_last_analysis": evo.get("dream_last_analysis"),
            "github_last_search": evo.get("github_last_search"),
            "pending_proposals": len(self.engine.get_pending_proposals()),
            "adopted_proposals": len(self.engine._load_pool().get("adopted", [])),
        }

    def _should_run(self, memory: Dict, timestamp_key: str, interval_hours: int) -> bool:
        """判断是否应该运行某项检查"""
        evo = memory.get("evolution", {})
        last = evo.get(timestamp_key)
        if not last:
            return True
        try:
            last_time = datetime.fromisoformat(last.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (now - last_time) >= timedelta(hours=interval_hours)
        except Exception:
            return True

    def _get_recent_decisions(self, memory: Dict, limit: int = 10) -> List[Dict]:
        """获取近期决策记录（从最近交易中推断）"""
        decisions = []
        recent_trades = memory.get("recent_trades", [])

        for trade in recent_trades[-limit:]:
            decisions.append({
                "cycle_id": trade.get("timestamp", ""),
                "action": trade.get("action", "HOLD"),
                "decision_rationale": trade.get("lesson", ""),
                "confidence": trade.get("confidence", 0),
                "per_coin_scores": {},
            })

        if len(decisions) < limit:
            hold_streak = memory.get("hold_streak", 0)
            for i in range(min(hold_streak, limit - len(decisions))):
                decisions.append({
                    "cycle_id": f"hold_{i}",
                    "action": "HOLD",
                    "decision_rationale": "观望等待机会",
                    "confidence": 0.3,
                    "per_coin_scores": {},
                })

        return decisions


def _export_to_shared_knowledge(scheduler: EvolutionScheduler):
    """
    将进化结果导出到共享知识目录，供易经推理系统使用
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        import importlib.util
        yijing_dir = Path(__file__).parent.parent.parent / "11-易经推理系统"
        bridge_path = yijing_dir / "scripts" / "memory_l4" / "knowledge_bridge.py"
        spec = importlib.util.spec_from_file_location("knowledge_bridge", str(bridge_path))
        knowledge_bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(knowledge_bridge)
        bridge = knowledge_bridge.KnowledgeBridge()
        
        status = scheduler.get_evolution_status()
        adopted_params = status.get("adopted_params", {})
        
        if adopted_params:
            result = bridge.export_ab_evolved_params(
                adopted_params=adopted_params,
                source="ab_trading_evolution",
                description="AB Trading三层反思进化系统已采纳的参数",
            )
            if result["ok"]:
                print(f"[进化调度器] ✅ 已导出 {result['params_count']} 个进化参数到共享目录")
            else:
                print(f"[进化调度器] ❌ 参数导出失败: {result.get('error')}")
        
        memory = load_memory()
        contradictions = memory.get("contradictions", [])
        if contradictions:
            result = bridge.export_ab_contradictions(
                contradictions=contradictions,
                source="a8_theory_practice",
            )
            if result["ok"]:
                print(f"[进化调度器] ✅ 已导出 {result['patterns_count']} 个矛盾模式")
        
        regime = {
            "state": memory.get("market_state", "neutral"),
            "trend_strength": memory.get("trend_strength", 0.5),
            "volatility": memory.get("volatility", 0.5),
        }
        bridge.export_market_regime(regime)
        print(f"[进化调度器] ✅ 已导出市场状态: {regime['state']}")

    except Exception as e:
        print(f"[进化调度器] 共享知识导出失败: {e}")


def run_evolution_cycle():
    """运行一个进化周期"""
    print("=" * 60)
    print("[进化调度器] 三层反思进化周期启动")
    print("=" * 60)

    scheduler = EvolutionScheduler()
    results = scheduler.run_all_evolution_checks()

    _export_to_shared_knowledge(scheduler)

    print("\n" + "=" * 60)
    print("[进化调度器] 进化周期完成")
    print("=" * 60)

    status = scheduler.get_evolution_status()
    print(f"\n进化状态:")
    print(f"  已采纳参数: {status['adopted_params']}")
    print(f"  进化次数: {status['evolution_count']}")
    print(f"  成功/失败: {status['successful_evolutions']}/{status['failed_evolutions']}")
    print(f"  待处理提议: {status['pending_proposals']}")
    print(f"  已采纳提议: {status['adopted_proposals']}")

    return results


if __name__ == "__main__":
    run_evolution_cycle()
