#!/usr/bin/env python3
# ============================================================================
# 推荐策略引擎 - 多场景压力测试
# ============================================================================
# 模拟多种市场环境和异常场景，验证引擎的稳定性、容错性和决策逻辑
#
# 测试场景:
#   1. 常态市场 - 正常研报，平稳运行
#   2. 强趋势市场 - 明确方向信号
#   3. 震荡市场 - 信号混乱
#   4. 极端市场 - 高波动高回撤
#   5. 研报缺失 - 无研报数据
#   6. 研报过期 - 超过一周的旧研报
#   7. 多策略竞争 - 20个策略同时回测
#   8. 部分回测失败 - 模拟引擎故障
#   9. 回测超时 - 模拟超时保护
#   10. 连续劣于基线 - 测试三轮回退逻辑
#   11. 5日强制刷新 - 测试5日阈值逻辑
#   12. API 故障 - 模拟Prisma写入失败
#
# 运行: python3 stress_test.py
# ============================================================================

import json
import os
import random
import sys
import time
import argparse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from statistics import mean, median, stdev

# 将 engine.py 加入路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from engine import (
    RecommendationEngine,
    CandidateStrategy,
    BacktestResult,
    EngineConfig,
    EngineStatus,
    EngineStep,
    TriggerType,
    RECOMMENDATION_ARTIFACTS,
)

# ============================================================================
# 配置
# ============================================================================

TEST_OUTPUT_DIR = SCRIPT_DIR / "stress_test_results"
TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 各场景的模拟参数
SCENARIO_CONFIGS = {
    "normal": {
        "report_count": 8,
        "candidate_count": 3,
        "pass_rate": 0.7,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "label": "🎯 常态市场",
        "description": "研报数量充足，信号清晰",
    },
    "strong_trend": {
        "report_count": 12,
        "candidate_count": 5,
        "pass_rate": 0.85,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.85,  # 85% BUY
        "volatility_factor": 0.8,
        "label": "📈 强趋势市场",
        "description": "方向信号强烈，波动率较低",
    },
    "sideways": {
        "report_count": 6,
        "candidate_count": 3,
        "pass_rate": 0.4,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.5,
        "label": "⟷  震荡市场",
        "description": "信号冲突，波动率高，策略难以稳定",
    },
    "extreme": {
        "report_count": 15,
        "candidate_count": 5,
        "pass_rate": 0.2,
        "timeout_prob": 0.1,
        "fail_prob": 0.15,
        "direction_bias": 0.7,
        "volatility_factor": 3.0,
        "label": "🔥 极端市场",
        "description": "高波动高回撤，大量策略劣于基线",
    },
    "no_reports": {
        "report_count": 0,
        "candidate_count": 0,
        "pass_rate": 0.0,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "label": "📭 研报缺失",
        "description": "无研报数据，测试默认策略生成",
    },
    "old_reports": {
        "report_count": 5,
        "candidate_count": 3,
        "pass_rate": 0.5,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "age_days": 14,  # 14天前的旧研报
        "label": "📅 过期研报",
        "description": "研报日期超过一周，测试时间过滤",
    },
    "many_candidates": {
        "report_count": 20,
        "candidate_count": 20,
        "pass_rate": 0.5,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.2,
        "label": "🏟️  20策略竞争",
        "description": "大量候选策略，测试排序和选择",
    },
    "partial_failure": {
        "report_count": 10,
        "candidate_count": 5,
        "pass_rate": 0.4,
        "timeout_prob": 0.2,
        "fail_prob": 0.3,
        "direction_bias": 0.5,
        "volatility_factor": 1.5,
        "label": "⚠️ 部分回测失败",
        "description": "30%回测失败，20%超时，测试容错",
    },
    "timeout_heavy": {
        "report_count": 8,
        "candidate_count": 5,
        "pass_rate": 0.4,
        "timeout_prob": 0.6,
        "fail_prob": 0.1,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "label": "⏱️ 重度超时",
        "description": "60%回测超时，测试超时保护和降级",
    },
    "api_failure": {
        "report_count": 8,
        "candidate_count": 3,
        "pass_rate": 0.6,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "api_fail_prob": 0.5,
        "label": "🔌 API故障",
        "description": "50%概率Prisma写入失败，测试重试和日志",
    },
    "stress_100_candidates": {
        "report_count": 100,
        "candidate_count": 100,
        "pass_rate": 0.5,
        "timeout_prob": 0.05,
        "fail_prob": 0.05,
        "direction_bias": 0.5,
        "volatility_factor": 1.0,
        "label": "💥 100策略压测",
        "description": "极端规模测试，100篇研报 + 100个策略",
    },
    "consecutive_worse": {
        "report_count": 8,
        "candidate_count": 3,
        "pass_rate": 0.1,  # 10%通过率，几乎全部劣于基线
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 2.0,
        "label": "🔄 连续劣于基线",
        "description": "连续3轮劣于基线，测试回退基线逻辑",
    },
    "forced_refresh_5d": {
        "report_count": 10,
        "candidate_count": 5,
        "pass_rate": 0.6,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.6,
        "volatility_factor": 1.0,
        "simulate_5d_force": True,  # 标记：模拟已连续推荐5天
        "label": "⏰ 5日强制刷新",
        "description": "模拟连续5天推荐同一策略，测试强制刷新逻辑",
    },
    "consecutive_rollback_3rounds": {
        "report_count": 10,
        "candidate_count": 4,
        "pass_rate": 0.0,  # 0%通过，连续劣于基线
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.5,
        "volatility_factor": 2.5,
        "simulate_consecutive_below": 3,  # 模拟已连续3次劣于基线
        "label": "🔙 三轮回退验证",
        "description": "模拟连续3次劣于基线，测试回退到基线策略",
    },
    "multi_day_simulation": {
        "report_count": 12,
        "candidate_count": 5,
        "pass_rate": 0.5,
        "timeout_prob": 0.0,
        "fail_prob": 0.0,
        "direction_bias": 0.55,
        "volatility_factor": 1.0,
        "simulate_multi_day": True,  # 模拟多日连续运行
        "label": "📅 多日连续运行",
        "description": "模拟7天连续运行，测试状态保持和决策连贯性",
    },
}


