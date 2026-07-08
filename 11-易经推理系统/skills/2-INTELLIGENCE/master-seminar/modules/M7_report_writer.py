"""
M7: 报告生成器 (Report Writer)
生成结构化研讨报告
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

class ReportWriter:
    """
    报告生成器
    
    职责:
    1. 生成Markdown格式研讨报告
    2. 生成JSON格式摘要
    3. 归档到指定目录
    """
    
    def __init__(self, template_dir: Optional[str] = None):
        if template_dir is None:
            template_dir = str(Path.home() / ".workbuddy" / "skills" / "master-seminar" / "templates")
        
        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, context) -> str:
        """
        生成研讨报告
        
        Args:
            context: SeminarContext对象
            
        Returns:
            Markdown格式报告
        """
        # 导入结论提取器来转换结论对象
        from M5_conclusion_extractor import SeminarConclusion
        
        # 如果context.conclusions是对象，转换为dict
        if hasattr(context, 'conclusions') and isinstance(context.conclusions, SeminarConclusion):
            context = self._convert_context_to_dict(context)
        
        report = self._generate_header(context)
        report += self._generate_overview(context)
        report += self._generate_camps(context)
        report += self._generate_debate(context)
        report += self._generate_conclusion(context)
        report += self._generate_evolution(context)
        report += self._generate_footer(context)
        
        return report
    
    def _convert_context_to_dict(self, context):
        """将SeminarContext转换为可字典访问的形式"""
        from M5_conclusion_extractor import ConclusionExtractor
        extractor = ConclusionExtractor()
        
        # 创建一个简单的dict-like对象
        class DictLike:
            def __init__(self, data):
                self._data = data
            def get(self, key, default=None):
                return self._data.get(key, default)
        
        # 转换conclusions
        if hasattr(context, 'conclusions'):
            context.conclusions = extractor.to_dict(context.conclusions)
        
        return context
    
    def _generate_header(self, context) -> str:
        """生成报告头"""
        emoji_map = {
            "REGIME_CHANGE": "🔄 Regime变化",
            "A5_EXECUTION": "⚡ A5执行后",
            "MANUAL": "🎯 手动触发",
            "CONSECUTIVE_SKIP": "⚠️ 连续跳过"
        }
        
        trigger_emoji = emoji_map.get(context.trigger_type, "📋")
        
        return f"""# 🎓 大师研讨报告

**研讨ID**: `{context.seminar_id}`  
**触发类型**: {trigger_emoji}  
**时间**: {datetime.fromisoformat(context.timestamp).strftime('%Y-%m-%d %H:%M:%S')}  
**当前Regime**: `{context.current_regime}`  
**源报告**: `{context.source_report}`

---

## 📊 市场状态

| 指标 | 值 |
|:---|:---:|
"""
    
    def _generate_overview(self, context) -> str:
        """生成概览"""
        market = context.market_state or {}
        
        parts = []
        for key, value in market.items():
            if isinstance(value, float):
                parts.append(f"| {key} | {value:.4f} |")
            else:
                parts.append(f"| {key} | {value} |")
        
        if not parts:
            parts = ["| - | - |"]
        
        return "\n".join(parts) + "\n\n---\n\n"
    
    def _generate_camps(self, context) -> str:
        """生成阵营信息"""
        from M2_master_selector import MASTERS
        
        section = "## 🏛️ 阵营分配\n\n"
        
        for camp_name, masters in context.camps.items():
            if not masters:
                continue
            
            emoji = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(camp_name, "⚪")
            camp_display = {"bullish": "多方阵营", "neutral": "中立阵营", "bearish": "空方阵营"}.get(camp_name, camp_name)
            
            section += f"### {emoji} {camp_display}\n\n"
            section += "| 大师 | 风格 | 权重 | 核心观点 |\n"
            section += "|:---|:---|:---:|:---|\n"
            
            for master_id in masters:
                master = MASTERS.get(master_id)
                if master:
                    section += f"| {master.name} | {master.core_style} | {master.weight:.2f} | - |\n"
            
            section += "\n"
        
        return section + "---\n\n"
    
    def _generate_debate(self, context) -> str:
        """生成辩论详情"""
        from M2_master_selector import MASTERS
        
        section = "## 💬 辩论详情\n\n"
        
        for round_data in context.debate_rounds:
            phase = round_data.get("phase", "")
            round_num = round_data.get("round_num", 0)
            
            phase_display = {
                "intra_camp": "🏠 分阵营内部讨论",
                "cross_debate": "⚔️ 交叉辩论",
                "final_rebuttal": "🎯 最终陈述"
            }.get(phase, phase)
            
            section += f"### Round {round_num}: {phase_display}\n\n"
            
            if phase == "intra_camp":
                camp = round_data.get("camp", "")
                emoji = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(camp, "⚪")
                
                for stmt in round_data.get("statements", []):
                    section += f"**{stmt.get('master_name', '')}**: {stmt.get('content', '')}\n\n"
                
                section += f"_{emoji} 阵营总结_: {round_data.get('thesis_summary', '')}\n\n"
            
            elif phase == "cross_debate":
                # 多方攻击
                for attack in round_data.get("bull_attacks", []):
                    section += f"🟢 **{attack.get('speaker', '')}**: {attack.get('content', '')}\n\n"
                
                # 空方攻击
                for attack in round_data.get("bear_attacks", []):
                    section += f"🔴 **{attack.get('speaker', '')}**: {attack.get('content', '')}\n\n"
                
                # 关键争议
                disputes = round_data.get("key_disputes", [])
                if disputes:
                    section += "**⚖️ 关键争议:**\n\n"
                    for d in disputes:
                        emoji = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(d.get("camp", ""), "⚪")
                        section += f"- {emoji} {d.get('issue', '')}\n"
                    section += "\n"
            
            elif phase == "final_rebuttal":
                for rebuttal in round_data.get("rebuttals", []):
                    emoji = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(rebuttal.get("camp", ""), "⚪")
                    section += f"{emoji} **{rebuttal.get('speaker', '')}**:\n"
                    section += f"- 坚守: {rebuttal.get('final_point', '')}\n"
                    section += f"- 让步: {rebuttal.get('concession', '')}\n"
                    section += f"- 建议: {rebuttal.get('advice', '')}\n\n"
            
            section += "---\n\n"
        
        return section
    
    def _generate_conclusion(self, context) -> str:
        """生成结论"""
        conc = context.conclusions
        if not conc:
            return "## 📋 结论\n\n_暂无结论_\n\n---\n\n"
        
        bias = conc.get("bias", 0)
        bias_label = self._get_bias_label(bias)
        bias_emoji = self._get_bias_emoji(bias)
        
        section = f"""## 📋 研讨结论

