"""
M3: 阵营生成器 (Camp Generator)
分配大师到多空/中立阵营
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

@dataclass
class Camp:
    """阵营"""
    name: str  # bullish/neutral/bearish
    masters: List[str] = field(default_factory=list)
    thesis: str = ""
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    rebuttals: List[str] = field(default_factory=list)

@dataclass
class CampAllocation:
    """阵营分配结果"""
    bullish: Camp
    neutral: Camp
    bearish: Camp
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bullish": {
                "masters": self.bullish.masters,
                "thesis": self.bullish.thesis,
                "evidence": self.bullish.evidence,
                "confidence": self.bullish.confidence
            },
            "neutral": {
                "masters": self.neutral.masters,
                "thesis": self.neutral.thesis,
                "evidence": self.neutral.evidence,
                "confidence": self.neutral.confidence
            },
            "bearish": {
                "masters": self.bearish.masters,
                "thesis": self.bearish.thesis,
                "evidence": self.bearish.evidence,
                "confidence": self.bearish.confidence
            }
        }


# 阵营立场定义
CAMP_STANCES = {
    "bullish": {
        "emoji": "🟢",
        "default_thesis": "市场将延续上涨趋势",
        "key_signals": ["突破关键阻力", "资金流入", "情绪乐观"]
    },
    "neutral": {
        "emoji": "🟡",
        "default_thesis": "市场方向不明，等待信号确认",
        "key_signals": ["区间震荡", "多空博弈", "等待突破"]
    },
    "bearish": {
        "emoji": "🔴",
        "default_thesis": "市场面临回调或下跌风险",
        "key_signals": ["跌破支撑", "资金流出", "情绪恐慌"]
    }
}


class CampGenerator:
    """
    阵营生成器
    
    职责:
    1. 将大师分配到多空/中立阵营
    2. 根据市场状态调整阵营配置
    3. 生成各阵营的初始立场
    """
    
    def __init__(self):
        self.stances = CAMP_STANCES.copy()
    
    def generate(self,
                masters: List[str],
                market_state: Dict[str, Any] = None,
                force_balance: bool = True) -> Dict[str, List[str]]:
        """
        生成阵营分配
        
        Args:
            masters: 已选择的大师列表
            market_state: 市场状态
            force_balance: 是否强制平衡阵营
            
        Returns:
            阵营分配字典 {"bullish": [...], "neutral": [...], "bearish": [...]}
        """
        market_state = market_state or {}
        
        # 从大师选择器获取大师信息
        from M2_master_selector import MASTERS
        
        camps = {
            "bullish": [],
            "neutral": [],
            "bearish": []
        }
        
        # 1. 根据大师预设阵营分配
        for master_id in masters:
            master = MASTERS.get(master_id)
            if master:
                camps[master.camp].append(master_id)
        
        # 2. 平衡阵营 (可选)
        if force_balance:
            camps = self._balance_camps(camps, masters)
        
        # 3. 记录阵营分配
        self.current_allocation = camps
        
        return camps
    
    def _balance_camps(self,
                      camps: Dict[str, List[str]],
                      all_masters: List[str]) -> Dict[str, List[str]]:
        """
        平衡各阵营的大师数量
        
        规则:
        - 如果某阵营为空，从其他阵营调配
        - 尽量保持3阵营都有大师
        - 中立阵营最多1-2位大师
        """
        from M2_master_selector import MASTERS
        
        # 检查空阵营
        empty_camps = [c for c, ms in camps.items() if not ms]
        
        # 如果有空阵营，尝试从其他阵营调配
        if empty_camps and len(all_masters) >= 2:
            # 中立阵营为空时，从其他阵营各调一位
            if "neutral" in empty_camps and len(all_masters) >= 3:
                for camp in ["bullish", "bearish"]:
                    if camps[camp]:
                        master_to_move = camps[camp].pop(0)
                        camps["neutral"].append(master_to_move)
                        break
        
        return camps
    
    def generate_initial_thesis(self,
                              camp_name: str,
                              market_state: Dict[str, Any],
                              masters: List[str]) -> str:
        """
        生成阵营初始立场
        
        Args:
            camp_name: 阵营名称
            market_state: 市场状态
            masters: 该阵营的大师列表
            
        Returns:
            初始立场文本
        """
        from M2_master_selector import MASTERS
        
        stance = self.stances.get(camp_name, self.stances["neutral"])
        
        # 获取大师风格描述
        master_styles = []
        for master_id in masters[:3]:  # 最多3位
            master = MASTERS.get(master_id)
            if master:
                master_styles.append(f"{master.name}({master.core_style})")
        
        # 生成立场
        if master_styles:
            thesis = f"{stance['emoji']} {stance['default_thesis']}\n"
            thesis += f"代表大师: {', '.join(master_styles)}\n"
            thesis += f"核心观点: "
        else:
            thesis = f"{stance['emoji']} {stance['default_thesis']}"
        
        return thesis
    
    def generate_evidence(self,
                         camp_name: str,
                         market_state: Dict[str, Any]) -> List[str]:
        """
        生成阵营支撑证据
        
        Args:
            camp_name: 阵营名称
            market_state: 市场状态
            
        Returns:
            证据列表
        """
        stance = self.stances.get(camp_name, self.stances["neutral"])
        evidence = []
        
        # 根据市场状态生成证据
        if market_state:
            price = market_state.get("price", 0)
            trend = market_state.get("trend", "NEUTRAL")
            funding_rate = market_state.get("funding_rate", 0)
            fgi = market_state.get("fgi", 50)
            
            if camp_name == "bullish":
                if trend in ["UP", "BULL"]:
                    evidence.append(f"趋势向上: 价格{trend}")
                if funding_rate > 0:
                    evidence.append(f"资金费率正: 多头主导 ({funding_rate:.4f}%)")
                if fgi > 60:
                    evidence.append(f"恐惧贪婪指数乐观: {fgi}")
                    
            elif camp_name == "bearish":
                if trend in ["DOWN", "BEAR"]:
                    evidence.append(f"趋势向下: 价格{trend}")
                if funding_rate < 0:
                    evidence.append(f"资金费率负: 空头主导 ({funding_rate:.4f}%)")
                if fgi < 40:
                    evidence.append(f"恐惧贪婪指数恐慌: {fgi}")
                    
            else:  # neutral
                evidence.append(f"价格区间: ${price:,.0f}")
                evidence.append(f"资金费率中性: {funding_rate:.4f}%")
                evidence.append(f"情绪指数: {fgi} (中性区间)")
        
        # 添加默认信号
        evidence.extend(stance.get("key_signals", []))
        
        return evidence[:5]  # 最多5条证据
    
    def create_allocation(self,
                         camps: Dict[str, List[str]],
                         market_state: Dict[str, Any] = None) -> CampAllocation:
        """
        创建完整的阵营分配对象
        
        Args:
            camps: 阵营分配
            market_state: 市场状态
            
        Returns:
            CampAllocation对象
        """
        market_state = market_state or {}
        
        bullish = Camp(
            name="bullish",
            masters=camps.get("bullish", []),
            thesis=self.generate_initial_thesis("bullish", market_state, camps.get("bullish", [])),
            evidence=self.generate_evidence("bullish", market_state)
        )
        
        neutral = Camp(
            name="neutral",
            masters=camps.get("neutral", []),
            thesis=self.generate_initial_thesis("neutral", market_state, camps.get("neutral", [])),
            evidence=self.generate_evidence("neutral", market_state)
        )
        
        bearish = Camp(
            name="bearish",
            masters=camps.get("bearish", []),
            thesis=self.generate_initial_thesis("bearish", market_state, camps.get("bearish", [])),
            evidence=self.generate_evidence("bearish", market_state)
        )
        
        return CampAllocation(bullish=bullish, neutral=neutral, bearish=bearish)
