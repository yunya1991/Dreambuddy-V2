"""
执行反馈收集 — 记录实际交易结果，计算与回测预期的偏差

记录每次交易的场景、编排模式和结果，
当偏差超过阈值时触发进化优化。
"""

from __future__ import annotations

import json
import os
import math
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExecutionFeedback:
    """执行反馈"""
    scenario_id: str           # "BULL_NORMAL_ACCELERATING"
    pattern_used: str          # "c_f_chain"
    timestamp: str             # ISO格式
    trades: List[Dict[str, Any]] = field(default_factory=list)
    actual_sharpe: float = 0.0
    expected_sharpe: float = 0.0
    deviation: float = 0.0     # (actual - expected) / |expected|
    direction_accuracy: float = 0.0  # 方向准确率
    trigger_evolution: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionFeedbackCollector:
    """执行反馈收集器

    用法:
        collector = ExecutionFeedbackCollector(memory)
        collector.record("BULL_NORMAL_ACCELERATING", "c_f_chain", {"direction":"LONG","result":0.03})
        feedback = collector.evaluate("BULL_NORMAL_ACCELERATING")
        if feedback.trigger_evolution:
            # 触发进化优化
    """

    # 触发进化的阈值
    DIRECTION_ACCURACY_THRESHOLD = 0.5   # 连续3笔方向准确率<50%
    DEVIATION_THRESHOLD = 0.3            # 偏差>30%
    MIN_TRADES_FOR_EVAL = 3             # 最少3笔交易才评估
    # P1-1: 数据有效性阈值 — result=0(未平仓)占比超过此值时暂停进化
    ZERO_RESULT_RATIO_THRESHOLD = 0.8

    def __init__(self, memory=None):
        self.memory = memory
        self._records: Dict[str, List[Dict[str, Any]]] = {}
        self._path = str(Path(__file__).parent / "execution_feedback.json")
        self._load()

    def _load(self):
        """加载历史反馈记录"""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._records = json.load(f)
            except Exception:
                self._records = {}

    def _save(self):
        """保存反馈记录"""
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)

    def record(self, scenario_id: str, pattern: str, trade_result: Dict[str, Any]) -> None:
        """记录单笔交易结果

        Args:
            scenario_id: 场景ID
            pattern: 使用的编排模式
            trade_result: {"direction": "LONG", "result": 0.03, "expected": "LONG", ...}
        """
        if scenario_id not in self._records:
            self._records[scenario_id] = []

        entry = {
            "pattern": pattern,
            "timestamp": datetime.now().isoformat(),
            "status": "open",  # P0-1: 标记开仓状态，平仓时改为 closed
            **trade_result,
        }
        self._records[scenario_id].append(entry)

        # 只保留最近100条
        if len(self._records[scenario_id]) > 100:
            self._records[scenario_id] = self._records[scenario_id][-100:]

        self._save()

    def update_exit_result(self, scenario_id: str, symbol: str, entry_price: float,
                           exit_price: float, result: float) -> bool:
        """P0-1: 平仓时回填实际结果到最近的开仓记录

        根据 scenario_id + symbol + entry_price 匹配最近一条 result=0 的开仓记录，
        回填 exit_price 和 result，闭合反馈环。

        Args:
            scenario_id: 场景ID
            symbol: 交易对
            entry_price: 开仓价
            exit_price: 平仓价
            result: 实际收益率（已扣手续费）

        Returns:
            True 如果成功更新，False 如果未找到匹配记录
        """
        records = self._records.get(scenario_id, [])
        sym_upper = symbol.upper().strip()

        # 从最新记录往前找，匹配 result=0 且 symbol+entry_price 匹配的开仓记录
        for r in reversed(records):
            rec_sym = str(r.get("symbol", "")).upper().strip()
            rec_entry = float(r.get("entry_price", 0))
            # entry_price 容差 0.1%（应对浮点精度和滑点）
            price_match = (rec_entry > 0 and entry_price > 0
                           and abs(rec_entry - entry_price) < entry_price * 0.001)
            if (r.get("result", 0) == 0
                    and rec_sym == sym_upper
                    and price_match):
                r["exit_price"] = exit_price
                r["result"] = result
                r["exit_timestamp"] = datetime.now().isoformat()
                r["status"] = "closed"
                self._save()
                logger.info(
                    f"P0-1 反馈回填: {scenario_id} | {symbol} | "
                    f"entry={entry_price} exit={exit_price} result={result:.4f}"
                )
                return True

        logger.warning(
            f"P0-1 未找到匹配开仓记录: {scenario_id} | {symbol} | entry={entry_price}"
        )
        return False

    def evaluate(self, scenario_id: str) -> ExecutionFeedback:
        """评估某场景的执行反馈

        Args:
            scenario_id: 场景ID

        Returns:
            ExecutionFeedback: 反馈结果
        """
        records = self._records.get(scenario_id, [])
        recent = records[-self.MIN_TRADES_FOR_EVAL * 3:]  # 最近9笔

        # 获取预期值
        expected_sharpe = 0.0
        if self.memory:
            scenario_data = self.memory.get_scenario(scenario_id)
            if scenario_data:
                expected_sharpe = scenario_data.get("metrics", {}).get("sharpe", 0)

        # 计算实际指标
        trades = []
        returns = []
        direction_correct = 0
        direction_total = 0

        for r in recent:
            trade = {
                "direction": r.get("direction", "HOLD"),
                "result": r.get("result", 0),
                "expected_direction": r.get("expected_direction"),
            }
            trades.append(trade)

            ret = r.get("result", 0)
            if ret is not None:
                returns.append(ret)

            # 方向准确率
            if r.get("expected_direction"):
                direction_total += 1
                if r.get("direction") == r.get("expected_direction"):
                    direction_correct += 1

        # 计算实际夏普
        actual_sharpe = 0.0
        if len(returns) >= 2:
            avg = sum(returns) / len(returns)
            std = math.sqrt(sum((r - avg) ** 2 for r in returns) / len(returns))
            if std > 0:
                actual_sharpe = avg / std * math.sqrt(730)  # 年化

        # 偏差
        if expected_sharpe != 0:
            deviation = abs(actual_sharpe - expected_sharpe) / abs(expected_sharpe)
        else:
            deviation = 0.0

        # 方向准确率
        direction_accuracy = direction_correct / direction_total if direction_total > 0 else 1.0

        # 触发判定
        trigger = False
        if len(returns) >= self.MIN_TRADES_FOR_EVAL:
            # P1-1: 数据有效性检查 — result=0 占比过高时暂停进化
            zero_count = sum(1 for r in returns if r == 0)
            zero_ratio = zero_count / len(returns) if returns else 0
            if zero_ratio > self.ZERO_RESULT_RATIO_THRESHOLD:
                # 绝大多数交易未平仓，无有效收益数据，不触发进化
                trigger = False
                logger.info(
                    f"场景 {scenario_id} 数据无效: {zero_count}/{len(returns)} 笔 result=0 "
                    f"(占比 {zero_ratio:.0%} > {self.ZERO_RESULT_RATIO_THRESHOLD:.0%}), 暂停进化触发"
                )
            else:
                # 条件1: 连续3笔方向准确率<50%
                if direction_accuracy < self.DIRECTION_ACCURACY_THRESHOLD:
                    trigger = True
                # 条件2: 偏差>30%
                if deviation > self.DEVIATION_THRESHOLD:
                    trigger = True

        return ExecutionFeedback(
            scenario_id=scenario_id,
            pattern_used=recent[-1]["pattern"] if recent else "unknown",
            timestamp=datetime.now().isoformat(),
            trades=trades,
            actual_sharpe=round(actual_sharpe, 4),
            expected_sharpe=round(expected_sharpe, 4),
            deviation=round(deviation, 4),
            direction_accuracy=round(direction_accuracy, 4),
            trigger_evolution=trigger,
        )

    def should_trigger_evolution(self, feedback: ExecutionFeedback) -> bool:
        """判断是否应触发进化"""
        return feedback.trigger_evolution

    def get_all_feedbacks(self) -> List[ExecutionFeedback]:
        """获取所有场景的反馈摘要"""
        return [self.evaluate(sid) for sid in self._records.keys()]

    def get_all_scenario_ids(self) -> List[str]:
        """获取所有有记录的场景ID"""
        return list(self._records.keys())

    def get_stats(self, scenario_id: str) -> Dict[str, Any]:
        """获取单场景统计"""
        records = self._records.get(scenario_id, [])
        if not records:
            return {"total_trades": 0}

        returns = [r.get("result", 0) for r in records if r.get("result") is not None]
        wins = sum(1 for r in returns if r > 0)

        return {
            "total_trades": len(records),
            "win_rate": round(wins / len(returns), 4) if returns else 0,
            "avg_return": round(sum(returns) / len(returns), 4) if returns else 0,
            "total_return": round(sum(returns), 4) if returns else 0,
            "patterns_used": list(set(r.get("pattern", "?") for r in records)),
        }

    def sync_verification_status(self) -> int:
        """P2-1: 根据反馈数据同步场景验证状态

        将有实验反馈数据的场景标记为 verified，
        无反馈数据的场景标记为 unverified。

        Returns:
            标注为 unverified 的场景数量
        """
        if not self.memory:
            return 0

        # 有反馈记录的场景 = 已验证
        verified_ids = set(self._records.keys())
        unverified_count = self.memory.mark_unverified(verified_ids)
        return unverified_count
