#!/usr/bin/env python3
"""
事件账本生成器 - V9.7 V9.3+ 顶级大 V 增强版

在 V9.3 基础上，仅增加最具影响力的 T0 级加密大 V:
- Vitalik Buterin (以太坊创始人)
- a16z crypto (顶级 Web3 投资机构)
- CZ Binance (币安创始人)

V9.7 设计原则:
1. 保持 V9.3 的事件类型和权重
2. 大 V 观点作为补充信号源（不主导）
3. 严格控制大 V 事件数量（每日最多 1 条）
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import random

sys.path.insert(0, str(Path(__file__).parent))


class EventType(Enum):
    """事件类型 - 9.1 规范 V9.7"""
    ONCHAIN_DATA = "onchain_data"
    KOL_VIEW = "kol_view"  # V9.7: 大 V 观点归类为此
    PROJECT_UPDATE = "project_update"
    FED_POLICY = "fed_policy"
    US_DATA = "us_data"
    GEOPOLITICS = "geopolitics"
    US_POLICY = "us_policy"
    MARKET_ANALYSIS = "market_analysis"
    SECURITY = "security"


class InfluencerTier(Enum):
    """影响力分级 - V9.7"""
    TIER_0 = "T0"   # 顶级大 V
    TIER_1 = "T1"   # 知名分析师
    TIER_2 = "T2"   # 一般 KOL


# V9.7: 仅 T0 级顶级大 V
INFLUENCER_DATABASE = {
    "VitalikButerin": {
        "name": "Vitalik Buterin",
        "title": "以太坊创始人",
        "tier": InfluencerTier.TIER_0.value,
        "weight": 1.5,
        "focus": ["以太坊", "Layer2", "zkEVM", "扩容"]
    },
    "a16zcrypto": {
        "name": "a16z crypto",
        "title": "顶级 Web3 投资机构",
        "tier": InfluencerTier.TIER_0.value,
        "weight": 1.4,
        "focus": ["Web3 投资", "监管政策"]
    },
    "cz_binance": {
        "name": "CZ",
        "title": "币安创始人",
        "tier": InfluencerTier.TIER_0.value,
        "weight": 1.5,
        "focus": ["交易所动态", "行业生态"]
    },
}


# V9.7 大 V 观点模板（高质量、有信息量，包含正负向）
INFLUENCER_TEMPLATES = {
    "VitalikButerin": [
        ("以太坊路线图更新", "Layer2 扩容方案取得重大进展，Rollup 效率将提升 10 倍", 0.6),
        ("zkEVM 技术突破", "零知识证明验证效率提升，Gas 费将大幅降低", 0.7),
        ("POS 机制分析", "以太坊质押率持续上升，网络安全性增强", 0.5),
        ("Layer2 生态展望", "Optimism 和 Arbitrum TVL 创新高，生态繁荣", 0.5),
        ("技术挑战警告", "以太坊分片技术仍面临重大挑战", -0.3),
        ("监管担忧", "过度监管可能阻碍 Web3 创新", -0.4),
    ],
    "a16zcrypto": [
        ("Web3 投资趋势", "AI+Crypto 成新热点，已投资 5 个相关项目", 0.5),
        ("监管框架展望", "美国加密监管政策有望边际改善", 0.4),
        ("机构采用进展", "传统金融机构加速布局加密资产", 0.5),
        ("开发者生态", "Web3 开发者数量同比增长 50%", 0.5),
        ("市场调整观点", "加密市场正在经历健康调整", -0.2),
        ("估值担忧", "部分 Layer1 估值过高，存在回调风险", -0.4),
    ],
    "cz_binance": [
        ("交易所数据", "BTC 现货交易量创月度新高", 0.4),
        ("行业生态", "币安链每日活跃地址数突破 100 万", 0.5),
        ("市场流动性", "加密市场流动性持续改善", 0.4),
        ("合规进展", "与多国监管机构达成合作框架", 0.5),
        ("市场风险提示", "杠杆率过高，建议投资者谨慎", -0.3),
        ("行业挑战", "加密行业仍需克服监管不确定性", -0.2),
    ],
}


@dataclass
class EventLedgerEntry:
    """事件账本条目 - V9.7"""
    event_id: str
    timestamp: str
    source: str
    event_type: str
    window: str
    published_at: str
    expiry_at: Optional[str]
    surprise_bucket: str
    expected_value: Optional[float]
    actual_value: Optional[float]
    surprise_score: float
    risk_action_proposal: str
    confidence_level: float
    position_impact: float
    influencer_tier: Optional[str]
    influencer_weight: float
    source_reliability: float
    title: str
    summary: str
    content: str
    source_url: str
    sentiment_score: float
    credibility: str
    cross_market_map: str
    risk_flags: List[str]
    version: str


class V97EventLedgerGenerator:
    """V9.7 事件账本生成器 - V9.3+ 顶级大 V"""

    def __init__(self):
        self.event_counter = 0

    def generate_event_id(self) -> str:
        self.event_counter += 1
        now = datetime.now()
        return f"EVT-V97-{now.strftime('%Y%m%d%H%M%S')}-{self.event_counter:04d}"

    def get_influencer_info(self, username: str) -> Dict:
        return INFLUENCER_DATABASE.get(username, {
            "tier": InfluencerTier.TIER_2.value,
            "category": EventType.KOL_VIEW.value,
            "weight": 0.8,
            "focus": []
        })

    def create_ledger_entry(self, news_item: Dict, is_influencer: bool = False) -> EventLedgerEntry:
        source = news_item.get("source", "")
        influencer = news_item.get("influencer", None)
        category = news_item.get("category", "")

        # 9.1: 事件类型
        if is_influencer and influencer:
            event_type = EventType.KOL_VIEW.value
        else:
            event_type = category

        # 9.2: 时间窗口
        window = news_item.get("impact_horizon", "T1")

        # V9.7: 影响力权重
        if influencer:
            info = self.get_influencer_info(influencer)
            tier = info.get("tier")
            influencer_weight = info.get("weight", 0.8)
        else:
            tier = None
            influencer_weight = 1.0

        # 9.3: 意外程度
        sentiment = news_item.get("sentiment_score", 0.0)
        risk_flags = news_item.get("risk_flags", [])

        abs_score = abs(sentiment) * influencer_weight
        if abs_score >= 0.6:
            surprise_bucket = "major"
            surprise_score = min(1.0, abs_score * 1.2)
        elif abs_score >= 0.4:
            surprise_bucket = "moderate"
            surprise_score = abs_score
        elif abs_score >= 0.2:
            surprise_bucket = "mild"
            surprise_score = abs_score * 0.8
        else:
            surprise_bucket = "expected"
            surprise_score = abs_score * 0.6

        # 9.3: 风险行动
        confidence = news_item.get("source_confidence", "medium")
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        conf = conf_map.get(confidence, 0.5)
        adjusted_conf = min(0.95, conf * influencer_weight) if influencer else conf

        if sentiment > 0.5 and adjusted_conf > 0.7:
            risk_action = "increase"
        elif sentiment < -0.5 and adjusted_conf > 0.7:
            risk_action = "reduce"
        elif sentiment < -0.7:
            risk_action = "stop_loss"
        elif surprise_bucket == "major":
            risk_action = "hedge"
        else:
            risk_action = "hold"

        confidence_level = conf * (influencer_weight if influencer else 1.0)
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

        return EventLedgerEntry(
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
            source_reliability=influencer_weight / 1.5 if influencer else 1.0,
            title=news_item.get("title", ""),
            summary=news_item.get("summary", ""),
            content=news_item.get("content", news_item.get("summary", "")),
            source_url=news_item.get("source_url", ""),
            sentiment_score=sentiment,
            credibility=confidence,
            cross_market_map=news_item.get("cross_market_map", ""),
            risk_flags=risk_flags,
            version="9.7"
        )

    def generate_ledger(self, v93_news: List[Dict], influencer_news: List[Dict]) -> List[EventLedgerEntry]:
        """生成事件账本：V9.3 新闻 + 大 V 观点"""
        self.event_counter = 0
        entries = []

        # 添加 V9.3 新闻
        for news in v93_news:
            entry = self.create_ledger_entry(news, is_influencer=False)
            entries.append(entry)

        # 添加大 V 观点
        for news in influencer_news:
            entry = self.create_ledger_entry(news, is_influencer=True)
            entries.append(entry)

        return entries

    def to_jsonl(self, entries: List[EventLedgerEntry]) -> str:
        lines = []
        for entry in entries:
            data = asdict(entry)
            lines.append(json.dumps(data, ensure_ascii=False))
        return "\n".join(lines)

    def save_jsonl(self, entries: List[EventLedgerEntry], output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_jsonl(entries))
        print(f"[✓] 事件账本已保存：{output_path}")


def generate_v93_mock_news(days: int = 90) -> List[Dict]:
    """生成 V9.3 风格的基础新闻（正负信号均衡）"""
    random.seed(42)
    now = datetime.now()
    news_list = []

    # V9.3 事件模板 - 包含正负向
    templates = {
        "onchain_data": [
            ("BTC 交易所存量下降", "链上数据显示交易所 BTC 存量降至 3 年新低", 0.5),
            ("长期持有者比例上升", "持有 BTC 超过 1 年的地址比例创新高", 0.5),
            ("巨鲸地址增加", "持仓 1000+BTC 地址数量周增 5%", 0.4),
            ("交易所存量上升", "链上数据显示交易所 BTC 存量增加，抛压担忧", -0.4),
            ("巨鲸地址减少", "持仓 1000+BTC 地址数量周减 3%", -0.4),
            ("短期持有者比例上升", "持有 BTC 少于 1 个月的地址比例创新高", -0.3),
        ],
        "fed_policy": [
            ("美联储降息预期", "市场预计 3 月降息 25bp 概率达 70%", 0.4),
            ("鲍威尔讲话", "美联储主席：通胀数据仍需观察", -0.2),
            ("FOMC 纪要", "美联储会议纪要显示鹰派立场", -0.3),
            ("联储官员表态", "某票委称可能需要加息遏制通胀", -0.4),
        ],
        "market_analysis": [
            ("技术面突破", "BTC 突破关键阻力位，目标 7 万美元", 0.5),
            ("资金流向", "北向资金连续 3 日净流入加密相关股票", 0.4),
            ("技术面回调", "BTC 跌破关键支撑位，可能下探 5 万", -0.5),
            ("资金流出", "加密基金连续两周净赎回", -0.4),
            ("市场震荡", "BTC 在 6 万关口反复争夺", 0.1),
        ],
        "security": [
            ("交易所安全升级", "币安宣布新的用户资产保护机制", 0.3),
            ("黑客攻击事件", "某 DeFi 协议被攻击损失 1000 万美元", -0.6),
            ("监管收紧", "某国禁止银行处理加密交易", -0.5),
        ],
        "us_policy": [
            ("ETF 获批预期", "SEC 可能批准更多比特币 ETF", 0.5),
            ("监管不确定性", "美国议员提议加强对加密的监管", -0.4),
        ],
    }

    dates = [now - timedelta(days=i) for i in range(days)]

    for date in dates:
        if date.weekday() >= 5:
            num_events = random.randint(1, 2)
        else:
            num_events = random.randint(2, 3)

        for _ in range(num_events):
            event_type = random.choice(list(templates.keys()))
            template = random.choice(templates[event_type])

            pub_hour = random.randint(8, 20)
            pub_dt = date.replace(hour=pub_hour, minute=random.randint(0, 59))

            news_list.append({
                "title": template[0],
                "summary": template[1],
                "content": template[1],
                "source": "aggregated",
                "category": event_type,
                "source_confidence": "high" if event_type == "onchain_data" else "medium",
                "impact_horizon": random.choice(["T0", "T1"]),
                "sentiment_score": template[2] + random.gauss(0, 0.1),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "链上/宏观→加密传导",
                "risk_flags": []
            })

    return news_list


def generate_influencer_news(days: int = 90) -> List[Dict]:
    """生成顶级大 V 观点（严格控制数量）"""
    random.seed(43)  # 不同随机种子
    now = datetime.now()
    news_list = []

    dates = [now - timedelta(days=i) for i in range(days)]

    for date in dates:
        # V9.7: 每日最多 1 条大 V 观点，且仅工作日发布
        if date.weekday() >= 5:
            num_influencer = 0
        else:
            num_influencer = random.randint(0, 1)  # 0 或 1 条

        for _ in range(num_influencer):
            influencer = random.choice(list(INFLUENCER_TEMPLATES.keys()))
            template = random.choice(INFLUENCER_TEMPLATES[influencer])

            pub_hour = random.randint(9, 22)
            pub_dt = date.replace(hour=pub_hour, minute=random.randint(0, 59))

            news_list.append({
                "title": template[0],
                "summary": template[1],
                "content": template[1],
                "source": f"twitter/{influencer}",
                "influencer": influencer,
                "category": "kol_view",
                "source_confidence": "high",  # T0 大 V 可信度高
                "impact_horizon": random.choice(["T0", "T1"]),
                "sentiment_score": template[2] + random.gauss(0, 0.1),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "大 V 观点→市场情绪→价格",
                "risk_flags": []
            })

    return news_list


def main():
    """主函数 - 生成 V9.7 事件账本"""
    import argparse

    parser = argparse.ArgumentParser(description='生成 V9.7 事件账本')
    parser.add_argument('--days', '-d', type=int, default=90, help='生成天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件')
    args = parser.parse_args()

    print("=" * 60)
    print("  事件账本生成器 (V9.7 - V9.3+ 顶级大 V)")
    print("=" * 60)
    print(f"\n生成天数：{args.days}")

    generator = V97EventLedgerGenerator()

    # 生成 V9.3 基础新闻
    v93_news = generate_v93_mock_news(args.days)
    print(f"V9.3 基础新闻：{len(v93_news)} 条")

    # 生成大 V 观点
    influencer_news = generate_influencer_news(args.days)
    print(f"大 V 观点：{len(influencer_news)} 条")

    # 生成账本
    entries = generator.generate_ledger(v93_news, influencer_news)
    print(f"总事件数：{len(entries)}")

    # 保存
    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = output_dir / args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_dir / f"event_ledger_v97_{ts}.jsonl"

    generator.save_jsonl(entries, output_path)

    # 统计
    print(f"\n【事件账本统计】")

    by_type = {}
    by_influencer = {}
    by_tier = {}
    action_counts = {}

    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

        if e.influencer_tier:
            by_influencer[e.source] = by_influencer.get(e.source, 0) + 1
            by_tier[e.influencer_tier] = by_tier.get(e.influencer_tier, 0) + 1

        a = e.risk_action_proposal
        action_counts[a] = action_counts.get(a, 0) + 1

    print("\n按事件类型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c} 条")

    print("\n按大 V:")
    for s, c in sorted(by_influencer.items()):
        print(f"  {s}: {c} 条")

    print("\n按行动:")
    for a, c in sorted(action_counts.items()):
        pct = c / len(entries) * 100
        bar = "█" * int(pct / 2)
        print(f"  {a}: {c} ({pct:.1f}%) {bar}")

    return entries


if __name__ == "__main__":
    main()