### 🎯 多空倾向

{bias_emoji} **倾向**: {bias_label} ({bias:+.2f})  
📊 **置信度**: {conc.get('confidence', 0):.0%}  
🤝 **大师一致性**: {conc.get('master_agreement', 0):.0%}

### ✅ 可执行建议

"""
        
        for i, suggestion in enumerate(conc.get("actionable_suggestions", []), 1):
            section += f"{i}. {suggestion}\n"
        
        section += "\n### 🟢 多方信号\n\n"
        for signal in conc.get("bull_signals", []):
            section += f"- {signal}\n"
        
        section += "\n### 🔴 空方信号\n\n"
        for signal in conc.get("bear_signals", []):
            section += f"- {signal}\n"
        
        section += "\n### ⚠️ 风险警告\n\n"
        for warning in conc.get("risk_warnings", []):
            section += f"- {warning}\n"
        
        section += "\n---\n\n"
        return section
    
    def _generate_evolution(self, context) -> str:
        """生成进化信息"""
        section = "## 🔄 大师进化\n\n"
        
        if not context.evolution_updates:
            section += "_本次研讨未触发大师权重更新_\n\n"
            return section
        
        section += "| 大师 | 原权重 | 新权重 | 变化 | 采纳率 | 原因 |\n"
        section += "|:---|:---:|:---:|:---:|:---:|:---|\n"
        
        for master_id, update in context.evolution_updates.items():
            change = update.get("change", 0)
            change_str = f"{change:+.2f}"
            if change > 0:
                change_str = f"⬆️ {change:+.2f}"
            elif change < 0:
                change_str = f"⬇️ {change:+.2f}"
            
            section += f"| {master_id} | {update.get('old_weight', 0):.2f} | {update.get('new_weight', 0):.2f} | {change_str} | {update.get('adoption_rate', 0):.0%} | {self._get_change_reason(update)} |\n"
        
        section += "\n"
        return section
    
    def _generate_footer(self, context) -> str:
        """生成页脚"""
        return f"""---

*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  
*大师研讨SKILL v1.0.0 - Dream-MultiSkill System*
"""
    
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
    
    def _get_bias_emoji(self, bias: float) -> str:
        """获取倾向emoji"""
        if bias >= 1.5:
            return "🟢🟢"
        elif bias >= 0.5:
            return "🟢"
        elif bias <= -1.5:
            return "🔴🔴"
        elif bias <= -0.5:
            return "🔴"
        else:
            return "🟡"
    
    def _get_change_reason(self, update: Dict) -> str:
        """获取变化原因"""
        rate = update.get("adoption_rate", 0)
        if rate > 0.7:
            return "建议被采纳"
        elif rate < 0.4:
            return "建议被忽视"
        else:
            return "表现中等"
    
    def generate_summary_json(self, context) -> Dict:
        """生成JSON摘要"""
        return {
            "seminar_id": context.seminar_id,
            "timestamp": context.timestamp,
            "trigger_type": context.trigger_type,
            "current_regime": context.current_regime,
            "masters": {
                "total": len(context.selected_masters),
                "bullish": len(context.camps.get("bullish", [])),
                "neutral": len(context.camps.get("neutral", [])),
                "bearish": len(context.camps.get("bearish", []))
            },
            "conclusion": {
                "bias": context.conclusions.get("bias", 0),
                "confidence": context.conclusions.get("confidence", 0),
                "agreement": context.conclusions.get("master_agreement", 0),
                "suggestions": context.conclusions.get("actionable_suggestions", [])
            },
            "evolution": {
                "masters_updated": list(context.evolution_updates.keys()),
                "max_weight_change": max([abs(u.get("change", 0)) for u in context.evolution_updates.values()], default=0)
            }
        }
