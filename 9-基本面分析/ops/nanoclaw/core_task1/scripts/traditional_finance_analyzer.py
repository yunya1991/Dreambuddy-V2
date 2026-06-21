#!/usr/bin/env python3
"""
传统金融信息分析与价值投资框架
基于经典投资理论的新闻分析方法

参考框架：
1. 格雷厄姆 - 多德：证券分析（内在价值、安全边际）
2. 费雪：怎样选择成长股（闲聊法则、定性分析）
3. 波特：竞争优势理论（护城河分析）
4. 达利欧：原则（经济机器运行规律）
5. CFA 框架：宏观 - 行业 - 公司三层分析
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta


class ImpactType(Enum):
    """影响类型"""
    POSITIVE = "positive"      # 利好
    NEGATIVE = "negative"      # 利空
    NEUTRAL = "neutral"        # 中性
    UNCERTAIN = "uncertain"    # 不确定


class TimeHorizon(Enum):
    """时间维度"""
    IMMEDIATE = "T0"    # 当日/即时
    SHORT = "T1"        # 数日/短期
    MEDIUM = "T2"       # 数周/中期
    LONG = "T3"         # 数月/长期


class ConfidenceLevel(Enum):
    """可信度等级（基于 CFA 框架）"""
    HIGH = "high"      # 官方/一手/可验证
    MEDIUM = "medium"  # 主流/多源一致
    LOW = "low"        # 单源/传闻/观点


@dataclass
class NewsItem:
    """新闻项目"""
    title: str
    content: str
    source: str
    published_at: datetime
    category: str

    # 传统金融分析维度
    impact_type: ImpactType = ImpactType.NEUTRAL
    time_horizon: TimeHorizon = TimeHorizon.MEDIUM
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    # 价值投资分析维度
    affects_moat: bool = False      # 是否影响护城河
    affects_management: bool = False # 是否影响管理层评估
    affects_financials: bool = False # 是否影响财务状况

    # 宏观分析维度（达利欧框架）
    affects_productivity: bool = False  # 生产力影响
    affects_debt_cycle: bool = False    # 债务周期影响
    affects_liquidity: bool = False     # 流动性影响

    # 评分
    signal_strength: float = 0.0  # 信号强度 (-1 到 +1)

    # 原始数据
    raw_data: Dict = field(default_factory=dict)


@dataclass
class SignalAnalysis:
    """信号分析结果"""
    timestamp: datetime
    news_items: List[NewsItem]

    # 综合信号
    composite_signal: float = 0.0  # 综合信号 (-1 到 +1)
    confidence_weighted_signal: float = 0.0  # 可信度加权信号

    # 分类信号
    macro_signal: float = 0.0       # 宏观信号
    industry_signal: float = 0.0    # 行业信号
    company_signal: float = 0.0     # 公司信号

    # 时间维度信号
    immediate_signal: float = 0.0   # 即时信号
    short_term_signal: float = 0.0  # 短期信号

    # 风险提示
    risk_flags: List[str] = field(default_factory=list)

    # 投资建议（基于信号强度）
    recommendation: str = "hold"  # buy/hold/sell
    position_suggestion: float = 0.0  # 建议仓位 (0-1)


class TraditionalFinanceAnalyzer:
    """
    传统金融分析器

    核心原则：
    1. 安全边际：负面消息权重更高
    2. 长期视角：区分短期噪音和长期趋势
    3. 护城河思维：关注结构性变化而非暂时波动
    4. 逆向思考：市场共识可能错误
    5. 能力圈：只在自己理解的领域下注
    """

    def __init__(self):
        # 可信度权重（基于 CFA 框架）
        self.confidence_weights = {
            ConfidenceLevel.HIGH: 1.0,
            ConfidenceLevel.MEDIUM: 0.6,
            ConfidenceLevel.LOW: 0.3
        }

        # 时间衰减因子
        self.time_decay = {
            TimeHorizon.IMMEDIATE: 1.0,
            TimeHorizon.SHORT: 0.7,
            TimeHorizon.MEDIUM: 0.4,
            TimeHorizon.LONG: 0.2
        }

        # 影响类型基础分值
        self.impact_scores = {
            ImpactType.POSITIVE: 0.5,
            ImpactType.NEUTRAL: 0.0,
            ImpactType.NEGATIVE: -0.5,
            ImpactType.UNCERTAIN: 0.0
        }

        # 负面偏见系数（安全边际原则）
        self.negative_bias = 1.3  # 负面消息权重增加 30%

    def analyze_news(self, news_data: Dict) -> NewsItem:
        """
        分析单条新闻，应用传统金融框架

        分析维度：
        1. 信息来源可靠性（CFA 框架）
        2. 影响时间维度
        3. 护城河影响
        4. 宏观周期位置
        """
        item = NewsItem(
            title=news_data.get("title", ""),
            content=news_data.get("summary", news_data.get("key_fact", "")),
            source=news_data.get("source_url", ""),
            published_at=datetime.fromisoformat(news_data.get("published_at", datetime.now().isoformat())),
            category=news_data.get("category", news_data.get("topic", "general"))
        )

        # 1. 可信度评估
        source_conf = news_data.get("source_confidence", "medium")
        if source_conf == "high":
            item.confidence = ConfidenceLevel.HIGH
        elif source_conf == "low":
            item.confidence = ConfidenceLevel.LOW
        else:
            item.confidence = ConfidenceLevel.MEDIUM

        # 2. 时间维度评估
        horizon = news_data.get("impact_horizon", "T1")
        item.time_horizon = TimeHorizon(horizon) if horizon in [h.value for h in TimeHorizon] else TimeHorizon.MEDIUM

        # 3. 影响类型和信号强度分析
        item.impact_type, item.signal_strength = self._analyze_signal_strength(news_data)

        # 4. 护城河影响评估
        item.affects_moat = self._check_moat_impact(news_data)

        # 5. 宏观周期评估（达利欧框架）
        item.affects_debt_cycle = self._check_debt_cycle_impact(news_data)
        item.affects_liquidity = self._check_liquidity_impact(news_data)

        # 6. 应用负面偏见（安全边际）
        if item.impact_type == ImpactType.NEGATIVE:
            item.signal_strength *= self.negative_bias

        item.raw_data = news_data
        return item

    def _analyze_signal_strength(self, news_data: Dict) -> Tuple[ImpactType, float]:
        """
        分析信号强度

        基于：
        - 新闻内容关键词
        - 影响路径描述
        - 风险旗标
        """
        text = (news_data.get("title", "") + " " +
                news_data.get("summary", "") + " " +
                news_data.get("key_fact", "") + " " +
                news_data.get("market_impact", "")).lower()

        # 利好关键词
        positive_keywords = [
            "利好", "上涨", "突破", "新高", "流入", "强劲", "超预期",
            "宽松", "放松", "支持", "增长", "繁荣", "复苏"
        ]

        # 利空关键词
        negative_keywords = [
            "利空", "下跌", "抛售", "调查", "风险", "担忧", "收紧",
            "调查", "监管", "制裁", "衰退", "危机", "违约", "恶化",
            "承压", "利空", "抛售", "暴跌"
        ]

        # 不确定性关键词
        uncertain_keywords = [
            "传闻", "可能", "考虑", "拟", "或", "预计", "分析师称"
        ]

        pos_score = sum(1 for kw in positive_keywords if kw in text)
        neg_score = sum(1 for kw in negative_keywords if kw in text)
        unc_score = sum(1 for kw in uncertain_keywords if kw in text)

        # 检查风险旗标
        risk_flags = news_data.get("risk_flags", [])
        if risk_flags:
            unc_score += len(risk_flags)
            neg_score += len([f for f in risk_flags if "风险" in f or "恶化" in f])

        # 计算净信号
        net_score = pos_score - neg_score

        # 确定影响类型
        if net_score > 1:
            impact_type = ImpactType.POSITIVE
        elif net_score < -1:
            impact_type = ImpactType.NEGATIVE
        elif unc_score > pos_score + neg_score:
            impact_type = ImpactType.UNCERTAIN
        else:
            impact_type = ImpactType.NEUTRAL

        # 计算信号强度（-1 到 +1）
        total = pos_score + neg_score + unc_score
        if total == 0:
            signal_strength = 0.0
        else:
            signal_strength = (pos_score - neg_score) / total

        return impact_type, signal_strength

    def _check_moat_impact(self, news_data: Dict) -> bool:
        """检查是否影响护城河（结构性竞争优势）"""
        text = (news_data.get("title", "") + " " +
                news_data.get("content", "")).lower()

        moat_keywords = [
            "市场份额", "垄断", "壁垒", "专利", "技术领先",
            "网络效应", "转换成本", "规模优势", "品牌"
        ]
        return any(kw in text for kw in moat_keywords)

    def _check_debt_cycle_impact(self, news_data: Dict) -> bool:
        """检查是否影响债务周期"""
        text = (news_data.get("title", "") + " " +
                news_data.get("content", "")).lower()

        debt_keywords = [
            "利率", "降息", "加息", "信贷", "债务", "杠杆",
            "美联储", "货币政策", "流动性", "量化宽松"
        ]
        return any(kw in text for kw in debt_keywords)

    def _check_liquidity_impact(self, news_data: Dict) -> bool:
        """检查是否影响流动性"""
        text = (news_data.get("title", "") + " " +
                news_data.get("content", "")).lower()

        liquidity_keywords = [
            "ETF", "流入", "流出", "资金", "成交量", "交易量",
            "储备", "供给", "需求", "持仓"
        ]
        return any(kw in text for kw in liquidity_keywords)

    def generate_signal(self, news_items: List[NewsItem]) -> SignalAnalysis:
        """
        生成综合信号分析

        遵循原则：
        1. 可信度加权
        2. 时间衰减
        3. 负面偏见
        4. 宏观 - 行业 - 公司三层分离
        """
        analysis = SignalAnalysis(
            timestamp=datetime.now(),
            news_items=news_items
        )

        if not news_items:
            return analysis

        # 计算各项信号
        weighted_signals = []
        macro_signals = []
        industry_signals = []
        company_signals = []
        immediate_signals = []
        short_term_signals = []
        merged_risk_flags: dict[str, list[str]] = {}

        for item in news_items:
            # 可信度加权信号
            conf_weight = self.confidence_weights[item.confidence]
            time_weight = self.time_decay[item.time_horizon]
            weighted_signal = item.signal_strength * conf_weight * time_weight
            weighted_signals.append(weighted_signal)

            # 分类信号
            if item.category in ["fed", "us_data", "geopolitics", "us_policy"]:
                macro_signals.append(weighted_signal)
            elif item.category in ["onchain_data", "project_update"]:
                industry_signals.append(weighted_signal)
            elif item.category in ["kols_view", "market_analysis"]:
                company_signals.append(weighted_signal)

            # 时间维度信号
            if item.time_horizon == TimeHorizon.IMMEDIATE:
                immediate_signals.append(weighted_signal)
            if item.time_horizon in [TimeHorizon.IMMEDIATE, TimeHorizon.SHORT]:
                short_term_signals.append(weighted_signal)

            # 收集风险旗标
            flags = item.raw_data.get("risk_flags", [])
            if isinstance(flags, list) and flags:
                title = str(item.title or "").strip()
                if title:
                    bucket = merged_risk_flags.get(title)
                    if bucket is None:
                        bucket = []
                        merged_risk_flags[title] = bucket
                    for f in flags:
                        s = str(f).strip()
                        if not s:
                            continue
                        if s not in bucket:
                            bucket.append(s)

        # 综合信号（简单平均）
        analysis.composite_signal = sum(weighted_signals) / len(weighted_signals) if weighted_signals else 0

        # 可信度加权信号（考虑负面偏见）
        analysis.confidence_weighted_signal = sum(weighted_signals) / len(weighted_signals) if weighted_signals else 0

        # 分类信号
        analysis.macro_signal = sum(macro_signals) / len(macro_signals) if macro_signals else 0
        analysis.industry_signal = sum(industry_signals) / len(industry_signals) if industry_signals else 0
        analysis.company_signal = sum(company_signals) / len(company_signals) if company_signals else 0

        # 时间维度信号
        analysis.immediate_signal = sum(immediate_signals) / len(immediate_signals) if immediate_signals else 0
        analysis.short_term_signal = sum(short_term_signals) / len(short_term_signals) if short_term_signals else 0

        if merged_risk_flags:
            analysis.risk_flags = [
                f"{title}: {' / '.join(reasons)}" if reasons else f"{title}: unknown"
                for title, reasons in merged_risk_flags.items()
            ]

        # 生成投资建议
        analysis.recommendation, analysis.position_suggestion = self._generate_recommendation(analysis)

        return analysis

    def _generate_recommendation(self, analysis: SignalAnalysis) -> Tuple[str, float]:
        """
        生成投资建议

        基于：
        1. 综合信号强度
        2. 信号一致性（宏观/行业/公司）
        3. 风险提示

        仓位建议遵循凯利公式简化版
        """
        signal = analysis.confidence_weighted_signal

        # 检查信号一致性
        signals = [analysis.macro_signal, analysis.industry_signal, analysis.company_signal]
        non_zero = [s for s in signals if s != 0]
        if len(non_zero) >= 2:
            # 所有信号同向时增加信心
            all_same_direction = all(s > 0 for s in non_zero) or all(s < 0 for s in non_zero)
            if all_same_direction:
                signal *= 1.2  # 一致性加成

        # 风险提示减分
        if len(analysis.risk_flags) > 3:
            signal *= 0.8  # 过多风险旗标时降低信心

        # 生成建议
        if signal > 0.3:
            recommendation = "buy"
            position = min(0.3 + (signal - 0.3) * 0.5, 0.8)  # 最大 80% 仓位
        elif signal < -0.3:
            recommendation = "sell"
            position = max(0.1 + signal * 0.3, 0)  # 最小 0% 仓位，最多 30%
        else:
            recommendation = "hold"
            position = 0.5  # 中性 50% 仓位

        return recommendation, position


def example_usage():
    """使用示例"""
    analyzer = TraditionalFinanceAnalyzer()

    # 示例新闻
    news_data = {
        "title": "比特币 ETF 单日净流入超 5 亿美元",
        "summary": "贝莱德 IBIT 单日流入 3.2 亿美元，总资产管理规模突破 500 亿",
        "source_url": "https://example.com/news/123",
        "published_at": datetime.now().isoformat(),
        "category": "onchain_data",
        "source_confidence": "high",
        "impact_horizon": "T0",
        "market_impact": "短期利好 BTC 价格",
        "risk_flags": []
    }

    item = analyzer.analyze_news(news_data)
    print(f"新闻：{item.title}")
    print(f"信号强度：{item.signal_strength:.2f}")
    print(f"影响类型：{item.impact_type.value}")
    print(f"可信度：{item.confidence.value}")
    print(f"影响流动性：{item.affects_liquidity}")

    # 生成信号
    analysis = analyzer.generate_signal([item])
    print(f"\n综合信号：{analysis.composite_signal:.2f}")
    print(f"建议：{analysis.recommendation}")
    print(f"建议仓位：{analysis.position_suggestion:.0%}")


if __name__ == "__main__":
    example_usage()
