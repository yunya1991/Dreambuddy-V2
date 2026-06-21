#!/usr/bin/env python3
"""
事件账本生成器 - V9.6 精简优化版

V9.6 优化点:
1. 减少新闻数量，提高质量门槛
2. 仅使用高权重事件类型 (tech_leader, vc_view, onchain_analyst)
3. 金十数据仅保留 crypto 相关
4. 提高 sentiment 阈值，过滤噪音

目标：重现 V9.3 的成功
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
    """事件类型 - 9.1 规范 V9.6"""
    ONCHAIN_DATA = "onchain_data"
    KOL_VIEW = "kol_view"
    PROJECT_UPDATE = "project_update"
    FED_POLICY = "fed_policy"
    US_DATA = "us_data"
    GEOPOLITICS = "geopolitics"
    US_POLICY = "us_policy"
    MARKET_ANALYSIS = "market_analysis"
    SECURITY = "security"
    JIN10_NEWS = "jin10_news"
    TECH_LEADER = "tech_leader"
    VC_VIEW = "vc_view"
    ONCHAIN_ANALYST = "onchain_analyst"
    TRADER_VIEW = "trader_view"


class InfluencerTier(Enum):
    """影响力分级 - V9.6"""
    TIER_0 = "T0"
    TIER_1 = "T1"
    TIER_2 = "T2"
    TIER_3 = "T3"


# V9.6: 精简大 V 数据库，仅保留高质量来源
INFLUENCER_DATABASE = {
    # 技术派（仅 Vitalik）
    "VitalikButerin": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "tech_leader",
        "weight": 1.5,
        "focus": ["以太坊", "Layer2", "zkEVM"]
    },

    # 投资机构（仅顶级）
    "a16zcrypto": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "vc_view",
        "weight": 1.4,
        "focus": ["Web3 投资"]
    },
    "cz_binance": {
        "tier": InfluencerTier.TIER_0.value,
        "category": "vc_view",
        "weight": 1.5,
        "focus": ["交易所动态"]
    },

    # 链上分析师（仅高质量）
    "woonomic": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "onchain_analyst",
        "weight": 1.3,
        "focus": ["链上数据"]
    },
    "glassnode": {
        "tier": InfluencerTier.TIER_1.value,
        "category": "onchain_analyst",
        "weight": 1.3,
        "focus": ["链上指标"]
    },
}


@dataclass
class EventLedgerEntry:
    """事件账本条目 - V9.6"""
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


class V96EventLedgerGenerator:
    """V9.6 事件账本生成器"""

    def __init__(self):
        self.event_counter = 0

    def generate_event_id(self) -> str:
        self.event_counter += 1
        now = datetime.now()
        return f"EVT-V96-{now.strftime('%Y%m%d%H%M%S')}-{self.event_counter:04d}"

    def get_influencer_info(self, username: str) -> Dict:
        return INFLUENCER_DATABASE.get(username, {
            "tier": InfluencerTier.TIER_3.value,
            "category": "kol_view",
            "weight": 0.8,
            "focus": []
        })

    def classify_event_type(self, category: str, source: str, influencer: str = None) -> str:
        if source == "jin10" and category == "crypto":
            return EventType.JIN10_NEWS.value
        if influencer:
            info = self.get_influencer_info(influencer)
            return info.get("category", EventType.KOL_VIEW.value)
        return category

    def create_ledger_entry(self, news_item: Dict) -> EventLedgerEntry:
        source = news_item.get("source", "")
        influencer = news_item.get("influencer", None)
        category = news_item.get("category", "")

        event_type = self.classify_event_type(category, source, influencer)

        # V9.6: 仅高权重事件类型
        if event_type not in ["tech_leader", "vc_view", "onchain_analyst", "onchain_data", "crypto"]:
            return None

        window = news_item.get("impact_horizon", "T1")

        if influencer:
            info = self.get_influencer_info(influencer)
            tier = info.get("tier")
            influencer_weight = info.get("weight", 0.8)
        else:
            tier = None
            influencer_weight = news_item.get("source_weight", 1.0)

        sentiment = news_item.get("sentiment_score", 0.0)
        risk_flags = news_item.get("risk_flags", [])

        # 意外程度分级
        abs_score = abs(sentiment)
        if abs_score >= 0.6:
            surprise_bucket = "major"
            surprise_score = min(1.0, abs_score * influencer_weight * 1.2)
        elif abs_score >= 0.4:
            surprise_bucket = "moderate"
            surprise_score = min(1.0, abs_score * influencer_weight)
        elif abs_score >= 0.2:
            surprise_bucket = "mild"
            surprise_score = abs_score * influencer_weight * 0.8
        else:
            surprise_bucket = "expected"
            surprise_score = abs_score * influencer_weight * 0.6

        # 风险行动
        confidence = news_item.get("source_confidence", "medium")
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        conf = conf_map.get(confidence, 0.5)
        adjusted_conf = min(0.95, conf * influencer_weight)

        if sentiment > 0.4 and adjusted_conf > 0.6:
            risk_action = "increase"
        elif sentiment < -0.4 and adjusted_conf > 0.6:
            risk_action = "reduce"
        elif sentiment < -0.6:
            risk_action = "stop_loss"
        elif surprise_bucket == "major":
            risk_action = "hedge"
        else:
            risk_action = "hold"

        confidence_level = conf * influencer_weight
        position_impact = sentiment * confidence_level

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
            source_reliability=influencer_weight / 1.5,
            title=news_item.get("title", ""),
            summary=news_item.get("summary", ""),
            content=news_item.get("content", news_item.get("summary", "")),
            source_url=news_item.get("source_url", ""),
            sentiment_score=sentiment,
            credibility=confidence,
            cross_market_map=news_item.get("cross_market_map", ""),
            risk_flags=risk_flags,
            version="9.6"
        )

    def generate_ledger(self, news_list: List[Dict]) -> List[EventLedgerEntry]:
        self.event_counter = 0
        entries = []
        for news in news_list:
            entry = self.create_ledger_entry(news)
            if entry:  # V9.6: 过滤低质量事件
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


def generate_v96_mock_news(days: int = 90) -> List[Dict]:
    """
    生成 V9.6 模拟新闻（精简高质量）
    """
    random.seed(42)
    now = datetime.now()
    news_list = []

    # 仅保留高质量模板
    high_quality_templates = {
        "VitalikButerin": [
            ("以太坊路线图更新", "Layer2 扩容方案取得重大进展", 0.6),
            ("zkEVM 技术突破", "零知识证明效率提升 10 倍", 0.7),
            ("合并后展望", "ETH 通缩预期增强", 0.5),
        ],
        "woonomic": [
            ("BTC 链上数据强劲", "长期持有者比例创新高", 0.5),
            ("交易所存量下降", "供应紧缩信号显现", 0.6),
            ("巨鲸地址增加", "机构持仓持续上升", 0.5),
        ],
        "a16zcrypto": [
            ("Web3 投资趋势", "AI+Crypto 成新热点", 0.5),
            ("监管框架展望", "美国政策有望边际改善", 0.4),
        ],
        "glassnode": [
            ("MVRV 比率分析", "市场估值处于合理区间", 0.3),
            ("网络活跃度上升", "交易数量创新高", 0.5),
        ],
    }

    dates = [now - timedelta(days=i) for i in range(days)]

    for date in dates:
        # V9.6: 大幅减少每日新闻数量（重现 V9.3 的精简模式）
        if date.weekday() >= 5:
            num_high_quality = random.randint(0, 1)  # 周末 0-1 条
        else:
            num_high_quality = random.randint(1, 2)  # 工作日 1-2 条

        for _ in range(num_high_quality):
            influencer = random.choice(list(high_quality_templates.keys()))
            template = random.choice(high_quality_templates[influencer])
            info = INFLUENCER_DATABASE.get(influencer, {})

            pub_hour = random.randint(8, 20)
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
                "impact_horizon": random.choice(["T0", "T1"]),
                "sentiment_score": template[2] + random.gauss(0, 0.1),
                "published_at": pub_dt.isoformat(),
                "cross_market_map": "大 V 观点→市场情绪传导",
                "risk_flags": []
            })

    return news_list


def main():
    """主函数 - 生成 V9.6 事件账本"""
    import argparse

    parser = argparse.ArgumentParser(description='生成 V9.6 事件账本')
    parser.add_argument('--days', '-d', type=int, default=90, help='生成天数')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件')
    args = parser.parse_args()

    print("=" * 60)
    print("  事件账本生成器 (V9.6 - 精简优化版)")
    print("=" * 60)
    print(f"\n生成天数：{args.days}")

    generator = V96EventLedgerGenerator()

    news_list = generate_v96_mock_news(args.days)
    print(f"生成新闻数：{len(news_list)}")

    entries = generator.generate_ledger(news_list)
    print(f"生成事件条目：{len(entries)}")

    output_dir = Path(__file__).parent.parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = output_dir / args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_dir / f"event_ledger_v96_{ts}.jsonl"

    generator.save_jsonl(entries, output_path)

    # 统计
    print(f"\n【事件账本统计】")

    by_type = {}
    by_tier = {}

    for e in entries:
        t = e.event_type
        by_type[t] = by_type.get(t, 0) + 1

        if e.influencer_tier:
            by_tier[e.influencer_tier] = by_tier.get(e.influencer_tier, 0) + 1

    print("\n按事件类型:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c} 条")

    print("\n按大 V 分级:")
    for tier, c in sorted(by_tier.items()):
        print(f"  {tier}: {c} 条")

    return entries


if __name__ == "__main__":
    main()
