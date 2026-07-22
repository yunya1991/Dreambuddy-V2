"""
Dream OS 交易能力域 — 交易分析评估器 (TradingAnalysisEvaluator)

**核心职责**:
    1. 亏损原因分析 — 分析交易失败的根本原因
    2. 模块能力评估 — 评估每个节点/模块在不同场景下的表现
    3. 模块回测 — 对单个模块或模块组合进行回测验证
    4. 编排推荐 — 基于分析结果推荐最优节点编排

**设计理念**:
    Dream OS 交易系统的核心不是"自身交易"，而是"分析评估 → 模块能力回测 → 节点编排推荐"的质量提升闭环。
    系统通过分析亏损原因，评估各模块能力，回测验证改进效果，最终推荐最优节点编排。

**亏损原因分类**:
    - ENTRY_SIGNAL: 入场信号质量问题
    - EXIT_SIGNAL: 离场信号质量问题
    - TREND_FILTER: 趋势过滤失效
    - SIGNAL_QUALITY: 信号质量评估不足
    - MARKET_RECOGNITION: 市场状态识别错误
    - STOP_LOSS: 止损设置不合理
    - TAKE_PROFIT: 止盈设置不合理
    - VOLATILITY: 波动率估计偏差
    - MOMENTUM: 动量判断错误
    - CORRELATION: 多资产相关性未考虑

**模块能力维度**:
    - 准确率 (accuracy): 方向判断准确率
    - 成功率 (success_rate): 交易胜率
    - 效益 (profit_factor): 盈亏比
    - 稳定性 (stability): 连续盈利/亏损次数
    - 时效性 (timeliness): 信号提前/延迟程度
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)


# ============================================================
# 数据类型定义
# ============================================================

@dataclass
class TradeAnalysisResult:
    """单笔交易分析结果"""
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl: float
    pnl_percent: float
    holding_period: int
    scenario: str
    chain_used: str
    nodes_used: List[str]

    # 分析结果
    loss_reasons: List[str] = field(default_factory=list)
    loss_reason_scores: Dict[str, float] = field(default_factory=dict)
    root_cause: Optional[str] = None
    module_issues: List[str] = field(default_factory=list)

    # 模块表现
    module_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def is_profitable(self) -> bool:
        return self.pnl_percent > 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleCapability:
    """模块能力评估结果"""
    module_id: str
    module_name: str
    total_trades: int
    winning_trades: int
    avg_pnl: float
    max_win: float
    max_loss: float
    accuracy: float          # 方向判断准确率
    success_rate: float      # 交易胜率
    profit_factor: float     # 盈亏比
    stability_score: float   # 稳定性评分
    timeliness_score: float  # 时效性评分

    # 场景细分表现
    scenario_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestModuleResult:
    """模块回测结果"""
    module_ids: List[str]
    scenario: str
    period: str
    total_trades: int
    winning_trades: int
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    avg_trade_pnl: float
    profit_factor: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestrationRecommendation:
    """编排推荐结果"""
    scenario: str
    recommended_chain: str
    recommended_nodes: List[str]
    confidence: float
    reasoning: str
    expected_improvement: float
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradingAnalysisReport:
    """交易分析评估报告"""
    report_id: str
    generated_at: str
    analyzed_trades: int
    profitable_trades: int
    avg_pnl: float

    # 亏损原因分布
    loss_reason_distribution: Dict[str, int] = field(default_factory=dict)
    top_loss_reasons: List[Tuple[str, int]] = field(default_factory=list)

    # 模块能力评估
    module_capabilities: Dict[str, ModuleCapability] = field(default_factory=dict)

    # 模块回测结果
    backtest_results: List[BacktestModuleResult] = field(default_factory=list)

    # 编排推荐
    orchestration_recommendations: Dict[str, OrchestrationRecommendation] = field(default_factory=dict)

    # 改进建议
    improvement_suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["module_capabilities"] = {k: v.to_dict() for k, v in self.module_capabilities.items()}
        result["backtest_results"] = [r.to_dict() for r in self.backtest_results]
        result["orchestration_recommendations"] = {k: v.to_dict() for k, v in self.orchestration_recommendations.items()}
        return result

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        lines = []
        lines.append(f"# 交易分析评估报告")
        lines.append(f"**报告ID**: {self.report_id}")
        lines.append(f"**生成时间**: {self.generated_at}")
        lines.append(f"\n## 概览")
        lines.append(f"- 分析交易数: {self.analyzed_trades}")
        lines.append(f"- 盈利交易数: {self.profitable_trades}")
        lines.append(f"- 胜率: {self.profitable_trades/self.analyzed_trades*100:.1f}%")
        lines.append(f"- 平均盈亏: {self.avg_pnl:.2f}%")

        lines.append(f"\n## 亏损原因分布")
        for reason, count in self.top_loss_reasons:
            rate = count / self.analyzed_trades * 100
            lines.append(f"- **{reason}**: {count} 次 ({rate:.1f}%)")

        lines.append(f"\n## 模块能力评估")
        for mid, cap in self.module_capabilities.items():
            lines.append(f"\n### {mid} - {cap.module_name}")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 交易数 | {cap.total_trades} |")
            lines.append(f"| 胜率 | {cap.success_rate*100:.1f}% |")
            lines.append(f"| 准确率 | {cap.accuracy*100:.1f}% |")
            lines.append(f"| 盈亏比 | {cap.profit_factor:.2f} |")
            lines.append(f"| 稳定性 | {cap.stability_score:.2f} |")

        lines.append(f"\n## 编排推荐")
        for scenario, rec in self.orchestration_recommendations.items():
            lines.append(f"\n### {scenario}")
            lines.append(f"- **推荐链路**: {rec.recommended_chain}")
            lines.append(f"- **推荐节点**: {', '.join(rec.recommended_nodes)}")
            lines.append(f"- **置信度**: {rec.confidence*100:.1f}%")
            lines.append(f"- **预期改进**: {rec.expected_improvement*100:.1f}%")
            lines.append(f"- **理由**: {rec.reasoning}")

        lines.append(f"\n## 改进建议")
        for i, suggestion in enumerate(self.improvement_suggestions, 1):
            lines.append(f"{i}. {suggestion}")

        return "\n".join(lines)


# ============================================================
# 核心评估器
# ============================================================

class TradingAnalysisEvaluator:
    """交易分析评估器 — Dream OS 交易系统的核心组件

    用法:
        evaluator = TradingAnalysisEvaluator()

        # 1. 分析亏损原因
        results = evaluator.analyze_loss_reasons(trade_history)

        # 2. 评估模块能力
        capabilities = evaluator.evaluate_module_capabilities(trade_history)

        # 3. 回测模块组合
        backtest = evaluator.backtest_modules(module_ids=["C1", "C2"], scenario="BULL_NORMAL_ACCELERATING")

        # 4. 生成编排推荐
        recommendations = evaluator.recommend_orchestration()

        # 5. 生成完整报告
        report = evaluator.generate_report(trade_history)
    """

    # 亏损原因分类及检测规则
    LOSS_REASON_RULES = {
        "ENTRY_SIGNAL": {
            "description": "入场信号质量问题",
            "detect": lambda trade: trade.get("entry_confidence", 0) < 0.6,
            "weight": 0.25,
        },
        "EXIT_SIGNAL": {
            "description": "离场信号质量问题",
            "detect": lambda trade: trade.get("exit_reason", "") in ("forced", "timed_out"),
            "weight": 0.2,
        },
        "TREND_FILTER": {
            "description": "趋势过滤失效",
            "detect": lambda trade: (trade.get("scenario", "").startswith("NEUTRAL") and
                                     trade.get("pnl_percent", 0) < -2),
            "weight": 0.15,
        },
        "SIGNAL_QUALITY": {
            "description": "信号质量评估不足",
            "detect": lambda trade: trade.get("signal_strength", 0) < 0.5,
            "weight": 0.15,
        },
        "MARKET_RECOGNITION": {
            "description": "市场状态识别错误",
            "detect": lambda trade: trade.get("scenario_mismatch", False),
            "weight": 0.12,
        },
        "STOP_LOSS": {
            "description": "止损设置不合理",
            "detect": lambda trade: (trade.get("pnl_percent", 0) < -3 and
                                     trade.get("stop_loss_hit", False)),
            "weight": 0.1,
        },
        "TAKE_PROFIT": {
            "description": "止盈设置不合理",
            "detect": lambda trade: (trade.get("pnl_percent", 0) > 0 and
                                     trade.get("pnl_percent", 0) < 1 and
                                     trade.get("take_profit_hit", False)),
            "weight": 0.08,
        },
        "VOLATILITY": {
            "description": "波动率估计偏差",
            "detect": lambda trade: abs(trade.get("actual_volatility", 0) -
                                        trade.get("estimated_volatility", 0)) /
                                    max(trade.get("estimated_volatility", 1), 0.001) > 0.5,
            "weight": 0.08,
        },
        "MOMENTUM": {
            "description": "动量判断错误",
            "detect": lambda trade: trade.get("momentum_confidence", 0) < 0.4,
            "weight": 0.07,
        },
        "CORRELATION": {
            "description": "多资产相关性未考虑",
            "detect": lambda trade: trade.get("correlation_conflict", False),
            "weight": 0.05,
        },
    }

    # 模块能力权重
    CAPABILITY_WEIGHTS = {
        "accuracy": 0.3,
        "success_rate": 0.25,
        "profit_factor": 0.2,
        "stability_score": 0.15,
        "timeliness_score": 0.1,
    }

    def __init__(self):
        self._trade_history: List[Dict[str, Any]] = []
        self._module_cache: Dict[str, ModuleCapability] = {}
        self._orchestration_memory: Dict[str, Any] = {}

    def set_orchestration_memory(self, memory: Dict[str, Any]) -> None:
        """设置编排记忆数据，用于补充模块能力评估"""
        self._orchestration_memory = memory

    def _filter_closed_trades(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤已平仓交易（排除未平仓的）"""
        return [t for t in trades if t.get("exit_price", 0) > 0 or t.get("pnl_percent", 0) != 0]

    # ── 1. 亏损原因分析 ──────────────────────────────────────

    def analyze_loss_reasons(self, trade_history: Optional[List[Dict[str, Any]]] = None) -> List[TradeAnalysisResult]:
        """分析交易亏损原因

        Args:
            trade_history: 交易历史列表，每条包含:
                {
                    "trade_id": str, "symbol": str, "direction": str,
                    "entry_price": float, "exit_price": float, "pnl_percent": float,
                    "holding_period": int, "scenario": str, "chain_used": str,
                    "nodes_used": List[str], "entry_confidence": float,
                    "exit_reason": str, "stop_loss_hit": bool, "take_profit_hit": bool,
                    ...
                }

        Returns:
            分析结果列表
        """
        history = trade_history or self._trade_history
        if not history:
            return []

        results = []
        for trade in history:
            result = self._analyze_single_trade(trade)
            results.append(result)

        return results

    def _analyze_single_trade(self, trade: Dict[str, Any]) -> TradeAnalysisResult:
        """分析单笔交易的亏损原因"""
        result = TradeAnalysisResult(
            trade_id=trade.get("trade_id", ""),
            symbol=trade.get("symbol", ""),
            direction=trade.get("direction", ""),
            entry_price=trade.get("entry_price", 0),
            exit_price=trade.get("exit_price", 0),
            pnl=trade.get("pnl", 0),
            pnl_percent=trade.get("pnl_percent", 0),
            holding_period=trade.get("holding_period", 0),
            scenario=trade.get("scenario", ""),
            chain_used=trade.get("chain_used", ""),
            nodes_used=trade.get("nodes_used", []),
        )

        if result.is_profitable():
            return result

        loss_reason_scores = {}
        for reason_code, rule in self.LOSS_REASON_RULES.items():
            if rule["detect"](trade):
                loss_reason_scores[reason_code] = rule["weight"]

        result.loss_reason_scores = loss_reason_scores
        result.loss_reasons = sorted(loss_reason_scores.keys(), key=lambda x: -loss_reason_scores[x])

        if result.loss_reasons:
            result.root_cause = result.loss_reasons[0]

        result.module_issues = self._identify_module_issues(trade, loss_reason_scores)

        return result

    def _identify_module_issues(self, trade: Dict[str, Any], loss_scores: Dict[str, float]) -> List[str]:
        """根据亏损原因识别问题模块"""
        issues = []
        reason_to_modules = {
            "ENTRY_SIGNAL": ["C1", "C2", "C3", "A4"],
            "EXIT_SIGNAL": ["A5", "A9", "C5"],
            "TREND_FILTER": ["A0", "A1", "C1", "C2"],
            "SIGNAL_QUALITY": ["A2", "A4", "A7"],
            "MARKET_RECOGNITION": ["A0", "A6", "C1"],
            "STOP_LOSS": ["A3", "A5", "G1"],
            "TAKE_PROFIT": ["A3", "A5", "G1"],
            "VOLATILITY": ["C3", "A3"],
            "MOMENTUM": ["C2", "A1"],
            "CORRELATION": ["F2", "G1"],
        }

        for reason in sorted(loss_scores.keys(), key=lambda x: -loss_scores[x])[:3]:
            for module_id in reason_to_modules.get(reason, []):
                if module_id in trade.get("nodes_used", []):
                    issues.append(f"{module_id}: {reason}")

        return issues

    # ── 2. 模块能力评估 ──────────────────────────────────────

    def evaluate_module_capabilities(self,
                                     trade_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, ModuleCapability]:
        """评估各模块的能力

        Returns:
            {module_id: ModuleCapability}
        """
        history = trade_history or self._trade_history
        if not history:
            return {}

        closed_trades = self._filter_closed_trades(history)
        all_trades = history

        module_trades = defaultdict(list)
        for trade in all_trades:
            for node_id in trade.get("nodes_used", []):
                module_trades[node_id].append(trade)

        capabilities = {}
        for module_id, trades in module_trades.items():
            closed_module_trades = self._filter_closed_trades(trades)
            cap = self._evaluate_single_module(module_id, trades, closed_module_trades)
            capabilities[module_id] = cap

        self._module_cache = capabilities
        return capabilities

    def _evaluate_single_module(self, module_id: str, 
                                all_trades: List[Dict[str, Any]],
                                closed_trades: List[Dict[str, Any]]) -> ModuleCapability:
        """评估单个模块的能力，融合实际交易和编排记忆数据"""
        module_names = {
            "A0": "矛盾论分析", "A1": "深度调研", "A2": "综合分析",
            "A3": "策略制定", "A4": "决策门禁", "A5": "执行规划",
            "A6": "市态监控", "A7": "实践门禁", "A8": "统一升华", "A9": "离场策略",
            "C1": "技术扫描", "C2": "动量分析", "C3": "波动率分析", "C5": "离场系统",
            "F1": "新闻分析", "F2": "资金流分析", "F3": "估值分析",
            "F4": "链上数据", "F5": "宏观分析",
            "G1": "风控", "G2": "治理",
        }

        memory_stats = self._get_module_memory_stats(module_id)

        total_trades = len(all_trades)
        closed_count = len(closed_trades)

        if closed_count > 0:
            winning_trades = sum(1 for t in closed_trades if t.get("pnl_percent", 0) > 0)
            pnls = [t.get("pnl_percent", 0) for t in closed_trades]
            avg_pnl = sum(pnls) / closed_count
            max_win = max(pnls)
            max_loss = min(pnls)
            success_rate = winning_trades / closed_count

            wins = [p for p in pnls if p > 0]
            losses = [abs(p) for p in pnls if p < 0]
            profit_factor = sum(wins) / sum(losses) if losses else 1.0
        elif memory_stats:
            winning_trades = int(memory_stats.get("sample_count", 0) * memory_stats.get("win_rate", 0.5))
            avg_pnl = memory_stats.get("return", 0) * 100
            max_win = avg_pnl * 2 if avg_pnl > 0 else 0
            max_loss = avg_pnl * 1.5 if avg_pnl < 0 else 0
            success_rate = memory_stats.get("win_rate", 0.5)
            profit_factor = memory_stats.get("profit_factor", 1.0)
        else:
            winning_trades = 0
            avg_pnl = 0
            max_win = 0
            max_loss = 0
            success_rate = 0.5
            profit_factor = 1.0

        accuracy = self._calculate_accuracy(all_trades)
        stability_score = self._calculate_stability(all_trades)
        timeliness_score = self._calculate_timeliness(all_trades)

        if memory_stats:
            stability_score = max(stability_score, min(1.0, 0.5 + memory_stats.get("sharpe", 0) * 0.05))

        scenario_performance = self._calculate_scenario_performance(module_id, all_trades)

        return ModuleCapability(
            module_id=module_id,
            module_name=module_names.get(module_id, module_id),
            total_trades=total_trades,
            winning_trades=winning_trades,
            avg_pnl=round(avg_pnl, 4),
            max_win=round(max_win, 4),
            max_loss=round(max_loss, 4),
            accuracy=round(accuracy, 4),
            success_rate=round(success_rate, 4),
            profit_factor=round(profit_factor, 4),
            stability_score=round(stability_score, 4),
            timeliness_score=round(timeliness_score, 4),
            scenario_performance=scenario_performance,
        )

    def _get_module_memory_stats(self, module_id: str) -> Dict[str, float]:
        """从编排记忆中获取模块的历史统计数据"""
        scenarios = self._orchestration_memory.get("scenarios", {})
        stats = {"sample_count": 0, "win_rate": 0, "return": 0, "sharpe": 0, "profit_factor": 1.0}

        total_weight = 0
        for scenario, info in scenarios.items():
            nodes = info.get("nodes", [])
            if module_id in nodes:
                metrics = info.get("metrics", {})
                sample_count = info.get("sample_count", 0)
                if sample_count >= 10:
                    weight = sample_count
                    total_weight += weight
                    stats["sample_count"] += sample_count
                    stats["win_rate"] += metrics.get("win_rate", 0.5) * weight
                    stats["return"] += metrics.get("return", 0) * weight
                    stats["sharpe"] += metrics.get("sharpe", 0) * weight

        if total_weight > 0:
            stats["win_rate"] /= total_weight
            stats["return"] /= total_weight
            stats["sharpe"] /= total_weight
            return stats

        return {}

    def _calculate_accuracy(self, trades: List[Dict[str, Any]]) -> float:
        """计算方向判断准确率"""
        if not trades:
            return 0.5
        correct = 0
        for trade in trades:
            direction = trade.get("direction", "")
            actual_move = trade.get("exit_price", 0) - trade.get("entry_price", 0)
            if (direction == "LONG" and actual_move > 0) or (direction == "SHORT" and actual_move < 0):
                correct += 1
        return correct / len(trades)

    def _calculate_stability(self, trades: List[Dict[str, Any]]) -> float:
        """计算稳定性评分（连续亏损次数的倒数）"""
        if len(trades) < 3:
            return 0.5

        max_streak = 0
        current_streak = 0
        prev_profit = None

        for trade in trades:
            is_profit = trade.get("pnl_percent", 0) > 0
            if prev_profit is not None and is_profit == prev_profit:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
            prev_profit = is_profit

        # 连续亏损/盈利次数越少，稳定性越高
        penalty = max_streak / len(trades)
        return max(0.1, 1.0 - penalty)

    def _calculate_timeliness(self, trades: List[Dict[str, Any]]) -> float:
        """计算时效性评分（信号提前程度）"""
        if not trades:
            return 0.5
        avg_holding = sum(t.get("holding_period", 0) for t in trades) / len(trades)
        optimal_holding = 4

        if avg_holding == 0:
            return 0.5

        ratio = abs(avg_holding - optimal_holding) / optimal_holding
        return max(0.1, min(1.0, 1.0 - ratio * 0.5))

    def _calculate_scenario_performance(self, module_id: str, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """计算模块在不同场景下的表现"""
        by_scenario = defaultdict(list)
        for trade in trades:
            scenario = trade.get("scenario", "UNKNOWN")
            by_scenario[scenario].append(trade)

        result = {}
        for scenario, scenario_trades in by_scenario.items():
            if len(scenario_trades) < 2:
                continue
            wins = sum(1 for t in scenario_trades if t.get("pnl_percent", 0) > 0)
            pnls = [t.get("pnl_percent", 0) for t in scenario_trades]
            result[scenario] = {
                "trades": len(scenario_trades),
                "win_rate": round(wins / len(scenario_trades), 4),
                "avg_pnl": round(sum(pnls) / len(pnls), 4),
                "max_drawdown": round(min(pnls), 4),
            }

        return result

    # ── 3. 模块回测 ──────────────────────────────────────────

    def backtest_modules(self,
                         module_ids: List[str],
                         scenario: str,
                         period: str = "90d",
                         price_data: Optional[List[Dict[str, Any]]] = None) -> BacktestModuleResult:
        """回测指定模块组合在特定场景下的表现

        Args:
            module_ids: 要回测的模块ID列表
            scenario: 目标场景
            period: 回测周期
            price_data: 价格数据（可选，不提供则使用默认数据）

        Returns:
            回测结果
        """
        trades = self._generate_backtest_trades(module_ids, scenario, period, price_data)

        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t > 0)
        total_return = sum(trades) / 100
        max_drawdown = self._calculate_max_drawdown(trades)
        sharpe_ratio = self._calculate_sharpe(trades)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_trade_pnl = sum(trades) / total_trades if total_trades > 0 else 0

        wins = [t for t in trades if t > 0]
        losses = [abs(t) for t in trades if t < 0]
        profit_factor = sum(wins) / sum(losses) if losses else 1.0

        return BacktestModuleResult(
            module_ids=module_ids,
            scenario=scenario,
            period=period,
            total_trades=total_trades,
            winning_trades=winning_trades,
            total_return=round(total_return, 4),
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            win_rate=round(win_rate, 4),
            avg_trade_pnl=round(avg_trade_pnl, 4),
            profit_factor=round(profit_factor, 4),
        )

    def _generate_backtest_trades(self, module_ids: List[str], scenario: str,
                                   period: str, price_data: Optional[List[Dict[str, Any]]]) -> List[float]:
        """生成回测交易（简化版：基于模块能力估算）"""
        if not self._module_cache:
            return []

        base_win_rate = 0.5
        base_avg_pnl = 0

        for mid in module_ids:
            cap = self._module_cache.get(mid)
            if cap:
                base_win_rate = (base_win_rate + cap.success_rate) / 2
                base_avg_pnl = (base_avg_pnl + cap.avg_pnl) / 2

        scenario_factor = {
            "BULL": 1.1, "BEAR": 1.1, "NEUTRAL": 0.8,
        }.get(scenario.split("_")[0], 1.0)

        num_trades = {
            "30d": 10, "60d": 20, "90d": 30, "180d": 60,
        }.get(period, 30)

        import random
        trades = []
        for _ in range(num_trades):
            if random.random() < base_win_rate * scenario_factor:
                pnl = abs(base_avg_pnl) * (0.5 + random.random())
            else:
                pnl = -abs(base_avg_pnl) * (0.5 + random.random() * 0.5)
            trades.append(pnl)

        return trades

    def _calculate_max_drawdown(self, trades: List[float]) -> float:
        """计算最大回撤"""
        if not trades:
            return 0
        cumulative = 0
        max_dd = 0
        peak = 0
        for pnl in trades:
            cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_dd = max(max_dd, drawdown)
        return max_dd

    def _calculate_sharpe(self, trades: List[float]) -> float:
        """计算夏普比率"""
        if len(trades) < 2:
            return 0
        avg = sum(trades) / len(trades)
        variance = sum((t - avg) ** 2 for t in trades) / len(trades)
        std = variance ** 0.5 if variance > 0 else 0.001
        if std == 0:
            return 0
        return avg / std * (len(trades) ** 0.5)

    # ── 4. 编排推荐 ──────────────────────────────────────────

    def recommend_orchestration(self,
                                scenarios: Optional[List[str]] = None,
                                module_capabilities: Optional[Dict[str, ModuleCapability]] = None) -> \
            Dict[str, OrchestrationRecommendation]:
        """推荐最优节点编排

        Args:
            scenarios: 目标场景列表
            module_capabilities: 模块能力评估结果

        Returns:
            {scenario: OrchestrationRecommendation}
        """
        caps = module_capabilities or self._module_cache
        if not caps:
            return {}

        memory_scenarios = list(self._orchestration_memory.get("scenarios", {}).keys())
        target_scenarios = scenarios or memory_scenarios

        recommendations = {}
        for scenario in target_scenarios:
            rec = self._generate_recommendation(scenario, caps)
            recommendations[scenario] = rec

        return recommendations

    def _generate_recommendation(self, scenario: str,
                                  module_capabilities: Dict[str, ModuleCapability]) -> OrchestrationRecommendation:
        """为单个场景生成编排推荐，融合模块能力评估和编排记忆数据"""
        parts = scenario.split("_")
        trend = parts[0]
        vol = parts[1] if len(parts) > 1 else "NORMAL"

        memory_info = self._orchestration_memory.get("scenarios", {}).get(scenario, {})
        memory_nodes = memory_info.get("nodes", [])
        memory_pattern = memory_info.get("best_pattern", "")
        memory_score = memory_info.get("score", 0)
        memory_metrics = memory_info.get("metrics", {})

        module_scores = {}
        for mid, cap in module_capabilities.items():
            base_score = (cap.accuracy * self.CAPABILITY_WEIGHTS["accuracy"] +
                          cap.success_rate * self.CAPABILITY_WEIGHTS["success_rate"] +
                          cap.profit_factor * self.CAPABILITY_WEIGHTS["profit_factor"] +
                          cap.stability_score * self.CAPABILITY_WEIGHTS["stability_score"] +
                          cap.timeliness_score * self.CAPABILITY_WEIGHTS["timeliness_score"])

            scenario_pf = cap.scenario_performance.get(scenario)
            if scenario_pf and scenario_pf["win_rate"] > 0.5:
                base_score *= (1 + scenario_pf["win_rate"] * 0.2)

            if mid in memory_nodes:
                base_score *= (1 + memory_score * 0.3)

            module_scores[mid] = base_score

        chain_templates = {
            ("BULL", "LOW"): ["C1", "C2", "A1", "A4", "A5"],
            ("BULL", "NORMAL"): ["C1", "C2", "C3", "A1", "A4", "A5"],
            ("BULL", "HIGH"): ["C1", "C2", "C3", "A0", "A4", "A5", "A9"],
            ("BULL", "EXTREME"): ["C1", "C3", "A0", "A4", "A5", "G1"],
            ("BEAR", "LOW"): ["C1", "C2", "A1", "A4", "A5"],
            ("BEAR", "NORMAL"): ["C1", "C2", "C3", "A1", "A4", "A5"],
            ("BEAR", "HIGH"): ["C1", "C2", "C3", "A0", "A4", "A5", "A9"],
            ("BEAR", "EXTREME"): ["C1", "C3", "A0", "A4", "A5", "G1"],
            ("NEUTRAL", "LOW"): ["C1", "C3", "A0", "A7", "A5"],
            ("NEUTRAL", "NORMAL"): ["C1", "C3", "A0", "A7", "A5"],
            ("NEUTRAL", "HIGH"): ["C1", "C3", "A0", "A7", "A5", "G1"],
            ("NEUTRAL", "EXTREME"): ["C1", "C3", "A0", "A7", "A5", "G1"],
        }

        key = (trend, vol) if (trend, vol) in chain_templates else (trend,)
        template = chain_templates.get(key, ["C1", "C2", "C3", "A4", "A5"])

        if memory_nodes and memory_score > 0.5:
            template = memory_nodes

        scored_nodes = [(mid, module_scores.get(mid, 0.5)) for mid in template]
        scored_nodes.sort(key=lambda x: -x[1])

        selected_nodes = [mid for mid, score in scored_nodes if score > 0.3]
        if not selected_nodes:
            selected_nodes = template

        avg_score = sum(module_scores.get(mid, 0.5) for mid in selected_nodes) / len(selected_nodes)
        
        memory_confidence = min(1.0, memory_score + memory_metrics.get("win_rate", 0.5) * 0.2) if memory_score > 0 else 0
        confidence = min(1.0, avg_score * 0.5 + memory_confidence * 0.5)

        strong_modules = [mid for mid, score in scored_nodes[:3] if score > 0.6]
        weak_modules = [mid for mid, score in scored_nodes if score < 0.4]

        reasoning = f"基于{trend}趋势{vol}波动率场景"
        if memory_pattern:
            reasoning += f"，历史最优模式: {memory_pattern}"
        if strong_modules:
            reasoning += f"，强模块: {', '.join(strong_modules)}"
        if weak_modules:
            reasoning += f"，需改进模块: {', '.join(weak_modules)}"

        chain_name = memory_pattern if memory_pattern else f"{trend.lower()}_{vol.lower()}_chain"

        return OrchestrationRecommendation(
            scenario=scenario,
            recommended_chain=chain_name,
            recommended_nodes=selected_nodes,
            confidence=round(confidence, 4),
            reasoning=reasoning,
            expected_improvement=round((confidence - 0.5) * 0.5, 4),
            evidence={
                "module_scores": {mid: round(module_scores.get(mid, 0), 4) for mid in selected_nodes},
                "chain_template": template,
                "memory_best_pattern": memory_pattern,
                "memory_score": memory_score,
                "memory_metrics": memory_metrics,
            },
        )

    # ── 5. 生成完整报告 ──────────────────────────────────────

    def generate_report(self, trade_history: List[Dict[str, Any]],
                        scenarios: Optional[List[str]] = None) -> TradingAnalysisReport:
        """生成完整的交易分析评估报告"""
        self._trade_history = trade_history

        analyses = self.analyze_loss_reasons()
        capabilities = self.evaluate_module_capabilities()
        recommendations = self.recommend_orchestration(scenarios=scenarios)

        # 统计亏损原因分布
        loss_reasons = []
        for analysis in analyses:
            loss_reasons.extend(analysis.loss_reasons)

        reason_dist = Counter(loss_reasons)
        top_reasons = reason_dist.most_common(5)

        # 计算概览指标
        total_trades = len(analyses)
        profitable = sum(1 for a in analyses if a.is_profitable())
        avg_pnl = sum(a.pnl_percent for a in analyses) / total_trades if total_trades > 0 else 0

        # 生成改进建议
        suggestions = self._generate_improvement_suggestions(reason_dist, capabilities)

        # 回测关键模块组合
        backtest_results = []
        for scenario, rec in recommendations.items():
            if rec.recommended_nodes:
                backtest = self.backtest_modules(rec.recommended_nodes, scenario)
                backtest_results.append(backtest)

        return TradingAnalysisReport(
            report_id=f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            generated_at=datetime.now().isoformat(),
            analyzed_trades=total_trades,
            profitable_trades=profitable,
            avg_pnl=round(avg_pnl, 4),
            loss_reason_distribution=dict(reason_dist),
            top_loss_reasons=top_reasons,
            module_capabilities=capabilities,
            backtest_results=backtest_results,
            orchestration_recommendations=recommendations,
            improvement_suggestions=suggestions,
        )

    def _generate_improvement_suggestions(self,
                                           loss_reasons: Counter,
                                           capabilities: Dict[str, ModuleCapability]) -> List[str]:
        """生成改进建议"""
        suggestions = []

        # 根据亏损原因生成建议
        if loss_reasons.get("ENTRY_SIGNAL", 0) > 0:
            suggestions.append("入场信号质量不足，建议增加信号过滤条件或提高 A4 门禁阈值")

        if loss_reasons.get("TREND_FILTER", 0) > 0:
            suggestions.append("趋势过滤失效，建议优化 A0 矛盾分析或增加趋势确认节点")

        if loss_reasons.get("STOP_LOSS", 0) > 0:
            suggestions.append("止损设置不合理，建议收紧止损参数或增加动态止损机制")

        if loss_reasons.get("VOLATILITY", 0) > 0:
            suggestions.append("波动率估计偏差，建议优化 C3 波动率分析或使用自适应参数")

        # 根据模块能力生成建议
        for mid, cap in capabilities.items():
            if cap.success_rate < 0.4:
                suggestions.append(f"模块 {mid} 胜率偏低 ({cap.success_rate*100:.1f}%)，建议检查逻辑或考虑替换")
            if cap.stability_score < 0.3:
                suggestions.append(f"模块 {mid} 稳定性不足 ({cap.stability_score:.2f})，建议增加风控")

        return suggestions[:10]

    # ── 数据管理 ─────────────────────────────────────────────

    def load_trade_history(self, file_path: str) -> int:
        """从文件加载交易历史"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self._trade_history = json.load(f)
            logger.info(f"已加载 {len(self._trade_history)} 条交易记录")
            return len(self._trade_history)
        except Exception as e:
            logger.error(f"加载交易历史失败: {e}")
            return 0

    def save_report(self, report: TradingAnalysisReport, file_path: str) -> None:
        """保存报告到文件"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"报告已保存: {file_path}")
        except Exception as e:
            logger.error(f"保存报告失败: {e}")

    def save_report_markdown(self, report: TradingAnalysisReport, file_path: str) -> None:
        """保存 Markdown 格式报告"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report.to_markdown())
            logger.info(f"Markdown 报告已保存: {file_path}")
        except Exception as e:
            logger.error(f"保存报告失败: {e}")

    def __repr__(self) -> str:
        return f"<TradingAnalysisEvaluator history={len(self._trade_history)} modules={len(self._module_cache)}>"
