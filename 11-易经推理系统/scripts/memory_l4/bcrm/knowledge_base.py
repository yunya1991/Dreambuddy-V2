"""
BCRM 知识库。

包含：
- 六十四卦知识
- 技术指标知识
- 交易规则
- 宏观知识
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class KnowledgeEntry:
    """知识条目。"""
    id: str = ""
    category: str = ""
    title: str = ""
    content: str = ""
    confidence: float = 0.8
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "confidence": self.confidence,
            "tags": self.tags,
        }


@dataclass
class GuaKnowledge:
    """卦象知识。"""
    gua: str = ""
    name_cn: str = ""
    nature: str = ""
    wuxing: str = ""
    market_meaning: str = ""
    typical_patterns: List[str] = field(default_factory=list)
    trading_implications: List[str] = field(default_factory=list)
    risk_points: List[str] = field(default_factory=list)
    historical_win_rate: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gua": self.gua,
            "name_cn": self.name_cn,
            "nature": self.nature,
            "wuxing": self.wuxing,
            "market_meaning": self.market_meaning,
            "typical_patterns": self.typical_patterns,
            "trading_implications": self.trading_implications,
            "risk_points": self.risk_points,
            "historical_win_rate": self.historical_win_rate,
        }


class BCRMKnowledgeBase:
    """
    BCRM 知识库。
    """

    def __init__(self):
        self._technical = {}
        self._rules = {}
        self._macro = {}
        self._gua_knowledge = {}
        self._init_default_knowledge()

    def _init_default_knowledge(self):
        """初始化默认知识。"""
        # 技术指标知识
        self._add_technical(KnowledgeEntry(
            id="tech_ma",
            category="technical",
            title="移动平均线（MA）",
            content="移动平均线是最常用的趋势指标，反映一段时间内的平均价格。",
            tags=["technical", "trend", "ma"],
        ))
        self._add_technical(KnowledgeEntry(
            id="tech_macd",
            category="technical",
            title="MACD 指标",
            content="MACD 由快线、慢线和柱状图组成，用于判断趋势强度和转折。",
            tags=["technical", "momentum", "macd"],
        ))
        self._add_technical(KnowledgeEntry(
            id="tech_rsi",
            category="technical",
            title="相对强弱指标（RSI）",
            content="RSI 衡量价格变动的速度和变化，范围 0-100。",
            tags=["technical", "oscillator", "rsi"],
        ))

        # 交易规则
        self._add_rule(KnowledgeEntry(
            id="rule_risk_1",
            category="rule",
            title="止损原则",
            content="单笔交易亏损不超过总资金的 2%。",
            tags=["risk", "rule"],
        ))
        self._add_rule(KnowledgeEntry(
            id="rule_trend_1",
            category="rule",
            title="顺势而为",
            content="不逆大趋势操作，趋势不明朗时观望。",
            tags=["trend", "rule"],
        ))
        self._add_rule(KnowledgeEntry(
            id="rule_position_1",
            category="rule",
            title="仓位管理",
            content="根据置信度调整仓位，高置信度重仓，低置信度轻仓。",
            tags=["position", "rule", "risk"],
        ))

        # 八卦知识
        from ._constants import (
            GUA_QIAN, GUA_KUN, GUA_ZHEN, GUA_XUN,
            GUA_KAN, GUA_LI, GUA_GEN, GUA_DUI,
            GUA_NAMES_CN, GUA_NATURE, GUA_WUXING,
        )

        gua_info = {
            GUA_QIAN: {
                "market_meaning": "乾卦代表纯阳，强势上涨，趋势明确",
                "typical_patterns": ["突破新高", "放量上涨", "均线多头排列"],
                "trading_implications": ["顺势做多", "持仓待涨", "注意顶部信号"],
                "risk_points": ["阳极而阴", "物极必反", "警惕顶部背离"],
                "win_rate": 0.62,
            },
            GUA_KUN: {
                "market_meaning": "坤卦代表纯阴，下跌趋势，空头主导",
                "typical_patterns": ["跌破支撑", "放量下跌", "均线空头排列"],
                "trading_implications": ["顺势做空", "空仓观望", "等待底部信号"],
                "risk_points": ["阴极而阳", "超跌反弹", "警惕底部背离"],
                "win_rate": 0.58,
            },
            GUA_ZHEN: {
                "market_meaning": "震卦代表震动，剧烈波动，变盘在即",
                "typical_patterns": ["大幅震荡", "成交量放大", "方向选择"],
                "trading_implications": ["轻仓操作", "设置止损", "等待方向明确"],
                "risk_points": ["假突破", "多空双杀", "波动剧烈"],
                "win_rate": 0.48,
            },
            GUA_XUN: {
                "market_meaning": "巽卦代表风，缓慢上涨，润物无声",
                "typical_patterns": ["稳步攀升", "量能温和", "趋势延续"],
                "trading_implications": ["持有为主", "逢低加仓", "耐心持有"],
                "risk_points": ["涨速慢", "易被洗盘", "需耐心"],
                "win_rate": 0.55,
            },
            GUA_KAN: {
                "market_meaning": "坎卦代表水，险象环生，下跌风险",
                "typical_patterns": ["阴跌不止", "层层破位", "风险较大"],
                "trading_implications": ["谨慎操作", "严格止损", "空仓为佳"],
                "risk_points": ["持续下跌", "深不见底", "多凶险"],
                "win_rate": 0.45,
            },
            GUA_LI: {
                "market_meaning": "离卦代表火，光明正大，上涨热情",
                "typical_patterns": ["放量上涨", "情绪高涨", "趋势强劲"],
                "trading_implications": ["顺势做多", "积极参与", "注意热度"],
                "risk_points": ["过热回调", "情绪退潮", "追高风险"],
                "win_rate": 0.60,
            },
            GUA_GEN: {
                "market_meaning": "艮卦代表山，止跌企稳，横盘整理",
                "typical_patterns": ["横盘震荡", "止跌企稳", "方向不明"],
                "trading_implications": ["观望为主", "等待突破", "高抛低吸"],
                "risk_points": ["横盘时间长", "假突破", "操作空间小"],
                "win_rate": 0.50,
            },
            GUA_DUI: {
                "market_meaning": "兑卦代表泽，乐观上涨，人气旺盛",
                "typical_patterns": ["乐观情绪", "人气旺盛", "利好频出"],
                "trading_implications": ["顺势做多", "关注情绪", "及时止盈"],
                "risk_points": ["乐极生悲", "利好出尽", "情绪反转"],
                "win_rate": 0.56,
            },
        }

        for gua, info in gua_info.items():
            self._gua_knowledge[gua] = GuaKnowledge(
                gua=gua,
                name_cn=GUA_NAMES_CN.get(gua, ""),
                nature=GUA_NATURE.get(gua, ""),
                wuxing=GUA_WUXING.get(gua, ""),
                market_meaning=info["market_meaning"],
                typical_patterns=info["typical_patterns"],
                trading_implications=info["trading_implications"],
                risk_points=info["risk_points"],
                historical_win_rate=info["win_rate"],
            )

    def _add_technical(self, entry: KnowledgeEntry):
        self._technical[entry.id] = entry

    def _add_rule(self, entry: KnowledgeEntry):
        self._rules[entry.id] = entry

    def get_gua_knowledge(self, gua: str) -> Optional[GuaKnowledge]:
        """获取卦象知识。"""
        return self._gua_knowledge.get(gua)

    def get_all_gua_knowledge(self) -> Dict[str, GuaKnowledge]:
        """获取所有卦象知识。"""
        return dict(self._gua_knowledge)

    def get_technical_knowledge(self, tech_id: str) -> Optional[KnowledgeEntry]:
        """获取技术指标知识。"""
        return self._technical.get(tech_id)

    def search_technical(self, keyword: str) -> List[KnowledgeEntry]:
        """搜索技术知识。"""
        keyword = keyword.lower()
        results = []
        for entry in self._technical.values():
            if (keyword in entry.title.lower() or
                keyword in entry.content.lower() or
                any(keyword in t.lower() for t in entry.tags)):
                results.append(entry)
        return results

    def get_rules(self, category: str = None) -> List[KnowledgeEntry]:
        """获取规则。"""
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if category in r.tags]
        return rules

    def get_macro_knowledge(self, topic: str = None) -> List[KnowledgeEntry]:
        """获取宏观知识。"""
        macros = list(self._macro.values())
        if topic:
            macros = [m for m in macros if topic in m.title or topic in m.content]
        return macros

    def query_by_gua_and_stage(self, gua: str, stage: str) -> List[GuaKnowledge]:
        """按卦象和阶段查询知识。"""
        results = []
        gk = self._gua_knowledge.get(gua)
        if gk:
            results.append(gk)
        return results

    def add_knowledge(self, entry: KnowledgeEntry, category: str = "rule"):
        """添加知识。"""
        if category == "technical":
            self._technical[entry.id] = entry
        elif category == "rule":
            self._rules[entry.id] = entry
        else:
            self._macro[entry.id] = entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gua_knowledge": {k: v.to_dict() for k, v in self._gua_knowledge.items()},
            "technical_knowledge": {k: v.to_dict() for k, v in self._technical.items()},
            "rule_knowledge": {k: v.to_dict() for k, v in self._rules.items()},
            "macro_knowledge": {k: v.to_dict() for k, v in self._macro.items()},
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


_kb_instance = None


def default_knowledge_base() -> BCRMKnowledgeBase:
    """获取默认知识库单例。"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = BCRMKnowledgeBase()
    return _kb_instance