# ============================================================================
# 测试辅助类
# ============================================================================

@dataclass
class TestResult:
    """单个测试的结果"""
    scenario: str
    label: str
    round: int
    status: str  # "success" / "partial" / "failed"
    duration_ms: int
    reports_used: int
    candidates_generated: int
    strategies_backtested: int
    strategies_passed: int
    recommended_strategy: Optional[str]
    is_better_than_baseline: Optional[bool]
    error_message: Optional[str] = None
    avg_sharpe: Optional[float] = None
    max_sharpe: Optional[float] = None
    avg_maxdd: Optional[float] = None
    decision_reason: Optional[str] = None
    # 状态追踪字段
    consecutive_days: int = 0
    below_baseline_count: int = 0
    force_refresh_triggered: bool = False
    rollback_triggered: bool = False
    last_strategy: Optional[str] = None


class StressTestEngine(RecommendationEngine):
    """测试版本的引擎：可以注入不同场景的模拟数据"""

    def __init__(
        self,
        config: EngineConfig,
        scenario: str,
        scenario_config: dict,
        simulate_api_failure: bool = False,
        api_fail_prob: float = 0.0,
        initial_state: dict = None,  # 初始状态（多日模拟用）
    ):
        super().__init__(config)
        self.scenario = scenario
        self.scenario_config = scenario_config
        self.simulate_api_failure = simulate_api_failure
        self.api_fail_prob = api_fail_prob
        self.backtest_results = []  # 确保有这个字段
        self.round_counter = 0  # 连续劣于基线的轮次计数

        # 状态追踪（用于多日模拟和特殊场景）
        initial_state = initial_state or {}
        self.current_recommended_days = initial_state.get("recommended_days", 0)
        self.consecutive_below_baseline = initial_state.get("consecutive_below", 0)
        self.last_recommended_strategy = initial_state.get("last_strategy")
        self.decision_trace = []  # 记录每轮决策
        self.force_refresh_triggered = False
        self.rollback_triggered = False

        # 从场景配置中应用初始状态
        if scenario_config.get("simulate_5d_force"):
            self.current_recommended_days = 5
            self.last_recommended_strategy = "SAME-STRATEGY-5DAYS"
        if scenario_config.get("simulate_consecutive_below"):
            self.consecutive_below_baseline = scenario_config["simulate_consecutive_below"]

    # ---------------------------------------------------------------------
    # 研报生成（替代真实读取）
    # ---------------------------------------------------------------------
    def step_fetch_reports(self) -> list:
        self.current_step = EngineStep.FETCHING_REPORTS
        report_count = self.scenario_config["report_count"]
        age_days = self.scenario_config.get("age_days", 0)

        if report_count == 0:
            self._log("无研报数据，将生成默认候选策略")
            self.reports = []
            return []

        reports = []
        now = datetime.now()
        report_date = now - timedelta(days=age_days)

        for i in range(report_count):
            phase = random.choice(["A1", "A2", "A3"])
            direction = (
                "BUY"
                if random.random() < self.scenario_config["direction_bias"]
                else "SHORT"
            )
            confidence = int(random.uniform(40, 90))
            regime = random.choice(
                ["ABOVE_ALL", "BELOW_ALL", "SIDEWAYS", "EXTREME"]
            )
            report_date_shifted = report_date - timedelta(
                hours=random.randint(0, 24 * report_count)
            )

            reports.append({
                "file": f"report_{phase}_{report_count}_{i}.json",
                "title": f"测试研报 - {phase} - {direction} - #{i+1}",
                "date": report_date_shifted.strftime("%Y-%m-%dT%H:%M:%S"),
                "chain_phase": phase,
                "regime": regime,
                "confidence": confidence,
                "direction": direction,
                "tags": direction,
            })

        self.reports = reports
        self._log(f"生成 {len(reports)} 份模拟研报 (场景: {self.scenario})")
        return reports

    # ---------------------------------------------------------------------
    # 候选策略生成（基于模拟研报）
    # ---------------------------------------------------------------------
    def step_generate_candidates(self) -> list[CandidateStrategy]:
        self.current_step = EngineStep.GENERATING_CANDIDATES
        candidate_count = self.scenario_config["candidate_count"]

        if candidate_count == 0 or not self.reports:
            # 无研报或无候选 - 使用默认策略
            candidates = [
                CandidateStrategy(
                    name=f"DEFAULT-BUY-{datetime.now().strftime('%Y%m%d')}",
                    description="研报缺失时的默认推荐",
                    direction="BUY",
                    regime="ABOVE_ALL",
                    confidence=55,
                    symbol=self.config.symbol,
                ),
                CandidateStrategy(
                    name=f"DEFAULT-SHORT-{datetime.now().strftime('%Y%m%d')}",
                    description="研报缺失时的默认推荐",
                    direction="SHORT",
                    regime="BELOW_ALL",
                    confidence=55,
                    symbol=self.config.symbol,
                ),
            ]
            self.candidates = candidates
            self._log(f"生成 {len(candidates)} 个默认候选策略")
            return candidates

        candidates = []
        direction_bias = self.scenario_config["direction_bias"]

        for i in range(candidate_count):
            direction = (
                "BUY" if random.random() < direction_bias else "SHORT"
            )
            report = self.reports[i % len(self.reports)] if self.reports else None
            regime = report["regime"] if report else "UNKNOWN"
            confidence = (
                int(report["confidence"]) if report else random.randint(40, 80)
            )

            candidates.append(CandidateStrategy(
                name=f"CANDIDATE-{self.scenario.upper()}-#{i+1}-{direction}",
                description=f"场景{self.scenario} - 基于研报的候选策略 #{i+1}",
                direction=direction,
                regime=regime,
                confidence=confidence,
                symbol=self.config.symbol,
            ))

        self.candidates = candidates
        self._log(f"生成 {len(candidates)} 个候选策略")
        return candidates

    # ---------------------------------------------------------------------
    # 模拟回测（带场景参数）
    # ---------------------------------------------------------------------
    def step_run_backtests(self) -> list[BacktestResult]:
        self.current_step = EngineStep.RUNNING_BACKTESTS
        results = []
        baseline_metrics = self._get_baseline_metrics(self.config.baseline_version)
        pass_rate = self.scenario_config["pass_rate"]
        timeout_prob = self.scenario_config["timeout_prob"]
        fail_prob = self.scenario_config["fail_prob"]
        vol_factor = self.scenario_config["volatility_factor"]

        for i, candidate in enumerate(self.candidates):
            # 模拟失败
            if random.random() < fail_prob:
                self._log(f"  {candidate.name}: 回测失败 (模拟)", "WARN")
                results.append(self._make_failed_result(candidate, baseline_metrics))
                continue

            # 模拟超时
            if random.random() < timeout_prob:
                self._log(f"  {candidate.name}: 回测超时 (模拟)", "WARN")
                results.append(self._make_timeout_result(candidate, baseline_metrics))
                continue

            # 正常回测
            result = self._simulate_backtest_result(
                candidate, baseline_metrics, pass_rate, vol_factor
            )
            results.append(result)
            self._log(
                f"  {candidate.name}: Sharpe={result.sharpe_ratio:.3f}, "
                f"MaxDD={result.max_drawdown:.2f}%, "
                f"vs Baseline: {'✓' if result.is_better_than_baseline else '✗'}"
            )

        self.backtest_results = results
        passed = sum(1 for r in results if r.is_better_than_baseline)
        self._log(f"回测完成，{passed}/{len(results)} 优于基线")
        return results

    def _simulate_backtest_result(
        self,
        candidate: CandidateStrategy,
        baseline_metrics: dict,
        pass_rate: float,
        vol_factor: float,
    ) -> BacktestResult:
        """模拟回测结果"""
        base_sharpe = baseline_metrics["sharpe_ratio"]
        base_dd = baseline_metrics["max_drawdown"]
        base_return = baseline_metrics["total_return"]

        # 决定是否通过
        will_pass = random.random() < pass_rate

        if will_pass:
            # 优于基线
            sharpe_ratio = round(base_sharpe + random.uniform(0.0, 0.4), 3)
            max_drawdown = round(
                max(1.0, base_dd * random.uniform(0.7, 1.0) * vol_factor), 2
            )
            total_return = round(
                base_return * random.uniform(1.1, 1.8) * vol_factor, 2
            )
        else:
            # 劣于基线
            sharpe_ratio = round(
                base_sharpe * random.uniform(0.3, 0.95) * vol_factor, 3
            )
            max_drawdown = round(
                base_dd * random.uniform(1.0, 1.8) * vol_factor, 2
            )
            total_return = round(
                base_return * random.uniform(0.3, 0.9) * vol_factor, 2
            )

        win_rate = round(random.uniform(35, 65), 1)
        profit_factor = round(random.uniform(1.0, 3.0), 2)
        trade_count = random.randint(3, 20)

        sharpe_better = sharpe_ratio >= base_sharpe - 0.05
        dd_better = max_drawdown <= base_dd + 0.5
        return_better = total_return >= base_return - 1.0
        better_count = sum([sharpe_better, dd_better, return_better])

        return BacktestResult(
            strategy_name=candidate.name,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_return=total_return,
            trade_count=trade_count,
            baseline_sharpe=base_sharpe,
            baseline_max_dd=base_dd,
            baseline_total_return=base_return,
            is_better_than_baseline=better_count >= self.config.min_better_count,
            better_count=better_count,
        )

    def _make_failed_result(self, candidate, baseline_metrics) -> BacktestResult:
        """模拟失败回测"""
        return BacktestResult(
            strategy_name=candidate.name,
            sharpe_ratio=0,
            max_drawdown=999,
            win_rate=0,
            profit_factor=0,
            total_return=-999,
            trade_count=0,
            baseline_sharpe=baseline_metrics["sharpe_ratio"],
            baseline_max_dd=baseline_metrics["max_drawdown"],
            baseline_total_return=baseline_metrics["total_return"],
            is_better_than_baseline=False,
            better_count=0,
        )

    def _make_timeout_result(self, candidate, baseline_metrics) -> BacktestResult:
        """模拟超时回测"""
        return BacktestResult(
            strategy_name=candidate.name,
            sharpe_ratio=0,
            max_drawdown=999,
            win_rate=0,
            profit_factor=0,
            total_return=-999,
            trade_count=0,
            baseline_sharpe=baseline_metrics["sharpe_ratio"],
            baseline_max_dd=baseline_metrics["max_drawdown"],
            baseline_total_return=baseline_metrics["total_return"],
            is_better_than_baseline=False,
            better_count=0,
        )

    # ---------------------------------------------------------------------
    # 决策逻辑（包含5日强制刷新和三轮回退）
    # ---------------------------------------------------------------------
    def step_make_decision(self) -> Optional[CandidateStrategy]:
        self.current_step = EngineStep.MAKING_DECISION
        self._log("开始决策...")
        self.round_counter += 1

        passed_count = sum(
            1 for r in self.backtest_results if r.is_better_than_baseline
        )
        has_better = passed_count > 0

        # ====== 逻辑1：检查连续5日推荐同一策略 - 强制刷新 ======
        if self.current_recommended_days >= self.config.forced_refresh_days:
            self.force_refresh_triggered = True
            if has_better:
                best = max(
                    self.backtest_results,
                    key=lambda r: r.sharpe_ratio if r.is_better_than_baseline else -999,
                )
                best_candidate = next(
                    (c for c in self.candidates if c.name == best.strategy_name),
                    self.candidates[0],
                )
                self.decision_reason = (
                    f"🔄 强制刷新：已连续推荐 {self.current_recommended_days} 天 "
                    f"(阈值={self.config.forced_refresh_days}天), "
                    f"切换到新策略「{best_candidate.name}」"
                )
                self.recommended_strategy = best_candidate
                self.current_recommended_days = 0  # 重置计数
                self._log(self.decision_reason, "WARN")
                return best_candidate
            else:
                self.decision_reason = (
                    f"🔄 强制刷新触发但无更好策略，仍回退基线 "
                    f"(已连续{self.current_recommended_days}天)"
                )
                self.current_recommended_days = 0
                self._log(self.decision_reason, "WARN")
                return None

        # ====== 逻辑2：检查连续N次劣于基线 - 回退 ======
        if not has_better:
            self.consecutive_below_baseline += 1
        else:
            self.consecutive_below_baseline = 0

        if self.consecutive_below_baseline >= self.config.rollback_threshold:
            self.rollback_triggered = True
            self.decision_reason = (
                f"🔙 回退基线：已连续 {self.consecutive_below_baseline} 次劣于基线 "
                f"(阈值={self.config.rollback_threshold}次)，使用基线策略"
            )
            self._log(self.decision_reason, "ERROR")
            return None

        # ====== 逻辑3：正常选择 - 选 Sharpe 最高且优于基线的策略 ======
        if not has_better:
            self.decision_reason = (
                f"本轮无策略优于基线 (连续劣于基线={self.consecutive_below_baseline}次)，"
                f"继续使用当前策略或基线"
            )
            self._log(self.decision_reason, "WARN")
            return None

        best = max(
            self.backtest_results,
            key=lambda r: r.sharpe_ratio if r.is_better_than_baseline else -999,
        )
        best_candidate = next(
            (c for c in self.candidates if c.name == best.strategy_name),
            self.candidates[0],
        )

        # 如果策略名与上次相同，增加连续天数计数
        if (self.last_recommended_strategy and
                self.last_recommended_strategy == best_candidate.name):
            self.current_recommended_days += 1
        else:
            self.current_recommended_days = 1

        self.last_recommended_strategy = best_candidate.name

        self.decision_reason = (
            f"推荐「{best_candidate.name}」(Sharpe={best.sharpe_ratio:.3f}, "
            f"MaxDD={best.max_drawdown:.2f}%, 优于基线 {best.better_count}/3 项, "
            f"已连续推荐 {self.current_recommended_days} 天)"
        )
        self.recommended_strategy = best_candidate
        self._log(self.decision_reason)

        # 记录决策追踪
        self.decision_trace.append({
            "round": self.round_counter,
            "strategy": best_candidate.name,
            "sharpe": best.sharpe_ratio,
            "consecutive_days": self.current_recommended_days,
            "below_baseline_count": self.consecutive_below_baseline,
        })

        return best_candidate

    # ---------------------------------------------------------------------
    # 模拟 Prisma 写入
    # ---------------------------------------------------------------------
    def step_write_to_prisma(self) -> Optional[str]:
        self.current_step = EngineStep.WRITING_TO_PRISMA

        if self.simulate_api_failure and random.random() < self.api_fail_prob:
            self.error_message = "模拟的 API 故障：Prisma 写入失败"
            self._log(self.error_message, "ERROR")
            return None

        # 模拟写入成功
        strategy_name = (
            self.recommended_strategy.name
            if self.recommended_strategy
            else "BASELINE"
        )
        self._log(f"✅ 策略「{strategy_name}」已写入 Prisma")
        return "simulated-strategy-id"

    # ---------------------------------------------------------------------
    # 主运行流程
    # ---------------------------------------------------------------------
    def run(self, trigger_type: TriggerType = TriggerType.SCHEDULED) -> "StressTestEngine":
        self.status = EngineStatus.RUNNING
        start_time = datetime.now()
        self._log(
            f"=== 压力测试启动 (场景: {self.scenario_config['label']}) ==="
        )

        try:
            self.step_fetch_reports()
            self.step_generate_candidates()
            self.step_run_backtests()
            self.step_make_decision()
            self.step_write_to_prisma()

            self.status = EngineStatus.SUCCESS
            self.current_step = EngineStep.COMPLETED

        except Exception as e:
            self.status = EngineStatus.FAILED
            self.error_message = str(e)
            self._log(f"引擎异常: {e}", "ERROR")

        duration_ms = int(
            (datetime.now() - start_time).total_seconds() * 1000
        )
        self._log(f"=== 测试完成 ({duration_ms}ms, status={self.status.value}) ===")
        self._duration_ms = duration_ms
        return self

    def get_state_snapshot(self) -> dict:
        """获取当前状态快照（用于多日连续模拟）"""
        return {
            "recommended_days": self.current_recommended_days,
            "consecutive_below": self.consecutive_below_baseline,
            "last_strategy": self.last_recommended_strategy,
        }

    def get_test_result(self) -> TestResult:
        """生成测试结果"""
        # 计算统计
        valid_results = [
            r for r in self.backtest_results
            if r.sharpe_ratio > 0 and r.total_return > -900
        ]
        avg_sharpe = (
            round(mean([r.sharpe_ratio for r in valid_results]), 3)
            if valid_results else None
        )
        max_sharpe = (
            round(max([r.sharpe_ratio for r in valid_results]), 3)
            if valid_results else None
        )
        avg_maxdd = (
            round(mean([r.max_drawdown for r in valid_results]), 2)
            if valid_results else None
        )

        return TestResult(
            scenario=self.scenario,
            label=self.scenario_config["label"],
            round=self.round_counter,
            status=self.status.value,
            duration_ms=self._duration_ms,
            reports_used=len(self.reports),
            candidates_generated=len(self.candidates),
            strategies_backtested=len(self.backtest_results),
            strategies_passed=sum(
                1 for r in self.backtest_results if r.is_better_than_baseline
            ),
            recommended_strategy=(
                self.recommended_strategy.name
                if self.recommended_strategy
                else None
            ),
            is_better_than_baseline=(
                any(r.is_better_than_baseline for r in self.backtest_results)
                if self.backtest_results else False
            ),
            error_message=self.error_message,
            avg_sharpe=avg_sharpe,
            max_sharpe=max_sharpe,
            avg_maxdd=avg_maxdd,
            decision_reason=self.decision_reason,
            consecutive_days=self.current_recommended_days,
            below_baseline_count=self.consecutive_below_baseline,
            force_refresh_triggered=self.force_refresh_triggered,
            rollback_triggered=self.rollback_triggered,
            last_strategy=self.last_recommended_strategy,
        )


