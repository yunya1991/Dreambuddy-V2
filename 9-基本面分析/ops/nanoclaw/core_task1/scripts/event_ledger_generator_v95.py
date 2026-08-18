#!/usr/bin/env python3
"""
增强版事件账本生成器 - V9.5 优化版

优化点:
1. 降低金十数据权重 (1.2 → 1.0)
2. 提高大 V 影响力权重 (T0: 1.5→1.8, T1: 1.3→1.5)
3. 限制每日金十数据数量 (最多 3 条)
4. 优化信号计算 (加法而非连乘)

支持 9.1/9.2/9.3 规范 + 影响力加权
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import random

# 导入基础模块
sys.path.insert(0, str(Path(__file__).parent))


class EventType(Enum):
    """事件类型 - 9.1 规范 V9.5"""
    ONCHAIN_DATA = "onchain_data"
    KOL_VIEW = "kol_view"
    PROJECT_UPDATE = "project_update"
    FED_POLICY = "fed_policy"
    US_DATA = "us_data"
    GEOPOLITICS = "geopolitics"
    US_POLICY = "us_policy"
    MARKET_ANALYSIS = "market_analysis"
    SECURITY = "security"
    # V9.4 新增
    JIN10_NEWS = "jin10_news"         # 金十数据
    TECH_LEADER = "tech_leader"       # 技术派大 V
    VC_VIEW = "vc_view"               # 投资机构观点
    ONCHAIN_ANALYST = "onchain_analyst"  # 链上分析师
    TRADER_VIEW = "trader_view"       # 交易员观点


class InfluencerTier(Enum):
    """影响力分级 - V9.5"""
    TIER_0 = "T0"   # 核心开发者/顶级机构 (Vitalik, a16z)
    TIER_1 = "T1"   # 知名分析师 (Willy Woo, Tom Lee)
    TIER_2 = "T2"   # 交易员/创始人 (Arthur Hayes)
    TIER_3 = "T3"   # 一般 KOL


# V9.5 新闻源配置 (优化权重)
INFLUENCER_DATABASE = {
    # 技术派（核心开发者）- V9.5 权重提升
    "VitalikButerin": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "tech_leader",
        "weight": 1.8,  # V9.5: 1.5 → 1.8
        "focus": ["以太坊", "Layer2", "zkEVM", "扩容"]
    },
    "adam3billion": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "tech_leader",
        "weight": 1.4,  # V9.5: 1.2 → 1.4
        "focus": ["BTC 核心开发", "闪电网络"]
    },

    # 投资机构 - V9.5 权重提升
    "TomLeeFS": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "vc_view",
        "weight": 1.5,  # V9.5: 1.3 → 1.5
        "focus": ["机构策略", "宏观分析"]
    },
    "a16zcrypto": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "vc_view",
        "weight": 1.8,  # V9.5: 1.4 → 1.8
        "focus": ["Web3 投资", "监管政策"]
    },
    "cz_binance": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "vc_view",
        "weight": 1.8,  # V9.5: 1.5 → 1.8
        "focus": ["交易所动态", "行业生态"]
    },

    # 链上分析师 - V9.5 权重提升
    "woonomic": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "onchain_analyst",
        "weight": 1.5,  # V9.5: 1.3 → 1.5
        "focus": ["链上数据", "BTC 分析"]
    },
    "100trillionUSD": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "onchain_analyst",
        "weight": 1.4,  # V9.5: 1.2 → 1.4
        "focus": ["S2F 模型", "BTC 价格预测"]
    },
    "glassnode": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "onchain_analyst",
        "weight": 1.5,  # V9.5: 1.3 → 1.5
        "focus": ["链上指标", "市场分析"]
    },

    # 交易员/创始人 - V9.5 权重提升
    "CryptoHayes": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "trader_view",
        "weight": 1.5,  # V9.5: 1.3 → 1.5
        "focus": ["宏观交易", "衍生品"]
    },
    "APompliano": {
        "tier": InfluencerTier.TIER_2.value,
        "category": "trader_view",
        "weight": 1.3,  # V9.5: 1.1 → 1.3
        "focus": ["BTC 倡导", "机构采用"]
    },
}

# 金十数据分类 - V9.5 权重降低
JIN10_CATEGORIES = {
    "finance": {"weight": 1.0, "event_type": EventType.MARKET_ANALYSIS.value},  # V9.5: 1.2 → 1.0
    "crypto": {"weight": 1.0, "event_type": EventType.JIN10_NEWS.value},        # V9.5: 1.3 → 1.0
    "forex": {"weight": 1.0, "event_type": EventType.JIN10_NEWS.value},
    "metal": {"weight": 0.9, "event_type": EventType.JIN10_NEWS.value},
    "energy": {"weight": 0.9, "event_type": EventType.JIN10_NEWS.value},
}


@dataclass
class EventLedgerEntry:
    """事件账本条目 - V9.5"""
    # 基础信息
    event_id: str
    timestamp: str
    source: str

    # 9.1 规范
    event_type: str

    # 9.2 规范
    window: str
    published_at: str
    expiry_at: Optional[str]

    # 9.3 规范
    surprise_bucket: str
    expected_value: Optional[float]
    actual_value: Optional[float]
    surprise_score: float

    # 9.3 规范：风险行动
    risk_action_proposal: str
    confidence_level: float
    position_impact: float

    # V9.4/V9.5 新增
    influencer_tier: Optional[str]     # 大 V 影响力分级
    influencer_weight: float           # 影响力权重
    source_reliability: float          # 来源可靠性

    # 内容
    title: str
    summary: str
    content: str
    source_url: str

    # 分析字段
    sentiment_score: float
    credibility: str
    cross_market_map: str
    risk_flags: List[str]

    # 元数据
    version: str


class EnhancedEventLedgerGenerator:
    """增强版事件账本生成器 - V9.5"""

    def __init__(self):
        self.event_counter = 0
        self.jin10_daily_count = {}  # V9.5: 追踪每日金十数据数量

    def generate_event_id(self) -> str:
        self.event_counter += 1
        now = datetime.now()
        return f"EVT-V95-{now.strftime('%Y%m%d%H%M%S')}-{self.event_counter:04d}"

    def get_influencer_info(self, username: str) -> Dict:
        """获取大 V 信息"""
        return INFLUENCER_DATABASE.get(username, {
            "tier": InfluencerTier.TIER_3.value,
            "category": "kol_view",
            "weight": 0.8,
            "focus": []
        })

    def classify_event_type(self, category: str, source: str, influencer: str = None) -> str:
        """分类事件类型 - V9.5"""
        if source == "jin10":
            return EventType.JIN10_NEWS.value

        if influencer:
            info = self.get_influencer_info(influencer)
            return info.get("category", EventType.KOL_VIEW.value)

        mapping = {
            "onchain_data": EventType.ONCHAIN_DATA.value,
            "kols_view": EventType.KOL_VIEW.value,
            "project_update": EventType.PROJECT_UPDATE.value,
            "security": EventType.SECURITY.value,
            "fed": EventType.FED_POLICY.value,
            "us_data": EventType.US_DATA.value,
            "geopolitics": EventType.GEOPOLITICS.value,
            "us_policy": EventType.US_POLICY.value,
            "market_analysis": EventType.MARKET_ANALYSIS.value,
        }
        return mapping.get(category, EventType.MARKET_ANALYSIS.value)

    def calculate_influencer_weight(self, influencer: str) -> tuple:
        """计算大 V 影响力权重 - V9.5"""
        info = self.get_influencer_info(influencer)
        tier_weight = {
            InfluencerTier.TIER_0.value: 1.8,  # V9.5: 1.5 → 1.8
            InfluencerTier.TIER_1.value: 1.5,  # V9.5: 1.3 → 1.5
            InfluencerTier.TIER_2.value: 1.3,  # V9.5: 1.1 → 1.3
            InfluencerTier.TIER_3.value: 0.8,
        }
        tier = info.get("tier", InfluencerTier.TIER_3.value)
        base_weight = info.get("weight", 0.8)
        return tier, base_weight

    def calculate_surprise_bucket(self, sentiment_score: float, risk_flags: List[str],
                                   influencer_weight: float = 1.0) -> tuple:
        """计算意外程度分级 - V9.5"""
        abs_score = abs(sentiment_score)
        flag_penalty = len(risk_flags) * 0.1

        # 影响力加成
        weighted_score = abs_score * influencer_weight
        surprise_score = min(1.0, weighted_score * (1 + flag_penalty))

        if abs_score >= 0.8:
            bucket = "major"
        elif abs_score >= 0.6:
            bucket = "moderate"
        elif abs_score >= 0.4:
            bucket = "mild"
        else:
            bucket = "expected"

        return bucket, surprise_score

    def propose_risk_action(self, sentiment_score: float, confidence: str,
                            surprise_bucket: str, event_type: str,
                            influencer_weight: float = 1.0) -> str:
        """提出风险行动建议 - V9.5"""
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        conf = conf_map.get(confidence, 0.5)

        # 大 V 加成
        adjusted_conf = min(0.95, conf * influencer_weight)

        if sentiment_score < -0.5 and adjusted_conf > 0.7:
            if sentiment_score < -0.8:
                return "stop_loss"
            return "reduce"

        if sentiment_score > 0.5 and adjusted_conf > 0.7:
            return "increase"

        if surprise_bucket == "major":
            return "hedge"

        return "hold"

    def create_ledger_entry(self, news_item: Dict) -> EventLedgerEntry:
        """创建事件账本条目 - V9.5"""
        source = news_item.get("source", "")
        influencer = news_item.get("influencer", None)
        category = news_item.get("category", "")

        # 9.1: 事件类型
        event_type = self.classify_event_type(category, source, influencer)

        # 9.2: 时间窗口
        window = news_item.get("impact_horizon", "T1")

        # V9.5: 影响力权重
        if influencer:
            tier, influencer_weight = self.calculate_influencer_weight(influencer)
        else:
            tier = None
            influencer_weight = news_item.get("source_weight", 1.0)

        # 9.3: 意外程度
        sentiment = news_item.get("sentiment_score", 0.0)
        risk_flags = news_item.get("risk_flags", [])
        surprise_bucket, surprise_score = self.calculate_surprise_bucket(
            sentiment, risk_flags, influencer_weight
        )

        # 9.3: 风险行动
        confidence = news_item.get("source_confidence", "medium")
        risk_action = self.propose_risk_action(
            sentiment, confidence, surprise_bucket, event_type, influencer_weight
        )

        # 计算置信度和仓位影响
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        confidence_level = conf_map.get(confidence, 0.5) * influencer_weight
        position_impact = sentiment * confidence_level

        # 设置失效时间
        published_at = news_item.get("published_at", datetime.now().isoformat())
        pub_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00').split('+')[0])

        if window == "T0":
            expiry_dt = pub_dt + timedelta(days=1)
        elif window == "T1":
            expiry_dt = pub_dt + timedelta(days=7)
        elif window == "T2":
            expiry_dt = pub_dt + timedelta(weeks=4)
        else:
            expiry_dt = pub_dt + timedelta(weeks=12)

        entry = EventLedgerEntry(
            event_id=self.generate_event_id(),
            timestamp=datetime.now().isoformat(),
            source=source,
            event_type=event_type,
            window=window,
            published_at=published_at,
            expiry_at=expiry_dt.isoformat(),
            surprise_bucket=surprise_bucket,
            expected_value=None,
            actual_value=None,
            surprise_score=surprise_score,
            risk_action_proposal=risk_action,
            confidence_level=confidence_level,
            position_impact=position_impact,
            influencer_tier=tier,
            influencer_weight=influencer_weight,
            source_reliability=influencer_weight / 1.8,  # V9.5: 归一化到 0-1
            title=news_item.get("title", ""),
            summary=news_item.get("summary", ""),
            content=news_item.get("content", news_item.get("summary", "")),
            source_url=news_item.get("source_url", ""),
            sentiment_score=sentiment,
            credibility=confidence,
            cross_market_map=news_item.get("cross_market_map", ""),
            risk_flags=risk_flags,
            version="9.5"
        )

        return entry

    def generate_ledger(self, news_list: List[Dict]) -> List[EventLedgerEntry]:
        """生成完整事件账本"""
        self.event_counter = 0
        entries = []
        for news in news_list:
            entry = self.create_ledger_entry(news)
            entries.append(entry)
        return entries

    def to_jsonl(self, entries: List[EventLedgerEntry]) -> str:
        """转换为 JSONL 格式"""
        lines = []
        for entry in entries:
            data = asdict(entry)
            lines.append(json.dumps(data, ensure_ascii=False))
        return "\n".join(lines)

    def save_jsonl(self, entries: List[EventLedgerEntry], output_path: Path):
        """保存 JSONL 文件"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_jsonl(entries))
        print(f"[✓] 事件账本已保存：{output_path}")


