#!/usr/bin/env python3
"""
事件账本生成器 - V9.8 V9.3+ 链上资金转移大 V 增强版

在 V9.3 基础上，仅增加与**链上资金转移**相关的大 V 观点:
- 巨鲸地址转账
- 交易所资金流入/流出
- ETF 持仓变动
- 机构/公司持仓变动
- 稳定币铸币/销毁

V9.8 设计原则:
1. 保持 V9.3 的事件类型和权重
2. 大 V 观点仅聚焦链上资金转移（高信息含量）
3. 严格控制大 V 事件数量（每 3-4 天 1 条）
4. 正负信号均衡
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
    """事件类型 - 9.1 规范 V9.8"""
    ONCHAIN_DATA = "onchain_data"
    KOL_VIEW = "kol_view"
    PROJECT_UPDATE = "project_update"
    FED_POLICY = "fed_policy"
    US_DATA = "us_data"
    GEOPOLITICS = "geopolitics"
    US_POLICY = "us_policy"
    MARKET_ANALYSIS = "market_analysis"
    SECURITY = "security"


# V9.8: 链上资金转移相关大 V 观点模板
# 仅包含与资金流向、持仓变动、链上转移相关的内容
ONCHAIN_FLOW_TEMPLATES = [
    # 正向信号（资金流入/增持）
    {
        "title": "巨鲸地址大额转入",
        "summary": "链上数据显示某未知巨鲸地址从交易所转入 5000 BTC 至冷钱包，长期持有意愿增强",
        "sentiment": 0.6,
        "action": "increase",
        "source": "woonomic"
    },
    {
        "title": "交易所 BTC 存量下降",
        "summary": "Glassnode 数据：交易所 BTC 存量周减 3 万枚，创 2018 年以来新低，供应紧缩",
        "sentiment": 0.5,
        "action": "increase",
        "source": "glassnode"
    },
    {
        "title": "MicroStrategy 再增持",
        "summary": "微策略公司宣布再购入 1 万枚 BTC，总持仓突破 20 万枚，成本约 5.8 万美元",
        "sentiment": 0.6,
        "action": "increase",
        "source": "cz_binance"
    },
    {
        "title": "ETF 净流入创新高",
        "summary": "贝莱德 IBIT 单日净流入 5 亿美元，创 ETF 获批以来最高，机构配置需求强劲",
        "sentiment": 0.7,
        "action": "increase",
        "source": "a16zcrypto"
    },
    {
        "title": "稳定币大量铸造",
        "summary": "USDT 过去 24 小时增发 20 亿美元，USDC 增发 5 亿，加密市场流动性充裕",
        "sentiment": 0.5,
        "action": "increase",
        "source": "VitalikButerin"
    },
    {
        "title": "长期持有者增持",
        "summary": "链上数据：持有 BTC 超过 1 年的地址数量周增 8%，长期持有者比例创新高",
        "sentiment": 0.5,
        "action": "increase",
        "source": "woonomic"
    },
    {
        "title": "机构托管量上升",
        "summary": "Coinbase 托管 BTC 量突破 100 万枚，机构持仓持续增加",
        "sentiment": 0.4,
        "action": "increase",
        "source": "a16zcrypto"
    },
    # 负向信号（资金流出/减持）
    {
        "title": "巨鲸地址大额转出至交易所",
        "summary": "链上监测：某沉睡 5 年的巨鲸地址向币安转入 1 万 BTC，可能准备抛售",
        "sentiment": -0.6,
        "action": "reduce",
        "source": "woonomic"
    },
    {
        "title": "ETF 净流出",
        "summary": "灰度 GBTC 单日净流出 3 亿美元，连续 5 日净赎回，抛压担忧",
        "sentiment": -0.5,
        "action": "reduce",
        "source": "a16zcrypto"
    },
    {
        "title": "交易所存量上升",
        "summary": "Glassnode 数据：交易所 BTC 存量周增 5 万枚，潜在抛压增加",
        "sentiment": -0.4,
        "action": "reduce",
        "source": "glassnode"
    },
    {
        "title": "稳定币大量销毁",
        "summary": "USDT 过去 24 小时销毁 10 亿美元，USDC 销毁 3 亿，市场流动性收紧",
        "sentiment": -0.5,
        "action": "reduce",
        "source": "VitalikButerin"
    },
    {
        "title": "机构减持公告",
        "summary": "某上市公司宣布出售 50% BTC 持仓，市场对其他机构效仿表示担忧",
        "sentiment": -0.6,
        "action": "reduce",
        "source": "cz_binance"
    },
    {
        "title": "短期持有者比例上升",
        "summary": "链上数据：持有 BTC 少于 1 个月的地址比例月增 15%，投机情绪升温",
        "sentiment": -0.4,
        "action": "reduce",
        "source": "glassnode"
    },
    # 中性/警示信号
    {
        "title": "交易所资金双向流动",
        "summary": "大额转账活跃但净流入流出基本持平，市场处于震荡整理",
        "sentiment": 0.1,
        "action": "hold",
        "source": "woonomic"
    },
    {
        "title": "杠杆率过高警示",
        "summary": "衍生品未平仓合约创历史新高，建议投资者注意风险",
        "sentiment": -0.3,
        "action": "hedge",
        "source": "cz_binance"
    },
]

# 大 V 信息
INFLUENCER_DATA = {
    "woonomic": {
        "name": "Willy Woo",
        "title": "链上数据分析师",
        "tier": "T1",
        "weight": 1.3,
        "focus": "链上数据、BTC 分析"
    },
    "glassnode": {
        "name": "Glassnode",
        "title": "链上数据分析机构",
        "tier": "T1",
        "weight": 1.3,
        "focus": "链上指标、市场分析"
    },
    "VitalikButerin": {
        "name": "Vitalik Buterin",
        "title": "以太坊创始人",
        "tier": "T0",
        "weight": 1.5,
        "focus": "以太坊、稳定币"
    },
    "a16zcrypto": {
        "name": "a16z crypto",
        "title": "顶级 Web3 投资机构",
        "tier": "T0",
        "weight": 1.4,
        "focus": "机构投资、ETF"
    },
    "cz_binance": {
        "name": "CZ",
        "title": "币安创始人",
        "tier": "T0",
        "weight": 1.5,
        "focus": "交易所、机构"
    },
}


@dataclass
class EventLedgerEntry:
    """事件账本条目 - V9.8"""
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


class V98EventLedgerGenerator:
    """V9.8 事件账本生成器"""

    def __init__(self):
        self.event_counter = 0

    def generate_event_id(self) -> str:
        self.event_counter += 1
        now = datetime.now()
        return f"EVT-V98-{now.strftime('%Y%m%d%H%M%S')}-{self.event_counter:04d}"

    def create_ledger_entry(self, news_item: Dict, is_onchain_flow: bool = False) -> EventLedgerEntry:
        source = news_item.get("source", "")
        influencer = news_item.get("influencer", None)
        category = news_item.get("category", "")

        # 9.1: 事件类型
        if is_onchain_flow and influencer:
            event_type = EventType.KOL_VIEW.value
        else:
            event_type = category

        # 9.2: 时间窗口
        window = news_item.get("impact_horizon", "T1")

        # V9.8: 影响力权重
        if influencer:
            info = INFLUENCER_DATA.get(influencer, {"tier": "T2", "weight": 0.8})
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
            version="9.8"
        )

    def generate_ledger(self, v93_news: List[Dict], onchain_flow_news: List[Dict]) -> List[EventLedgerEntry]:
        self.event_counter = 0
        entries = []

        for news in v93_news:
            entry = self.create_ledger_entry(news, is_onchain_flow=False)
            entries.append(entry)

        for news in onchain_flow_news:
            entry = self.create_ledger_entry(news, is_onchain_flow=True)
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
        ],
        "market_analysis": [
            ("技术面突破", "BTC 突破关键阻力位，目标 7 万美元", 0.5),
            ("资金流向", "北向资金连续 3 日净流入加密相关股票", 0.4),
            ("技术面回调", "BTC 跌破关键支撑位，可能下探 5 万", -0.5),
            ("资金流出", "加密基金连续两周净赎回", -0.4),
        ],
        "security": [
            ("交易所安全升级", "币安宣布新的用户资产保护机制", 0.3),
            ("黑客攻击事件", "某 DeFi 协议被攻击损失 1000 万美元", -0.6),
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


def generate_onchain_flow_news(days: int = 90) -> List[Dict]:
    """生成链上资金转移相关大 V 观点（高信息含量）"""
    random.seed(45)  # 不同随机种子
    now = datetime.now()
    news_list = []

    dates = [now - timedelta(days=i) for i in range(days)]

    # 正负向模板分离
    positive_templates = [t for t in ONCHAIN_FLOW_TEMPLATES if t["sentiment"] > 0.2]
    negative_templates = [t for t in ONCHAIN_FLOW_TEMPLATES if t["sentiment"] < -0.2]
    neutral_templates = [t for t in ONCHAIN_FLOW_TEMPLATES if -0.2 <= t["sentiment"] <= 0.2]

    for date in dates:
        # V9.8: 每 3-4 天 1 条链上资金新闻
        if date.weekday() >= 5:
            num_onchain = 0
        else:
            # 约每 3.5 天 1 条
            num_onchain = 1 if (date - now).days % 4 == 0 else 0

        for _ in range(num_onchain):
            # 正负向均衡分布
            r = random.random()
            if r < 0.45:
                template = random.choice(positive_templates)
            elif r < 0.85:
                template = random.choice(negative_templates)
            else:
                template = random.choice(neutral_templates)

            influencer = template.get("source", "woonomic")
            info = INFLUENCER_DATA.get(influencer, {"tier": "T2", "weight": 0.8})

            pub_hour = random.randint(9, 22)
            pub_dt = date.replace(hour=pub_hour, minute=random.randint(0, 59))

            news_list.append({
                "title": template["title"],
                "summary": template["summary"],
                "content": template["summary"],
                "source": f"twitter/{influencer}",
                "influencer": influencer,
                "category": "kol_view",
                "source_confidence": "high",
                "impact_horizon": random.choice(["T0", "T1"]),
                "sentiment_score": template["sentiment"] + random.gauss(0, 0.08),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "链上资金→市场情绪→价格",
                "risk_flags": [],
                "preset_action": template.get("action", "hold")
            })

    return news_list


def main():
    """主函数 - 生成 V9.8 事件账本"""
    import argparse

    parser = argparse.ArgumentParser(description='生成 V9.8 事件账本')
    parser.add_argument('--days', '-d', type=int, default=90, help='生成天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件')
    args = parser.parse_args()

    print("=" * 60)
    print("  事件账本生成器 (V9.8 - V9.3+ 链上资金转移大 V)")
    print("=" * 60)
    print(f"\n生成天数：{args.days}")

    generator = V98EventLedgerGenerator()

    # 生成 V9.3 基础新闻
    v93_news = generate_v93_mock_news(args.days)
    print(f"V9.3 基础新闻：{len(v93_news)} 条")

    # 生成链上资金转移大 V 观点
    onchain_news = generate_onchain_flow_news(args.days)
    print(f"链上资金大 V 观点：{len(onchain_news)} 条")

    # 生成账本
    entries = generator.generate_ledger(v93_news, onchain_news)
    print(f"总事件数：{len(entries)}")

    # 保存
    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = output_dir / args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_dir / f"event_ledger_v98_{ts}.jsonl"

    generator.save_jsonl(entries, output_path)

    # 统计
    print(f"\n【事件账本统计】")

    by_type = {}
    by_influencer = {}
    action_counts = {}
    sentiment_dist = {"positive": 0, "negative": 0, "neutral": 0}

    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

        if e.influencer_tier:
            by_influencer[e.source] = by_influencer.get(e.source, 0) + 1

        a = e.risk_action_proposal
        action_counts[a] = action_counts.get(a, 0) + 1

        if e.sentiment_score > 0.2:
            sentiment_dist["positive"] += 1
        elif e.sentiment_score < -0.2:
            sentiment_dist["negative"] += 1
        else:
            sentiment_dist["neutral"] += 1

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

    print("\n情感分布:")
    for s, c in sentiment_dist.items():
        pct = c / len(entries) * 100
        print(f"  {s}: {c} ({pct:.1f}%)")

    return entries


if __name__ == "__main__":
    main()
