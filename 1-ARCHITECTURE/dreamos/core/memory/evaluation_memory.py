"""
Dream OS 评估记忆系统 (EvaluationMemory)

**核心设计理念**:
    参考人类记忆模型（短期→中期→长期→元记忆）和 Hermes 的轨迹保存机制，
    构建 Dream OS 交易系统的"评估记忆"，让系统越用越聪明，编排越来越合理。

**四层记忆架构**:
    L0 短期记忆 (Short-term)   - 最近 N 笔交易的即时反馈，快速响应
    L1 中期记忆 (Mid-term)     - 场景-编排映射、模块能力评估，持续优化
    L2 长期记忆 (Long-term)    - 经验教训、失败模式、最佳实践，知识沉淀
    L3 元记忆 (Meta)           - 关于学习的记忆，自适应优化评估策略

**核心机制**:
    1. 记忆巩固：短期→中期→长期，需要足够证据支持
    2. 遗忘曲线：旧记忆按时间衰减，新记忆权重更高
    3. 知识迁移：相似场景之间的经验可以复用
    4. 教训晋升：经验教训验证后从候选晋升为正式
    5. 元学习：学习"什么评估方法有效"，自适应调整策略

**记忆生命周期**:
    交易执行 → L0短期记忆 → 评估回测 → L1中期记忆 → 经验提炼 → L2长期记忆
                                              ↓
                                          L3元记忆（优化评估策略）
"""

from __future__ import annotations

import json
import os
import logging
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# 数据类型定义
# ============================================================

@dataclass
class ShortTermMemory:
    """L0 短期记忆 - 最近交易的即时反馈"""
    recent_trades: List[Dict[str, Any]] = field(default_factory=list)
    max_size: int = 100

    def add_trade(self, trade: Dict[str, Any]) -> None:
        self.recent_trades.append(trade)
        if len(self.recent_trades) > self.max_size:
            self.recent_trades = self.recent_trades[-self.max_size:]

    def get_recent(self, n: int = 10) -> List[Dict[str, Any]]:
        return self.recent_trades[-n:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recent_trades": self.recent_trades,
            "max_size": self.max_size,
        }


