#!/usr/bin/env python3
"""
子系统能力评估器 — 阶段2实现

职责:
1. 从各子系统采集交易记录（V15、易经、三屏等）
2. 按场景分类交易记录
3. 计算场景-系统二维能力评分（5维：准确率/胜率/盈亏比/稳定性/时效性）
4. 输出场景→最优子系统映射表
5. 与 Dream OS 自身回测对比

约束:
- 仅基于历史数据进行离线评估
- 不实时干预任何子系统
- 评估结果用于 Dream OS 自身交易系统的节点优化参考
"""

from __future__ import annotations

import csv
import json
import logging
import gzip
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("subsystem_capability_evaluator")

# 项目路径
BASE_DIR = Path(__file__).parent
while BASE_DIR.name != "dreambuddy-v2":
    BASE_DIR = BASE_DIR.parent


# ============================================================
# 数据类型定义
# ============================================================

@dataclass
class SubsystemTrade:
    """子系统交易记录（标准化格式）"""
    trade_id: str
    system: str                  # v15 | yijing | screen3 | ab_trading
    symbol: str
    direction: str               # LONG | SHORT
    entry_time: str
    entry_price: float
    exit_time: Optional[str]
    exit_price: Optional[float]
    pnl_percent: float
    holding_bars: int
    scenario: str                # 场景ID（需要推断）
    confidence: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioSystemMetrics:
    """单个场景-系统的指标"""
    scenario: str
    system: str
    total_trades: int
    winning_trades: int
    win_rate: float
    avg_pnl: float
    total_return: float
    max_drawdown: float
    accuracy: float              # 方向准确率
    stability: float             # 稳定性评分
    sharpe: float                # 夏普比率
    score: float                 # 综合评分

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubsystemCapabilityReport:
    """子系统能力评估报告"""
    generated_at: str
    total_trades_analyzed: int
    systems_evaluated: List[str]
    scenario_metrics: Dict[str, Dict[str, Dict]]  # scenario -> system -> metrics
    best_systems: Dict[str, str]                   # scenario -> best_system
    recommendations: Dict[str, str]                # scenario -> recommendation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 子系统交易记录提取器
# ============================================================

