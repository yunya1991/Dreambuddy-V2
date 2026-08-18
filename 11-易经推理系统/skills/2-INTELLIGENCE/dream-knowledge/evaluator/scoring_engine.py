#!/usr/bin/env python3
"""
知识库评估引擎 | Knowledge Scoring Engine
=====================================

核心功能:
1. 策略/工具自动评分
2. 分级管理 (S/A/B/C)
3. 证据链验证
4. 评分更新

评分维度:
- 基础质量 (30分)
- 实证表现 (40分)
- 适用广度 (15分)
- 进化潜力 (15分)
"""

import json
import yaml
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ============== 配置 ==============

SCORING_CONFIG = {
    "基础质量": {
        "logic_completeness": {"max": 10, "desc": "入场/出场/风控逻辑是否完整"},
        "parameter_clarity": {"max": 10, "desc": "参数是否明确可执行"},
        "executability": {"max": 10, "desc": "是否可以在实盘中执行"}
    },
    "实证表现": {
        "historical_win_rate": {"max": 20, "desc": "历史验证胜率"},
        "risk_reward_ratio": {"max": 10, "desc": "风险收益比表现"},
        "practice_count": {"max": 10, "desc": "实战验证次数"}
    },
    "适用广度": {
        "regime_coverage": {"max": 10, "desc": "适用的Regime数量"},
        "tool_compatibility": {"max": 5, "desc": "工具兼容范围"}
    },
    "进化潜力": {
        "optimization_space": {"max": 10, "desc": "可优化/迭代空间"},
        "extensibility": {"max": 5, "desc": "扩展性评分"}
    }
}

TIER_THRESHOLDS = {
    "S": 80,  # >=80
    "A": 60,  # 60-79
    "B": 40,  # 40-59
    "C": 0    # <40
}

TIER_LABELS = {
    "S": "⭐⭐⭐",
    "A": "⭐⭐",
    "B": "⭐",
    "C": "❌"
}

# ============== 数据结构 ==============

@dataclass
class EvidenceItem:
    """证据链条目"""
    type: str  # practice / theory / distillation
    episode_id: Optional[str] = None
    result: Optional[str] = None  # success / partial / failure
    date: str = ""
    notes: str = ""
    win_rate: float = 0.0  # 胜率 0-1
    risk_reward: float = 0.0  # 风险收益比


@dataclass
class KnowledgeEntry:
    """知识条目"""
    name: str
    type: str  # strategy / tool
    regime: List[str] = field(default_factory=list)
    tool_type: str = ""
    
    id: str = ""
    score: int = 0
    tier: str = "C"
    source: str = ""  # 联网搜索 / 实践复盘 / 蒸馏产物
    
    created: str = ""
    updated: str = ""
    verifications: int = 0
    status: str = "active"  # active / archived / deprecated
    
    # 评分维度
    logic_completeness: int = 0
    parameter_clarity: int = 0
    executability: int = 0
    historical_win_rate: int = 0
    risk_reward_ratio: int = 0
    practice_count: int = 0
    regime_coverage: int = 0
    tool_compatibility: int = 0
    optimization_space: int = 0
    extensibility: int = 0
    
    # 证据链
    evidence_chain: List[EvidenceItem] = field(default_factory=list)
    
    # 内容
    summary: str = ""
    entry_rules: str = ""
    exit_rules: str = ""
    risk_management: str = ""
    practice_records: str = ""
    optimization_history: str = ""


# ============== 评分引擎 ==============