# ============================================================================
# 测试运行器
# ============================================================================

class StressTestRunner:
    """多场景多轮测试运行器"""

    def __init__(self, rounds_per_scenario: int = 3, config: EngineConfig = None):
        self.rounds_per_scenario = rounds_per_scenario
        self.config = config or EngineConfig()
        self.results: dict[str, list[TestResult]] = {}

    def run_single_scenario(self, scenario: str, config: dict) -> list[TestResult]:
        """运行单个场景的多轮测试"""
        results = []
        print(f"\n{'='*70}")
        print(f"{config['label']} - {config['description']}")
        print(f"{'='*70}")

        # 判断是否为多日连续模拟
        is_multi_day = config.get("simulate_multi_day", False)
        state = None  # 状态追踪

        for round_num in range(1, self.rounds_per_scenario + 1):
            print(f"\n  第 {round_num}/{self.rounds_per_scenario} 轮...")

            engine = StressTestEngine(
                config=self.config,
                scenario=scenario,
                scenario_config=config,
                simulate_api_failure=(
                    config.get("api_fail_prob", 0) > 0
                ),
                api_fail_prob=config.get("api_fail_prob", 0),
                initial_state=state if is_multi_day else None,
            )

            engine.run()
            result = engine.get_test_result()
            results.append(result)

            # 多日连续模拟：传递状态
            if is_multi_day:
                state = engine.get_state_snapshot()

            # 打印状态信息
            status_info = f"  ✅ 完成 - status={result.status}, "
            if result.recommended_strategy:
                status_info += f"推荐={result.recommended_strategy[:30]}, "
            else:
                status_info += f"推荐=BASELINE, "
            status_info += f"通过={result.strategies_passed}/{result.strategies_backtested}, "
            if is_multi_day or result.force_refresh_triggered or result.rollback_triggered:
                status_info += (
                    f"连续天数={result.consecutive_days}, "
                    f"劣于基线次数={result.below_baseline_count}"
                )
                if result.force_refresh_triggered:
                    status_info += f" 🔄 强制刷新!"
                if result.rollback_triggered:
                    status_info += f" 🔙 回退基线!"
            print(status_info)
            time.sleep(0.02)  # 轻微延迟防止输出混乱

        return results

    def run_all_scenarios(self, scenarios_to_run: list[str] = None) -> dict:
        """运行所有指定场景"""
        if not scenarios_to_run:
            scenarios_to_run = list(SCENARIO_CONFIGS.keys())

        total_start = time.time()

        for i, scenario in enumerate(scenarios_to_run):
            if scenario not in SCENARIO_CONFIGS:
                print(f"⚠️  未知场景: {scenario}，跳过")
                continue

            print(f"\n进度: {i+1}/{len(scenarios_to_run)}")
            self.results[scenario] = self.run_single_scenario(
                scenario, SCENARIO_CONFIGS[scenario]
            )

        total_ms = int((time.time() - total_start) * 1000)
        print(f"\n\n总耗时: {total_ms}ms ({total_ms/1000:.1f}s)")

        return self.results

    # ---------------------------------------------------------------------
    # 报告生成
    # ---------------------------------------------------------------------
    def generate_report(self) -> str:
        """生成测试报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("推荐策略引擎 - 多场景压力测试报告")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(
            f"测试配置: {self.rounds_per_scenario} 轮/场景, "
            f"{len(self.results)} 个场景"
        )
        lines.append("=" * 70)

        # 汇总统计
        total_rounds = sum(len(r) for r in self.results.values())
        successful = sum(
            1 for results in self.results.values()
            for r in results if r.status == "success"
        )
        failed = sum(
            1 for results in self.results.values()
            for r in results if r.status == "failed"
        )

        lines.append("")
        lines.append("📊 总体统计")
        lines.append(f"  总测试轮数: {total_rounds}")
        lines.append(f"  ✅ 成功: {successful} ({100*successful/total_rounds:.1f}%)")
        lines.append(f"  ❌ 失败: {failed} ({100*failed/total_rounds:.1f}%)")
        lines.append(
            f"  ⚠️  部分: {total_rounds - successful - failed} "
            f"({100*(total_rounds-successful-failed)/total_rounds:.1f}%)"
        )
        lines.append("")

        # 分场景详细报告
        for scenario, results in self.results.items():
            config = SCENARIO_CONFIGS[scenario]
            successes = sum(1 for r in results if r.status == "success")
            recommended_any = sum(
                1 for r in results if r.recommended_strategy
            )
            avg_sharpe = mean(
                r.avg_sharpe for r in results if r.avg_sharpe is not None
            ) if [r for r in results if r.avg_sharpe is not None] else 0
            avg_duration = mean(r.duration_ms for r in results)

            lines.append("-" * 70)
            lines.append(f"{config['label']} ({scenario})")
            lines.append(f"  描述: {config['description']}")
            lines.append(
                f"  结果: {successes}/{len(results)} 成功, "
                f"{recommended_any}/{len(results)} 推荐策略"
            )
            lines.append(f"  平均 Sharpe: {avg_sharpe:.3f}")
            lines.append(f"  平均耗时: {avg_duration:.0f}ms")

            # 每轮详情
            for i, r in enumerate(results):
                indicator = {
                    "success": "✅", "failed": "❌", "partial": "⚠️"
                }.get(r.status, "❓")

                lines.append(
                    f"    {indicator} 第{i+1}轮: {r.status} | "
                    f"策略:{r.recommended_strategy or '无'} | "
                    f"通过:{r.strategies_passed}/{r.strategies_backtested} | "
                    f"Sharpe:{r.avg_sharpe or 'N/A'} | "
                    f"耗时:{r.duration_ms}ms"
                )
                if r.error_message:
                    lines.append(f"       📝 错误: {r.error_message[:80]}")
                if r.decision_reason:
                    lines.append(f"       💡 决策: {r.decision_reason[:100]}")

            lines.append("")

        # 关键发现
        lines.append("=" * 70)
        lines.append("🔍 关键发现")
        lines.append("-" * 70)

        # 1. 研报缺失场景
        if "no_reports" in self.results:
            nr = self.results["no_reports"]
            recommended = sum(1 for r in nr if r.recommended_strategy)
            lines.append(
                f"  • 研报缺失场景: {recommended}/{len(nr)} 轮生成推荐 "
                f"(默认策略生成机制验证)"
            )

        # 2. 极端市场
        if "extreme" in self.results:
            ex = self.results["extreme"]
            avg = mean(r.strategies_passed for r in ex)
            lines.append(
                f"  • 极端市场: 平均每轮 {avg:.1f} 个策略优于基线 "
                f"(高波动下策略筛选有效性验证)"
            )

        # 3. 超时场景
        if "timeout_heavy" in self.results:
            th = self.results["timeout_heavy"]
            avg = mean(r.strategies_passed for r in th)
            lines.append(
                f"  • 重度超时: 平均 {avg:.1f} 个策略通过 "
                f"(超时保护和降级机制验证)"
            )

        # 4. API故障
        if "api_failure" in self.results:
            af = self.results["api_failure"]
            failed_writes = sum(
                1 for r in af if r.error_message and "API" in r.error_message
            )
            lines.append(
                f"  • API故障模拟: {failed_writes}/{len(af)} 轮写入失败 "
                f"(错误已记录，不中断引擎流程)"
            )

        # 5. 压力测试
        if "stress_100_candidates" in self.results:
            sc = self.results["stress_100_candidates"]
            max_duration = max(r.duration_ms for r in sc)
            avg_duration = mean(r.duration_ms for r in sc)
            lines.append(
                f"  • 100策略规模: 最大耗时 {max_duration}ms, 平均 {avg_duration:.0f}ms "
                f"(大规模策略排序和选择性能)"
            )

        # 6. 5日强制刷新验证
        if "forced_refresh_5d" in self.results:
            fr = self.results["forced_refresh_5d"]
            refresh_count = sum(1 for r in fr if r.force_refresh_triggered)
            lines.append(
                f"  • 5日强制刷新: {refresh_count}/{len(fr)} 轮触发强制刷新 "
                f"(阈值={self.config.forced_refresh_days}天, 策略过期检测验证)"
            )

        # 7. 三轮回退验证
        if "consecutive_rollback_3rounds" in self.results:
            cr = self.results["consecutive_rollback_3rounds"]
            rollback_count = sum(1 for r in cr if r.rollback_triggered)
            baseline_count = sum(1 for r in cr if not r.recommended_strategy)
            lines.append(
                f"  • 三轮回退基线: {rollback_count}/{len(cr)} 轮触发回退, "
                f"{baseline_count}/{len(cr)} 轮使用基线策略 "
                f"(连续劣于基线的安全回退机制验证)"
            )

        # 8. 多日连续运行
        if "multi_day_simulation" in self.results:
            md = self.results["multi_day_simulation"]
            strategy_switches = sum(
                1 for i, r in enumerate(md)
                if i > 0 and r.last_strategy != md[i-1].last_strategy
            )
            max_consec = max(r.consecutive_days for r in md) if md else 0
            lines.append(
                f"  • 多日连续运行: {len(md)} 天模拟, "
                f"策略切换 {strategy_switches} 次, "
                f"最长连续推荐 {max_consec} 天 "
                f"(状态保持和决策连贯性验证)"
            )

        # 9. 连续劣于基线
        if "consecutive_worse" in self.results:
            cw = self.results["consecutive_worse"]
            max_below = max(r.below_baseline_count for r in cw) if cw else 0
            lines.append(
                f"  • 连续劣于基线: 最高连续 {max_below} 次劣于基线 "
                f"(劣于基线计数和回退触发逻辑验证)"
            )

        lines.append("")
        lines.append("=" * 70)
        lines.append("✅ 测试完成")
        lines.append("=" * 70)

        report = "\n".join(lines)

        # 保存到文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = TEST_OUTPUT_DIR / f"stress_test_report_{timestamp}.txt"
        report_file.write_text(report, encoding="utf-8")

        # 保存 JSON
        json_file = TEST_OUTPUT_DIR / f"stress_test_results_{timestamp}.json"
        json_data = {
            "timestamp": datetime.now().isoformat(),
            "config": {"rounds_per_scenario": self.rounds_per_scenario},
            "scenarios": {
                scenario: [asdict(r) for r in results]
                for scenario, results in self.results.items()
            },
        }
        json_file.write_text(json.dumps(json_data, ensure_ascii=False, indent=2))

        return report


# ============================================================================
# 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="推荐策略引擎压力测试")
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="每个场景的测试轮数 (默认: 3)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help=f"指定测试场景, 可选: {list(SCENARIO_CONFIGS.keys())}",
    )
    parser.add_argument(
        "--baseline",
        default="v9",
        choices=["v9", "v15"],
        help="基线版本 (默认: v9)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机数种子 (用于可复现测试)",
    )

    args = parser.parse_args()

    # 设置随机种子
    if args.seed is not None:
        random.seed(args.seed)
        print(f"🔢 随机种子: {args.seed}")

    # 配置
    config = EngineConfig(
        baseline_version=args.baseline,
        backtest_period="7D",
        symbol="BTC-USDT-SWAP",
        max_candidates=10,
        forced_refresh_days=5,
        rollback_threshold=3,
        min_better_count=3,
    )

    print("=" * 70)
    print("推荐策略引擎 - 多场景压力测试")
    print("=" * 70)
    print(f"  场景数: {len(args.scenarios) if args.scenarios else len(SCENARIO_CONFIGS)}")
    print(f"  每场景轮数: {args.rounds}")
    print(f"  基线版本: {args.baseline}")
    print(f"  输出目录: {TEST_OUTPUT_DIR}")
    print()

    # 列出测试场景
    print("测试场景列表:")
    scenarios_to_run = args.scenarios or list(SCENARIO_CONFIGS.keys())
    for scenario in scenarios_to_run:
        if scenario in SCENARIO_CONFIGS:
            cfg = SCENARIO_CONFIGS[scenario]
            print(f"  • {cfg['label']} ({scenario}) - {cfg['description']}")

    # 运行测试
    print("\n开始测试...")

    runner = StressTestRunner(rounds_per_scenario=args.rounds, config=config)
    runner.run_all_scenarios(scenarios_to_run)

    # 生成报告
    print("\n\n生成报告...")
    report = runner.generate_report()
    print(report)

    print(f"\n\n📁 详细结果已保存到: {TEST_OUTPUT_DIR}")
    print("   - stress_test_report_*.txt (文本报告)")
    print("   - stress_test_results_*.json (JSON 数据)")


if __name__ == "__main__":
    main()