@dataclass
class ModuleCapabilityMemory:
    """模块能力记忆 - L1中期记忆的一部分"""
    module_id: str
    module_name: str
    total_trades: int = 0
    weighted_win_rate: float = 0.5
    weighted_sharpe: float = 0.0
    weighted_profit_factor: float = 1.0
    scenario_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)
    last_updated: str = ""
    confidence: float = 0.0
    trend: str = "stable"  # improving / declining / stable

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioOrchestrationMemory:
    """场景编排记忆 - L1中期记忆的一部分"""
    scenario_id: str
    best_pattern: str
    best_nodes: List[str]
    score: float
    sample_count: int
    confidence: str
    metrics: Dict[str, float] = field(default_factory=dict)
    pattern_history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: str = ""
    inferred: bool = False
    inferred_from: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LessonMemory:
    """L2 长期记忆 - 经验教训"""
    lesson_id: str
    title: str
    description: str
    category: str  # strategy / risk / execution / market / module
    severity: str  # low / medium / high / critical
    action_suggestion: str = ""
    evidence_count: int = 0
    verification_count: int = 0
    confidence: float = 0.0
    status: str = "candidate"  # candidate / verified / deprecated
    learned_at: str = ""
    last_verified_at: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    related_scenarios: List[str] = field(default_factory=list)
    related_modules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetaMemory:
    """L3 元记忆 - 关于学习的记忆"""
    evaluation_strategies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    trigger_effectiveness: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    learning_curve: List[Dict[str, Any]] = field(default_factory=list)
    best_practices: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvaluationMemory:
    """评估记忆系统 - Dream OS 的"学习大脑"

    **四层记忆架构**:
        L0: 短期记忆 - 最近N笔交易，快速响应
        L1: 中期记忆 - 模块能力、场景编排，持续优化
        L2: 长期记忆 - 经验教训、失败模式，知识沉淀
        L3: 元记忆   - 自适应优化评估策略

    **用法**:
        memory = EvaluationMemory()
        memory.load()

        # 记录交易
        memory.record_trade(trade_data)

        # 从评估结果学习
        memory.learn_from_evaluation(evaluation_report)

        # 获取最优编排
        best = memory.get_best_orchestration("BULL_NORMAL_ACCELERATING")

        # 获取经验教训
        lessons = memory.get_lessons(category="risk", min_confidence=0.7)
    """

    # 遗忘曲线参数（半衰期，单位：天）
    FORGETTING_HALF_LIFE = 30

    # 记忆晋升阈值
    LESSON_VERIFICATION_THRESHOLD = 5  # 验证N次后晋升为verified

    # 权重衰减因子
    RECENT_WEIGHT = 0.6  # 近期数据权重
    HISTORICAL_WEIGHT = 0.4  # 历史数据权重

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._default_path()
        self._data = self._empty_structure()

        self.short_term = ShortTermMemory()
        self.module_capabilities: Dict[str, ModuleCapabilityMemory] = {}
        self.scenario_orchestrations: Dict[str, ScenarioOrchestrationMemory] = {}
        self.lessons: Dict[str, LessonMemory] = {}
        self.meta = MetaMemory()

    def _default_path(self) -> str:
        return str(Path(__file__).parent / "evaluation_memory.json")

    def _empty_structure(self) -> Dict[str, Any]:
        return {
            "version": "2.0.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": None,
            "total_evaluations": 0,
            "total_trades_recorded": 0,
            "memory_levels": {
                "short_term": {},
                "mid_term": {
                    "module_capabilities": {},
                    "scenario_orchestrations": {},
                },
                "long_term": {
                    "lessons": {},
                },
                "meta": {},
            },
        }

    # ── 持久化 ──────────────────────────────────────────────

    def load(self) -> bool:
        """加载记忆数据"""
        if not os.path.exists(self.path):
            logger.info(f"评估记忆文件不存在: {self.path}，使用空记忆")
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            levels = self._data.get("memory_levels", {})

            # L0: 短期记忆
            st = levels.get("short_term", {})
            self.short_term = ShortTermMemory(
                recent_trades=st.get("recent_trades", []),
                max_size=st.get("max_size", 100),
            )

            # L1: 中期记忆 - 模块能力
            mc = levels.get("mid_term", {}).get("module_capabilities", {})
            for mid, data in mc.items():
                self.module_capabilities[mid] = ModuleCapabilityMemory(**data)

            # L1: 中期记忆 - 场景编排
            so = levels.get("mid_term", {}).get("scenario_orchestrations", {})
            for sid, data in so.items():
                self.scenario_orchestrations[sid] = ScenarioOrchestrationMemory(**data)

            # L2: 长期记忆 - 经验教训
            lessons = levels.get("long_term", {}).get("lessons", {})
            for lid, data in lessons.items():
                self.lessons[lid] = LessonMemory(**data)

            # L3: 元记忆
            meta_data = levels.get("meta", {})
            if meta_data:
                self.meta = MetaMemory(
                    evaluation_strategies=meta_data.get("evaluation_strategies", {}),
                    trigger_effectiveness=meta_data.get("trigger_effectiveness", {}),
                    learning_curve=meta_data.get("learning_curve", []),
                    best_practices=meta_data.get("best_practices", []),
                )

            logger.info(
                f"评估记忆已加载: "
                f"{len(self.module_capabilities)} 模块, "
                f"{len(self.scenario_orchestrations)} 场景, "
                f"{len(self.lessons)} 教训"
            )
            return True

        except Exception as e:
            logger.warning(f"加载评估记忆失败: {e}，使用空记忆")
            return False

    def save(self) -> None:
        """保存记忆数据"""
        self._data["last_updated"] = datetime.now().isoformat()
        self._data["memory_levels"] = {
            "short_term": self.short_term.to_dict(),
            "mid_term": {
                "module_capabilities": {
                    mid: mem.to_dict()
                    for mid, mem in self.module_capabilities.items()
                },
                "scenario_orchestrations": {
                    sid: mem.to_dict()
                    for sid, mem in self.scenario_orchestrations.items()
                },
            },
            "long_term": {
                "lessons": {
                    lid: lesson.to_dict()
                    for lid, lesson in self.lessons.items()
                },
            },
            "meta": self.meta.to_dict(),
        }

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

        logger.info(
            f"评估记忆已保存: "
            f"{len(self.module_capabilities)} 模块, "
            f"{len(self.scenario_orchestrations)} 场景, "
            f"{len(self.lessons)} 教训"
        )

    # ── L0: 短期记忆 ───────────────────────────────────────

    def record_trade(self, trade: Dict[str, Any]) -> None:
        """记录一笔交易到短期记忆"""
        self.short_term.add_trade(trade)
        self._data["total_trades_recorded"] += 1

    def get_recent_trades(self, n: int = 10) -> List[Dict[str, Any]]:
        """获取最近N笔交易"""
        return self.short_term.get_recent(n)

    # ── L1: 中期记忆 ───────────────────────────────────────

    def learn_from_evaluation(self, evaluation_report: Dict[str, Any]) -> Dict[str, Any]:
        """从评估报告中学习，更新中期记忆

        Args:
            evaluation_report: 评估报告字典

        Returns:
            学习摘要
        """
        self._data["total_evaluations"] += 1
        now = datetime.now().isoformat()

        # 1. 更新模块能力记忆
        module_updates = self._update_module_capabilities(
            evaluation_report.get("module_capabilities", {})
        )

        # 2. 更新场景编排记忆
        scenario_updates = self._update_scenario_orchestrations(
            evaluation_report.get("orchestration_recommendations", {})
        )

        # 3. 提取经验教训（L2）
        new_lessons = self._extract_lessons(evaluation_report)

        # 4. 更新元记忆（L3）
        self._update_meta_memory(evaluation_report, {
            "module_updates": len(module_updates),
            "scenario_updates": len(scenario_updates),
            "new_lessons": len(new_lessons),
        })

        # 5. 记录学习曲线
        self._record_learning_curve(evaluation_report)

        summary = {
            "modules_updated": module_updates,
            "scenarios_updated": scenario_updates,
            "new_lessons": new_lessons,
            "total_evaluations": self._data["total_evaluations"],
        }

        logger.info(
            f"评估学习完成: "
            f"{len(module_updates)} 模块更新, "
            f"{len(scenario_updates)} 场景更新, "
            f"{len(new_lessons)} 新教训"
        )

        return summary

    def _update_module_capabilities(self, new_capabilities: Dict[str, Any]) -> List[str]:
        """更新模块能力记忆（带遗忘曲线的加权平均）"""
        updated = []
        now = datetime.now().isoformat()

        for mid, cap_data in new_capabilities.items():
            if mid not in self.module_capabilities:
                # 新模块，直接初始化
                self.module_capabilities[mid] = ModuleCapabilityMemory(
                    module_id=mid,
                    module_name=cap_data.get("module_name", mid),
                    total_trades=cap_data.get("total_trades", 0),
                    weighted_win_rate=cap_data.get("success_rate", 0.5),
                    weighted_sharpe=cap_data.get("avg_pnl", 0),
                    weighted_profit_factor=cap_data.get("profit_factor", 1.0),
                    scenario_performance=cap_data.get("scenario_performance", {}),
                    last_updated=now,
                    confidence=min(1.0, cap_data.get("total_trades", 0) / 50),
                    trend="stable",
                )
            else:
                # 已有模块，加权更新（遗忘曲线）
                existing = self.module_capabilities[mid]
                new_trades = cap_data.get("total_trades", 0)
                total_trades = existing.total_trades + new_trades

                # 计算时间衰减因子
                decay_factor = self._calculate_decay_factor(existing.last_updated)

                # 加权更新
                old_weight = self.HISTORICAL_WEIGHT * decay_factor
                new_weight = self.RECENT_WEIGHT

                total_weight = old_weight + new_weight

                old_win_rate = existing.weighted_win_rate
                new_win_rate = cap_data.get("success_rate", 0.5)
                updated_win_rate = (old_win_rate * old_weight + new_win_rate * new_weight) / total_weight

                # 判断趋势
                if updated_win_rate > old_win_rate + 0.02:
                    trend = "improving"
                elif updated_win_rate < old_win_rate - 0.02:
                    trend = "declining"
                else:
                    trend = "stable"

                existing.weighted_win_rate = round(updated_win_rate, 4)
                existing.total_trades = total_trades
                existing.weighted_sharpe = round(cap_data.get("avg_pnl", 0), 4)
                existing.weighted_profit_factor = round(cap_data.get("profit_factor", 1.0), 4)
                existing.last_updated = now
                existing.confidence = round(min(1.0, total_trades / 100), 4)
                existing.trend = trend

                # 更新场景表现
                for scenario, perf in cap_data.get("scenario_performance", {}).items():
                    if scenario not in existing.scenario_performance:
                        existing.scenario_performance[scenario] = perf
                    else:
                        old_p = existing.scenario_performance[scenario]
                        old_p["win_rate"] = round(
                            (old_p.get("win_rate", 0.5) * old_weight +
                             perf.get("win_rate", 0.5) * new_weight) / total_weight,
                            4
                        )

            updated.append(mid)

        return updated

    def _update_scenario_orchestrations(self, recommendations: Dict[str, Any]) -> List[str]:
        """更新场景编排记忆"""
        updated = []
        now = datetime.now().isoformat()

        for scenario, rec in recommendations.items():
            new_score = rec.get("confidence", 0)
            new_pattern = rec.get("recommended_chain", "")
            new_nodes = rec.get("recommended_nodes", [])

            if scenario not in self.scenario_orchestrations:
                # 新场景
                self.scenario_orchestrations[scenario] = ScenarioOrchestrationMemory(
                    scenario_id=scenario,
                    best_pattern=new_pattern,
                    best_nodes=new_nodes,
                    score=new_score,
                    sample_count=10,
                    confidence="high" if new_score > 0.7 else "medium" if new_score > 0.5 else "low",
                    metrics=rec.get("evidence", {}).get("metrics", {}),
                    pattern_history=[{
                        "pattern": new_pattern,
                        "nodes": new_nodes,
                        "score": new_score,
                        "timestamp": now,
                    }],
                    last_updated=now,
                    inferred=rec.get("evidence", {}).get("memory_best_pattern", "") == "",
                    inferred_from=rec.get("evidence", {}).get("memory_best_pattern", None),
                )
            else:
                existing = self.scenario_orchestrations[scenario]

                # 如果新评分显著更好（>5%提升），更新
                if new_score > existing.score * 1.05:
                    # 记录历史
                    existing.pattern_history.append({
                        "pattern": existing.best_pattern,
                        "nodes": existing.best_nodes,
                        "score": existing.score,
                        "timestamp": existing.last_updated,
                    })
                    if len(existing.pattern_history) > 10:
                        existing.pattern_history = existing.pattern_history[-10:]

                    existing.best_pattern = new_pattern
                    existing.best_nodes = new_nodes
                    existing.score = round(new_score, 4)
                    existing.confidence = "high" if new_score > 0.7 else "medium" if new_score > 0.5 else "low"
                    existing.last_updated = now
                    existing.sample_count = min(100, existing.sample_count + 10)
                    existing.metrics = rec.get("evidence", {}).get("metrics", existing.metrics)

            updated.append(scenario)

        return updated

    def _calculate_decay_factor(self, last_updated_str: str) -> float:
        """计算遗忘曲线衰减因子"""
        if not last_updated_str:
            return 0.5

        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            days_passed = (datetime.now() - last_updated).total_seconds() / 86400
            # 指数衰减：半衰期30天
            decay = 0.5 ** (days_passed / self.FORGETTING_HALF_LIFE)
            return max(0.1, decay)
        except Exception:
            return 0.5

    # ── L2: 长期记忆 ───────────────────────────────────────

    def _extract_lessons(self, evaluation_report: Dict[str, Any]) -> List[str]:
        """从评估报告中提取经验教训"""
        new_lessons = []
        now = datetime.now().isoformat()

        # 1. 从亏损原因分布中提取教训
        loss_reasons = evaluation_report.get("loss_reason_distribution", {})
        total_trades = evaluation_report.get("analyzed_trades", 0)

        for reason, count in loss_reasons.items():
            if total_trades == 0:
                continue
            ratio = count / total_trades

            # 高频亏损原因 → 教训
            if ratio > 0.1 and count >= 3:
                lesson_id = f"lesson_loss_{reason.lower()}"
                title, description, suggestion = self._get_lesson_content(reason)

                if lesson_id not in self.lessons:
                    self.lessons[lesson_id] = LessonMemory(
                        lesson_id=lesson_id,
                        title=title,
                        description=description,
                        category="risk" if reason in ("STOP_LOSS", "TAKE_PROFIT") else "strategy",
                        severity="high" if ratio > 0.3 else "medium" if ratio > 0.2 else "low",
                        action_suggestion=suggestion,
                        evidence_count=count,
                        verification_count=0,
                        confidence=round(min(0.9, ratio * 2), 3),
                        status="candidate",
                        learned_at=now,
                        context={"loss_reason": reason, "frequency": ratio},
                        related_modules=self._get_related_modules(reason),
                    )
                    new_lessons.append(lesson_id)
                else:
                    # 更新已有教训
                    lesson = self.lessons[lesson_id]
                    lesson.evidence_count += count
                    lesson.confidence = round(min(0.95, lesson.confidence + ratio * 0.1), 3)

                    # 验证次数足够 → 晋升为 verified
                    if (lesson.status == "candidate" and
                            lesson.evidence_count >= self.LESSON_VERIFICATION_THRESHOLD):
                        lesson.status = "verified"
                        lesson.last_verified_at = now
                        logger.info(f"教训晋升为 verified: {lesson_id}")

        # 2. 从模块能力中提取教训
        module_caps = evaluation_report.get("module_capabilities", {})
        for mid, cap in module_caps.items():
            success_rate = cap.get("success_rate", 0.5)
            if success_rate < 0.4 and cap.get("total_trades", 0) >= 10:
                lesson_id = f"lesson_module_low_win_{mid}"
                if lesson_id not in self.lessons:
                    self.lessons[lesson_id] = LessonMemory(
                        lesson_id=lesson_id,
                        title=f"模块 {mid} 胜率偏低",
                        description=f"{cap.get('module_name', mid)} 模块胜率仅 {success_rate*100:.1f}%，低于40%阈值",
                        category="module",
                        severity="medium",
                        action_suggestion=f"建议检查 {mid} 模块逻辑，或考虑替换/降级使用",
                        evidence_count=cap.get("total_trades", 0),
                        confidence=0.6,
                        status="candidate",
                        learned_at=now,
                        related_modules=[mid],
                    )
                    new_lessons.append(lesson_id)

        return new_lessons

    def _get_lesson_content(self, reason: str) -> Tuple[str, str, str]:
        """根据亏损原因获取教训内容"""
        lessons_map = {
            "ENTRY_SIGNAL": (
                "入场信号质量不足",
                "入场信号置信度偏低，导致大量亏损交易",
                "建议提高 A4 门禁阈值，或优化 C1/C2 入场信号生成逻辑"
            ),
            "EXIT_SIGNAL": (
                "离场信号质量问题",
                "离场时机把握不好，导致盈利回吐或亏损扩大",
                "建议优化 A9/C5 离场系统，增加动态止损止盈机制"
            ),
            "TREND_FILTER": (
                "趋势过滤失效",
                "在震荡市场中趋势判断错误",
                "建议优化 A0 矛盾分析，增加趋势确认机制，震荡市减少交易频率"
            ),
            "SIGNAL_QUALITY": (
                "信号质量评估不足",
                "信号强度判断不准确，弱信号也入场",
                "建议优化 A2/A7 信号质量评估，提高信号过滤标准"
            ),
            "MARKET_RECOGNITION": (
                "市场状态识别错误",
                "对当前市场环境判断错误",
                "建议优化 A6 市态监控，增加多维度市场识别指标"
            ),
            "STOP_LOSS": (
                "止损设置不合理",
                "止损触发过于频繁或止损幅度过大",
                "建议优化 A3 止损策略，使用 ATR 动态止损，根据波动率调整"
            ),
            "TAKE_PROFIT": (
                "止盈设置不合理",
                "止盈过早导致盈利不足，或过晚导致回吐",
                "建议优化 A3 止盈策略，使用移动止盈或分批止盈"
            ),
            "VOLATILITY": (
                "波动率估计偏差",
                "对市场波动率估计不准确",
                "建议优化 C3 波动率分析，使用多周期波动率综合判断"
            ),
            "MOMENTUM": (
                "动量判断错误",
                "动量指标判断与实际走势相反",
                "建议优化 C2 动量分析，增加多时间帧动量确认"
            ),
            "CORRELATION": (
                "多资产相关性未考虑",
                "未考虑资产间相关性，导致风险集中",
                "建议增加 F2 资金流分析中的相关性分析"
            ),
        }
        return lessons_map.get(reason, (f"{reason} 问题", f"{reason} 导致亏损", f"优化 {reason} 相关逻辑"))

    def _get_related_modules(self, reason: str) -> List[str]:
        """获取与亏损原因相关的模块"""
        relation_map = {
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
        return relation_map.get(reason, [])

    def get_lessons(self, category: Optional[str] = None,
                    min_confidence: float = 0.0,
                    status: Optional[str] = None,
                    limit: int = 20) -> List[LessonMemory]:
        """获取经验教训

        Args:
            category: 类别过滤
            min_confidence: 最低置信度
            status: 状态过滤 (candidate / verified / deprecated)
            limit: 返回数量上限

        Returns:
            教训列表（按置信度降序）
        """
        lessons = list(self.lessons.values())

        if category:
            lessons = [l for l in lessons if l.category == category]
        if status:
            lessons = [l for l in lessons if l.status == status]
        if min_confidence > 0:
            lessons = [l for l in lessons if l.confidence >= min_confidence]

        lessons.sort(key=lambda l: (-l.confidence, -l.evidence_count))
        return lessons[:limit]

    # ── L3: 元记忆 ─────────────────────────────────────────

    def _update_meta_memory(self, report: Dict[str, Any], learning_stats: Dict[str, Any]) -> None:
        """更新元记忆 - 关于学习的记忆"""
        trigger_type = report.get("trigger_event", {}).get("event_type", "unknown")

        # 记录触发效果
        if trigger_type not in self.meta.trigger_effectiveness:
            self.meta.trigger_effectiveness[trigger_type] = {
                "count": 0,
                "avg_improvement": 0.0,
                "total_improvement": 0.0,
                "last_triggered": "",
            }

        eff = self.meta.trigger_effectiveness[trigger_type]
        eff["count"] += 1
        eff["last_triggered"] = datetime.now().isoformat()

        improvement = learning_stats.get("scenario_updates", 0) * 0.01
        eff["total_improvement"] += improvement
        eff["avg_improvement"] = round(eff["total_improvement"] / eff["count"], 4)

    def _record_learning_curve(self, report: Dict[str, Any]) -> None:
        """记录学习曲线数据点"""
        self.meta.learning_curve.append({
            "timestamp": datetime.now().isoformat(),
            "evaluations": self._data["total_evaluations"],
            "trades": self._data["total_trades_recorded"],
            "verified_lessons": sum(1 for l in self.lessons.values() if l.status == "verified"),
            "high_conf_scenarios": sum(
                1 for s in self.scenario_orchestrations.values()
                if s.confidence == "high"
            ),
        })

        if len(self.meta.learning_curve) > 100:
            self.meta.learning_curve = self.meta.learning_curve[-100:]

    def get_optimal_evaluation_strategy(self) -> Dict[str, Any]:
        """根据元记忆获取最优评估策略

        Returns:
            推荐的评估策略配置
        """
        # 分析各触发器的效果
        trigger_stats = []
        for trigger, data in self.meta.trigger_effectiveness.items():
            if data["count"] >= 2:
                trigger_stats.append((trigger, data["avg_improvement"]))

        trigger_stats.sort(key=lambda x: -x[1])

        # 推荐策略
        strategy = {
            "recommended_triggers": [t for t, _ in trigger_stats[:3]] if trigger_stats else ["scheduled", "loss"],
            "optimal_interval_hours": 24,  # 默认24小时
            "priority_order": [
                "loss", "drawdown", "manual", "market", "threshold", "scheduled"
            ],
        }

        return strategy

    # ── 知识迁移 ────────────────────────────────────────────

    def transfer_knowledge(self, from_scenario: str, to_scenario: str) -> float:
        """在相似场景间迁移知识

        Args:
            from_scenario: 源场景
            to_scenario: 目标场景

        Returns:
            迁移置信度 (0-1)
        """
        source = self.scenario_orchestrations.get(from_scenario)
        if not source or source.confidence == "low":
            return 0.0

        similarity = self._calculate_scenario_similarity(from_scenario, to_scenario)
        if similarity < 0.3:
            return 0.0

        target = self.scenario_orchestrations.get(to_scenario)
        if not target:
            self.scenario_orchestrations[to_scenario] = ScenarioOrchestrationMemory(
                scenario_id=to_scenario,
                best_pattern=source.best_pattern,
                best_nodes=list(source.best_nodes),
                score=round(source.score * similarity, 4),
                sample_count=0,
                confidence="low",
                metrics=dict(source.metrics),
                last_updated=datetime.now().isoformat(),
                inferred=True,
                inferred_from=from_scenario,
            )
        else:
            if target.confidence == "low" and source.confidence in ("medium", "high"):
                target.best_pattern = source.best_pattern
                target.best_nodes = list(source.best_nodes)
                target.score = round(max(target.score, source.score * similarity), 4)
                target.inferred = True
                target.inferred_from = from_scenario
                target.last_updated = datetime.now().isoformat()

        return round(similarity * (0.8 if source.confidence == "high" else 0.5), 4)

    def _calculate_scenario_similarity(self, s1: str, s2: str) -> float:
        """计算两个场景的相似度"""
        p1 = s1.split("_")
        p2 = s2.split("_")

        if len(p1) < 2 or len(p2) < 2:
            return 0.0

        similarity = 0.0

        # 趋势相同 +0.4
        if p1[0] == p2[0]:
            similarity += 0.4

        # 波动率相同 +0.3
        if len(p1) > 1 and len(p2) > 1 and p1[1] == p2[1]:
            similarity += 0.3

        # 动量相同 +0.3
        if len(p1) > 2 and len(p2) > 2 and p1[2] == p2[2]:
            similarity += 0.3

        return similarity

    # ── 查询接口 ────────────────────────────────────────────

    def get_best_orchestration(self, scenario_id: str) -> Optional[ScenarioOrchestrationMemory]:
        """获取指定场景的最优编排"""
        return self.scenario_orchestrations.get(scenario_id)

    def get_module_capability(self, module_id: str) -> Optional[ModuleCapabilityMemory]:
        """获取指定模块的能力评估"""
        return self.module_capabilities.get(module_id)

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计信息"""
        return {
            "version": self._data.get("version", "unknown"),
            "total_evaluations": self._data.get("total_evaluations", 0),
            "total_trades_recorded": self._data.get("total_trades_recorded", 0),
            "short_term_trades": len(self.short_term.recent_trades),
            "module_count": len(self.module_capabilities),
            "scenario_count": len(self.scenario_orchestrations),
            "lesson_count": len(self.lessons),
            "verified_lessons": sum(1 for l in self.lessons.values() if l.status == "verified"),
            "candidate_lessons": sum(1 for l in self.lessons.values() if l.status == "candidate"),
            "high_conf_scenarios": sum(
                1 for s in self.scenario_orchestrations.values()
                if s.confidence == "high"
            ),
            "improving_modules": sum(
                1 for m in self.module_capabilities.values()
                if m.trend == "improving"
            ),
            "declining_modules": sum(
                1 for m in self.module_capabilities.values()
                if m.trend == "declining"
            ),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"<EvaluationMemory "
            f"modules={stats['module_count']} "
            f"scenarios={stats['scenario_count']} "
            f"lessons={stats['lesson_count']} "
            f"evaluations={stats['total_evaluations']}>"
        )
