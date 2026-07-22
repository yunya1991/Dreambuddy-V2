"""
回测精调器 — Level 2 精调

职责：
1. 调用 Dream OS 回测引擎，跑基线 vs 增强模式
2. 按场景拆分交易记录，对比每个场景下子系统贡献
3. 生成精调权重：场景→子系统有效性评分

数据来源：Dream OS 回测引擎（历史 K 线模拟）
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("backtest_fine_tuner")

# 确保项目路径在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve()
while _PROJECT_ROOT.name != "1-ARCHITECTURE":
    _PROJECT_ROOT = _PROJECT_ROOT.parent
    if _PROJECT_ROOT == _PROJECT_ROOT.parent:
        break
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# 数据类型
# ============================================================

@dataclass
class ScenarioComparison:
    """单个场景的基线 vs 增强对比"""
    scenario_id: str
    # 基线（无子系统）
    baseline_trades: int = 0
    baseline_win_rate: float = 0.0
    baseline_avg_return: float = 0.0
    # 增强（有子系统）
    enhanced_trades: int = 0
    enhanced_win_rate: float = 0.0
    enhanced_avg_return: float = 0.0
    # 增量
    win_rate_delta: float = 0.0       # 胜率变化 (pp)
    return_delta: float = 0.0         # 收益变化 (pp)
    # 评估
    subsystem_effective: bool = False  # 子系统是否有正向贡献
    effectiveness_score: float = 0.0   # 有效性评分 (0-1)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "baseline": {
                "trades": self.baseline_trades,
                "win_rate": round(self.baseline_win_rate, 4),
                "avg_return": round(self.baseline_avg_return, 4),
            },
            "enhanced": {
                "trades": self.enhanced_trades,
                "win_rate": round(self.enhanced_win_rate, 4),
                "avg_return": round(self.enhanced_avg_return, 4),
            },
            "delta": {
                "win_rate_pp": round(self.win_rate_delta, 2),
                "return_pp": round(self.return_delta, 2),
            },
            "subsystem_effective": self.subsystem_effective,
            "effectiveness_score": round(self.effectiveness_score, 4),
        }


# ============================================================
# 回测精调器
# ============================================================

class BacktestFineTuner:
    """回测精调器 — Level 2

    通过对比基线（无子系统）和增强（有子系统）的回测结果，
    精调各场景下子系统节点的有效性。
    """

    # 子系统节点列表
    SUBSYSTEM_NODES = ["C_S3_TREND", "C_MARTIN_V15", "A_YJ_INFER"]

    def __init__(self, symbols: str = "BTC", interval: str = "1h"):
        self.symbols = symbols.split(",") if isinstance(symbols, str) else symbols
        self.interval = interval
        self._comparisons: Optional[Dict[str, ScenarioComparison]] = None

    def _run_backtest(self, enable_subsystem: bool):
        """运行一次回测"""
        from dreamos.cli.dreamos_backtester import DreamOSBacktester

        bt = DreamOSBacktester(enable_subsystem=enable_subsystem)
        results = []
        for symbol in self.symbols:
            result = bt.backtest_symbol(symbol.strip(), self.interval)
            results.append(result)
        return results

    def _split_trades_by_scenario(self, results) -> Dict[str, list]:
        """按场景拆分交易记录"""
        scenario_trades: Dict[str, list] = defaultdict(list)
        for result in results:
            for trade in result.trades:
                sid = trade.scenario_id or "UNKNOWN"
                scenario_trades[sid].append(trade)
        return scenario_trades

    def _calc_scenario_metrics(self, trades: list) -> Tuple[int, float, float]:
        """计算场景指标：(交易数, 胜率, 平均收益)"""
        if not trades:
            return 0, 0.0, 0.0
        total = len(trades)
        wins = sum(1 for t in trades if t.return_pct > 0)
        win_rate = wins / total
        avg_return = sum(t.return_pct for t in trades) / total
        return total, win_rate, avg_return

    def fine_tune(self) -> Dict[str, ScenarioComparison]:
        """执行回测精调

        1. 跑基线回测（无子系统）
        2. 跑增强回测（有子系统）
        3. 按场景拆分对比
        4. 生成有效性评分

        Returns:
            Dict[scenario_id, ScenarioComparison]
        """
        logger.info("=== Level 2 回测精调启动 ===")

        # 1. 基线回测
        logger.info("运行基线回测（无子系统）...")
        baseline_results = self._run_backtest(enable_subsystem=False)
        baseline_trades = self._split_trades_by_scenario(baseline_results)

        # 2. 增强回测
        logger.info("运行增强回测（有子系统）...")
        enhanced_results = self._run_backtest(enable_subsystem=True)
        enhanced_trades = self._split_trades_by_scenario(enhanced_results)

        # 3. 按场景对比
        all_scenarios = set(baseline_trades.keys()) | set(enhanced_trades.keys())
        comparisons: Dict[str, ScenarioComparison] = {}

        for sid in sorted(all_scenarios):
            b_trades = baseline_trades.get(sid, [])
            e_trades = enhanced_trades.get(sid, [])

            b_count, b_win, b_ret = self._calc_scenario_metrics(b_trades)
            e_count, e_win, e_ret = self._calc_scenario_metrics(e_trades)

            win_delta = (e_win - b_win) * 100  # pp
            ret_delta = (e_ret - b_ret) * 100  # pp

            # 有效性评分：胜率提升 * 0.5 + 收益提升 * 0.5
            # 归一化到 0-1
            score = 0.0
            effective = False
            if b_count > 0 or e_count > 0:
                # 胜率贡献：正向加分，负向减分
                win_score = max(0, min(win_delta / 10.0, 1.0)) if win_delta > 0 else max(-0.5, win_delta / 20.0)
                # 收益贡献
                ret_score = max(0, min(ret_delta / 5.0, 1.0)) if ret_delta > 0 else max(-0.5, ret_delta / 10.0)
                score = max(0.0, 0.5 + (win_score + ret_score) / 2.0)  # 基础 0.5
                effective = win_delta > 0 or ret_delta > 0

            comparisons[sid] = ScenarioComparison(
                scenario_id=sid,
                baseline_trades=b_count,
                baseline_win_rate=b_win,
                baseline_avg_return=b_ret,
                enhanced_trades=e_count,
                enhanced_win_rate=e_win,
                enhanced_avg_return=e_ret,
                win_rate_delta=win_delta,
                return_delta=ret_delta,
                subsystem_effective=effective,
                effectiveness_score=score,
            )

        self._comparisons = comparisons
        logger.info(f"回测精调完成：{len(comparisons)} 个场景已分析")
        return comparisons

    def get_effective_subsystems(self, scenario_id: str) -> List[str]:
        """获取场景下有效的子系统列表

        根据回测对比，返回该场景下子系统是否有效。
        如果有效，返回所有子系统节点；如果无效，返回空列表。
        """
        if self._comparisons is None:
            self.fine_tune()

        comp = self._comparisons.get(scenario_id)
        if comp and comp.subsystem_effective:
            return list(self.SUBSYSTEM_NODES)
        return []

    def get_subsystem_weights(self, scenario_id: str) -> Dict[str, float]:
        """获取场景下子系统权重（基于回测精调）

        如果子系统在该场景有效，权重提高；否则降低。
        """
        if self._comparisons is None:
            self.fine_tune()

        comp = self._comparisons.get(scenario_id)
        if not comp:
            # 无数据，均等权重
            return {n: 1.0 / len(self.SUBSYSTEM_NODES) for n in self.SUBSYSTEM_NODES}

        if comp.subsystem_effective:
            # 有效：按 effectiveness_score 加权
            base_weight = comp.effectiveness_score
            return {n: base_weight for n in self.SUBSYSTEM_NODES}
        else:
            # 无效：降低权重
            return {n: 0.2 for n in self.SUBSYSTEM_NODES}

    def summary(self) -> str:
        """生成精调摘要"""
        if self._comparisons is None:
            return "回测精调未运行，请先调用 fine_tune()"

        lines = ["回测精调摘要（Level 2）", "=" * 60]
        lines.append(f"{'场景':<35} {'基线胜率':>8} {'增强胜率':>8} {'Δ胜率':>8} {'Δ收益':>8} {'有效':>6}")
        lines.append("-" * 90)

        effective_count = 0
        for sid, comp in sorted(self._comparisons.items()):
            lines.append(
                f"{sid:<35} {comp.baseline_win_rate:>7.1%} {comp.enhanced_win_rate:>7.1%} "
                f"{comp.win_rate_delta:>+7.1f}pp {comp.return_delta:>+7.1f}pp "
                f"{'✓' if comp.subsystem_effective else '✗':>6}"
            )
            if comp.subsystem_effective:
                effective_count += 1

        lines.append("-" * 90)
        lines.append(f"有效场景: {effective_count}/{len(self._comparisons)}")

        return "\n".join(lines)
