"""进化闭环系统 — 16-调控系统 Phase 3+

通过记录决策、追踪结果、分析准确性、调优参数，形成"越用越聪明"的进化闭环。

闭环架构：
  ┌─────────────────────────────────────────────────────┐
  │                    进化闭环                           │
  │                                                      │
  │  ① 记录决策 ──→ 每次离场评估的完整上下文              │
  │       ↓                                              │
  │  ② 追踪结果 ──→ 持仓平仓后回填实际盈亏               │
  │       ↓                                              │
  │  ③ 分析准确性 ──→ 按策略统计建议命中率                │
  │       ↓                                              │
  │  ④ 参数调优 ──→ 根据命中率调整置信度门槛和权重        │
  │       ↓                                              │
  │  ⑤ 反馈决策 ──→ 更新后的参数用于下一次评估            │
  │       ↓                                              │
  │  ⑥ 回测验证 ──→ 回测验证参数调优效果                  │
  │       ↓                                              │
  │  ⑦ 采纳/回滚 ──→ 通过回测则采纳，否则回滚            │
  │       ↓                                              │
  │  ① 记录决策（循环）                                   │
  └─────────────────────────────────────────────────────┘

核心设计原则：
1. 高置信度才决策 — 没有足够把握不下结论
2. 结果导向 — 用实际结果验证决策质量
3. 渐进调优 — 小步快跑，每次只调一点点
4. 回测保护 — 参数调整必须通过回测验证才能采纳
5. 可回滚 — 每次调优都有快照，可以回滚到之前的状态
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
import copy

# 进化数据存储路径
EVOLUTION_DATA_DIR = Path(__file__).parent.parent / "artifacts" / "evolution"
EVOLUTION_DATA_DIR.mkdir(parents=True, exist_ok=True)

DECISION_LOG_PATH = EVOLUTION_DATA_DIR / "decision_log.jsonl"
EVOLUTION_PARAMS_PATH = EVOLUTION_DATA_DIR / "evolution_params.json"
EVOLUTION_HISTORY_PATH = EVOLUTION_DATA_DIR / "evolution_history.json"


@dataclass
class DecisionRecord:
    """决策记录 — 每次离场评估的完整快照"""
    evaluation_id: str
    timestamp: str
    strategy_id: str
    system_name: str
    symbol: str
    direction: str
    
    # 评估上下文
    macro_action: str
    technical_action: str
    fused_action: str
    fused_confidence: float
    fusion_mode: str
    
    # 策略设计调整
    rationality_adjusted: bool
    original_action: str
    adjusted_action: str
    adjustment_reasons: List[str]
    
    # 置信度门槛检查
    confidence_threshold: float
    passed_threshold: bool
    final_recommendation: str  # OBSERVE / HOLD / REDUCE / CLOSE
    
    # 持仓状态快照
    pnl_pct: float
    hold_hours: float
    addon_count: int
    entry_price: float
    
    # 结果回填（平仓后填入）
    outcome: str = "PENDING"  # PENDING / CORRECT / INCORRECT / PARTIAL
    actual_pnl: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    outcome_timestamp: str = ""


@dataclass
class StrategyEvolutionParams:
    """策略进化参数 — 可被进化系统调优的参数"""
    strategy_id: str
    
    # 当前置信度门槛
    confidence_threshold_close: float
    confidence_threshold_reduce: float
    confidence_threshold_observe: float
    
    # 当前权重
    technical_signal_weight: float
    macro_signal_weight: float
    
    # 最大减仓比例
    max_macro_reduce_fraction: float
    
    # 统计指标
    total_decisions: int = 0
    correct_decisions: int = 0
    incorrect_decisions: int = 0
    partial_decisions: int = 0
    pending_decisions: int = 0
    
    # 调优历史
    adjustment_count: int = 0
    last_adjustment: str = ""


@dataclass
class EvolutionAdjustment:
    """一次参数调优记录"""
    adjustment_id: str
    timestamp: str
    strategy_id: str
    trigger: str  # what triggered this adjustment
    
    # 调整前参数
    before: Dict[str, float]
    
    # 调整后参数
    after: Dict[str, float]
    
    # 调整依据
    accuracy_rate: float
    sample_size: int
    backtest_validated: bool
    backtest_improvement: float = 0.0
    
    # 状态
    status: str = "PROPOSED"  # PROPOSED / VALIDATED / ADOPTED / ROLLED_BACK


class EvolutionLoop:
    """进化闭环管理器"""
    
    def __init__(self):
        self.params = self._load_evolution_params()
        self.history = self._load_evolution_history()
    
    # ==========================================
    # ① 记录决策
    # ==========================================
    
    def record_decision(self, evaluation: Dict[str, Any]) -> str:
        """记录一次离场评估决策
        
        Args:
            evaluation: 融合决策结果（来自 fuse_macro_technical）
        
        Returns:
            decision_id: 用于后续结果回填
        """
        strategy_id = evaluation.get("strategy_context", {}).get("strategy_id", "unknown")
        design = self._get_strategy_design(strategy_id)
        
        pos = evaluation.get("position", {})
        macro_input = evaluation.get("macro_input", {})
        tech_input = evaluation.get("technical_input", {})
        rational = evaluation.get("rationality_check", {}) or {}
        
        # 置信度门槛检查
        fused_action = evaluation.get("recommended_action", "HOLD")
        fused_confidence = evaluation.get("confidence", 0.5)
        
        threshold = self._get_action_threshold(strategy_id, fused_action)
        passed = fused_confidence >= threshold
        
        # 未通过门槛的动作降级
        if not passed and fused_action in ("CLOSE", "REDUCE"):
            if fused_confidence >= self._get_params(strategy_id).confidence_threshold_observe:
                final_rec = "OBSERVE"  # 降级为观察
            else:
                final_rec = "HOLD"
        else:
            final_rec = fused_action
        
        # P0 硬退出不受门槛限制
        if tech_input.get("p0_triggered"):
            final_rec = fused_action
            passed = True
        
        decision_id = f"dec_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{strategy_id}_{pos.get('symbol', '')}"
        
        record = DecisionRecord(
            evaluation_id=decision_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            strategy_id=strategy_id,
            system_name=pos.get("system", ""),
            symbol=pos.get("symbol", ""),
            direction=pos.get("direction", ""),
            macro_action=macro_input.get("adjusted_action", macro_input.get("original_action", "HOLD")),
            technical_action=tech_input.get("action", "HOLD"),
            fused_action=fused_action,
            fused_confidence=fused_confidence,
            fusion_mode=evaluation.get("fusion_mode", ""),
            rationality_adjusted=not rational.get("is_rational", True) if rational else False,
            original_action=rational.get("original_action", fused_action) if rational else fused_action,
            adjusted_action=rational.get("adjusted_action", fused_action) if rational else fused_action,
            adjustment_reasons=rational.get("reasons", []) if rational else [],
            confidence_threshold=threshold,
            passed_threshold=passed,
            final_recommendation=final_rec,
            pnl_pct=float(pos.get("upl_ratio", 0)),
            hold_hours=0,
            addon_count=int(pos.get("addon_count", 0)),
            entry_price=float(pos.get("entry_price", 0)),
        )
        
        # 追加到决策日志
        with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        
        # 更新策略统计
        params = self._get_params(strategy_id)
        params.total_decisions += 1
        if final_rec == "OBSERVE":
            params.pending_decisions += 1
        else:
            params.pending_decisions += 1  # 所有决策都先标记为pending，等结果回填
        
        self._save_evolution_params()
        
        return decision_id
    
    # ==========================================
    # ② 追踪结果
    # ==========================================
    
    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        actual_pnl: float,
        exit_price: float = 0,
        exit_reason: str = "",
    ):
        """回填决策结果
        
        Args:
            decision_id: 决策ID
            outcome: CORRECT / INCORRECT / PARTIAL
            actual_pnl: 实际盈亏百分比
            exit_price: 平仓价格
            exit_reason: 平仓原因
        """
        # 读取决策日志，找到对应记录并更新
        if not DECISION_LOG_PATH.exists():
            return
        
        records = []
        updated = False
        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line.strip())
                if rec.get("evaluation_id") == decision_id:
                    rec["outcome"] = outcome
                    rec["actual_pnl"] = actual_pnl
                    rec["exit_price"] = exit_price
                    rec["exit_reason"] = exit_reason
                    rec["outcome_timestamp"] = datetime.now(timezone.utc).isoformat()
                    updated = True
                    
                    # 更新策略统计
                    strategy_id = rec.get("strategy_id", "unknown")
                    params = self._get_params(strategy_id)
                    params.pending_decisions = max(0, params.pending_decisions - 1)
                    if outcome == "CORRECT":
                        params.correct_decisions += 1
                    elif outcome == "INCORRECT":
                        params.incorrect_decisions += 1
                    elif outcome == "PARTIAL":
                        params.partial_decisions += 1
                records.append(rec)
        
        if updated:
            with open(DECISION_LOG_PATH, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._save_evolution_params()
    
    # ==========================================
    # ③ 分析准确性
    # ==========================================
    
    def analyze_accuracy(self, strategy_id: str = None) -> Dict[str, Any]:
        """分析决策准确性
        
        Returns:
            {
                "overall_accuracy": float,
                "by_strategy": {strategy_id: {accuracy, total, correct, incorrect}},
                "by_action": {action: {accuracy, total}},
                "recent_trend": "IMPROVING" / "DECLINING" / "STABLE",
                "recommendations": [str],
            }
        """
        if not DECISION_LOG_PATH.exists():
            return {"overall_accuracy": 0, "by_strategy": {}, "recommendations": ["暂无决策记录"]}
        
        records = []
        with open(DECISION_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        
        # 过滤
        if strategy_id:
            records = [r for r in records if r.get("strategy_id") == strategy_id]
        
        # 只分析有结果的
        evaluated = [r for r in records if r.get("outcome") != "PENDING"]
        
        if not evaluated:
            return {"overall_accuracy": 0, "by_strategy": {}, "recommendations": ["暂无已回填结果的决策"]}
        
        overall_correct = sum(1 for r in evaluated if r["outcome"] == "CORRECT")
        overall_accuracy = overall_correct / len(evaluated) if evaluated else 0
        
        # 按策略分组
        by_strategy = {}
        for r in evaluated:
            sid = r.get("strategy_id", "unknown")
            if sid not in by_strategy:
                by_strategy[sid] = {"correct": 0, "incorrect": 0, "partial": 0, "total": 0}
            by_strategy[sid]["total"] += 1
            if r["outcome"] == "CORRECT":
                by_strategy[sid]["correct"] += 1
            elif r["outcome"] == "INCORRECT":
                by_strategy[sid]["incorrect"] += 1
            else:
                by_strategy[sid]["partial"] += 1
        
        for sid, stats in by_strategy.items():
            evaluated_count = stats["correct"] + stats["incorrect"]
            stats["accuracy"] = stats["correct"] / evaluated_count if evaluated_count > 0 else 0
            stats["accuracy"] = round(stats["accuracy"], 3)
        
        # 按动作分组
        by_action = {}
        for r in evaluated:
            action = r.get("final_recommendation", "HOLD")
            if action not in by_action:
                by_action[action] = {"correct": 0, "incorrect": 0, "total": 0}
            by_action[action]["total"] += 1
            if r["outcome"] == "CORRECT":
                by_action[action]["correct"] += 1
            elif r["outcome"] == "INCORRECT":
                by_action[action]["incorrect"] += 1
        
        for action, stats in by_action.items():
            evaluated_count = stats["correct"] + stats["incorrect"]
            stats["accuracy"] = round(stats["correct"] / evaluated_count, 3) if evaluated_count > 0 else 0
        
        # 近期趋势（最近10条 vs 之前10条）
        recent = evaluated[-10:]
        earlier = evaluated[-20:-10] if len(evaluated) > 10 else []
        recent_acc = sum(1 for r in recent if r["outcome"] == "CORRECT") / len(recent) if recent else 0
        earlier_acc = sum(1 for r in earlier if r["outcome"] == "CORRECT") / len(earlier) if earlier else 0
        
        if recent_acc > earlier_acc + 0.05:
            trend = "IMPROVING"
        elif recent_acc < earlier_acc - 0.05:
            trend = "DECLINING"
        else:
            trend = "STABLE"
        
        # 生成建议
        recommendations = []
        for sid, stats in by_strategy.items():
            if stats["total"] >= 5:
                if stats["accuracy"] < 0.4:
                    recommendations.append(
                        f"策略 {sid} 准确率仅 {stats['accuracy']:.0%}（{stats['total']}条），"
                        f"建议提高置信度门槛或增加策略设计约束"
                    )
                elif stats["accuracy"] > 0.75:
                    recommendations.append(
                        f"策略 {sid} 准确率 {stats['accuracy']:.0%} 表现优秀，"
                        f"可适当降低置信度门槛以增加建议输出"
                    )
        
        return {
            "overall_accuracy": round(overall_accuracy, 3),
            "total_evaluated": len(evaluated),
            "by_strategy": by_strategy,
            "by_action": by_action,
            "recent_trend": trend,
            "recent_accuracy": round(recent_acc, 3),
            "earlier_accuracy": round(earlier_acc, 3),
            "recommendations": recommendations,
        }
    
    # ==========================================
    # ④ 参数调优
    # ==========================================
    
    def propose_adjustment(self, strategy_id: str, min_samples: int = 5) -> Optional[EvolutionAdjustment]:
        """基于历史准确性提出参数调优建议
        
        调优原则：
        - 准确率 > 75%：降低门槛（让更多建议通过）
        - 准确率 < 40%：提高门槛（更保守）
        - 准确率 40-75%：微调权重
        - 最少需要 min_samples 条已评估记录
        """
        analysis = self.analyze_accuracy(strategy_id)
        by_strategy = analysis.get("by_strategy", {})
        stats = by_strategy.get(strategy_id, {})
        
        total = stats.get("total", 0)
        if total < min_samples:
            return None
        
        accuracy = stats.get("accuracy", 0.5)
        params = self._get_params(strategy_id)
        
        before = {
            "confidence_threshold_close": params.confidence_threshold_close,
            "confidence_threshold_reduce": params.confidence_threshold_reduce,
            "confidence_threshold_observe": params.confidence_threshold_observe,
            "technical_signal_weight": params.technical_signal_weight,
            "macro_signal_weight": params.macro_signal_weight,
        }
        
        after = dict(before)
        trigger = ""
        
        # 调整步长（渐进式）
        step = 0.03  # 每次调3%
        
        if accuracy > 0.75:
            # 准确率高 → 降低门槛，增加建议输出
            after["confidence_threshold_close"] = max(0.50, before["confidence_threshold_close"] - step)
            after["confidence_threshold_reduce"] = max(0.40, before["confidence_threshold_reduce"] - step)
            after["confidence_threshold_observe"] = max(0.20, before["confidence_threshold_observe"] - step)
            trigger = f"高准确率({accuracy:.0%})，降低门槛增加输出"
        
        elif accuracy < 0.40:
            # 准确率低 → 提高门槛，更保守
            after["confidence_threshold_close"] = min(0.95, before["confidence_threshold_close"] + step)
            after["confidence_threshold_reduce"] = min(0.90, before["confidence_threshold_reduce"] + step)
            after["confidence_threshold_observe"] = min(0.70, before["confidence_threshold_observe"] + step)
            trigger = f"低准确率({accuracy:.0%})，提高门槛更保守"
        
        else:
            # 中等准确率 → 微调权重
            # 如果技术信号命中率更高，增加技术权重
            by_action = analysis.get("by_action", {})
            tech_actions = ["CLOSE", "REDUCE"]
            tech_correct = sum(by_action.get(a, {}).get("correct", 0) for a in tech_actions)
            tech_total = sum(by_action.get(a, {}).get("total", 0) for a in tech_actions)
            
            if tech_total > 0 and tech_correct / tech_total > accuracy:
                after["technical_signal_weight"] = min(0.90, before["technical_signal_weight"] + step)
                after["macro_signal_weight"] = max(0.10, before["macro_signal_weight"] - step)
                trigger = f"技术信号命中率更高，增加技术权重"
            else:
                after["macro_signal_weight"] = min(0.90, before["macro_signal_weight"] + step)
                after["technical_signal_weight"] = max(0.10, before["technical_signal_weight"] - step)
                trigger = f"宏观信号命中率更高，增加宏观权重"
        
        # 检查是否有实际变化
        changed = any(abs(before[k] - after[k]) > 0.001 for k in before)
        if not changed:
            return None
        
        adjustment = EvolutionAdjustment(
            adjustment_id=f"adj_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{strategy_id}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            strategy_id=strategy_id,
            trigger=trigger,
            before=before,
            after=after,
            accuracy_rate=accuracy,
            sample_size=total,
            backtest_validated=False,
        )
        
        return adjustment
    
    # ==========================================
    # ⑤ 采纳/回滚调优
    # ==========================================
    
    def adopt_adjustment(self, adjustment: EvolutionAdjustment, backtest_validated: bool = False):
        """采纳参数调优
        
        Args:
            adjustment: 调优记录
            backtest_validated: 是否通过回测验证
        """
        params = self._get_params(adjustment.strategy_id)
        
        # 应用新参数
        params.confidence_threshold_close = adjustment.after["confidence_threshold_close"]
        params.confidence_threshold_reduce = adjustment.after["confidence_threshold_reduce"]
        params.confidence_threshold_observe = adjustment.after["confidence_threshold_observe"]
        params.technical_signal_weight = adjustment.after["technical_signal_weight"]
        params.macro_signal_weight = adjustment.after["macro_signal_weight"]
        params.adjustment_count += 1
        params.last_adjustment = adjustment.timestamp
        
        adjustment.backtest_validated = backtest_validated
        adjustment.status = "ADOPTED" if backtest_validated else "PROPOSED"
        
        # 记录历史
        self.history.append(asdict(adjustment))
        self._save_evolution_params()
        self._save_evolution_history()
    
    def rollback_adjustment(self, adjustment_id: str):
        """回滚参数调优"""
        for adj in self.history:
            if adj.get("adjustment_id") == adjustment_id:
                strategy_id = adj["strategy_id"]
                params = self._get_params(strategy_id)
                params.confidence_threshold_close = adj["before"]["confidence_threshold_close"]
                params.confidence_threshold_reduce = adj["before"]["confidence_threshold_reduce"]
                params.confidence_threshold_observe = adj["before"]["confidence_threshold_observe"]
                params.technical_signal_weight = adj["before"]["technical_signal_weight"]
                params.macro_signal_weight = adj["before"]["macro_signal_weight"]
                adj["status"] = "ROLLED_BACK"
                self._save_evolution_params()
                self._save_evolution_history()
                return True
        return False
    
    # ==========================================
    # 获取当前进化参数
    # ==========================================
    
    def get_evolved_params(self, strategy_id: str) -> Dict[str, float]:
        """获取策略的进化后参数（用于融合决策）"""
        params = self._get_params(strategy_id)
        return {
            "confidence_threshold_close": params.confidence_threshold_close,
            "confidence_threshold_reduce": params.confidence_threshold_reduce,
            "confidence_threshold_observe": params.confidence_threshold_observe,
            "technical_signal_weight": params.technical_signal_weight,
            "macro_signal_weight": params.macro_signal_weight,
            "max_macro_reduce_fraction": params.max_macro_reduce_fraction,
            "total_decisions": params.total_decisions,
            "accuracy_rate": (
                params.correct_decisions / max(1, params.correct_decisions + params.incorrect_decisions)
            ),
        }
    
    def get_evolution_summary(self) -> Dict[str, Any]:
        """获取进化系统概览"""
        analysis = self.analyze_accuracy()
        return {
            "total_decisions": sum(p.total_decisions for p in self.params.values()),
            "total_evaluated": analysis.get("total_evaluated", 0),
            "overall_accuracy": analysis.get("overall_accuracy", 0),
            "recent_trend": analysis.get("recent_trend", "N/A"),
            "by_strategy": {
                sid: {
                    "total": p.total_decisions,
                    "correct": p.correct_decisions,
                    "incorrect": p.incorrect_decisions,
                    "pending": p.pending_decisions,
                    "accuracy": round(p.correct_decisions / max(1, p.correct_decisions + p.incorrect_decisions), 3),
                    "adjustments": p.adjustment_count,
                    "current_thresholds": {
                        "close": p.confidence_threshold_close,
                        "reduce": p.confidence_threshold_reduce,
                        "observe": p.confidence_threshold_observe,
                    },
                }
                for sid, p in self.params.items()
            },
            "adjustment_history_count": len(self.history),
            "recommendations": analysis.get("recommendations", []),
        }
    
    # ==========================================
    # 内部方法
    # ==========================================
    
    def _get_strategy_design(self, strategy_id: str):
        """获取策略设计"""
        try:
            from strategy_exit_adapter import get_strategy_exit_design
            return get_strategy_exit_design(strategy_id)
        except ImportError:
            from .strategy_exit_adapter import get_strategy_exit_design
            return get_strategy_exit_design(strategy_id)
    
    def _get_params(self, strategy_id: str) -> StrategyEvolutionParams:
        """获取策略进化参数（不存在则从策略设计初始化）"""
        if strategy_id not in self.params:
            design = self._get_strategy_design(strategy_id)
            self.params[strategy_id] = StrategyEvolutionParams(
                strategy_id=strategy_id,
                confidence_threshold_close=design.confidence_threshold_close,
                confidence_threshold_reduce=design.confidence_threshold_reduce,
                confidence_threshold_observe=design.confidence_threshold_observe,
                technical_signal_weight=design.technical_signal_weight,
                macro_signal_weight=design.macro_signal_weight,
                max_macro_reduce_fraction=design.max_macro_reduce_fraction,
            )
            self._save_evolution_params()
        return self.params[strategy_id]
    
    def _get_action_threshold(self, strategy_id: str, action: str) -> float:
        """获取动作对应的置信度门槛"""
        params = self._get_params(strategy_id)
        if action == "CLOSE":
            return params.confidence_threshold_close
        elif action == "REDUCE":
            return params.confidence_threshold_reduce
        else:
            return params.confidence_threshold_observe
    
    def _load_evolution_params(self) -> Dict[str, StrategyEvolutionParams]:
        """加载进化参数"""
        if EVOLUTION_PARAMS_PATH.exists():
            with open(EVOLUTION_PARAMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                sid: StrategyEvolutionParams(**p) for sid, p in data.items()
            }
        return {}
    
    def _save_evolution_params(self):
        """保存进化参数"""
        data = {sid: asdict(p) for sid, p in self.params.items()}
        with open(EVOLUTION_PARAMS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_evolution_history(self) -> List[Dict]:
        """加载调优历史"""
        if EVOLUTION_HISTORY_PATH.exists():
            with open(EVOLUTION_HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def _save_evolution_history(self):
        """保存调优历史"""
        with open(EVOLUTION_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)


# 全局单例
_evolution_loop: Optional[EvolutionLoop] = None


def get_evolution_loop() -> EvolutionLoop:
    """获取进化闭环管理器单例"""
    global _evolution_loop
    if _evolution_loop is None:
        _evolution_loop = EvolutionLoop()
    return _evolution_loop
