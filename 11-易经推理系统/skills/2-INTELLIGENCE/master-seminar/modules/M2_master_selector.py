"""
M2: 大师选择器 (Master Selector)
根据Regime和触发条件选择相关大师
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class MasterProfile:
    """大师画像"""
    id: str
    name: str
    camp: str  # bullish/neutral/bearish
    core_style: str
    strong_regimes: List[str]
    weak_regimes: List[str]
    weight: float = 1.0
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


# 已蒸馏的10位大师
MASTERS = {
    "soros": MasterProfile(
        id="soros",
        name="George Soros",
        camp="bullish",
        core_style="反身性理论、宏观择时",
        strong_regimes=["HIGH_VOL", "BEAR", "CRISIS_RECOVERY"],
        weak_regimes=["STABLE_BULL", "DEFLATION"]
    ),
    "druckenmiller": MasterProfile(
        id="druckenmiller",
        name="Stanley Druckenmiller",
        camp="bullish",
        core_style="趋势追踪、杠杆大师",
        strong_regimes=["TREND_BULL", "HIGH_VOL", "BULL"],
        weak_regimes=["BEAR", "RANGE"]
    ),
    "buffett": MasterProfile(
        id="buffett",
        name="Warren Buffett",
        camp="bullish",
        core_style="价值投资、长期持有",
        strong_regimes=["NEUTRAL", "BULL_REGIME", "STABLE_BULL"],
        weak_regimes=["HIGH_VOL", "CRISIS"]
    ),
    "oneil": MasterProfile(
        id="oneil",
        name="William O'Neil",
        camp="bullish",
        core_style="CANSLIM、成长股投资",
        strong_regimes=["BULL_REGIME", "TREND_BULL"],
        weak_regimes=["BEAR", "HIGH_VOL"]
    ),
    "livermore": MasterProfile(
        id="livermore",
        name="Jesse Livermore",
        camp="neutral",
        core_style="趋势识别、关键点交易",
        strong_regimes=["TREND", "RANGE", "BREAKOUT"],
        weak_regimes=["CRISIS", "SIDEWAYS"]
    ),
    "tharp": MasterProfile(
        id="tharp",
        name="Van Tharp",
        core_style="交易系统、仓位管理",
        camp="neutral",
        strong_regimes=["ALL"],
        weak_regimes=[],
        tags=["system_trader", "risk_manager"]
    ),
    "ptj": MasterProfile(
        id="ptj",
        name="Paul Tudor Jones",
        camp="bearish",
        core_style="宏观择时、危机Alpha",
        strong_regimes=["HIGH_VOL", "BEAR", "CRISIS"],
        weak_regimes=["STABLE_BULL", "BULL_REGIME"]
    ),
    "dalio": MasterProfile(
        id="dalio",
        name="Ray Dalio",
        camp="bearish",
        core_style="宏观对冲、风险平价",
        strong_regimes=["CRISIS", "DEFLATION", "HIGH_VOL"],
        weak_regimes=["INFLATION", "BULL_REGIME"]
    ),
    "talmans": MasterProfile(
        id="talmans",
        name="Walter Talmans",
        camp="neutral",
        core_style="技术分析、趋势跟踪",
        strong_regimes=["TREND", "BREAKOUT"],
        weak_regimes=["RANGE", "SIDEWAYS"]
    ),
    "michele": MasterProfile(
        id="michele",
        name="Michele",
        camp="neutral",
        core_style="量化系统、统计套利",
        strong_regimes=["RANGE", "SIDEWAYS", "MEAN_REVERSION"],
        weak_regimes=["TREND", "CRISIS"],
        tags=["quantitative", "statistical"]
    )
}

# Regime到大师阵营的映射
REGIME_MASTER_PREFERENCE = {
    "TREND_BULL": ["bullish", "neutral"],
    "BULL_REGIME": ["bullish", "neutral"],
    "STABLE_BULL": ["bullish", "neutral"],
    "HIGH_VOL_BULL": ["bullish", "bearish"],
    "BEAR": ["bearish", "neutral"],
    "HIGH_VOL_BEAR": ["bearish", "neutral"],
    "CRISIS": ["bearish", "neutral"],
    "CRISIS_RECOVERY": ["bullish", "neutral"],
    "RANGE": ["neutral"],
    "SIDEWAYS": ["neutral", "bullish"],
    "NEUTRAL": ["neutral", "bullish", "bearish"],
    "DEFLATION": ["bearish", "neutral"],
    "INFLATION": ["bullish", "bearish"]
}

# 触发类型到大师偏好的映射
TRIGGER_MASTER_PREFERENCE = {
    "REGIME_CHANGE": ["bullish", "bearish", "neutral"],  # 全量大师
    "A5_EXECUTION": ["bullish", "bearish"],  # 执行后需要多空判断
    "MANUAL": ["bullish", "bearish", "neutral"],  # 手动触发全量
    "CONSECUTIVE_SKIP": ["bullish", "bearish"]  # 连续跳过需要激进大师
}


class MasterSelector:
    """
    大师选择器
    
    职责:
    1. 根据当前Regime选择擅长的大师
    2. 根据触发类型调整大师组合
    3. 考虑大师权重和历史表现
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.masters = MASTERS.copy()
        self.regime_preference = REGIME_MASTER_PREFERENCE.copy()
        self.trigger_preference = TRIGGER_MASTER_PREFERENCE.copy()
        
        # 加载自定义配置
        if config_path:
            self._load_config(config_path)
    
    def _load_config(self, config_path: str):
        """加载自定义配置"""
        config_file = Path(config_path)
        if config_file.exists():
            config = json.loads(config_file.read_text())
            # 更新大师权重
            if "master_weights" in config:
                for master_id, weight in config["master_weights"].items():
                    if master_id in self.masters:
                        self.masters[master_id].weight = weight
    
    def select(self,
              regime: str,
              market_state: Dict[str, Any] = None,
              trigger_type: str = "MANUAL",
              max_masters: int = 6) -> List[str]:
        """
        选择大师
        
        Args:
            regime: 当前Regime
            market_state: 市场状态
            trigger_type: 触发类型
            max_masters: 最大大师数量
            
        Returns:
            选中的大师ID列表
        """
        if not regime:
            regime = "NEUTRAL"
        
        selected = []
        
        # 1. 根据Regime偏好选择阵营
        preferred_camps = self.regime_preference.get(regime, ["neutral"])
        if trigger_type in self.trigger_preference:
            preferred_camps = self.trigger_preference[trigger_type]
        
        # 2. 每个阵营选择1-2位大师
        for camp in preferred_camps:
            camp_masters = [
                m for m in self.masters.values() 
                if m.camp == camp
            ]
            
            # 根据Regime擅长程度排序
            camp_masters = self._sort_by_regime_fit(camp_masters, regime)
            
            # 选择前N个
            num_to_select = min(2, len(camp_masters), max_masters - len(selected))
            for master in camp_masters[:num_to_select]:
                if master.id not in selected:
                    selected.append(master.id)
            
            if len(selected) >= max_masters:
                break
        
        # 3. 确保至少有一位大师
        if not selected:
            selected = ["tharp", "livermore"]  # 默认选择中立大师
        
        return selected[:max_masters]
    
    def _sort_by_regime_fit(self, 
                           masters: List[MasterProfile],
                           regime: str) -> List[MasterProfile]:
        """根据Regime适配度排序"""
        def regime_score(master: MasterProfile) -> float:
            score = master.weight
            
            # 强Regime加分
            if regime in master.strong_regimes:
                score += 0.5
            
            # 弱Regime减分
            if regime in master.weak_regimes:
                score -= 0.3
            
            # 全能大师加权
            if "ALL" in master.strong_regimes:
                score += 0.2
            
            return score
        
        return sorted(masters, key=regime_score, reverse=True)
    
    def get_master(self, master_id: str) -> Optional[MasterProfile]:
        """获取大师画像"""
        return self.masters.get(master_id)
    
    def get_all_masters(self) -> Dict[str, MasterProfile]:
        """获取所有大师"""
        return self.masters.copy()
    
    def get_masters_by_camp(self, camp: str) -> List[MasterProfile]:
        """按阵营获取大师"""
        return [m for m in self.masters.values() if m.camp == camp]
    
    def update_weight(self, master_id: str, new_weight: float):
        """更新大师权重"""
        if master_id in self.masters:
            self.masters[master_id].weight = max(0.1, min(2.0, new_weight))
    
    def add_tag(self, master_id: str, tag: str):
        """为大师添加标签"""
        if master_id in self.masters and tag not in self.masters[master_id].tags:
            self.masters[master_id].tags.append(tag)
    
    def remove_tag(self, master_id: str, tag: str):
        """移除大师标签"""
        if master_id in self.masters and tag in self.masters[master_id].tags:
            self.masters[master_id].tags.remove(tag)
