"""
M5: 结论提取器 (Conclusion Extractor)
从辩论中提取多空结论和可执行建议
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SeminarConclusion:
    """研讨结论"""
    bias: float = 0.0  # -3 to +3, 0=neutral
    confidence: float = 0.5
    master_agreement: float = 0.5
    key_disputes: List[Dict] = field(default_factory=list)
    actionable_suggestions: List[str] = field(default_factory=list)
    bull_signals: List[str] = field(default_factory=list)
    bear_signals: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)


class ConclusionExtractor:
    """
    结论提取器
    
    职责:
    1. 计算多空倾向评分
    2. 提取关键争议点
    3. 生成可执行建议
    4. 汇总大师一致性
    """
    
    def __init__(self):
        self.bias_keywords = {
            "bullish": ["上涨", "突破", "买入", "多头", "做多", "看好", "加仓", "持有"],
            "bearish": ["下跌", "跌破", "卖出", "空头", "做空", "看空", "减仓", "止损"],
            "neutral": ["观望", "等待", "中性", "不确定", "观望", "谨慎"]
        }
    
    def extract(self,
              debate_rounds: List[Dict],
              camps: Dict[str, List[str]],
              market_state: Dict[str, Any] = None) -> SeminarConclusion:
        """
        从辩论中提取结论
        
        Args:
            debate_rounds: 辩论轮次列表
            camps: 阵营分配
            market_state: 市场状态
            
        Returns:
            SeminarConclusion对象
        """
        # 1. 计算多空倾向
        bias = self._calculate_bias(debate_rounds, camps)
        
        # 2. 计算大师一致性
        agreement = self._calculate_master_agreement(debate_rounds, camps)
        
        # 3. 提取关键争议点
        disputes = self._extract_disputes(debate_rounds)
        
        # 4. 生成可执行建议
        suggestions = self._generate_suggestions(bias, agreement, camps, market_state)
        
        # 5. 提取信号
        bull_signals = self._extract_signals(debate_rounds, "bullish")
        bear_signals = self._extract_signals(debate_rounds, "bearish")
        
        # 6. 风险警告
        risk_warnings = self._extract_risk_warnings(debate_rounds, camps)
        
        # 7. 计算置信度
        confidence = self._calculate_confidence(bias, agreement, disputes)
        
        return SeminarConclusion(
            bias=bias,
            confidence=confidence,
            master_agreement=agreement,
            key_disputes=disputes,
            actionable_suggestions=suggestions,
            bull_signals=bull_signals,
            bear_signals=bear_signals,
            risk_warnings=risk_warnings
        )
    
    def _calculate_bias(self,
                       debate_rounds: List[Dict],
                       camps: Dict[str, List[str]]) -> float:
        """
        计算多空倾向
        
        范围: -3 (极端看空) ~ 0 (中立) ~ +3 (极端看多)
        """
        # 基于阵营大师数量
        camp_weights = {
            "bullish": 1.0,
            "neutral": 0.0,
            "bearish": -1.0
        }
        
        bias = 0.0
        total_masters = 0
        
        for camp_name, masters in camps.items():
            weight = camp_weights.get(camp_name, 0)
            bias += weight * len(masters)
            total_masters += len(masters)
        
        if total_masters > 0:
            bias = bias / total_masters * 3  # 归一化到-3~+3
        
        return round(bias, 2)
    
    def _calculate_master_agreement(self,
                                   debate_rounds: List[Dict],
                                   camps: Dict[str, List[str]]) -> float:
        """
        计算大师一致性
        
        规则:
        - 如果大师都在同一阵营 → 高一致性 (0.8+)
        - 如果大师分散在3个阵营 → 低一致性 (0.3-)
        - 如果大师分散在2个阵营 → 中一致性 (0.5)
        """
        non_empty_camps = sum(1 for ms in camps.values() if ms)
        
        if non_empty_camps == 1:
            return 0.9  # 全员同一阵营
        elif non_empty_camps == 2:
            # 计算两阵营大师数量的差距
            camp_sizes = [len(ms) for ms in camps.values() if ms]
            if len(camp_sizes) == 2:
                diff = abs(camp_sizes[0] - camp_sizes[1])
                total = sum(camp_sizes)
                return round(1 - (diff / total) * 0.5, 2)
            return 0.5
        else:  # 3个阵营
            return 0.4
    
    def _extract_disputes(self, debate_rounds: List[Dict]) -> List[Dict]:
        """提取关键争议点"""
        disputes = []
        
        # 从交叉辩论中提取
        for round_data in debate_rounds:
            if round_data.get("phase") == "cross_debate":
                key_disputes = round_data.get("key_disputes", [])
                for dispute in key_disputes:
                    disputes.append({
                        "issue": dispute.get("issue", ""),
                        "camp": dispute.get("camp", ""),
                        "speaker": dispute.get("speaker", "")
                    })
        
        return disputes[:3]  # 最多3个
    
    def _generate_suggestions(self,
                            bias: float,
                            agreement: float,
                            camps: Dict[str, List[str]],
                            market_state: Dict[str, Any] = None) -> List[str]:
        """生成可执行建议"""
        suggestions = []
        
        # 基于倾向的建议
        if bias > 1.5:
            suggestions.append("🟢 多方占优: 可考虑顺势做多，止损设关键支撑下方")
        elif bias > 0.5:
            suggestions.append("🟢 偏多: 轻仓试探，谨慎追高")
        elif bias < -1.5:
            suggestions.append("🔴 空方占优: 可考虑对冲或做空，止损设关键阻力上方")
        elif bias < -0.5:
            suggestions.append("🔴 偏空: 控制仓位，等待确认")
        else:
            suggestions.append("🟡 中立: 建议观望，等待趋势明确")
        
        # 基于一致性的建议
        if agreement > 0.7:
            suggestions.append(f"⚡ 大师高度一致({agreement:.0%}): 可适当提高仓位")
        elif agreement < 0.4:
            suggestions.append(f"⚠️ 大师分歧较大({agreement:.0%}): 建议降低仓位或分批建仓")
        
        # 基于市场状态的具体建议
        if market_state:
            price = market_state.get("price", 0)
            if price > 0 and bias > 0:
                suggestions.append(f"建议入场区间: ${price * 0.98:,.0f} - ${price * 1.02:,.0f}")
        
        return suggestions[:4]  # 最多4条
    
    def _extract_signals(self,
                        debate_rounds: List[Dict],
                        camp: str) -> List[str]:
        """提取阵营信号"""
        signals = []
        
        # 从最终反驳中提取
        for round_data in debate_rounds:
            if round_data.get("phase") == "final_rebuttal":
                for rebuttal in round_data.get("rebuttals", []):
                    if rebuttal.get("camp") == camp:
                        advice = rebuttal.get("advice", "")
                        if advice:
                            signals.append(advice)
        
        return signals[:3]  # 每阵营最多3条
    
    def _extract_risk_warnings(self,
                               debate_rounds: List[Dict],
                               camps: Dict[str, List[str]]) -> List[str]:
        """提取风险警告"""
        warnings = []
        
        # 基于大师组成的风险
        if "bearish" in camps and "bullish" in camps:
            warnings.append("⚠️ 多空分歧较大，注意仓位控制")
        
        # 基于一致性的风险
        for round_data in debate_rounds:
            if round_data.get("phase") == "cross_debate":
                disputes = round_data.get("key_disputes", [])
                if len(disputes) > 2:
                    warnings.append("⚠️ 争议点多且复杂，建议谨慎操作")
        
        # 添加通用风险
        warnings.append("📊 所有建议仅供参考，请根据自身风险承受能力决策")
        
        return warnings[:3]
    
    def _calculate_confidence(self,
                            bias: float,
                            agreement: float,
                            disputes: List[Dict]) -> float:
        """
        计算置信度
        
        公式: base * agreement_boost * dispute_penalty
        """
        # 基础置信度
        base = 0.5
        
        # 一致性加成
        agreement_boost = 1 + agreement * 0.3
        
        # 争议点惩罚
        dispute_penalty = max(0.5, 1 - len(disputes) * 0.1)
        
        # 极端倾向置信度略低
        extreme_penalty = 1 - abs(bias) / 6 * 0.1
        
        confidence = base * agreement_boost * dispute_penalty * extreme_penalty
        
        return round(min(0.95, max(0.2, confidence)), 2)
    
    def to_dict(self, conclusion: SeminarConclusion) -> Dict:
        """转换为字典"""
        return {
            "bias": conclusion.bias,
            "bias_label": self._get_bias_label(conclusion.bias),
            "confidence": conclusion.confidence,
            "master_agreement": conclusion.master_agreement,
            "key_disputes": conclusion.key_disputes,
            "actionable_suggestions": conclusion.actionable_suggestions,
            "bull_signals": conclusion.bull_signals,
            "bear_signals": conclusion.bear_signals,
            "risk_warnings": conclusion.risk_warnings
        }
    
    def _get_bias_label(self, bias: float) -> str:
        """获取倾向标签"""
        if bias >= 2:
            return "强看多"
        elif bias >= 0.5:
            return "偏看多"
        elif bias <= -2:
            return "强看空"
        elif bias <= -0.5:
            return "偏看空"
        else:
            return "中性"