class SubsystemTradeExtractor:
    """从各子系统提取交易记录"""

    # V15 配置
    V15_STATE_FILE = "14-V15经典马丁策略/data/v15_state.json"
    V15_TRADE_AUDIT = "14-V15经典马丁策略/data/okx_client/sim_trades_audit.jsonl"

    # 易经配置
    YIJING_TRADER_DIR = "11-易经推理系统/data/polling_trader"
    YIJING_TRADE_AUDIT = "11-易经推理系统/data/okx_sim/sim_trades_audit.jsonl"
    YIJING_BCRM2_MEMORY = "11-易经推理系统/data/bcrm2/memory.json"

    # 三屏趋势配置（暂无独立交易记录，使用 Aster 执行器日志）
    SCREEN3_DIR = "12-三屏趋势系统/live"
    SCREEN3_SIGNAL_POOL = "12-三屏趋势系统/signal_pool/pool.json"
    SCREEN3_PERF_HISTORY = "12-三屏趋势系统/ml/models/perf_logs/perf_history.json"

    # 趋势策略配置（回测结果）
    TREND_SYSTEM_PERF = "trend-system/ml/models/perf_logs/perf_history.json"

    def extract_all(self) -> List[SubsystemTrade]:
        """提取所有子系统的交易记录"""
        trades = []

        # 1. V15
        trades.extend(self._extract_v15())

        # 2. 易经
        trades.extend(self._extract_yijing())

        # 3. 三屏趋势（回测结果转交易记录）
        trades.extend(self._extract_screen3_backtest())

        # 4. 趋势策略（回测结果转交易记录）
        trades.extend(self._extract_trend_system_backtest())

        logger.info(f"共提取 {len(trades)} 条交易记录")
        return trades

    def _extract_screen3_backtest(self) -> List[SubsystemTrade]:
        """从三屏趋势回测结果提取伪交易记录"""
        trades = []

        perf_file = BASE_DIR / self.SCREEN3_PERF_HISTORY
        if not perf_file.exists():
            logger.warning(f"三屏趋势性能日志不存在: {perf_file}")
            return trades

        try:
            with open(perf_file, "r") as f:
                perf_data = json.load(f)

            records = perf_data.get("records", [])
            for record in records:
                perf = record.get("performance", {})
                if not perf:
                    continue

                # 将回测结果转为伪交易记录
                total_return = perf.get("total_return_pct", 0)
                win_rate = perf.get("win_rate_pct", 0) / 100
                sharpe = perf.get("sharpe_ratio", 0)
                max_dd = perf.get("max_drawdown_pct", 0)
                profit_factor = perf.get("profit_factor", 1)

                # 基于回测指标估算交易数量
                # 假设回测期间平均每3天1笔交易
                date_range = record.get("date_range", [])
                if len(date_range) == 2:
                    start = datetime.strptime(date_range[0], "%Y-%m-%d")
                    end = datetime.strptime(date_range[1], "%Y-%m-%d")
                    days = (end - start).days
                    estimated_trades = max(1, days // 3)
                else:
                    estimated_trades = 30

                winning_trades = int(estimated_trades * win_rate)

                # 生成伪交易记录
                for i in range(estimated_trades):
                    is_win = i < winning_trades
                    if is_win:
                        pnl = total_return / max(1, winning_trades) if winning_trades > 0 else 0
                    else:
                        pnl = -max_dd / max(1, estimated_trades - winning_trades) if estimated_trades > winning_trades else 0

                    trade = SubsystemTrade(
                        trade_id=f"screen3_backtest_{record.get('version', 'v1')}_{i}",
                        system="screen3_trend",
                        symbol="BTC",  # 回测通常是 BTC
                        direction="LONG",
                        entry_time=date_range[0] if date_range else "",
                        entry_price=0,
                        exit_time=date_range[1] if len(date_range) > 1 else "",
                        exit_price=0,
                        pnl_percent=pnl,
                        holding_bars=72,  # 假设3天 = 72小时
                        scenario=self._infer_scenario_from_backtest(perf),
                        confidence=perf.get("win_rate_pct", 50) / 100,
                        meta={"version": record.get("version", ""), "period": record.get("period", ""), **perf},
                    )
                    trades.append(trade)

            logger.info(f"三屏趋势回测记录: {len(trades)} 条（估算）")
        except Exception as e:
            logger.error(f"提取三屏趋势回测失败: {e}")

        return trades

    def _extract_trend_system_backtest(self) -> List[SubsystemTrade]:
        """从趋势策略回测结果提取伪交易记录"""
        trades = []

        perf_file = BASE_DIR / self.TREND_SYSTEM_PERF
        if not perf_file.exists():
            logger.warning(f"趋势策略性能日志不存在: {perf_file}")
            return trades

        try:
            with open(perf_file, "r") as f:
                perf_data = json.load(f)

            records = perf_data.get("records", [])
            for record in records:
                perf = record.get("performance", {})
                if not perf:
                    continue

                total_return = perf.get("total_return_pct", 0)
                win_rate = perf.get("win_rate_pct", 0) / 100
                max_dd = perf.get("max_drawdown_pct", 0)

                date_range = record.get("date_range", [])
                if len(date_range) == 2:
                    start = datetime.strptime(date_range[0], "%Y-%m-%d")
                    end = datetime.strptime(date_range[1], "%Y-%m-%d")
                    days = (end - start).days
                    estimated_trades = max(1, days // 3)
                else:
                    estimated_trades = 30

                winning_trades = int(estimated_trades * win_rate)

                for i in range(estimated_trades):
                    is_win = i < winning_trades
                    if is_win:
                        pnl = total_return / max(1, winning_trades) if winning_trades > 0 else 0
                    else:
                        pnl = -max_dd / max(1, estimated_trades - winning_trades) if estimated_trades > winning_trades else 0

                    trade = SubsystemTrade(
                        trade_id=f"trend_backtest_{record.get('version', 'v1')}_{i}",
                        system="trend_system",
                        symbol="BTC",
                        direction="LONG",
                        entry_time=date_range[0] if date_range else "",
                        entry_price=0,
                        exit_time=date_range[1] if len(date_range) > 1 else "",
                        exit_price=0,
                        pnl_percent=pnl,
                        holding_bars=72,
                        scenario=self._infer_scenario_from_backtest(perf),
                        confidence=perf.get("win_rate_pct", 50) / 100,
                        meta={"version": record.get("version", ""), "period": record.get("period", ""), **perf},
                    )
                    trades.append(trade)

            logger.info(f"趋势策略回测记录: {len(trades)} 条（估算）")
        except Exception as e:
            logger.error(f"提取趋势策略回测失败: {e}")

        return trades

    def _infer_scenario_from_backtest(self, perf: Dict) -> str:
        """从回测指标推断场景"""
        sharpe = perf.get("sharpe_ratio", 0)
        max_dd = perf.get("max_drawdown_pct", 0)

        if sharpe > 1:
            trend = "BULL"
        elif sharpe < 0:
            trend = "BEAR"
        else:
            trend = "NEUTRAL"

        if max_dd > 15:
            volatility = "HIGH"
        elif max_dd < 5:
            volatility = "LOW"
        else:
            volatility = "NORMAL"

        return f"{trend}_{volatility}_NORMAL"

    def _extract_v15(self) -> List[SubsystemTrade]:
        """从 V15 系统提取交易记录"""
        trades = []

        # 从 v15_state.json 提取当前持仓
        state_file = BASE_DIR / self.V15_STATE_FILE
        if not state_file.exists():
            logger.warning(f"V15 state file not found: {state_file}")
            return trades

        try:
            with open(state_file, "r") as f:
                state = json.load(f)

            positions = state.get("positions", {})
            for symbol, pos in positions.items():
                trade = SubsystemTrade(
                    trade_id=f"v15_{symbol}_{pos.get('open_time', '')[:10]}",
                    system="v15_martin",
                    symbol=symbol,
                    direction=pos.get("direction", "LONG"),
                    entry_time=pos.get("open_time", ""),
                    entry_price=float(pos.get("entry_price", 0)),
                    exit_time=None,  # 未平仓
                    exit_price=None,
                    pnl_percent=float(pos.get("profit_pct", 0)) * 100,
                    holding_bars=self._estimate_holding_bars(pos.get("open_time", "")),
                    scenario=self._infer_scenario_from_position(pos),
                    confidence=float(pos.get("confidence", 50)) / 100,
                    meta=pos,
                )
                trades.append(trade)

            logger.info(f"V15 当前持仓: {len(trades)} 条")
        except Exception as e:
            logger.error(f"提取 V15 交易记录失败: {e}")

        # 从交易审计日志提取历史交易
        audit_file = BASE_DIR / self.V15_TRADE_AUDIT
        if audit_file.exists():
            try:
                with open(audit_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            if record.get("action") == "CLOSE":
                                trade = self._parse_v15_audit_close(record)
                                if trade:
                                    trades.append(trade)
                        except json.JSONDecodeError:
                            continue
                logger.info(f"V15 历史交易已加载")
            except Exception as e:
                logger.error(f"读取 V15 审计日志失败: {e}")

        return trades

    def _parse_v15_audit_close(self, record: Dict) -> Optional[SubsystemTrade]:
        """解析 V15 审计日志中的平仓记录"""
        try:
            return SubsystemTrade(
                trade_id=f"v15_{record.get('instId', '')}_{record.get('timestamp', '')}",
                system="v15_martin",
                symbol=record.get("instId", "").split("-")[0],
                direction=record.get("posSide", "LONG"),
                entry_time=record.get("open_time", record.get("timestamp", "")),
                entry_price=float(record.get("avgPx", record.get("entry_price", 0))),
                exit_time=record.get("timestamp", ""),
                exit_price=float(record.get("fillPx", 0)),
                pnl_percent=float(record.get("pnl", 0)) * 100,
                holding_bars=self._estimate_holding_bars(record.get("open_time", "")),
                scenario=self._infer_scenario_from_position(record),
                confidence=0.6,
                meta=record,
            )
        except Exception as e:
            return None

    def _extract_yijing(self) -> List[SubsystemTrade]:
        """从易经系统提取交易记录"""
        trades = []

        # 从审计日志提取（JSONL 格式）
        audit_file = BASE_DIR / self.YIJING_TRADE_AUDIT
        if audit_file.exists():
            try:
                with open(audit_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            # 只提取成功的非 dry_run 订单
                            if record.get("dry_run") or record.get("action") != "place_order":
                                continue
                            if record.get("result_code") != "0":
                                continue

                            trade = self._parse_yijing_audit_record(record)
                            if trade:
                                trades.append(trade)
                        except json.JSONDecodeError:
                            continue
                logger.info(f"易经审计日志交易: {len(trades)} 条")
            except Exception as e:
                logger.error(f"读取易经审计日志失败: {e}")

        return trades

    def _parse_yijing_audit_record(self, record: Dict) -> Optional[SubsystemTrade]:
        """解析易经审计日志中的交易记录"""
        try:
            payload = record.get("payload", {})
            result_data = record.get("result_data", [])
            if not result_data:
                return None

            result = result_data[0]
            inst_id = payload.get("instId", "")
            symbol = inst_id.split("-")[0]

            # 从 tag 或 side 推断方向
            side = payload.get("side", "")
            pos_side = payload.get("posSide", "")
            direction = "LONG" if pos_side == "long" else "SHORT"

            return SubsystemTrade(
                trade_id=f"yijing_{symbol}_{record.get('ts', '')[:19]}",
                system="yijing_bcrm",
                symbol=symbol,
                direction=direction,
                entry_time=record.get("ts", ""),
                entry_price=0,  # 审计日志中没有入场价
                exit_time=None,
                exit_price=None,
                pnl_percent=0,  # 审计日志中没有盈亏
                holding_bars=1,
                scenario=self._infer_scenario_from_yijing(payload),
                confidence=0.6,
                meta=record,
            )
        except Exception as e:
            return None

    def _estimate_holding_bars(self, open_time: str) -> int:
        """估算持仓K线数（假设1H周期）"""
        if not open_time:
            return 1
        try:
            if "T" in open_time:
                open_dt = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
            else:
                open_dt = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
            now = datetime.now(timezone.utc)
            hours = (now - open_dt).total_seconds() / 3600
            return max(1, int(hours))
        except Exception:
            return 1

    def _infer_scenario_from_position(self, pos: Dict) -> str:
        """从持仓信息推断场景（简化版）"""
        # 基于止损类型和波动率倍数推断
        sl_type = pos.get("stop_loss_type", "")
        vol_mult = pos.get("vol_mult", 1.0)

        # 简化场景推断
        if vol_mult < 0.5:
            volatility = "LOW"
        elif vol_mult > 1.5:
            volatility = "HIGH"
        else:
            volatility = "NORMAL"

        # 默认为 NEUTRAL（实际应该从市场数据计算）
        trend = "NEUTRAL"

        return f"{trend}_{volatility}_NORMAL"

    def _infer_scenario_from_yijing(self, record: Dict) -> str:
        """从易经记录推断场景"""
        # 如果记录中有 hexagram 信息，可以基于卦象推断
        hexagram = record.get("hexagram", "")
        if hexagram:
            # 简化：根据卦象属性推断
            if "乾" in hexagram or "泰" in hexagram:
                return "BULL_NORMAL_ACCELERATING"
            elif "坤" in hexagram or "否" in hexagram:
                return "BEAR_NORMAL_DECELERATING"

        return "NEUTRAL_NORMAL_NORMAL"


# ============================================================
# 场景-系统能力评估器
# ============================================================

class ScenarioSystemEvaluator:
    """场景-系统二维能力评估"""

    # 能力权重
    WEIGHTS = {
        "win_rate": 0.25,
        "accuracy": 0.20,
        "sharpe": 0.20,
        "stability": 0.20,
        "total_return": 0.15,
    }

    def evaluate(self, trades: List[SubsystemTrade]) -> SubsystemCapabilityReport:
        """执行评估"""
        logger.info(f"开始评估 {len(trades)} 条交易记录...")

        # 1. 按场景-系统分组
        grouped = self._group_by_scenario_system(trades)

        # 2. 计算各场景-系统的指标
        scenario_metrics = {}
        for (scenario, system), system_trades in grouped.items():
            if scenario not in scenario_metrics:
                scenario_metrics[scenario] = {}

            metrics = self._calculate_metrics(scenario, system, system_trades)
            scenario_metrics[scenario][system] = metrics.to_dict()

        # 3. 找出每个场景的最优系统
        best_systems = {}
        for scenario, systems in scenario_metrics.items():
            if not systems:
                continue
            best_system = max(systems.items(), key=lambda x: x[1]["score"])
            best_systems[scenario] = best_system[0]

        # 4. 生成推荐
        recommendations = {}
        for scenario, best_system in best_systems.items():
            recommendations[scenario] = f"场景 {scenario} 下 {best_system} 表现最佳，建议参考其信号"

        # 5. 生成报告
        report = SubsystemCapabilityReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_trades_analyzed=len(trades),
            systems_evaluated=list(set(t.system for t in trades)),
            scenario_metrics=scenario_metrics,
            best_systems=best_systems,
            recommendations=recommendations,
        )

        logger.info(f"评估完成: {len(scenario_metrics)} 个场景, {len(best_systems)} 个推荐")

        return report

    def _group_by_scenario_system(self, trades: List[SubsystemTrade]) -> Dict[Tuple[str, str], List[SubsystemTrade]]:
        """按场景-系统分组"""
        grouped = defaultdict(list)
        for trade in trades:
            key = (trade.scenario, trade.system)
            grouped[key].append(trade)
        return grouped

    def _calculate_metrics(self, scenario: str, system: str, trades: List[SubsystemTrade]) -> ScenarioSystemMetrics:
        """计算单个场景-系统的指标"""
        total_trades = len(trades)

        # 过滤已平仓交易
        closed_trades = [t for t in trades if t.exit_price is not None or t.pnl_percent != 0]

        if not closed_trades:
            # 使用未平仓交易
            closed_trades = trades

        winning_trades = sum(1 for t in closed_trades if t.pnl_percent > 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        pnls = [t.pnl_percent for t in closed_trades]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0
        total_return = sum(pnls)

        # 方向准确率
        accuracy = self._calculate_accuracy(closed_trades)

        # 稳定性（连续亏损次数的倒数）
        stability = self._calculate_stability(closed_trades)

        # 夏普比率
        sharpe = self._calculate_sharpe(pnls)

        # 最大回撤
        max_drawdown = self._calculate_max_drawdown(pnls)

        # 综合评分
        score = (
            win_rate * self.WEIGHTS["win_rate"] +
            accuracy * self.WEIGHTS["accuracy"] +
            min(sharpe / 2, 1) * self.WEIGHTS["sharpe"] +  # 夏普归一化
            stability * self.WEIGHTS["stability"] +
            (1 if total_return > 0 else 0) * self.WEIGHTS["total_return"]
        )

        return ScenarioSystemMetrics(
            scenario=scenario,
            system=system,
            total_trades=total_trades,
            winning_trades=winning_trades,
            win_rate=round(win_rate, 4),
            avg_pnl=round(avg_pnl, 4),
            total_return=round(total_return, 4),
            max_drawdown=round(max_drawdown, 4),
            accuracy=round(accuracy, 4),
            stability=round(stability, 4),
            sharpe=round(sharpe, 4),
            score=round(score, 4),
        )

    def _calculate_accuracy(self, trades: List[SubsystemTrade]) -> float:
        """计算方向准确率"""
        if not trades:
            return 0.5

        correct = 0
        for trade in trades:
            if trade.exit_price and trade.entry_price:
                price_change = trade.exit_price - trade.entry_price
                if (trade.direction == "LONG" and price_change > 0) or \
                   (trade.direction == "SHORT" and price_change < 0):
                    correct += 1

        return correct / len(trades) if trades else 0.5

    def _calculate_stability(self, trades: List[SubsystemTrade]) -> float:
        """计算稳定性评分"""
        if len(trades) < 3:
            return 0.5

        pnls = [t.pnl_percent for t in trades]
        max_streak = 0
        current_streak = 0
        prev_profit = None

        for pnl in pnls:
            is_profit = pnl > 0
            if prev_profit is not None and is_profit == prev_profit:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
            prev_profit = is_profit

        penalty = max_streak / len(trades)
        return max(0.1, 1.0 - penalty)

    def _calculate_sharpe(self, pnls: List[float]) -> float:
        """计算夏普比率"""
        if len(pnls) < 2:
            return 0

        avg = sum(pnls) / len(pnls)
        variance = sum((p - avg) ** 2 for p in pnls) / len(pnls)
        std = variance ** 0.5 if variance > 0 else 0.001

        if std == 0:
            return 0
        return avg / std * (len(pnls) ** 0.5)

    def _calculate_max_drawdown(self, pnls: List[float]) -> float:
        """计算最大回撤"""
        if not pnls:
            return 0

        cumulative = 0
        max_dd = 0
        peak = 0

        for pnl in pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_dd = max(max_dd, drawdown)

        return max_dd


# ============================================================
# 主入口
# ============================================================

def evaluate_subsystems(output_file: Optional[str] = None) -> SubsystemCapabilityReport:
    """执行子系统能力评估

    Args:
        output_file: 可选输出文件路径

    Returns:
        SubsystemCapabilityReport: 评估报告
    """
    # 1. 提取交易记录
    extractor = SubsystemTradeExtractor()
    trades = extractor.extract_all()

    if not trades:
        logger.warning("未提取到任何交易记录")
        return SubsystemCapabilityReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_trades_analyzed=0,
            systems_evaluated=[],
            scenario_metrics={},
            best_systems={},
            recommendations={},
        )

    # 2. 执行评估
    evaluator = ScenarioSystemEvaluator()
    report = evaluator.evaluate(trades)

    # 3. 输出到文件
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"评估报告已保存: {output_path}")

    return report


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="子系统能力评估器")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（JSON格式）"
    )

    args = parser.parse_args()

    report = evaluate_subsystems(args.output)

    # 打印摘要
    print("\n" + "="*60)
    print("子系统能力评估摘要")
    print("="*60)
    print(f"分析交易数: {report.total_trades_analyzed}")
    print(f"评估系统数: {len(report.systems_evaluated)}")
    print(f"评估系统: {', '.join(report.systems_evaluated)}")
    print(f"场景数: {len(report.scenario_metrics)}")

    if report.best_systems:
        print("\n场景最优系统:")
        for scenario, system in report.best_systems.items():
            print(f"  {scenario}: {system}")

    print("\n" + "="*60)

    if not args.output:
        print("\n完整报告:")
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()