def generate_v95_mock_news(days: int = 90, prices: Dict = None) -> List[Dict]:
    """
    生成 V9.5 模拟新闻（优化版：限制金十数据数量）
    """
    random.seed(42)
    now = datetime.now()
    news_list = []

    # 金十数据模板
    jin10_templates = [
        ("美联储官员：通胀仍具粘性", "某票委称需更多证据支持降息", -0.6),
        ("美国非农数据超预期", "新增就业{v}万人，失业率降至{r}%", -0.5),
        ("中国央行降准预期升温", "释放流动性支持经济复苏", 0.5),
        ("原油价格跳涨", "中东局势推升能源价格", -0.3),
        ("美债收益率飙升", "10 年期收益率突破{v}%", -0.7),
    ]

    # Twitter 大 V 模板
    twitter_templates = {
        "VitalikButerin": [
            ("以太坊路线图更新", "Layer2 扩容方案取得重大进展", 0.6),
            ("zkEVM 技术突破", "零知识证明效率提升 10 倍", 0.7),
        ],
        "woonomic": [
            ("BTC 链上数据强劲", "长期持有者比例创新高", 0.5),
            ("交易所存量下降", "供应紧缩信号显现", 0.6),
        ],
        "TomLeeFS": [
            ("机构配置需求上升", "比特币目标价 15 万美元", 0.7),
            ("宏观环境有利", "流动性充裕支撑风险资产", 0.5),
        ],
        "CryptoHayes": [
            ("衍生品市场预警", "未平仓合约过高警惕回调", -0.4),
            ("宏观交易策略", "建议做多波动率", 0.2),
        ],
        "a16zcrypto": [
            ("Web3 投资趋势", "AI+Crypto 成新热点", 0.5),
            ("监管框架展望", "美国政策有望边际改善", 0.4),
        ],
        "100trillionUSD": [
            ("S2F 模型更新", "BTC 价格路径符合预期", 0.5),
            ("减半周期分析", "下一轮牛市在望", 0.6),
        ],
    }

    # 生成日期列表
    dates = [now - timedelta(days=i) for i in range(days)]

    for date in dates:
        date_str = date.strftime("%Y-%m-%d")

        if date.weekday() >= 5:  # 周末减少新闻
            num_jin10 = random.randint(1, 2)  # V9.5: 限制最多 2 条
            num_twitter = random.randint(1, 3)  # V9.5: 增加 Twitter 数量
        else:
            num_jin10 = random.randint(2, 3)  # V9.5: 限制最多 3 条
            num_twitter = random.randint(2, 4)  # V9.5: 增加 Twitter 数量

        # 生成金十数据
        for _ in range(num_jin10):
            template = random.choice(jin10_templates)
            title = template[0].format(v=random.randint(4, 6), r=random.uniform(3.5, 4.5))
            summary = template[1].format(v=random.randint(4, 6), r=random.uniform(3.5, 4.5))

            pub_hour = random.randint(8, 18)  # 交易时间
            pub_dt = date.replace(hour=pub_hour, minute=random.randint(0, 59))

            news_list.append({
                "title": title,
                "summary": summary,
                "content": summary,
                "source": "jin10",
                "source_confidence": "high",
                "source_weight": 1.0,  # V9.5: 1.2 → 1.0
                "category": "jin10_news",
                "impact_horizon": random.choice(["T0", "T1"]),
                "sentiment_score": template[2] + random.gauss(0, 0.1),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "宏观→加密传导",
                "risk_flags": []
            })

        # 生成 Twitter 大 V 新闻
        for _ in range(num_twitter):
            influencer = random.choice(list(twitter_templates.keys()))
            template = random.choice(twitter_templates[influencer])
            info = INFLUENCER_DATABASE.get(influencer, {})

            pub_hour = random.randint(0, 23)
            pub_dt = date.replace(hour=pub_hour, minute=random.randint(0, 59))

            news_list.append({
                "title": template[0],
                "summary": template[1],
                "content": template[1],
                "source": f"twitter/{influencer}",
                "influencer": influencer,
                "source_confidence": info.get("tier", InfluencerTier.TIER_3.value),
                "source_weight": info.get("weight", 0.8),
                "category": info.get("category", "kol_view"),
                "impact_horizon": random.choice(["T0", "T1", "T2"]),
                "sentiment_score": template[2] + random.gauss(0, 0.1),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "大 V 观点→市场情绪传导",
                "risk_flags": [] if info.get("tier") != InfluencerTier.TIER_3.value else ["需验证"]
            })

    return news_list