class KnowledgeScorer:
    """知识评分引擎"""
    
    def __init__(self):
        self.config = SCORING_CONFIG
        self.thresholds = TIER_THRESHOLDS
        self.tier_labels = TIER_LABELS
    
    def calculate_score(self, entry: KnowledgeEntry) -> Tuple[int, str]:
        """
        计算总分和等级
        
        Returns:
            (总分, 等级)
        """
        # 确保各维度不超过max限制
        entry.extensibility = min(entry.extensibility, 5)
        entry.tool_compatibility = min(entry.tool_compatibility, 5)
        
        scores = {
            "logic_completeness": min(entry.logic_completeness, 10),
            "parameter_clarity": min(entry.parameter_clarity, 10),
            "executability": min(entry.executability, 10),
            "historical_win_rate": min(entry.historical_win_rate, 20),
            "risk_reward_ratio": min(entry.risk_reward_ratio, 10),
            "practice_count": min(entry.practice_count, 10),
            "regime_coverage": min(entry.regime_coverage, 10),
            "tool_compatibility": entry.tool_compatibility,
            "optimization_space": min(entry.optimization_space, 10),
            "extensibility": entry.extensibility
        }
        
        total = sum(scores.values())
        tier = self._calculate_tier(total)
        
        return total, tier
    
    def _calculate_tier(self, score: int) -> str:
        """根据分数计算等级"""
        if score >= self.thresholds["S"]:
            return "S"
        elif score >= self.thresholds["A"]:
            return "A"
        elif score >= self.thresholds["B"]:
            return "B"
        else:
            return "C"
    
    def evaluate_from_content(self, content: Dict) -> KnowledgeEntry:
        """
        根据内容自动评估
        
        Args:
            content: {
                "name": "策略名称",
                "type": "strategy",
                "regime": ["TREND_BULL"],
                "tool_type": "futures",
                "source": "联网搜索",
                "summary": "策略概述",
                "entry_rules": "入场规则",
                "exit_rules": "出场规则",
                "risk_management": "风险管理",
                "has_logic": True,  # 是否有完整逻辑
                "has_parameters": True,  # 是否有明确参数
                "can_execute": True,  # 是否可执行
                "win_rate": 0.65,  # 预估胜率
                "rr_ratio": 2.0,  # 风险收益比
                "regimes_covered": 2  # 覆盖的Regime数
            }
        """
        entry = KnowledgeEntry(
            name=content.get("name", ""),
            type=content.get("type", "strategy"),
            regime=content.get("regime", []),
            tool_type=content.get("tool_type", ""),
            source=content.get("source", "联网搜索"),
            summary=content.get("summary", ""),
            entry_rules=content.get("entry_rules", ""),
            exit_rules=content.get("exit_rules", ""),
            risk_management=content.get("risk_management", ""),
            id=str(uuid.uuid4())[:8],
            created=datetime.now().strftime("%Y-%m-%d"),
            updated=datetime.now().strftime("%Y-%m-%d")
        )
        
        # 基础质量评分 (自动)
        entry.logic_completeness = self._score_logic(content)
        entry.parameter_clarity = self._score_parameters(content)
        entry.executability = self._score_executability(content)
        
        # 实证表现评分 (需要验证数据)
        entry.historical_win_rate = self._score_win_rate(content.get("win_rate", 0))
        entry.risk_reward_ratio = self._score_rr_ratio(content.get("rr_ratio", 1.0))
        entry.practice_count = self._score_practice_count(content.get("verifications", 0))
        
        # 适用广度评分
        entry.regime_coverage = self._score_regime_coverage(len(entry.regime))
        entry.tool_compatibility = self._score_tool_compatibility(entry.tool_type)
        
        # 进化潜力 (默认中等)
        entry.optimization_space = 5
        entry.extensibility = 3
        
        # 计算总分和等级
        entry.score, entry.tier = self.calculate_score(entry)
        
        return entry
    
    def _score_logic(self, content: Dict) -> int:
        """评分逻辑完整性"""
        has_logic = content.get("has_logic", False)
        has_entry = bool(content.get("entry_rules"))
        has_exit = bool(content.get("exit_rules"))
        has_risk = bool(content.get("risk_management"))
        
        base = 5 if has_logic else 0
        bonus = 2 if has_entry else 0
        bonus += 2 if has_exit else 0
        bonus += 1 if has_risk else 0
        
        return min(10, base + bonus)
    
    def _score_parameters(self, content: Dict) -> int:
        """评分参数明确性"""
        has_params = content.get("has_parameters", False)
        has_summary = bool(content.get("summary"))
        
        score = 5 if has_params else 3
        score += 2 if has_summary else 0
        
        return min(10, score)
    
    def _score_executability(self, content: Dict) -> int:
        """评分可执行性"""
        can_execute = content.get("can_execute", True)
        has_rules = bool(content.get("entry_rules") and content.get("exit_rules"))
        
        score = 8 if (can_execute and has_rules) else 5
        return min(10, score)
    
    def _score_win_rate(self, win_rate: float) -> int:
        """评分历史胜率"""
        # 0.5 = 10分, 0.7 = 14分, 0.9+ = 20分
        if win_rate <= 0:
            return 0
        elif win_rate < 0.5:
            return int(win_rate * 10)
        else:
            return int(10 + (win_rate - 0.5) * 20)
    
    def _score_rr_ratio(self, rr_ratio: float) -> int:
        """评分风险收益比"""
        # 1.0 = 5分, 2.0 = 8分, 3.0+ = 10分
        if rr_ratio <= 0:
            return 0
        elif rr_ratio < 1.0:
            return int(rr_ratio * 5)
        elif rr_ratio < 2.0:
            return int(5 + (rr_ratio - 1.0) * 3)
        else:
            return min(10, int(8 + (rr_ratio - 2.0) * 1))
    
    def _score_practice_count(self, count: int) -> int:
        """评分实战次数"""
        # 0次=0分, 1次=3分, 3次=6分, 5次+=10分
        if count <= 0:
            return 0
        elif count == 1:
            return 3
        elif count == 2:
            return 5
        elif count == 3:
            return 7
        elif count == 4:
            return 9
        else:
            return 10
    
    def _score_regime_coverage(self, count: int) -> int:
        """评分Regime覆盖"""
        # 1个=3分, 2个=6分, 3个=8分, 4个+=10分
        if count <= 0:
            return 0
        elif count == 1:
            return 3
        elif count == 2:
            return 6
        elif count == 3:
            return 8
        else:
            return 10
    
    def _score_tool_compatibility(self, tool_type: str) -> int:
        """评分工具兼容"""
        # 单一工具=2分, 多种工具=4分, 跨市场=5分
        if not tool_type:
            return 1
        elif "," in tool_type:
            return 5
        else:
            return 3
    
    def adjust_score(self, entry: KnowledgeEntry, result: str, notes: str = "") -> Tuple[int, str]:
        """
        根据实践结果调整评分
        
        Args:
            entry: 知识条目
            result: success / partial / failure
            notes: 备注
        
        Returns:
            (调整后分数, 调整后等级)
        """
        # 调整规则
        if result == "success":
            adjustment = 5
            entry.verifications += 1
        elif result == "partial":
            adjustment = 0
            entry.verifications += 1
        else:  # failure
            adjustment = -10
            entry.verifications += 1
        
        # 限制范围
        new_score = max(0, min(100, entry.score + adjustment))
        
        # 重新计算等级
        new_tier = self._calculate_tier(new_score)
        
        # 添加证据
        evidence = EvidenceItem(
            type="practice",
            result=result,
            date=datetime.now().strftime("%Y-%m-%d"),
            notes=notes
        )
        entry.evidence_chain.append(evidence)
        
        # 更新
        entry.score = new_score
        entry.tier = new_tier
        entry.updated = datetime.now().strftime("%Y-%m-%d")
        
        return new_score, new_tier
    
    def generate_report(self, entry: KnowledgeEntry) -> str:
        """生成评分报告"""
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║                    知识评分报告                               ║
╠══════════════════════════════════════════════════════════════╣
║ 名称: {entry.name}
║ 类型: {entry.type} | Regime: {', '.join(entry.regime)}
║ 评分: {entry.score}/100 | 等级: {self.tier_labels[entry.tier]} ({entry.tier}级)
╠══════════════════════════════════════════════════════════════╣
║ 【基础质量】(30分)
║   逻辑完整性: {entry.logic_completeness}/10
║   参数明确性: {entry.parameter_clarity}/10
║   可执行性: {entry.executability}/10
╠══════════════════════════════════════════════════════════════╣
║ 【实证表现】(40分)
║   历史胜率: {entry.historical_win_rate}/20
║   风险收益: {entry.risk_reward_ratio}/10
║   实战次数: {entry.practice_count}/10
╠══════════════════════════════════════════════════════════════╣
║ 【适用广度】(15分)
║   Regime覆盖: {entry.regime_coverage}/10
║   工具兼容: {entry.tool_compatibility}/5
╠══════════════════════════════════════════════════════════════╣
║ 【进化潜力】(15分)
║   优化空间: {entry.optimization_space}/10
║   扩展性: {entry.extensibility}/5
╠══════════════════════════════════════════════════════════════╣
║ 验证次数: {entry.verifications}
║ 证据链: {len(entry.evidence_chain)}条
╚══════════════════════════════════════════════════════════════╝
"""
        return report


# ============== 主函数 ==============

def main():
    """测试评分引擎"""
    scorer = KnowledgeScorer()
    
    # 测试案例
    test_content = {
        "name": "网格策略",
        "type": "strategy",
        "regime": ["RANGE_BOUND"],
        "tool_type": "grid",
        "source": "联网搜索",
        "summary": "在震荡市场中网格化高卖低买",
        "entry_rules": "1. 确定震荡区间\n2. 等分10格\n3. 区间中部开始",
        "exit_rules": "1. 触及边界反向\n2. 止损区间外2%",
        "risk_management": "总仓位不超过30%",
        "has_logic": True,
        "has_parameters": True,
        "can_execute": True,
        "win_rate": 0.65,
        "rr_ratio": 1.5,
        "regimes_covered": 1,
        "verifications": 2
    }
    
    # 评估
    entry = scorer.evaluate_from_content(test_content)
    
    # 输出报告
    print(scorer.generate_report(entry))
    
    # 测试调整
    print("\n=== 测试评分调整 ===")
    print(f"原始评分: {entry.score}")
    new_score, new_tier = scorer.adjust_score(entry, "success", "首次验证成功")
    print(f"调整后: {new_score} ({new_tier}级)")


if __name__ == "__main__":
    main()
