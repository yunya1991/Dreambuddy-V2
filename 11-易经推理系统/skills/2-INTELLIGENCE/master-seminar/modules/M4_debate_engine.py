"""
M4: 辩论引擎 (Debate Engine)
驱动大师间辩论，生成多轮交锋
"""

import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class DebateRound:
    """辩论回合"""
    round_num: int
    phase: str  # "intra_camp", "cross_debate", "rebuttal"
    speakers: List[str] = field(default_factory=list)
    statements: List[Dict] = field(default_factory=list)
    key_dispute: str = ""
    resolution: str = ""

@dataclass
class MasterStatement:
    """大师陈述"""
    master_id: str
    master_name: str
    content: str
    evidence: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)  # 针对哪些大师
    timestamp: str = ""


class DebateEngine:
    """
    辩论引擎
    
    职责:
    1. 驱动分阵营内部讨论
    2. 生成多空交叉辩论
    3. 提取关键争议点
    4. 生成大师间的追问
    """
    
    def __init__(self, max_rounds: int = 3, max_thesis: int = 3):
        self.max_rounds = max_rounds
        self.max_thesis = max_thesis
        self.debate_prompts = self._load_debate_prompts()
    
    def _load_debate_prompts(self) -> Dict:
        """加载辩论提示词"""
        return {
            "intra_camp_intro": """你是{camp_name}阵营的{camp_master_names}。
当前议题: {topic}
市场状态: {market_summary}

请各大师阐述本阵营的核心论点，每个大师最多2个核心观点。
格式要求:
1. 观点要具体，基于市场数据
2. 要有对对方阵营的可能反驳预判
3. 体现大师独特的思考方式
""",
            "cross_debate_intro": """现在进入交叉辩论阶段。

🟢 多方阵营({bull_masters}): {bull_thesis}
🔴 空方阵营({bear_masters}): {bear_thesis}

请双方直接交锋:
1. 多方先攻击空方的弱点 (1-2个问题)
2. 空方反击 (1-2个问题)
3. 寻找核心分歧点
""",
            "rebuttal_intro": """辩论进入尾声。请各方做最终陈述:
1. 坚持的核心观点 (为什么你的判断更可能正确)
2. 承认对方的1个有效观点
3. 给投资者的最终建议
""",
            "judge_summary": """中立裁判总结:
参与大师: {all_masters}
核心争议: {key_disputes}

请裁判(Tharp/Livermore)做最终评价:
1. 哪方的论点更有说服力?
2. 市场可能如何演绎?
3. 投资者应该关注什么?
"""
        }
    
    def run(self,
           camps: Dict[str, List[str]],
           reports: Dict[str, str],
           market_state: Dict[str, Any],
           topic: str = "") -> List[Dict]:
        """
        运行完整辩论流程
        
        Args:
            camps: 阵营分配 {"bullish": [...], "neutral": [...], "bearish": [...]}
            reports: A系列报告 {"A1": "...", "A3": "...", "A5": "..."}
            market_state: 市场状态
            topic: 辩题
            
        Returns:
            辩论轮次列表
        """
        from M2_master_selector import MASTERS
        
        # 生成辩题
        if not topic:
            price = market_state.get("price", 0)
            topic = f"BTC当前价格约${price:,.0f}，市场将如何演绎?"
        
        # 生成市场摘要
        market_summary = self._generate_market_summary(market_state)
        
        rounds = []
        
        # Phase 1: 分阵营内部讨论
        camp_discussions = self._run_intra_camp_discussion(camps, topic, market_summary)
        rounds.extend(camp_discussions)
        
        # Phase 2: 交叉辩论
        cross_debate = self._run_cross_debate(
            camps, camp_discussions, topic, market_summary
        )
        rounds.append(cross_debate)
        
        # Phase 3: 最终反驳
        rebuttal = self._run_final_rebuttal(camps, rounds, topic, market_summary)
        rounds.append(rebuttal)
        
        return rounds
    
    def _generate_market_summary(self, market_state: Dict) -> str:
        """生成市场摘要"""
        if not market_state:
            return "市场状态信息不完整"
        
        parts = []
        
        if "price" in market_state:
            parts.append(f"BTC价格: ${market_state['price']:,.0f}")
        if "trend" in market_state:
            parts.append(f"趋势: {market_state['trend']}")
        if "funding_rate" in market_state:
            parts.append(f"资金费率: {market_state['funding_rate']:.4f}%")
        if "fgi" in market_state:
            parts.append(f"FGI: {market_state['fgi']}")
        if "regime" in market_state:
            parts.append(f"Regime: {market_state['regime']}")
        
        return " | ".join(parts) if parts else "市场状态信息不完整"
    
    def _run_intra_camp_discussion(self,
                                   camps: Dict[str, List[str]],
                                   topic: str,
                                   market_summary: str) -> List[Dict]:
        """运行阵营内部讨论"""
        from M2_master_selector import MASTERS
        
        discussions = []
        
        for camp_name, masters in camps.items():
            if not masters:
                continue
            
            camp_masters = [MASTERS.get(m) for m in masters if MASTERS.get(m)]
            
            # 生成内部讨论
            statements = []
            for master in camp_masters:
                prompt = self._generate_master_statement_prompt(
                    master, topic, market_summary, camp_name
                )
                # 这里会调用LLM生成陈述
                statement = self._simulate_master_statement(master, camp_name, topic)
                statements.append(statement)
            
            discussions.append({
                "round_num": len(discussions) + 1,
                "phase": "intra_camp",
                "camp": camp_name,
                "masters": masters,
                "statements": statements,
                "thesis_summary": self._summarize_camp_thesis(statements, camp_name)
            })
        
        return discussions
    
    def _generate_master_statement_prompt(self,
                                        master,
                                        topic: str,
                                        market_summary: str,
                                        camp_name: str) -> str:
        """生成大师陈述提示词"""
        camp_display = {"bullish": "🟢多方", "neutral": "🟡中立", "bearish": "🔴空方"}
        
        return f"""你是{master.name}，投资风格: {master.core_style}
当前位置: {camp_display.get(camp_name, camp_name)}阵营

当前议题: {topic}
市场状态: {market_summary}

请用{master.name}的思考方式，阐述1-2个核心观点。
要求:
1. 结合你的投资哲学
2. 基于市场数据分析
3. 指出你判断的关键依据
"""
    
    def _simulate_master_statement(self, master, camp_name: str, topic: str) -> Dict:
        """
        模拟大师陈述 (实际应调用LLM)
        
        注意: 实际实现中，这里应该调用LLM API生成真实的陈述
        """
        # 基于大师风格的预设观点
        preset_opinions = {
            "soros": "市场存在反身性，当前趋势可能自我强化。关键是识别市场共识的极点。",
            "druckenmiller": "趋势是你最好的朋友。在明确的趋势中，应该果断加仓。",
            "buffett": "别人恐惧时我贪婪，别人贪婪时我恐惧。优质资产在恐慌中更有价值。",
            "ptj": "我只在最有利的位置下重注。风险管理比赚钱更重要。",
            "dalio": "理解债务周期和经济机器的运作。宏观风险是首要考虑。",
            "livermore": "记住，价格总是沿着最小阻力方向运行。观察关键点位的突破。",
            "tharp": "交易是一个概率游戏。系统化的风险管理是关键。",
            "oneil": "CANSLIM法则: 成长股在突破时是最好的买入时机。",
            "talmans": "技术分析揭示了价格行为的规律。趋势线和支撑阻力是关键。",
            "michele": "量化模型可以消除情绪干扰。统计套利提供稳定的alpha。"
        }
        
        return {
            "master_id": master.id,
            "master_name": master.name,
            "content": preset_opinions.get(master.id, f"基于{master.core_style}进行分析"),
            "evidence": self._generate_evidence(master, camp_name),
            "targets": [],  # 内部讨论无特定目标
            "timestamp": datetime.now().isoformat()
        }
    
    def _generate_evidence(self, master, camp_name: str) -> List[str]:
        """生成大师证据"""
        evidence_templates = {
            "bullish": [
                "价格突破关键技术位",
                "机构资金持续流入",
                "市场情绪转向乐观"
            ],
            "neutral": [
                "等待趋势明确",
                "控制仓位风险",
                "关注突破方向"
            ],
            "bearish": [
                "关键支撑位测试",
                "宏观风险升温",
                "技术指标超买"
            ]
        }
        return evidence_templates.get(camp_name, [])[:2]
    
    def _summarize_camp_thesis(self, statements: List[Dict], camp_name: str) -> str:
        """总结阵营论点"""
        camp_summaries = {
            "bullish": "看多观点：",
            "neutral": "中立观点：",
            "bearish": "看空观点："
        }
        
        key_points = [s.get("content", "")[:50] for s in statements[:2]]
        
        return camp_summaries.get(camp_name, "") + " | ".join(key_points)
    
    def _run_cross_debate(self,
                          camps: Dict[str, List[str]],
                          camp_discussions: List[Dict],
                          topic: str,
                          market_summary: str) -> Dict:
        """运行交叉辩论"""
        from M2_master_selector import MASTERS
        
        bull_masters = camps.get("bullish", [])
        bear_masters = camps.get("bearish", [])
        
        # 多方提问
        bull_questions = []
        for m_id in bull_masters[:2]:  # 最多2位
            master = MASTERS.get(m_id)
            if master:
                bull_questions.append({
                    "speaker": master.name,
                    "content": f"请问空方: {self._generate_attack_question(master, 'bearish')}"
                })
        
        # 空方反击
        bear_questions = []
        for m_id in bear_masters[:2]:
            master = MASTERS.get(m_id)
            if master:
                bear_questions.append({
                    "speaker": master.name,
                    "content": f"请问多方: {self._generate_attack_question(master, 'bullish')}"
                })
        
        # 提取关键争议点
        key_disputes = self._extract_key_disputes(camp_discussions)
        
        return {
            "round_num": len(camp_discussions) + 1,
            "phase": "cross_debate",
            "bull_attacks": bull_questions,
            "bear_attacks": bear_questions,
            "key_disputes": key_disputes,
            "summary": self._generate_cross_summary(bull_questions, bear_questions, key_disputes)
        }
    
    def _generate_attack_question(self, master, target_camp: str) -> str:
        """生成攻击性问题"""
        questions = {
            "bullish": {
                "bearish": [
                    "空方如何解释当前的资金流入?",
                    "如果机构持续买入，价格还能跌吗?"
                ]
            },
            "bearish": {
                "bullish": [
                    "多方忽视的最大风险是什么?",
                    "如果趋势反转，你如何保护利润?"
                ]
            }
        }
        
        camp_questions = questions.get(master.camp, {}).get(target_camp, ["你的观点有什么支撑?"])
        return camp_questions[0] if camp_questions else "请说明你的判断依据"
    
    def _extract_key_disputes(self, camp_discussions: List[Dict]) -> List[str]:
        """提取关键争议点"""
        disputes = []
        
        for discussion in camp_discussions:
            if discussion.get("phase") == "intra_camp":
                camp = discussion.get("camp", "")
                statements = discussion.get("statements", [])
                
                for stmt in statements[:1]:  # 每阵营取1个代表陈述
                    content = stmt.get("content", "")
                    if content:
                        disputes.append({
                            "camp": camp,
                            "issue": content[:80],
                            "speaker": stmt.get("master_name", "")
                        })
        
        return disputes[:3]  # 最多3个争议点
    
    def _generate_cross_summary(self,
                               bull_attacks: List[Dict],
                               bear_attacks: List[Dict],
                               key_disputes: List[Dict]) -> str:
        """生成交叉辩论总结"""
        summary = "交叉辩论要点:\n"
        
        if bull_attacks:
            summary += "\n🟢 多方攻击:\n"
            for q in bull_attacks:
                summary += f"  - {q['speaker']}: {q['content']}\n"
        
        if bear_attacks:
            summary += "\n🔴 空方攻击:\n"
            for q in bear_attacks:
                summary += f"  - {q['speaker']}: {q['content']}\n"
        
        if key_disputes:
            summary += "\n⚖️ 关键争议:\n"
            for d in key_disputes:
                summary += f"  - [{d['camp']}] {d['issue']}\n"
        
        return summary
    
    def _run_final_rebuttal(self,
                           camps: Dict[str, List[str]],
                           all_rounds: List[Dict],
                           topic: str,
                           market_summary: str) -> Dict:
        """运行最终反驳"""
        from M2_master_selector import MASTERS
        
        rebuttals = []
        
        for camp_name, masters in camps.items():
            for m_id in masters[:1]:  # 每阵营1位代表
                master = MASTERS.get(m_id)
                if master:
                    rebuttal = {
                        "speaker": master.name,
                        "camp": camp_name,
                        "final_point": self._generate_final_point(master, camp_name),
                        "concession": self._generate_concession(master, camp_name),
                        "advice": self._generate_final_advice(master, camp_name)
                    }
                    rebuttals.append(rebuttal)
        
        return {
            "round_num": len(all_rounds) + 1,
            "phase": "final_rebuttal",
            "rebuttals": rebuttals,
            "summary": self._generate_rebuttal_summary(rebuttals)
        }
    
    def _generate_final_point(self, master, camp_name: str) -> str:
        """生成最终坚守点"""
        points = {
            "soros": "市场反身性会放大当前趋势，直到达到极端",
            "druckenmiller": "趋势确认后，应该持有甚至加仓",
            "buffett": "长期看，优质资产只会越来越值钱",
            "ptj": "风险管理第一，大机会来临时才有子弹",
            "dalio": "宏观周期决定一切，顺势而为",
            "livermore": "价格沿最小阻力方向，等待确认"
        }
        return points.get(master.id, "坚持我的投资原则")
    
    def _generate_concession(self, master, camp_name: str) -> str:
        """生成让步点"""
        concessions = {
            "bullish": "承认短期波动风险，但不改长期方向",
            "neutral": "承认方向不明，需要等待确认",
            "bearish": "承认多方有资金支撑，但趋势终将反转"
        }
        return concessions.get(camp_name, "承认对方有部分道理")
    
    def _generate_final_advice(self, master, camp_name: str) -> str:
        """生成最终建议"""
        advice = {
            "soros": "关注市场共识的极点，那是反转信号",
            "druckenmiller": "趋势明确时重仓，模糊时空仓",
            "buffett": "定投优质资产，不要理会短期波动",
            "ptj": "控制仓位，设置止损，等待高确定性机会",
            "dalio": "分散配置，对冲宏观风险",
            "livermore": "记录关键点位，突破时果断入场"
        }
        return advice.get(master.id, "严格执行交易计划")
    
    def _generate_rebuttal_summary(self, rebuttals: List[Dict]) -> str:
        """生成反驳总结"""
        summary = "最终陈述总结:\n\n"
        
        for r in rebuttals:
            emoji = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(r.get("camp", ""), "")
            summary += f"{emoji} {r['speaker']}:\n"
            summary += f"  坚持: {r['final_point']}\n"
            summary += f"  让步: {r['concession']}\n"
            summary += f"  建议: {r['advice']}\n\n"
        
        return summary
