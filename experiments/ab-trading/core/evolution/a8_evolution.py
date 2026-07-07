#!/usr/bin/env python3
"""
A8 理论与实践验证进化模块
基于A8-theory-practice-verification技能的自我批评自循环
检查理论与实践的结合情况，通过自我批评推动系统进化
"""
import json, os, time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

from .evolution_engine import EvolutionEngine, EvolutionSource, EvolutionStatus
from .backtest_engine import SimpleBacktestEngine

BASE_DIR = Path(__file__).parent.parent.parent
SKILL_A8_PATH = Path(__file__).parent.parent.parent.parent / "6-TRADING" / "skills" / "A8-theory-practice-verification" / "SKILL.md"


class A8TheoryPracticeEvolution:
    """
    A8理论与实践验证进化 - 纯粹理性内部批评自循环

    核心机制：
    1. 检验：检查A0-A7的理论和实践结合情况
    2. 验证：根据矛盾提出假说，并进行回测验证
    3. 批评与建议：基于批判性思维框架提出改进
    """

    def __init__(self, engine: EvolutionEngine):
        self.engine = engine
        self.backtest = SimpleBacktestEngine()
        self.inspection_log = BASE_DIR / "data" / "evolution" / "a8_inspection_log.json"
        self.inspection_log.parent.mkdir(parents=True, exist_ok=True)

    def run_daily_inspection(self, memory: Dict, recent_decisions: List[Dict]) -> Dict:
        """
        执行每日A8检验流程

        Args:
            memory: 当前记忆数据
            recent_decisions: 近期决策记录

        Returns:
            检验报告
        """
        print("[A8进化] 开始每日理论与实践检验...")

        report = {
            "inspection_id": f"a8_{int(time.time())}",
            "timestamp": self._now_iso(),
            "theory_practice_alignment": {},
            "contradictions_found": [],
            "evolution_proposals": [],
            "a0_refinement_suggestions": [],
            "a7_refinement_suggestions": [],
        }

        report["theory_practice_alignment"] = self._check_theory_practice_alignment(
            memory, recent_decisions
        )

        contradictions = self._identify_contradictions(memory, recent_decisions)
        report["contradictions_found"] = contradictions

        for contradiction in contradictions:
            proposals = self._generate_proposals_from_contradiction(contradiction, memory)
            report["evolution_proposals"].extend(proposals)

        self._save_inspection(report)

        print(f"[A8进化] 检验完成: 发现{len(contradictions)}个矛盾, 生成{len(report['evolution_proposals'])}个进化提议")
        return report

    def _check_theory_practice_alignment(self, memory: Dict, decisions: List[Dict]) -> Dict:
        """
        检查理论与实践的一致性
        """
        alignment = {
            "a0_guidance": "UNKNOWN",
            "a7_practice": "UNKNOWN",
            "theory_practice_loop": "UNKNOWN",
            "truth_verification": "UNKNOWN",
        }

        if not decisions:
            alignment["a0_guidance"] = "NO_DATA"
            alignment["a7_practice"] = "NO_DATA"
            return alignment

        lessons = memory.get("lessons", [])
        lesson_contents = [l.get("content", "") for l in lessons]

        hold_count = sum(1 for d in decisions if d.get("action") == "HOLD")
        long_count = sum(1 for d in decisions if d.get("action") == "LONG")
        short_count = sum(1 for d in decisions if d.get("action") == "SHORT")
        total = len(decisions)

        hold_ratio = hold_count / total if total > 0 else 0

        if hold_ratio > 0.8:
            alignment["a0_guidance"] = "FAIL"
            alignment["a0_issue"] = "过度保守，矛盾论分析可能过于强调风险而忽视机会"
        elif hold_ratio > 0.5:
            alignment["a0_guidance"] = "PARTIAL"
        else:
            alignment["a0_guidance"] = "PASS"

        recent_trades = memory.get("recent_trades", [])
        if recent_trades:
            wins = sum(1 for t in recent_trades if t.get("pnl_pct", 0) > 0)
            win_rate = wins / len(recent_trades) if recent_trades else 0
            if win_rate >= 0.5:
                alignment["a7_practice"] = "PASS"
            elif win_rate >= 0.3:
                alignment["a7_practice"] = "PARTIAL"
            else:
                alignment["a7_practice"] = "FAIL"
                alignment["a7_issue"] = "胜率偏低，实践方法需要改进"
        else:
            alignment["a7_practice"] = "NO_DATA"

        if alignment["a0_guidance"] == "PASS" and alignment["a7_practice"] == "PASS":
            alignment["theory_practice_loop"] = "PASS"
        elif alignment["a0_guidance"] == "FAIL" or alignment["a7_practice"] == "FAIL":
            alignment["theory_practice_loop"] = "FAIL"
        else:
            alignment["theory_practice_loop"] = "PARTIAL"

        total_trades = memory.get("total_trades", 0)
        if total_trades >= 5:
            alignment["truth_verification"] = "PASS" if win_rate >= 0.45 else "FAIL"
        else:
            alignment["truth_verification"] = "INSUFFICIENT_DATA"

        return alignment

    def _identify_contradictions(self, memory: Dict, decisions: List[Dict]) -> List[Dict]:
        """
        识别理论与实践中的矛盾
        """
        contradictions = []
        lessons = memory.get("lessons", [])
        lesson_contents = [l.get("content", "").lower() for l in lessons]

        if not decisions:
            return contradictions

        hold_count = sum(1 for d in decisions if d.get("action") == "HOLD")
        total = len(decisions)
        hold_ratio = hold_count / total if total > 0 else 0

        if hold_ratio > 0.8 and len(decisions) >= 5:
            contradictions.append({
                "id": "C_A8_001",
                "type": "theory_practice_mismatch",
                "description": "过度保守矛盾：理论上应该寻找交易机会，但实践中连续观望",
                "severity": "HIGH",
                "hypothesis": "系统被'缩量不交易'等教训过度约束，导致在震荡市中完全不交易",
                "verification_plan": "测试降低入场门槛后交易频率和胜率的变化",
            })

        loss_streak = memory.get("loss_streak", 0)
        if loss_streak >= 3:
            contradictions.append({
                "id": "C_A8_002",
                "type": "strategy_failure",
                "description": f"连续亏损{loss_streak}次，当前策略可能不适应市场环境",
                "severity": "CRITICAL",
                "hypothesis": "当前大师风格或策略参数与当前市场状态不匹配",
                "verification_plan": "回测不同大师风格在近期市场的表现",
            })

        max_dd = memory.get("max_drawdown_pct", 0)
        if max_dd > 10:
            contradictions.append({
                "id": "C_A8_003",
                "type": "risk_management",
                "description": f"最大回撤{max_dd:.1f}%超过10%，风控机制需要加强",
                "severity": "HIGH",
                "hypothesis": "止损设置过宽或仓位管理不当导致回撤过大",
                "verification_plan": "测试更严格的止损和更小仓位的回测表现",
            })

        duplicate_lessons = self._find_duplicate_lessons(lessons)
        if duplicate_lessons:
            contradictions.append({
                "id": "C_A8_004",
                "type": "memory_bloat",
                "description": f"存在{len(duplicate_lessons)}条重复教训，记忆系统有冗余",
                "severity": "LOW",
                "hypothesis": "每次HOLD都产生相似教训，记忆系统缺乏去重机制",
                "verification_plan": "实现教训去重和质量评估机制",
            })

        return contradictions

    def _find_duplicate_lessons(self, lessons: List[Dict]) -> List[Dict]:
        """查找重复的教训"""
        duplicates = []
        seen = set()
        for lesson in lessons:
            content = lesson.get("content", "")
            normalized = content[:30].lower()
            if normalized in seen:
                duplicates.append(lesson)
            seen.add(normalized)
        return duplicates

    def _generate_proposals_from_contradiction(self, contradiction: Dict, memory: Dict) -> List[Dict]:
        """
        从矛盾生成进化提议
        """
        proposals = []
        cid = contradiction.get("id", "")

        if cid == "C_A8_001":
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.A8_THEORY_PRACTICE,
                    title="降低动量阈值以提高交易频率",
                    description="当前动量阈值2%过高，在震荡市中难以触发交易。建议降低至1.5%，提高交易频率的同时保持合理胜率。",
                    strategy_params={"momentum_threshold": 0.015},
                    rationale="过度保守导致连续HOLD，降低动量阈值可以捕捉更多中等强度趋势",
                    priority="high",
                )
            )
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.A8_THEORY_PRACTICE,
                    title="降低量比阈值增强信号敏感度",
                    description="量比阈值从1.2降至1.0，在缩量市场中也能识别相对放量的机会",
                    strategy_params={"volume_threshold": 1.0},
                    rationale="缩量环境中，相对放量也可能预示短期趋势",
                    priority="medium",
                )
            )

        elif cid == "C_A8_002":
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.A8_THEORY_PRACTICE,
                    title="收紧止损降低单笔亏损",
                    description="连续亏损时，将止损从4%收紧至3%，降低单笔亏损幅度",
                    strategy_params={"stop_loss_pct": 0.03},
                    rationale="连败时降低单笔风险，保护资金安全",
                    priority="high",
                )
            )

        elif cid == "C_A8_003":
            proposals.append(
                self.engine.propose_evolution(
                    source=EvolutionSource.A8_THEORY_PRACTICE,
                    title="降低止盈止损比提高胜率",
                    description="将止盈从8%降至6%，止损保持4%，降低盈亏比但提高胜率",
                    strategy_params={"take_profit_pct": 0.06},
                    rationale="回撤过大可能因为止盈过高难以达到，适当降低止盈提高实现率",
                    priority="medium",
                )
            )

        return proposals

    def get_inspection_history(self, limit: int = 10) -> List[Dict]:
        """获取检验历史"""
        try:
            if self.inspection_log.exists():
                with open(self.inspection_log) as f:
                    log = json.load(f)
                return log.get("inspections", [])[-limit:]
        except Exception:
            pass
        return []

    def _save_inspection(self, report: Dict):
        """保存检验报告"""
        try:
            log = {"inspections": []}
            if self.inspection_log.exists():
                with open(self.inspection_log) as f:
                    log = json.load(f)
            log["inspections"].append(report)
            if len(log["inspections"]) > 100:
                log["inspections"] = log["inspections"][-100:]
            with open(self.inspection_log, "w") as f:
                json.dump(log, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