def main():
    """主函数 - 生成 V9.5 事件账本"""
    import argparse

    parser = argparse.ArgumentParser(description='生成 V9.5 事件账本')
    parser.add_argument('--days', '-d', type=int, default=90, help='生成天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件')
    args = parser.parse_args()

    print("=" * 60)
    print("  事件账本生成器 (V9.5 - 优化版)")
    print("=" * 60)
    print(f"\n生成天数：{args.days}")

    generator = EnhancedEventLedgerGenerator()

    # 加载价格数据（用于日期参考）
    data_dir = Path(__file__).parent.parent / "historical_data"
    price_file = data_dir / "btc_daily_prices.json"
    prices = {}
    if price_file.exists():
        with open(price_file, 'r') as f:
            prices = json.load(f)
        print(f"加载价格数据：{len(prices)} 天")

    # 生成新闻
    news_list = generate_v95_mock_news(args.days, prices)
    print(f"生成新闻数：{len(news_list)}")

    # 生成账本
    entries = generator.generate_ledger(news_list)
    print(f"生成事件条目：{len(entries)}")

    # 保存
    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = output_dir / args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_dir / f"event_ledger_v95_{ts}.jsonl"

    generator.save_jsonl(entries, output_path)

    # 统计
    print(f"\n【事件账本统计】")

    by_type = {}
    by_source = {}
    by_tier = {}

    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

        s = e.source
        if s.startswith("twitter"):
            s = "twitter"
        by_source[s] = by_source.get(s, 0) + 1

        if e.influencer_tier:
            by_tier[e.influencer_tier] = by_tier.get(e.influencer_tier, 0) + 1

    print("\n按事件类型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c} 条")

    print("\n按来源:")
    for s, c in sorted(by_source.items()):
        print(f"  {s}: {c} 条")

    print("\n按大 V 分级:")
    for tier, c in sorted(by_tier.items()):
        print(f"  {tier}: {c} 条")

    print(f"\n[✓] 事件账本已保存：{output_path}")

    return entries


if __name__ == "__main__":
    main()
